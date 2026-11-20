#!/usr/bin/env python3
"""Text-guided object detection on the same four-poster diagnostic crops."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import torch
from PIL import Image, ImageDraw
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

from run_florence_poster_multicase import CASES, ROOT, preview


QUERIES = {
    "cosmic_xrism": "spacecraft. satellite.",
    "cosmic_corona": "sun. solar corona.",
    "cosmic_scale": "white curved line. temperature scale.",
    "euclid_spacecraft": "spacecraft. space telescope.",
    "spherex_spacecraft": "spacecraft. space telescope.",
    "spherex_beams": "colored light beams. rainbow light rays.",
    "milky_center": "galaxy center. spiral arm.",
    "milky_sun": "sun. galaxy arm.",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=ROOT / "external/models/grounding-dino-tiny")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "predictions.jsonl"
    records = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            records[row["case_id"]] = row
    torch.set_num_threads(4)
    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(args.model, local_files_only=True).eval()
    for case in CASES:
        cid = case["id"]
        if cid in records and "error" not in records[cid]:
            continue
        target = args.output / cid
        target.mkdir(exist_ok=True)
        crop = Image.open(ROOT / case["image"]).convert("RGB").crop(tuple(case["crop"]))
        work = preview(crop, max_side=1600)
        work.save(target / "source.jpg", quality=92)
        query = QUERIES[cid]
        row = {"case_id": cid, "poster": case["poster"], "target": case["target"], "source": str((ROOT / case["image"]).resolve()), "crop_source_xyxy": case["crop"], "query": query}
        try:
            inputs = processor(images=work, text=query, return_tensors="pt")
            with torch.inference_mode():
                outputs = model(**inputs)
            result = processor.post_process_grounded_object_detection(outputs, inputs.input_ids, threshold=0.25, text_threshold=0.25, target_sizes=[work.size[::-1]])[0]
            row["detections"] = [
                {"label": str(label), "score": round(float(score), 4), "bbox_crop_xyxy": [round(float(x * crop.width / work.width), 1) if index % 2 == 0 else round(float(x * crop.height / work.height), 1) for index, x in enumerate(box)]}
                for label, score, box in zip(result["text_labels"], result["scores"].tolist(), result["boxes"].tolist())
            ]
            drawn = work.copy()
            d = ImageDraw.Draw(drawn)
            for detection in row["detections"]:
                x1, y1, x2, y2 = detection["bbox_crop_xyxy"]
                rect = (x1 * work.width / crop.width, y1 * work.height / crop.height, x2 * work.width / crop.width, y2 * work.height / crop.height)
                d.rectangle(rect, outline="#17d9bc", width=5)
                d.text((rect[0] + 4, max(0, rect[1] - 22)), f"{detection['label']} {detection['score']:.2f}", fill="#17d9bc", stroke_width=2, stroke_fill="black")
            drawn.save(target / "detections.jpg", quality=92)
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        records[cid] = row
        build_report(args.output, records)
        print(json.dumps({"case": cid, "detections": len(row.get("detections", [])), "error": row.get("error")}), flush=True)
    (args.output / "summary.json").write_text(json.dumps({"model": str(args.model), "cases": len(CASES), "completed_cases": len(records), "error_count": sum("error" in row for row in records.values()), "production_modified": False}, indent=2) + "\n")
    build_report(args.output, records)


def build_report(output: Path, records: dict) -> None:
    cards = []
    for case in CASES:
        cid = case["id"]
        row = records.get(cid, {})
        found = row.get("detections", [])
        status = row.get("error") or f"{len(found)} box(es): " + ", ".join(f"{x['label']} ({x['score']:.2f})" for x in found)
        cards.append(f"<section><h2>{html.escape(case['poster'])}: {html.escape(case['target'])}</h2><p>Prompt: {html.escape(QUERIES[cid])} · Source crop {case['crop']}. {html.escape(status)}</p><div><figure><img src='{cid}/source.jpg'><figcaption>Original local crop</figcaption></figure><figure><img src='{cid}/detections.jpg' onerror='this.style.display=\"none\"'><figcaption>Grounding DINO boxes</figcaption></figure></div></section>")
    page = "<!doctype html><meta charset='utf-8'><title>Grounding DINO poster pilot</title><style>body{font:15px system-ui;background:#f1f4f7;margin:2rem}section{background:white;padding:1rem;margin:1rem 0}section div{display:grid;grid-template-columns:repeat(2,1fr);gap:1rem}figure{margin:0}img{width:100%}p{color:#42515d}</style><h1>Text-guided detection across four posters</h1><p>Boxes are generated from hand-selected local crops and English object prompts. They are diagnostic detections, not verified segmentations.</p>" + "".join(cards)
    (output / "report.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
