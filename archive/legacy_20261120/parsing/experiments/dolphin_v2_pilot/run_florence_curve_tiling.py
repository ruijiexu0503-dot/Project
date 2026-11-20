#!/usr/bin/env python3
"""Try full-poster S-curve recovery via overlapping Florence polygons."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw
from transformers import AutoProcessor, Florence2ForConditionalGeneration

from run_florence_poster_multicase import ROOT, each_polygon, preview, render, run_one


TILES = [
    ("top_left", (0, 0, 3500, 3200)), ("top_right", (2000, 0, 5530, 3200)),
    ("middle_left", (0, 2300, 3500, 5800)), ("middle_right", (2000, 2300, 5530, 5800)),
    ("bottom_left", (0, 5000, 3500, 8192)), ("bottom_right", (2000, 5000, 5530, 8192)),
]
SOURCE = ROOT / "data/incoming/non_pdf_posters/nasa_cosmic_temperatures/Cosmic_Temperatures_Infographic_Final_Full.jpg"
TASK = "<REFERRING_EXPRESSION_SEGMENTATION>"
PHRASE = "the thick curved white temperature scale line"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=ROOT / "external/models/Florence-2-large-ft-native")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE).convert("RGB")
    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    model = Florence2ForConditionalGeneration.from_pretrained(args.model, dtype=torch.float16, local_files_only=True).to("cuda").eval()
    merged = Image.new("L", source.size)
    rows = []
    for tid, box in TILES:
        target = args.output / tid
        target.mkdir(exist_ok=True)
        crop = source.crop(box)
        preview(crop).save(target / "original.jpg", quality=91)
        row = {"tile_id": tid, "crop_source_xyxy": box, "prompt": PHRASE}
        try:
            result = run_one(model, processor, crop, TASK, PHRASE, 768)
            row.update(result)
            render(crop, result["answer"], TASK, target / "polygon_overlay.jpg")
            tile_mask = Image.new("L", crop.size)
            draw = ImageDraw.Draw(tile_mask)
            polygons = list(each_polygon(result["answer"].get("polygons", [])))
            for polygon in polygons:
                points = [(polygon[i], polygon[i + 1]) for i in range(0, len(polygon), 2)]
                draw.polygon(points, fill=255)
            merged.paste(Image.fromarray(np.maximum(np.asarray(merged.crop(box)), np.asarray(tile_mask)).astype(np.uint8)), box)
            row["polygon_count"] = len(polygons)
            row["mask_fraction"] = round(float(np.asarray(tile_mask).mean() / 255), 4)
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        print(json.dumps({"tile": tid, "polygons": row.get("polygon_count"), "error": row.get("error")}), flush=True)
    merged.save(args.output / "curve_union_mask.png")
    shown = preview(source, max_side=1800)
    mask_preview = merged.resize(shown.size, Image.Resampling.NEAREST)
    selected = np.asarray(mask_preview) > 0
    base = np.asarray(shown, dtype=np.float32)
    base[selected] = base[selected] * 0.5 + np.array([45, 240, 110]) * 0.5
    Image.fromarray(base.astype(np.uint8)).save(args.output / "full_poster_overlay.jpg", quality=93)
    (args.output / "predictions.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    (args.output / "summary.json").write_text(json.dumps({"tiles": len(TILES), "nonempty_tiles": sum(x.get("polygon_count", 0) > 0 for x in rows), "mask_fraction_of_full_page": round(float(np.asarray(merged).mean() / 255), 4), "error_count": sum("error" in x for x in rows), "manual_anchor_points": 0, "production_modified": False}, indent=2) + "\n")
    cards = []
    for row in rows:
        tid = row["tile_id"]
        cards.append(f"<section><h2>{html.escape(tid)}</h2><p>Polygons: {row.get('polygon_count', 0)} · Mask fraction: {row.get('mask_fraction', 0)}</p><div><img src='{tid}/original.jpg'><img src='{tid}/polygon_overlay.jpg'></div></section>")
    page = "<!doctype html><meta charset='utf-8'><title>Florence full-poster curve tiling</title><style>body{font:15px system-ui;margin:2rem;background:#f1f4f7}section{background:white;padding:1rem;margin:1rem 0}section div{display:grid;grid-template-columns:repeat(2,1fr);gap:.6rem}img{max-width:100%}.full{max-height:1000px}</style><h1>Automatic white-curve recovery over the full poster</h1><p>Florence receives one text phrase on six overlapping image tiles. The colored union is assembled without manual point anchors. Tiling does not guarantee one continuous curve; inspect the full overlay and each tile.</p><img class='full' src='full_poster_overlay.jpg'>" + "".join(cards)
    (args.output / "report.html").write_text(page)


if __name__ == "__main__":
    main()
