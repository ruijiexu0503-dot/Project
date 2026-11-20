#!/usr/bin/env python3
"""Build an offline review page from existing Dolphin-v2 scientific outputs."""
from __future__ import annotations

import base64
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / "parsing/experiments/dolphin_v2_pilot/work"
OUT = ROOT / "parsing/audits/dolphin_scientific_paper_results_v1"
CASES = [
    ("GW150914", "gw150914_page_0002", "parsing/output/deepseekocr2_split_render/gw150914_detection/page_0002/result_with_boxes.jpg"),
    ("GW150914", "gw150914_page_0004", "parsing/output/deepseekocr2_split_render/gw150914_detection/page_0004/result_with_boxes.jpg"),
    ("DETR", "detr_page_0003", "parsing/output/deepseekocr2_split_render/detr/page_0003/result_with_boxes.jpg"),
    ("DETR", "detr_page_0012", "parsing/output/deepseekocr2_split_render/detr/page_0012/result_with_boxes.jpg"),
    ("Climate Change with ML", "climate_ml_page_0005", "parsing/output/deepseekocr2_split_render/climate_change_with_ml/page_0005/result_with_boxes.jpg"),
    ("Climate Change with ML", "climate_ml_page_0020", "parsing/output/deepseekocr2_split_render/climate_change_with_ml/page_0020/result_with_boxes.jpg"),
    ("Hallmarks of Aging", "hallmarks_page_0004", "parsing/output/deepseekocr2_split_render/hallmarks_of_aging/page_0004/result_with_boxes.jpg"),
    ("Hallmarks of Aging", "hallmarks_page_0018", "parsing/output/deepseekocr2_split_render/hallmarks_of_aging/page_0018/result_with_boxes.jpg"),
    ("Entropy", "entropy_page_0010", "parsing/output/deepseekocr2_split_render/entropy/page_0010/result_with_boxes.jpg"),
]


def data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records, cards = [], []
    for document, case_id, deepseek_rel in CASES:
        case = WORK / case_id
        summary_path = case / "run_summary.json"
        if not summary_path.exists():
            records.append({"document": document, "case_id": case_id, "status": "pending"})
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        elements = json.loads((case / "output_json" / f"{case_id}.json").read_text(encoding="utf-8"))
        overlay = case / "layout_visualization" / f"{case_id}_layout.png"
        deepseek = ROOT / deepseek_rel
        rows = "".join(
            f"<tr><td>{e.get('reading_order','—')}</td><td>{html.escape(str(e.get('label','')))}</td>"
            f"<td>{html.escape(str(e.get('bbox','')))}</td><td>{html.escape(str(e.get('text',''))[:240])}</td></tr>"
            for e in elements
        )
        comparison = (
            f"<div><h3>DeepSeek OCR boxes</h3><img src='{data_url(deepseek)}'></div>"
            if deepseek.exists() else "<div><h3>DeepSeek overlay unavailable</h3></div>"
        )
        cards.append(
            f"<section><h2>{html.escape(document)} · {html.escape(case_id)}</h2>"
            f"<p>{summary['element_count']} elements · {summary['elapsed_seconds']:.1f}s · labels: "
            f"{html.escape(json.dumps(summary['label_distribution']))}</p>"
            f"<div class='pair'><div><h3>Dolphin-v2</h3><img src='{data_url(overlay)}'></div>{comparison}</div>"
            f"<details><summary>Dolphin elements and reading order</summary><table><thead><tr>"
            f"<th>Order</th><th>Label</th><th>Bbox</th><th>Content preview</th></tr></thead><tbody>{rows}</tbody></table></details></section>"
        )
        records.append({"document": document, "case_id": case_id, **summary})
    (OUT / "summary.json").write_text(json.dumps({"production_modified": False, "cases": records}, indent=2), encoding="utf-8")
    css = """<style>body{font:14px/1.45 system-ui;background:#eef2f6;margin:20px;color:#18212b}header,section{max-width:1500px;margin:18px auto;background:white;padding:18px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair img{width:100%;border:1px solid #aab4c0}table{width:100%;border-collapse:collapse}th,td{border:1px solid #ccd4df;padding:7px;text-align:left;vertical-align:top}@media(max-width:900px){.pair{grid-template-columns:1fr}}</style>"""
    pending = [r["case_id"] for r in records if r.get("status") == "pending"]
    body = f"<!doctype html><meta charset='utf-8'><title>Dolphin scientific-paper results</title>{css}<header><h1>Dolphin-v2 scientific-paper parsing</h1><p>Existing isolated outputs; Dolphin and DeepSeek overlays are shown side by side. Pending: {html.escape(', '.join(pending) or 'none')}.</p></header>{''.join(cards)}"
    (OUT / "report.html").write_text(body, encoding="utf-8")
    print(json.dumps({"complete": len(cards), "pending": pending, "report": str(OUT / 'report.html')}))


if __name__ == "__main__":
    main()
