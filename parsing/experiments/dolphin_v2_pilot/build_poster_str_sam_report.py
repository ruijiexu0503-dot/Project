#!/usr/bin/env python3
"""Build a local visual audit for the STR + SAM poster experiment."""
import argparse
import html
import json
import shutil
from pathlib import Path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--output", type=Path, required=True); ap.add_argument("--source", type=Path, required=True); args = ap.parse_args()
    summary = json.loads((args.output / "summary.json").read_text())
    text_rows, masks = rows(args.output / "str_text.jsonl"), rows(args.output / "sam_visual_candidates.jsonl")
    shutil.copy2(args.source, args.output / "source.jpg")
    text_table = "".join(f"<tr><td>{html.escape(r['id'])}</td><td>{r['confidence']:.3f}</td><td>{html.escape(r['text'])}</td><td>{html.escape(str(r['bbox']))}</td></tr>" for r in text_rows)
    mask_table = "".join(f"<tr><td>{html.escape(r['id'])}</td><td>{r['area_pixels']:,}</td><td>{r['text_overlap']:.3f}</td><td>{r['predicted_iou']:.3f}</td><td>{html.escape(str(r['bbox']))}</td></tr>" for r in masks)
    page = f'''<!doctype html><meta charset="utf-8"><title>Poster STR + SAM audit</title>
<style>body{{font:15px system-ui;max-width:1800px;margin:auto;padding:20px;background:#111827;color:#e5e7eb}}h1,h2{{color:white}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}figure{{margin:0}}img{{width:100%;background:#fff}}figcaption{{padding:8px;background:#1f2937}}pre{{background:#1f2937;padding:14px;white-space:pre-wrap}}table{{width:100%;border-collapse:collapse;background:#fff;color:#111827}}th,td{{border:1px solid #cbd5e1;padding:7px;vertical-align:top;text-align:left}}th{{background:#e2e8f0}}.scroll{{max-height:520px;overflow:auto}}@media(max-width:900px){{.pair{{grid-template-columns:1fr}}}}</style>
<h1>NASA Cosmic Temperatures poster — STR + SAM audit</h1>
<p>Orange: EasyOCR text regions. Green: SAM visual candidates whose text-mask overlap is below 20%.</p>
<pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>
<section class="pair"><figure><img src="source.jpg"><figcaption>Original raster</figcaption></figure><figure><img src="overlay.jpg"><figcaption>STR + SAM overlay</figcaption></figure></section>
<h2>Scene text recognition ({len(text_rows)} regions)</h2><section class="scroll"><table><tr><th>ID</th><th>confidence</th><th>text</th><th>source-pixel bbox</th></tr>{text_table}</table></section>
<h2>SAM visual candidates ({len(masks)} regions)</h2><section class="scroll"><table><tr><th>ID</th><th>area</th><th>text overlap</th><th>predicted IoU</th><th>source-pixel bbox</th></tr>{mask_table}</table></section>'''
    (args.output / "report.html").write_text(page, encoding="utf-8")


if __name__ == "__main__": main()
