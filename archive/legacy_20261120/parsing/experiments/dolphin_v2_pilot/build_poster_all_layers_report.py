#!/usr/bin/env python3
"""Build an inspectable all-component poster ledger without semantic filtering."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--output", type=Path, required=True); ap.add_argument("--curve-output", type=Path, required=True); args = ap.parse_args()
    text = rows(args.output / "str_text.jsonl"); visuals = rows(args.output / "sam_all_candidates.jsonl")
    source = Image.open(args.output / "source.jpg").convert("RGBA"); width, height = source.size
    skeleton = np.asarray(Image.open(args.curve_output / "s_curve_traced_skeleton.png").convert("L")) > 0
    rgba = np.zeros((height, width, 4), dtype=np.uint8); rgba[skeleton] = (30, 235, 120, 240)
    overlay = Image.alpha_composite(source, Image.fromarray(rgba)); draw = ImageDraw.Draw(overlay, "RGBA")
    for row in text: draw.rectangle(tuple(row["bbox"]), outline=(255, 181, 35, 210), width=4)
    overlay.convert("RGB").save(args.output / "all_layers_overlay.jpg", quality=93)
    geometry = {"id": "GEOMETRY_S_CURVE_001", "kind": "curve_skeleton", "path": "../poster_curve_tracing_diagnostic_v1/s_curve_traced_skeleton.png", "representation": "polyline/skeleton", "status": "diagnostic candidate"}
    ledger = {"source_dimensions": [width, height], "components": {"text": text, "visual_masks": visuals, "geometry": [geometry]}, "policy": "All proposals are retained. Semantic grouping may add links but may not delete components.", "production_modified": False}
    (args.output / "all_components.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    page = "<!doctype html><meta charset=utf-8><title>Poster all-component ledger</title><style>body{font:15px system-ui;max-width:1800px;margin:24px;background:#f5f7f9}section{background:#fff;padding:18px;margin:18px 0;border:1px solid #d6dfe6;border-radius:10px}img{max-width:100%;height:auto;border:1px solid #cad4dc}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#17222c;color:#eaf2f7;padding:14px}</style><h1>Poster all-component ledger</h1><p>Orange: OCR text proposals. Green: S-curve skeleton. Visual masks are retained separately as native-resolution PNGs; none are discarded because they overlap text.</p><section><img src='all_layers_overlay.jpg'></section><section><pre>" + html.escape(json.dumps({"text_components": len(text), "visual_mask_components": len(visuals), "geometry_components": 1, "policy": ledger["policy"]}, ensure_ascii=False, indent=2)) + "</pre></section><section><p><a href='all_components.json'>all_components.json</a> · <a href='sam_all_candidates.jsonl'>all SAM proposals</a> · <a href='str_text.jsonl'>all OCR proposals</a></p></section>"
    (args.output / "report.html").write_text(page, encoding="utf-8")


if __name__ == "__main__": main()
