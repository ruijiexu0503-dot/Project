#!/usr/bin/env python3
"""Render an inspectable gallery for every retained SAM mask."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--output", type=Path, required=True); args = ap.parse_args()
    rows = [json.loads(line) for line in (args.output / "sam_all_candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    preview_dir = args.output / "mask_previews"; preview_dir.mkdir(exist_ok=True)
    source = Image.open(args.output / "source.jpg").convert("RGBA")
    cards = []
    for row in rows:
        x1, y1, x2, y2 = (int(value) for value in row["bbox"])
        pad = max(80, int(max(x2 - x1, y2 - y1) * .12))
        crop_box = (max(0, x1-pad), max(0, y1-pad), min(source.width, x2+pad), min(source.height, y2+pad))
        base = source.crop(crop_box)
        mask = Image.open(args.output / row["mask_path"]).convert("L").crop(crop_box)
        scale = min(1.0, 680 / max(base.size)); preview_size = (round(base.width * scale), round(base.height * scale))
        base = base.resize(preview_size, Image.Resampling.LANCZOS)
        mask = mask.resize(preview_size, Image.Resampling.NEAREST)
        selected = np.asarray(mask) > 0
        color = np.zeros((preview_size[1], preview_size[0], 4), dtype=np.uint8); color[selected] = (20, 235, 170, 125)
        preview = Image.alpha_composite(base, Image.fromarray(color))
        filename = f"{row['id']}.jpg"; preview.convert("RGB").save(preview_dir / filename, quality=87)
        cards.append("<article><img src='mask_previews/" + filename + "'><h2>" + row["id"] + "</h2><p>area: " + str(row["area_pixels"]) + " px<br>text overlap: " + str(row["text_overlap"]) + "<br>IoU: " + str(row["predicted_iou"]) + "<br>stability: " + str(row["stability_score"]) + "</p></article>")
    source.close()
    page = "<!doctype html><meta charset=utf-8><title>SAM mask gallery</title><style>body{font:14px system-ui;background:#f3f6f8;margin:24px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}article{background:#fff;padding:12px;border:1px solid #d5dfe6;border-radius:9px}article img{width:100%;border:1px solid #c7d2db}h1{margin-bottom:4px}h2{font-size:16px;margin:8px 0 2px}p{color:#41505b}</style><h1>All retained SAM masks</h1><p>Each card is automatically cropped around one candidate. Cyan is the actual binary mask over that local original-image crop. Every candidate is retained, including masks that overlap text.</p><main>" + "".join(cards) + "</main>"
    (args.output / "mask_gallery.html").write_text(page, encoding="utf-8")


if __name__ == "__main__": main()
