#!/usr/bin/env python3
"""Group retained poster components by ID without asking a VLM for geometry."""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "EvidenceNet"))
from evidence_graph.llm_client import TransformersLLM, extract_json

TILES = [
    ("top_left", (0, 0, 3200, 3000)), ("top_right", (2300, 0, 5530, 3000)),
    ("middle_left", (0, 2500, 3200, 5700)), ("middle_right", (2300, 2500, 5530, 5700)),
    ("bottom_left", (0, 5200, 3200, 8192)), ("bottom_right", (2300, 5200, 5530, 8192)),
]


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def center_in(row: dict, box: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = row["bbox"]; cx, cy = (x1+x2)/2, (y1+y2)/2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def font(size: int):
    try: return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except Exception: return None


def local_box(bbox: list[float], tile: tuple[int, int, int, int]) -> list[float]:
    return [bbox[0]-tile[0], bbox[1]-tile[1], bbox[2]-tile[0], bbox[3]-tile[1]]


def prepare_tile(root: Path, output: Path, tile_id: str, tile: tuple[int, int, int, int], texts: list[dict], masks: list[dict]) -> dict:
    target = output / "tiles" / tile_id; target.mkdir(parents=True, exist_ok=True)
    source = Image.open(root / "source.jpg").convert("RGB"); original = source.crop(tile); source.close()
    original_path = target / "original.jpg"; original.save(original_path, quality=94)
    local_texts = [row for row in texts if center_in(row, tile)]
    local_masks = [row for row in masks if center_in(row, tile)]
    label_font = font(max(28, original.width // 60))
    text_view = original.copy(); draw = ImageDraw.Draw(text_view)
    for row in local_texts:
        box = local_box(row["bbox"], tile); draw.rectangle(box, outline="#ffb31f", width=5)
        draw.text((box[0]+4, max(0, box[1]-34)), row["id"], fill="#ffb31f", stroke_width=2, stroke_fill="black", font=label_font)
    text_path = target / "text_ids.jpg"; text_view.save(text_path, quality=92)
    visual_view = original.convert("RGBA"); overlay = np.zeros((original.height, original.width, 4), dtype=np.uint8)
    for index, row in enumerate(local_masks):
        mask = Image.open(root / row["mask_path"]).convert("L").crop(tile)
        selected = np.asarray(mask) > 0
        color = ((37 + index*67) % 210 + 35, (91 + index*43) % 190 + 45, (163 + index*29) % 170 + 65, 105)
        overlay[selected] = color
    visual_view = Image.alpha_composite(visual_view, Image.fromarray(overlay)); draw = ImageDraw.Draw(visual_view, "RGBA")
    for row in local_masks:
        box = local_box(row["bbox"], tile); draw.rectangle(box, outline=(20,245,190,220), width=4)
        draw.text((box[0]+4, max(0, box[1]-34)), row["id"], fill=(20,245,190,255), stroke_width=2, stroke_fill=(0,0,0,255), font=label_font)
    mask_path = target / "mask_ids.jpg"; visual_view.convert("RGB").save(mask_path, quality=92)
    return {
        "tile_id": tile_id, "tile_bbox_source_px": list(tile),
        "images": [str(original_path.resolve()), str(text_path.resolve()), str(mask_path.resolve())],
        "text_candidates": [{"id": r["id"], "text": r["text"], "confidence": r["confidence"]} for r in local_texts],
        "visual_candidates": [{"id": r["id"], "text_overlap": r["text_overlap"], "predicted_iou": r["predicted_iou"]} for r in local_masks],
        "geometry_candidates": [{"id": "GEOMETRY_S_CURVE_001", "kind": "temperature scale curve skeleton", "shared_across_tiles": True}],
    }


def prompt(case: dict) -> str:
    manifest = {key: case[key] for key in ("tile_id", "tile_bbox_source_px", "text_candidates", "visual_candidates", "geometry_candidates")}
    return """Group the retained components in one scientific-poster tile. Image 1 is the unmodified crop; image 2 labels OCR components; image 3 overlays the actual SAM masks and their IDs.

Use only IDs in the manifest. Never invent an ID or a bbox. A scientific evidence group may contain text, one or more visual masks, and the shared curve geometry. A visual and its label/value belong together. Select GEOMETRY_S_CURVE_001 only when the group explicitly marks or points to the temperature scale. Decorative fragments and logos may remain ungrouped. If a required visual or line has no suitable candidate, put it in missing_components instead of selecting an approximate mask.

Return compact JSON only:
{"tile_id":"...","groups":[{"description":"...","member_ids":["STR_...","SAM_..."],"relations":[{"source":"ID","target":"ID","type":"LABELS|MEASURES|MARKS|PART_OF|POINTS_TO|EXPLAINS"}],"complete_in_tile":true,"missing_components":[],"confidence":0.0}],"ungrouped_candidate_ids":["..."],"notes":["..."]}

CANDIDATE MANIFEST:
""" + json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False)+"\n" for row in rows), encoding="utf-8")


def build_report(output: Path, results: list[dict]) -> None:
    cards = []
    for row in results:
        tid = row["tile_id"]; pred = row.get("prediction", {})
        cards.append(f"<section><h2>{html.escape(tid)}</h2><div class='imgs'><figure><img src='tiles/{tid}/original.jpg'><figcaption>original</figcaption></figure><figure><img src='tiles/{tid}/text_ids.jpg'><figcaption>text IDs</figcaption></figure><figure><img src='tiles/{tid}/mask_ids.jpg'><figcaption>actual mask IDs</figcaption></figure></div><pre>{html.escape(json.dumps(pred, ensure_ascii=False, indent=2))}</pre></section>")
    page = "<!doctype html><meta charset=utf-8><title>Component-ID grouping</title><style>body{font:14px system-ui;background:#f3f6f8;margin:22px}section{background:white;padding:16px;margin:20px 0}.imgs{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.imgs img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#17212b;color:#edf3f6;padding:13px}</style><h1>Qwen component-ID grouping</h1><p>The model can link retained IDs but cannot create geometry. Missing candidates are reported explicitly.</p>" + "".join(cards)
    (output / "report.html").write_text(page, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--components", type=Path, required=True); ap.add_argument("--output", type=Path, required=True); ap.add_argument("--model", default=str(PROJECT / "external/models/Qwen3.5-35B-A3B")); ap.add_argument("--max-new-tokens", type=int, default=950); ap.add_argument("--resume", action="store_true")
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    texts = load_jsonl(args.components / "str_text.jsonl"); masks = load_jsonl(args.components / "sam_all_candidates.jsonl")
    cases = [prepare_tile(args.components, args.output, tid, tile, texts, masks) for tid, tile in TILES]
    checkpoint = args.output / "predictions.jsonl"
    existing = {r["tile_id"]: r for r in load_jsonl(checkpoint)} if args.resume and checkpoint.exists() else {}
    llm = TransformersLLM(args.model, dtype="bfloat16", max_new_tokens=args.max_new_tokens, require_cuda=True, enable_thinking=False)
    results = []
    for index, case in enumerate(cases, 1):
        if case["tile_id"] in existing: row = existing[case["tile_id"]]
        else:
            generation = llm.generate_raw_with_images("Ground scientific poster evidence to supplied component IDs. Return valid JSON only.", prompt(case), case["images"], args.max_new_tokens)
            try: prediction = extract_json(generation.raw)
            except Exception as exc: prediction = {"parse_error": str(exc), "raw": generation.raw}
            row = {"tile_id": case["tile_id"], "tile_bbox_source_px": case["tile_bbox_source_px"], "prediction": prediction, "production_modified": False}
            results.append(row); write_jsonl(checkpoint, results)
            print(json.dumps({"tile": index, "tile_id": case["tile_id"], "groups": len(prediction.get("groups", [])) if isinstance(prediction, dict) else 0}), flush=True)
            continue
        results.append(row)
    write_jsonl(args.output / "grouping.jsonl", results); build_report(args.output, results)
    (args.output / "summary.json").write_text(json.dumps({"tiles": len(results), "model": args.model, "group_count": sum(len(r.get("prediction", {}).get("groups", [])) for r in results), "production_modified": False}, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__": main()
