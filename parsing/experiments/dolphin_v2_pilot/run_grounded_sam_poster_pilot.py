#!/usr/bin/env python3
"""Prompt SAM with selected Grounding DINO boxes on native poster crops."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
import torch
import cv2
from PIL import Image, ImageDraw
from segment_anything import SamPredictor, sam_model_registry


ROOT = Path(__file__).resolve().parents[3]
SELECTED = {"cosmic_xrism": 2, "cosmic_corona": 0, "euclid_spacecraft": 1, "spherex_spacecraft": 0, "milky_sun": 2}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detections", type=Path, required=True)
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dets = {x["case_id"]: x for x in (json.loads(line) for line in args.detections.read_text().splitlines() if line.strip())}
    torch.set_num_threads(4)
    sam = sam_model_registry["vit_b"](checkpoint=str(args.checkpoint))
    sam.to(device="cpu").eval()
    predictor = SamPredictor(sam)
    rows = []
    for cid, detection_index in SELECTED.items():
        row = dets[cid]
        area = args.output / cid
        area.mkdir(exist_ok=True)
        src = Image.open(row["source"]).convert("RGB").crop(tuple(row["crop_source_xyxy"]))
        candidate = row["detections"][detection_index]
        bbox = np.array(candidate["bbox_crop_xyxy"], dtype=np.float32)
        shown = src.copy()
        shown.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
        shown.save(area / "source.jpg", quality=91)
        outline = shown.copy()
        d = ImageDraw.Draw(outline)
        sx, sy = shown.width / src.width, shown.height / src.height
        d.rectangle((bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy), outline="#17d9bc", width=5)
        outline.save(area / "box_prompt.jpg", quality=91)
        result = {"case_id": cid, "target": row["target"], "source": row["source"], "crop_source_xyxy": row["crop_source_xyxy"], "detection_index": detection_index, "detection_label": candidate["label"], "detection_score": candidate["score"], "box_prompt_crop_xyxy": candidate["bbox_crop_xyxy"], "selection": "manually chosen from Grounding DINO candidates for this diagnostic", "production_modified": False}
        try:
            predictor.set_image(np.asarray(src))
            masks, scores, _ = predictor.predict(box=bbox, multimask_output=True)
            result["sam_scores"] = [round(float(x), 4) for x in scores]
            result["mask_fractions"] = [round(float(x.mean()), 4) for x in masks]
            result["largest_component_retained_fraction"] = []
            for index, mask in enumerate(masks):
                Image.fromarray((mask * 255).astype(np.uint8)).save(area / f"mask_{index}.png")
                small = Image.fromarray((mask * 255).astype(np.uint8)).resize(shown.size, Image.Resampling.NEAREST)
                sel = np.asarray(small) > 0
                base = np.asarray(shown, dtype=np.float32)
                base[sel] = base[sel] * 0.48 + np.array([36, 226, 112]) * 0.52
                Image.fromarray(base.astype(np.uint8)).save(area / f"mask_{index}.jpg", quality=91)
                count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
                if count > 1:
                    largest = int(1 + np.argmax(stats[1:, cv2.CC_STAT_AREA]))
                    clean = labels == largest
                else:
                    clean = mask
                result["largest_component_retained_fraction"].append(round(float(clean.sum() / max(1, mask.sum())), 4))
                Image.fromarray((clean * 255).astype(np.uint8)).save(area / f"mask_{index}_largest.png")
                clean_small = Image.fromarray((clean * 255).astype(np.uint8)).resize(shown.size, Image.Resampling.NEAREST)
                clean_sel = np.asarray(clean_small) > 0
                cleaned = np.asarray(shown, dtype=np.float32)
                cleaned[clean_sel] = cleaned[clean_sel] * 0.48 + np.array([36, 226, 112]) * 0.52
                Image.fromarray(cleaned.astype(np.uint8)).save(area / f"mask_{index}_largest.jpg", quality=91)
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    (args.output / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    cards = []
    for row in rows:
        cid = row["case_id"]
        images = [f"<figure><img src='{cid}/source.jpg'><figcaption>Original crop</figcaption></figure>", f"<figure><img src='{cid}/box_prompt.jpg'><figcaption>Grounding DINO box</figcaption></figure>"]
        for index, score in enumerate(row.get("sam_scores", [])):
            images.append(f"<figure><img src='{cid}/mask_{index}.jpg'><figcaption>SAM candidate {index}, predicted score {score}</figcaption></figure>")
            images.append(f"<figure><img src='{cid}/mask_{index}_largest.jpg'><figcaption>Candidate {index}: largest connected region ({row['largest_component_retained_fraction'][index]:.1%} pixels retained)</figcaption></figure>")
        cards.append(f"<section><h2>{html.escape(row['target'])}</h2><p>Selected detector output: {html.escape(row['detection_label'])} ({row['detection_score']}). Box {row['box_prompt_crop_xyxy']}. {html.escape(row.get('error', ''))}</p><div>{''.join(images)}</div></section>")
    page = "<!doctype html><meta charset='utf-8'><title>Grounded SAM poster pilot</title><style>body{font:15px system-ui;margin:2rem;background:#f1f4f7}section{background:white;padding:1rem;margin:1rem 0}section div{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.5rem}figure{margin:0}img{width:100%}p{color:#42515d}</style><h1>Text detection followed by local SAM</h1><p>A detector candidate was manually selected for each case, then supplied as a box prompt to SAM ViT-B on the local crop. Green is the actual predicted mask. Largest-region cleaning is shown alongside each raw candidate. Scores are SAM predictions, not measured accuracy.</p>" + "".join(cards)
    (args.output / "report.html").write_text(page)


if __name__ == "__main__":
    main()
