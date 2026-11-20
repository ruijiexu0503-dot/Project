#!/usr/bin/env python3
"""Publish a compact audit of raster-only poster text recovery."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deepseek-root", type=Path, required=True)
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    page = args.deepseek_root / "nasa_cosmic_temperatures_poster" / "page_0001"
    elements_payload = json.loads((page / "elements.json").read_text(encoding="utf-8"))
    elements = elements_payload.get("elements", [])
    args.output.mkdir(parents=True, exist_ok=True)
    source_target = args.output / "poster_source.jpg"
    shutil.copy2(args.source_image, source_target)
    preview_source = page / "bboxes_preview.jpg"
    preview_target = args.output / "deepseek_text_blocks.jpg"
    if preview_source.exists():
        shutil.copy2(preview_source, preview_target)
    type_distribution = Counter(str(item.get("type", "unknown")) for item in elements)
    recovered = [item for item in elements if str(item.get("text", "")).strip()]
    summary = {
        "input_format": "native_jpeg",
        "dolphin_result": {"elements": 1, "types": {"fig": 1}, "recovered_text_blocks": 0},
        "deepseek_result": {
            "elements": len(elements),
            "text_bearing_elements": len(recovered),
            "type_distribution": dict(type_distribution),
            "recovered_words": sum(len(str(item.get("text", "")).split()) for item in recovered),
            "recovered_characters": sum(len(str(item.get("text", ""))) for item in recovered),
            "elements_with_bbox": sum(bool(item.get("bbox")) for item in elements),
        },
        "geometry_policy": "full poster remains visual parent; recovered text blocks are overlapping children with their own bboxes",
        "production_modified": False,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output / "recovered_elements.jsonl").open("w", encoding="utf-8") as handle:
        for item in elements:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td><pre>{}</pre></td></tr>".format(
            html.escape(str(item.get("order", ""))),
            html.escape(str(item.get("type", ""))),
            html.escape(json.dumps(item.get("bbox"), ensure_ascii=False)),
            html.escape(str(item.get("text", ""))),
        )
        for item in elements
    )
    preview = "<img src='deepseek_text_blocks.jpg'>" if preview_target.exists() else "<p>No preview generated.</p>"
    style = """<style>body{font:14px/1.45 system-ui;background:#0b1220;color:#eef4ff;margin:0}header,section{max-width:1600px;margin:18px auto;background:#142138;padding:18px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}img{width:100%;background:white}table{border-collapse:collapse;width:100%}td,th{border:1px solid #536987;padding:7px;vertical-align:top}pre{white-space:pre-wrap;word-break:break-word}@media(max-width:950px){.pair{grid-template-columns:1fr}}</style>"""
    report = f"<!doctype html><meta charset='utf-8'><title>Poster raster text recovery</title>{style}<header><h1>Native JPEG poster: text recovery audit</h1><p>Dolphin visual parent is retained. DeepSeekOCR2 text elements are added as overlapping children; the poster is not destructively split.</p><pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre></header><section><div class='pair'><figure><img src='poster_source.jpg'><figcaption>Native JPEG source / retained visual parent</figcaption></figure><figure>{preview}<figcaption>Recovered text/layout boxes</figcaption></figure></div></section><section><h2>Recovered elements</h2><table><thead><tr><th>order</th><th>type</th><th>bbox</th><th>text</th></tr></thead><tbody>{rows}</tbody></table></section>"
    (args.output / "report.html").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
