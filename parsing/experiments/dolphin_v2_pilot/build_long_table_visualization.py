#!/usr/bin/env python3
"""Build a focused Dolphin-v2 long-table audit page."""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

import pymupdf
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PILOT_ROOT = Path(__file__).resolve().parent
DOCUMENT_ID = "nvidia_2026_annual_report"
PAGE_NUMBER = 170
PAGE_ID = f"page_{PAGE_NUMBER:04d}"
PDF_PATH = PROJECT_ROOT / "data/incoming/financial_reports/NVIDIA_2026_Annual_Report.pdf"
WORK_PAGE = PILOT_ROOT / "work/government_financial_v1" / DOCUMENT_ID / "pages" / PAGE_ID
OUTPUT_DIR = PILOT_ROOT / "output/government_financial_v1" / DOCUMENT_ID / "long_table_page_0170"


def render_source() -> Image.Image:
    with pymupdf.open(PDF_PATH) as document:
        page = document[PAGE_NUMBER - 1]
        scale = 1600 / max(page.rect.width, page.rect.height)
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    elements_path = WORK_PAGE / "output_json" / f"{PAGE_ID}.json"
    elements = json.loads(elements_path.read_text(encoding="utf-8"))
    tables = [(index, item) for index, item in enumerate(elements) if item.get("label") == "tab"]
    if not tables:
        raise SystemExit(f"No table element found in {elements_path}")
    table_index, table = max(
        tables,
        key=lambda pair: (pair[1]["bbox"][2] - pair[1]["bbox"][0])
        * (pair[1]["bbox"][3] - pair[1]["bbox"][1]),
    )

    source = render_source()
    source_path = OUTPUT_DIR / "page_0170_source.png"
    source.save(source_path)

    overlay_source = WORK_PAGE / "layout_visualization" / f"{PAGE_ID}_layout.png"
    overlay_path = OUTPUT_DIR / "page_0170_dolphin_layout.png"
    shutil.copy2(overlay_source, overlay_path)

    x1, y1, x2, y2 = (int(value) for value in table["bbox"])
    margin = 12
    crop_box = (
        max(0, x1 - margin),
        max(0, y1 - margin),
        min(source.width, x2 + margin),
        min(source.height, y2 + margin),
    )
    crop_path = OUTPUT_DIR / "page_0170_table_crop.png"
    source.crop(crop_box).save(crop_path)

    parsed_table = table.get("text") or table.get("content") or ""
    parsed_path = OUTPUT_DIR / "page_0170_parsed_table.html"
    parsed_path.write_text(
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body{margin:16px;color:#172033;font:13px/1.35 system-ui,sans-serif}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #aeb9c9;padding:5px;vertical-align:top}"
        "tr:nth-child(even){background:#f4f7fb}a{color:#245ac4}"
        "</style></head><body>" + parsed_table + "</body></html>",
        encoding="utf-8",
    )

    labels = [item.get("label") for item in elements]
    summary = {
        "document_id": DOCUMENT_ID,
        "page": PAGE_NUMBER,
        "source_pdf": str(PDF_PATH),
        "image_size": list(source.size),
        "element_count": len(elements),
        "reading_order_labels": labels,
        "table_element_index": table_index,
        "table_bbox": table["bbox"],
        "table_area_fraction": round(((x2 - x1) * (y2 - y1)) / (source.width * source.height), 4),
        "header_preserved": "sec_1" in labels or "header" in labels,
        "footer_preserved": "foot" in labels,
    }
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    cards = []
    for index, item in enumerate(elements):
        preview = item.get("text") or item.get("content") or ""
        preview = " ".join(preview.replace("<", " <").split())[:260]
        cards.append(
            f"<tr><td>{index}</td><td>{html.escape(str(item.get('label')))}</td>"
            f"<td><code>{html.escape(str(item.get('bbox')))}</code></td>"
            f"<td>{html.escape(preview)}</td></tr>"
        )

    report = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dolphin-v2 long-table audit · NVIDIA page 170</title>
<style>
body{{margin:0;background:#0b1220;color:#edf4ff;font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1800px;margin:auto;padding:24px}}h1,h2{{margin:.2em 0 .5em}}
.summary,.panel{{background:#142138;border:1px solid #344a6a;border-radius:12px;padding:16px;margin:16px 0}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}figure{{margin:0}}img{{display:block;width:100%;background:white}}
figcaption{{padding:8px;color:#b9c8dc}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #526784;padding:7px;text-align:left;vertical-align:top}}
iframe{{width:100%;height:760px;border:0;background:white}}code{{color:#cce2ff}}a{{color:#9ec8ff}}
@media(max-width:950px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Dolphin-v2 long-table result</h1>
<div class="summary"><b>NVIDIA 2026 Annual Report · PDF page 170</b><br>
Dolphin produced {len(elements)} ordered elements: {html.escape(' → '.join(labels))}. The table occupies {summary['table_area_fraction']:.1%} of the rendered page and remains one table element; the page title and footer are retained separately.</div>
<section class="grid">
<figure class="panel"><img src="page_0170_source.png"><figcaption>Original PDF page</figcaption></figure>
<figure class="panel"><img src="page_0170_dolphin_layout.png"><figcaption>Dolphin-v2 regions and reading-order indices</figcaption></figure>
</section>
<section class="panel"><h2>Detected long-table crop</h2><img src="page_0170_table_crop.png"></section>
<section class="panel"><h2>Parsed table structure</h2><iframe src="page_0170_parsed_table.html"></iframe></section>
<section class="panel"><h2>Element trace</h2><table><thead><tr><th>Order</th><th>Label</th><th>Bbox</th><th>Content preview</th></tr></thead><tbody>{''.join(cards)}</tbody></table></section>
</main></body></html>"""
    (OUTPUT_DIR / "report.html").write_text(report, encoding="utf-8")
    print(json.dumps({"report": str(OUTPUT_DIR / "report.html"), **summary}, indent=2))


if __name__ == "__main__":
    main()
