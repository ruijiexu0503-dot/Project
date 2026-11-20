#!/usr/bin/env python3
"""Visualize the NIST AI RMF Table 1 continuation across PDF pages 27-29."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import pymupdf
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PILOT_ROOT = Path(__file__).resolve().parent
DOCUMENT_ID = "nist_ai_rmf_1_0"
PAGES = [27, 28, 29]
PDF_PATH = PROJECT_ROOT / "data/incoming/government_reports/NIST_AI_100-1_AI_RMF_1.0.pdf"
WORK_ROOT = PILOT_ROOT / "work/government_financial_v1" / DOCUMENT_ID / "pages"
OUTPUT_DIR = PILOT_ROOT / "output/government_financial_v1" / DOCUMENT_ID / "cross_page_table_0027_0029"


def render_page(document: pymupdf.Document, page_number: int) -> Image.Image:
    page = document[page_number - 1]
    scale = 1600 / max(page.rect.width, page.rect.height)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def text_of(element: dict) -> str:
    return element.get("text") or element.get("content") or ""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    page_sections = []

    with pymupdf.open(PDF_PATH) as document:
        for page_number in PAGES:
            page_id = f"page_{page_number:04d}"
            work_page = WORK_ROOT / page_id
            elements = json.loads(
                (work_page / "output_json" / f"{page_id}.json").read_text(encoding="utf-8")
            )
            table_index, table = next(
                (index, element)
                for index, element in enumerate(elements)
                if element.get("label") == "tab"
            )
            captions = [text_of(element) for element in elements if element.get("label") == "cap"]
            source = render_page(document, page_number)
            source_name = f"{page_id}_source.png"
            source.save(OUTPUT_DIR / source_name)

            overlay_name = f"{page_id}_dolphin_layout.png"
            shutil.copy2(
                work_page / "layout_visualization" / f"{page_id}_layout.png",
                OUTPUT_DIR / overlay_name,
            )

            x1, y1, x2, y2 = (int(value) for value in table["bbox"])
            crop_name = f"{page_id}_table_crop.png"
            source.crop((max(0, x1 - 10), max(0, y1 - 10), min(source.width, x2 + 10), min(source.height, y2 + 10))).save(
                OUTPUT_DIR / crop_name
            )

            parsed_name = f"{page_id}_parsed_table.html"
            (OUTPUT_DIR / parsed_name).write_text(
                "<!doctype html><html><head><meta charset='utf-8'><style>"
                "body{margin:12px;color:#172033;font:12px/1.35 system-ui,sans-serif}"
                "table{border-collapse:collapse;width:100%}td,th{border:1px solid #aeb9c9;padding:5px;vertical-align:top}"
                "tr:nth-child(even){background:#f4f7fb}</style></head><body>"
                + text_of(table)
                + "</body></html>",
                encoding="utf-8",
            )

            first_plain = " ".join(html.unescape(text_of(table)).replace("<", " <").split())[:260]
            last_plain = " ".join(html.unescape(text_of(table)).replace("<", " <").split())[-260:]
            record = {
                "page": page_number,
                "table_element_index": table_index,
                "table_bbox": table["bbox"],
                "captions": captions,
                "first_content_preview": first_plain,
                "last_content_preview": last_plain,
            }
            records.append(record)
            page_sections.append(
                f"<section><h2>PDF page {page_number}</h2>"
                f"<p><b>Reading-order element {table_index}</b> · bbox <code>{html.escape(str(table['bbox']))}</code><br>"
                f"Continuation cues: {html.escape(' | '.join(captions) or 'none')}</p>"
                f"<div class='pair'><figure><img src='{source_name}'><figcaption>Original page</figcaption></figure>"
                f"<figure><img src='{overlay_name}'><figcaption>Dolphin-v2 layout/order</figcaption></figure></div>"
                f"<details><summary>Table-only crop and parsed HTML</summary><img class='crop' src='{crop_name}'>"
                f"<iframe src='{parsed_name}'></iframe></details></section>"
            )

    summary = {
        "document_id": DOCUMENT_ID,
        "source_pdf": str(PDF_PATH),
        "pages": PAGES,
        "cross_page_table": "Table 1: Categories and subcategories for the GOVERN function",
        "dolphin_table_elements": 3,
        "cross_page_merged": False,
        "explicit_continuation_cues_preserved": True,
        "split_cell_transition": {
            "from_page": 28,
            "tail": "GOVERN 4: Organizational teams are committed to a culture",
            "to_page": 29,
            "head": "that considers and communicates AI risk.",
        },
        "page_details": records,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dolphin-v2 cross-page table audit · NIST AI RMF</title><style>
body{{margin:0;background:#0b1220;color:#edf4ff;font:15px/1.5 system-ui,sans-serif}}main{{max-width:1800px;margin:auto;padding:24px}}
header,section{{background:#142138;border:1px solid #344a6a;border-radius:12px;padding:18px;margin:16px 0}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
figure{{margin:0}}img{{display:block;width:100%;background:white}}figcaption{{padding:7px;color:#b9c8dc}}code{{color:#cce2ff}}details{{margin-top:14px}}summary{{cursor:pointer;font-weight:700}}
.crop{{margin-top:12px;max-height:850px;object-fit:contain}}iframe{{width:100%;height:620px;border:0;background:white;margin-top:12px}}.warn{{color:#ffd48a}}
@media(max-width:950px){{.pair{{grid-template-columns:1fr}}}}</style></head><body><main><header>
<h1>NIST AI RMF · cross-page Table 1</h1><p>The same table continues across PDF pages 27–29. Dolphin preserves the printed continuation cues, but currently emits three separate page-level <code>tab</code> elements.</p>
<p class="warn"><b>Important split:</b> page 28 ends “GOVERN 4: Organizational teams are committed to a culture”; page 29 begins “that considers and communicates AI risk.” These belong to one cell.</p>
</header>{''.join(page_sections)}</main></body></html>"""
    (OUTPUT_DIR / "report.html").write_text(report, encoding="utf-8")
    print(json.dumps({"report": str(OUTPUT_DIR / "report.html"), **summary}, indent=2))


if __name__ == "__main__":
    main()
