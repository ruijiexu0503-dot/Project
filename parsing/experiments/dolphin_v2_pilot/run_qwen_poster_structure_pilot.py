#!/usr/bin/env python3
"""Shadow pilot: Qwen proposes semantic visual groups before segmentation.

This is deliberately separate from the production parser.  It gives the VLM an
overview plus native-resolution crops, then records proposed groups, members,
and label/geometry relations in normalized source-image coordinates.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "EvidenceNet"))
from evidence_graph.llm_client import TransformersLLM, extract_json


CASES = {
    "cosmic_temperatures": {
        "image": PROJECT / "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg",
        "crops": [(0, 300, 3000, 8100), (2200, 300, 4700, 8100), (0, 0, 5530, 2400)],
        "audit_targets": ["temperature-scale curve with its ticks", "Solar corona image group with its label"],
    },
    "milky_way_location": {
        "image": PROJECT / "parsing/experiments/dolphin_v2_pilot/input/poster_comparison_v1/nasa_milky_way_location/Milky_Way_and_Our_Location.png",
        "crops": [(500, 400, 5100, 5200), (1200, 1300, 4400, 4500)],
        "audit_targets": ["galactic longitude/radius coordinate system with numeric labels", "central Milky Way illustration with labelled arms"],
    },
}


def prepare_images(case_id: str, case: dict, output: Path) -> list[Path]:
    target = output / "cases" / case_id
    target.mkdir(parents=True, exist_ok=True)
    source = Image.open(case["image"]).convert("RGB")
    overview = target / "overview.jpg"
    source.save(overview, quality=94)
    paths = [overview]
    for index, box in enumerate(case["crops"], 1):
        crop = source.crop(box)
        path = target / f"detail_{index:02d}.jpg"
        crop.save(path, quality=95)
        paths.append(path)
    source.close()
    return paths


def prompt(case_id: str, case: dict, width: int, height: int) -> str:
    payload = {
        "case_id": case_id,
        "source_dimensions_px": [width, height],
        "images": "Image 1 is the full poster. Subsequent images are native-resolution crops, in this order: " + json.dumps(case["crops"]),
        "audit_targets": case["audit_targets"],
    }
    return """You are identifying evidence-bearing structures in a scientific poster. Do not list every decorative object. First decide which text, geometry, and visuals must be read together to express one scientific fact or measurement.

Return JSON only. Coordinates use [x1,y1,x2,y2] normalized to 0..1000 against the full original poster, never crop coordinates. A group may contain disconnected members. Include only groups you can see. Do not invent unreadable text or relations.

Return exactly two groups: one for each audit target, in the given order. Each group may have at most four members: preserve the essential geometry/visual, label(s), and one representative numeric marker. Use a compact description. Do not add other interesting objects.

Required JSON schema:
{
  "poster_summary":"...",
  "groups":[{
    "id":"G1",
    "kind":"measurement_system|diagram_system|labelled_visual|illustration|text_panel|other",
    "description":"what this group communicates",
    "bbox_norm":[0,0,0,0],
    "members":[{"kind":"curve|axis|tick|numeric_label|text_label|visual|arrow|line|panel|other","description":"...","bbox_norm":[0,0,0,0],"text":"only if legible"}],
    "relations":[{"source_member":0,"target_member":1,"type":"LABELS|MEASURES|MARKS|PART_OF|POINTS_TO|EXPLAINS"}],
    "confidence":0.0,
    "needs_local_segmentation":true
  }],
  "unresolved":["..."],
  "notes_for_segmenter":["specific object or curve to segment"]
}

Hard rules:
- A visual with its nearby label is one group when they refer to each other.
- A scale/coordinate system includes its curve or axes, ticks and corresponding labels in one group.
- A plain background, repeated stars, logos, and decoration are not evidence groups unless they are explicitly labelled and informative.
- Do not make one group per SAM-like fragment.

POSTER METADATA:
""" + json.dumps(payload, ensure_ascii=False, indent=2)


def draw_overlay(image_path: Path, groups: list[dict], target: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    colors = [(230, 58, 57), (41, 127, 214), (28, 151, 93), (191, 95, 196), (238, 142, 45)]
    for index, group in enumerate(groups):
        box = group.get("bbox_norm")
        if not isinstance(box, list) or len(box) != 4: continue
        color = colors[index % len(colors)]
        xy = [box[0] * image.width / 1000, box[1] * image.height / 1000, box[2] * image.width / 1000, box[3] * image.height / 1000]
        draw.rectangle(xy, outline=color, width=max(5, image.width // 850))
        draw.text((xy[0] + 8, max(0, xy[1] - 25)), str(group.get("id", index + 1)), fill=color, stroke_width=1, stroke_fill="white")
    image.save(target, quality=93)
    image.close()


def report(output: Path, rows: list[dict]) -> None:
    cards = []
    for row in rows:
        case_dir = output / "cases" / row["case_id"]
        prediction = row.get("prediction") if isinstance(row.get("prediction"), dict) else {}
        cards.append("<section><h2>" + html.escape(row["case_id"]) + "</h2><img src='cases/" + html.escape(row["case_id"]) + "/overlay.jpg'><pre>" + html.escape(json.dumps(prediction, ensure_ascii=False, indent=2)) + "</pre></section>")
    page = "<!doctype html><meta charset=utf-8><title>Qwen poster structure pilot</title><style>body{font:15px system-ui;max-width:1500px;margin:22px auto;background:#f3f6f8}section{padding:18px;background:white;margin:20px 0}img{max-width:100%;border:1px solid #ccd5dc}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#17202a;color:#eaf1f5;padding:14px}</style><h1>Qwen-guided poster structure pilot</h1><p>Groups are proposals for downstream local segmentation, not accepted production evidence.</p>" + "".join(cards)
    (output / "report.html").write_text(page, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--output", required=True); ap.add_argument("--model", default=str(PROJECT / "external/models/Qwen3.5-35B-A3B")); ap.add_argument("--max-new-tokens", type=int, default=1000); ap.add_argument("--cases", default=",".join(CASES)); ap.add_argument("--resume", action="store_true")
    args = ap.parse_args(); output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "predictions.jsonl"
    existing = {r["case_id"]: r for r in (json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines())} if args.resume and checkpoint.exists() else {}
    rows = []
    llm = None
    selected = [item.strip() for item in args.cases.split(",") if item.strip()]
    unknown = sorted(set(selected) - set(CASES))
    if unknown: raise ValueError(f"Unknown cases: {unknown}")
    for case_id in selected:
        case = CASES[case_id]
        paths = prepare_images(case_id, case, output)
        source = Image.open(case["image"]); width, height = source.size; source.close()
        row = existing.get(case_id)
        if row is None:
            if llm is None: llm = TransformersLLM(args.model, dtype="bfloat16", max_new_tokens=args.max_new_tokens, require_cuda=True, enable_thinking=False)
            raw = llm.generate_raw_with_images("You return careful grounded JSON only.", prompt(case_id, case, width, height), [str(p) for p in paths], args.max_new_tokens).raw
            try: prediction = extract_json(raw)
            except Exception as exc: prediction = {"parse_error": str(exc)}
            row = {"case_id": case_id, "source": str(case["image"]), "crop_boxes_px": case["crops"], "prediction": prediction, "raw_response": raw, "model": args.model, "production_modified": False}
            with checkpoint.open("a", encoding="utf-8") as handle: handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        groups = row.get("prediction", {}).get("groups", []) if isinstance(row.get("prediction"), dict) else []
        draw_overlay(paths[0], groups, output / "cases" / case_id / "overlay.jpg")
        rows.append(row)
        print(json.dumps({"case_id": case_id, "groups": len(groups)}, ensure_ascii=False), flush=True)
    (output / "summary.json").write_text(json.dumps({"cases": len(rows), "model": args.model, "production_modified": False}, indent=2) + "\n", encoding="utf-8")
    report(output, rows)


if __name__ == "__main__": main()
