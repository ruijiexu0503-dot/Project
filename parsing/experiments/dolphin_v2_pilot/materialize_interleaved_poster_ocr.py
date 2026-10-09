#!/usr/bin/env python3
"""Materialize DeepSeekOCR2's interleaved ref/det + content stream.

Unlike the generic markdown-to-bbox zipper, this parser binds each content
chunk to the bbox printed immediately before it. Invalid geometry is retained
as unresolved rather than guessed.
"""

from __future__ import annotations

import argparse
import ast
import html
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PAIR = re.compile(
    r"<\|ref\|>(?P<label>.*?)<\|/ref\|><\|det\|>(?P<det>.*?)<\|/det\|>\s*\n"
    r"(?P<content>.*?)(?=\n<\|ref\|>|\n=+save results:|\Z)",
    re.S,
)


def clean_content(value: str) -> str:
    lines = [line.rstrip() for line in value.strip().splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw = args.log.read_text(encoding="utf-8", errors="replace")
    image = Image.open(args.image).convert("RGB")
    width, height = image.size
    records = []
    for index, match in enumerate(PAIR.finditer(raw)):
        label = match.group("label").strip()
        content = clean_content(match.group("content"))
        unresolved = None
        raw_bbox = None
        pixel_bbox = None
        try:
            parsed = ast.literal_eval(match.group("det").strip())
            raw_bbox = parsed[0] if isinstance(parsed, list) and parsed and isinstance(parsed[0], list) else parsed
            if not (isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4):
                raise ValueError("bbox is not a four-number list")
            x1, y1, x2, y2 = [float(value) for value in raw_bbox]
            if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
                raise ValueError("invalid normalized bbox ordering/range")
            pixel_bbox = [round(x1 / 999 * width), round(y1 / 999 * height), round(x2 / 999 * width), round(y2 / 999 * height)]
        except Exception as exc:  # preserve, never fabricate geometry
            unresolved = str(exc)
        records.append({
            "element_id": f"poster_text_{index:03d}",
            "order": index,
            "type": label,
            "text": content,
            "raw_bbox": raw_bbox,
            "bbox": pixel_bbox,
            "geometry_status": "trustworthy" if pixel_bbox else "unresolved",
            "unresolved_reason": unresolved,
            "visual_parent": "nasa_cosmic_temperatures_poster:fig:0",
            "provenance": "deepseekocr2_interleaved_ref_det_content",
        })

    with (args.output / "grounded_poster_text.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 24)
    except OSError:
        font = None
    for record in records:
        if not record["bbox"]:
            continue
        x1, y1, x2, y2 = record["bbox"]
        draw.rectangle((x1, y1, x2, y2), outline=(255, 60, 60), width=8)
        preview = record["text"].replace("\n", " ")[:38]
        draw.text((x1 + 3, max(0, y1 - 30)), f"T{record['order']:02d} {preview}", fill=(255, 255, 0), stroke_width=3, stroke_fill=(0, 0, 0), font=font)
    overlay = args.output / "grounded_poster_text_overlay.jpg"
    image.save(overlay, quality=90)
    summary = {
        "extracted_pairs": len(records),
        "trustworthy_geometry": sum(record["bbox"] is not None for record in records),
        "unresolved_geometry": sum(record["bbox"] is None for record in records),
        "text_words": sum(len(record["text"].split()) for record in records),
        "visual_parent_retained": True,
        "mapping_policy": "interleaved binding; no positional zip",
        "production_modified": False,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(
        "<tr><td>T{:02d}</td><td>{}</td><td>{}</td><td>{}</td><td><pre>{}</pre></td></tr>".format(
            record["order"], html.escape(record["type"]), record["geometry_status"],
            html.escape(json.dumps(record["bbox"])), html.escape(record["text"]),
        ) for record in records
    )
    style = "<style>body{font:14px/1.45 system-ui;background:#0b1220;color:#eef4ff}header,section{max-width:1600px;margin:18px auto;background:#142138;padding:18px}img{width:100%;background:white}table{border-collapse:collapse;width:100%}td,th{border:1px solid #536987;padding:7px;vertical-align:top}pre{white-space:pre-wrap;word-break:break-word}</style>"
    report = f"<!doctype html><meta charset='utf-8'><title>Grounded poster text</title>{style}<header><h1>Poster text recovery — interleaved provenance</h1><p>The full poster remains the visual parent. Text is attached only to the bbox emitted immediately before that content; invalid geometry remains unresolved.</p><pre>{html.escape(json.dumps(summary, indent=2))}</pre></header><section><img src='{overlay.name}'></section><section><table><thead><tr><th>ID</th><th>type</th><th>geometry</th><th>bbox</th><th>text</th></tr></thead><tbody>{rows}</tbody></table></section>"
    (args.output / "report.html").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
