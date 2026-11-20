#!/usr/bin/env python3
"""Build a compact offline audit for native-raster Dolphin poster cases."""

from __future__ import annotations

import argparse
import html
import json
import shutil
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.cases.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    cards, summaries = [], []
    for case in manifest["cases"]:
        case_id = case["case_id"]
        case_dir = args.work / case_id
        summary = json.loads((case_dir / "run_summary.json").read_text(encoding="utf-8"))
        parsed = json.loads((case_dir / "output_json" / f"{case_id}.json").read_text(encoding="utf-8"))
        elements = parsed if isinstance(parsed, list) else parsed.get("elements", parsed.get("content", []))
        labels = Counter(str(row.get("label", "UNKNOWN")) for row in elements)
        overlay_src = case_dir / "layout_visualization" / f"{case_id}_layout.png"
        overlay_dst = args.output / f"{case_id}_layout.png"
        shutil.copy2(overlay_src, overlay_dst)
        source = Path(__file__).resolve().parents[3] / case["input_image"]
        source_dst = args.output / f"{case_id}_source.jpg"
        shutil.copy2(source, source_dst)
        rows = "".join(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td><pre>{}</pre></td></tr>".format(
                index,
                html.escape(str(row.get("label", ""))),
                html.escape(json.dumps(row.get("bbox"), ensure_ascii=False)),
                html.escape(str(row.get("text", ""))[:700]),
            )
            for index, row in enumerate(elements)
        )
        result = {
            **summary,
            "input_format": case.get("input_format"),
            "source_image": case["input_image"],
            "label_distribution_recomputed": dict(labels),
            "production_modified": False,
        }
        summaries.append(result)
        cards.append(
            f"<section><h2>{html.escape(case_id)}</h2>"
            f"<pre>{html.escape(json.dumps(result, ensure_ascii=False, indent=2))}</pre>"
            f"<div class='pair'><figure><img src='{source_dst.name}'><figcaption>Native JPEG input</figcaption></figure>"
            f"<figure><img src='{overlay_dst.name}'><figcaption>Dolphin-v2 layout and reading order</figcaption></figure></div>"
            f"<details><summary>Parsed elements</summary><table><thead><tr><th>#</th><th>label</th><th>bbox</th><th>text</th></tr></thead><tbody>{rows}</tbody></table></details></section>"
        )
    output_summary = {
        "experiment": manifest["experiment"],
        "cases": summaries,
        "production_modified": False,
    }
    (args.output / "summary.json").write_text(json.dumps(output_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    css = """<style>body{font:14px/1.45 system-ui;background:#111827;color:#eef2ff;margin:0}header,section{max-width:1500px;margin:20px auto;background:#1f2937;padding:18px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}img{width:100%;background:white}table{border-collapse:collapse;width:100%}td,th{border:1px solid #64748b;padding:6px;vertical-align:top}pre{white-space:pre-wrap;word-break:break-word}@media(max-width:900px){.pair{grid-template-columns:1fr}}</style>"""
    report = f"<!doctype html><meta charset='utf-8'><title>Native JPEG poster audit</title>{css}<header><h1>Dolphin-v2 native JPEG poster audit</h1><p>The source is a JPEG supplied directly to the parser; no PDF rendering or PDF-native recovery is involved.</p></header>{''.join(cards)}"
    (args.output / "report.html").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
