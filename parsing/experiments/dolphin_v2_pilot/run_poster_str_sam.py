#!/usr/bin/env python3
"""STR + SAM shadow decomposition for the native NASA poster raster.

Text is detected/recognized first. SAM masks are then measured against the text
mask so that text is retained as grounded child evidence rather than swallowed
by a visual segment. No source image or production graph is changed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import easyocr
import numpy as np
import torch
from PIL import Image, ImageDraw
from segment_anything import SamAutomaticMaskGenerator, sam_model_registry


def box(rect):
    points = np.asarray(rect, dtype=float)
    return [round(float(points[:, 0].min()), 2), round(float(points[:, 1].min()), 2),
            round(float(points[:, 0].max()), 2), round(float(points[:, 1].max()), 2)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=Path, required=True)
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--easyocr-models", type=Path, required=True)
    ap.add_argument("--sam-max-side", type=int, default=1536)
    ap.add_argument("--save-mask-png", action="store_true", help="Persist every SAM candidate's native-resolution mask.")
    ap.add_argument("--retain-text-overlap", action="store_true", help="Keep text-overlapping masks as visual proposals instead of rejecting them.")
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    native = np.asarray(Image.open(args.image).convert("RGB")); h, w = native.shape[:2]
    Image.fromarray(native).save(args.output / "source.jpg", quality=94)
    # STR uses a moderately large raster; SAM receives a resized copy, with all
    # geometry mapped back to the unmodified source raster.
    str_scale = min(1.0, 3200 / max(h, w)); str_image = cv2.resize(native, (round(w * str_scale), round(h * str_scale))) if str_scale < 1 else native
    reader = easyocr.Reader(["en"], gpu=torch.cuda.is_available(), model_storage_directory=str(args.easyocr_models), download_enabled=False, verbose=False)
    recognized = reader.readtext(str_image, detail=1, paragraph=False, mag_ratio=1.5, text_threshold=0.55, low_text=0.3, link_threshold=0.35)
    text_rows = [{"id": f"STR_{i:03d}", "text": value, "confidence": round(float(confidence), 4),
                  "bbox": [round(v / str_scale, 2) for v in box(rect)]}
                 for i, (rect, value, confidence) in enumerate(recognized, 1) if value.strip()]
    text_mask = np.zeros((h, w), dtype=np.uint8)
    for row in text_rows:
        x1, y1, x2, y2 = map(int, row["bbox"]); pad = max(3, int((y2-y1) * .12))
        cv2.rectangle(text_mask, (max(0, x1-pad), max(0, y1-pad)), (min(w, x2+pad), min(h, y2+pad)), 1, -1)
    sam_scale = min(1.0, args.sam_max_side / max(h, w)); sam_image = cv2.resize(native, (round(w * sam_scale), round(h * sam_scale))) if sam_scale < 1 else native
    device = "cuda" if torch.cuda.is_available() else "cpu"
    sam = sam_model_registry["vit_b"](checkpoint=str(args.checkpoint)); sam.to(device=device)
    masks = SamAutomaticMaskGenerator(sam, points_per_side=24, pred_iou_thresh=0.88, stability_score_thresh=0.92,
                                     crop_n_layers=1, crop_n_points_downscale_factor=2, min_mask_region_area=120).generate(sam_image)
    visual_rows = []
    all_mask_rows = []
    mask_dir = args.output / "sam_masks"
    if args.save_mask_png: mask_dir.mkdir(exist_ok=True)
    for i, mask in enumerate(masks, 1):
        segmentation = cv2.resize(mask["segmentation"].astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
        area = int(segmentation.sum())
        if area < 600: continue
        overlap = float((segmentation & text_mask.astype(bool)).sum() / area)
        x, y, bw, bh = mask["bbox"]
        row = {"id": f"SAM_{i:04d}", "bbox": [round(x/sam_scale, 2), round(y/sam_scale, 2), round((x+bw)/sam_scale, 2), round((y+bh)/sam_scale, 2)],
               "area_pixels": area, "text_overlap": round(overlap, 4), "predicted_iou": round(float(mask["predicted_iou"]), 4),
               "stability_score": round(float(mask["stability_score"]), 4),
               "role": "TEXT_DOMINATED_REJECT" if overlap >= .20 else "VISUAL_CANDIDATE"}
        if args.save_mask_png:
            mask_path = mask_dir / f"{row['id']}.png"
            Image.fromarray((segmentation * 255).astype(np.uint8)).save(mask_path)
            row["mask_path"] = str(mask_path.relative_to(args.output))
        all_mask_rows.append(row)
        if row["role"] == "VISUAL_CANDIDATE" or args.retain_text_overlap: visual_rows.append(row)
    visual_rows.sort(key=lambda r: (-r["area_pixels"], r["id"]))
    overlay = Image.fromarray(native).convert("RGBA"); draw = ImageDraw.Draw(overlay, "RGBA")
    for row in visual_rows[:80]:
        x1, y1, x2, y2 = row["bbox"]; draw.rectangle((x1,y1,x2,y2), outline=(40,220,170,210), width=4)
    for row in text_rows:
        draw.rectangle(tuple(row["bbox"]), outline=(255,190,30,235), width=4)
    overlay.convert("RGB").save(args.output / "overlay.jpg", quality=92)
    (args.output / "str_text.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in text_rows))
    (args.output / "sam_visual_candidates.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in visual_rows))
    (args.output / "sam_all_candidates.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False)+"\n" for r in all_mask_rows))
    summary = {"source": str(args.image.resolve()), "source_dimensions": [w,h], "str_scale": str_scale, "sam_scale": sam_scale,
               "str_text_regions": len(text_rows), "str_words": sum(len(r["text"].split()) for r in text_rows),
               "sam_raw_masks": len(masks), "sam_retained_candidates": len(visual_rows), "sam_all_candidates": len(all_mask_rows),
               "text_mask_policy": "Text-overlapping masks retained" if args.retain_text_overlap else "SAM masks with >=20% text-mask overlap are rejected",
               "mask_png_saved": args.save_mask_png, "production_modified": False}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
