#!/usr/bin/env python3
"""Recover born-digital PDF text hidden by Dolphin `fig` regions.

This is a shadow audit. Images remain intact; recovered text is emitted as an
overlapping text layer with explicit visual-parent provenance.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT / "parsing/experiments/dolphin_v2_pilot/magazine_documents_v1.json"
DEFAULT_DOLPHIN = PROJECT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1"
DEFAULT_OUTPUT = PROJECT / "parsing/audits/dolphin_visual_overlay_text_v1"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("\u00ad", "")
    text = re.sub(r"-\s+", "", text)
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def intersection_coverage(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = max(1.0, (a[2] - a[0]) * (a[3] - a[1]))
    return inter / area


def center_inside(inner, outer) -> bool:
    x, y = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= x <= outer[2] and outer[1] <= y <= outer[3]


def native_blocks(page: fitz.Page, sx: float, sy: float) -> list[dict]:
    rows = []
    for block_index, block in enumerate(page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])):
        if block.get("type") != 0:
            continue
        lines = []
        for line_index, line in enumerate(block.get("lines", [])):
            spans = [span for span in line.get("spans", []) if str(span.get("text") or "").strip()]
            if not spans:
                continue
            text = "".join(str(span.get("text") or "") for span in spans).strip()
            box = line.get("bbox")
            if not text or not isinstance(box, (list, tuple)):
                continue
            lines.append({
                "line_index": line_index,
                "text": text,
                "bbox": [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy],
                "max_font_size": max(float(span.get("size") or 0) for span in spans),
            })
        if lines:
            rows.append({"native_block_index": block_index, "lines": lines})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--dolphin-root", type=Path, default=DEFAULT_DOLPHIN)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(args.manifest)
    all_rows = []
    document_summaries = []
    cards = []

    for spec in manifest["documents"]:
        doc_id = spec["document_id"]
        pdf = fitz.open(PROJECT / spec["input_pdf"])
        recovered_pages = 0
        recovered_blocks = 0
        recovered_lines = 0
        recovered_tokens = 0
        role_counts = Counter()
        for page_number in range(1, len(pdf) + 1):
            page_id = f"page_{page_number:04d}"
            page_root = args.dolphin_root / doc_id / "pages" / page_id
            result_path = page_root / "output_json" / f"{page_id}.json"
            layout_path = page_root / "layout_visualization" / f"{page_id}_layout.png"
            if not result_path.exists() or not layout_path.exists():
                continue
            elements = read_json(result_path)
            figures = [row for row in elements if row.get("label") == "fig" and isinstance(row.get("bbox"), list)]
            text_elements = [row for row in elements if row.get("label") != "fig" and isinstance(row.get("bbox"), list)]
            if not figures:
                continue
            with Image.open(layout_path) as source:
                image = source.convert("RGB")
            sx, sy = image.width / pdf[page_number - 1].rect.width, image.height / pdf[page_number - 1].rect.height
            dolphin_text = normalize("\n".join(str(row.get("text") or "") for row in text_elements))
            candidates = []
            for native in native_blocks(pdf[page_number - 1], sx, sy):
                grouped: dict[int, list[dict]] = {}
                for line in native["lines"]:
                    normalized = normalize(line["text"])
                    if not normalized:
                        continue
                    parent_candidates = []
                    for figure_index, figure in enumerate(figures):
                        coverage = intersection_coverage(line["bbox"], figure["bbox"])
                        if coverage >= 0.80 or (coverage >= 0.50 and center_inside(line["bbox"], figure["bbox"])):
                            parent_candidates.append((coverage, figure_index))
                    if not parent_candidates:
                        continue
                    if any(intersection_coverage(line["bbox"], row["bbox"]) >= 0.70 for row in text_elements):
                        continue
                    if len(normalized) >= 8 and normalized in dolphin_text:
                        continue
                    coverage, figure_index = max(parent_candidates)
                    grouped.setdefault(figure_index, []).append({**line, "visual_coverage": round(coverage, 5)})
                for figure_index, lines in grouped.items():
                    x1 = min(row["bbox"][0] for row in lines); y1 = min(row["bbox"][1] for row in lines)
                    x2 = max(row["bbox"][2] for row in lines); y2 = max(row["bbox"][3] for row in lines)
                    text = " ".join(row["text"] for row in lines)
                    word_count = len(normalize(text).split())
                    figure = figures[figure_index]
                    figure_area = (figure["bbox"][2] - figure["bbox"][0]) * (figure["bbox"][3] - figure["bbox"][1])
                    page_area = image.width * image.height
                    if max(row["max_font_size"] for row in lines) >= 20:
                        role_hint = "overlay_heading"
                    elif word_count >= 8:
                        role_hint = "overlay_prose_or_caption"
                    else:
                        role_hint = "visual_internal_label"
                    candidates.append({
                        "recovered_text_id": f"{doc_id}_{page_id}_pdftext_{native['native_block_index']:04d}_{figure_index:02d}",
                        "document_id": doc_id,
                        "page": page_id,
                        "text": text,
                        "bbox": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                        "geometry_members": [{"bbox": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)], "bbox_source": "pdf_native_text_layer"}],
                        "source": "pdf_native_text_layer",
                        "confidence": "high",
                        "role_hint": role_hint,
                        "visual_parent": {
                            "dolphin_reading_order": figure.get("reading_order"),
                            "bbox": figure["bbox"],
                            "page_area_fraction": round(figure_area / page_area, 5),
                        },
                        "line_count": len(lines),
                        "word_count": word_count,
                        "non_destructive_policy": "retain_visual_and_add_overlapping_text_layer",
                        "production_modified": False,
                    })
            if not candidates:
                image.close()
                continue
            recovered_pages += 1
            recovered_blocks += len(candidates)
            recovered_lines += sum(row["line_count"] for row in candidates)
            recovered_tokens += sum(row["word_count"] for row in candidates)
            role_counts.update(row["role_hint"] for row in candidates)
            all_rows.extend(candidates)
            draw = ImageDraw.Draw(image)
            for row in candidates:
                draw.rectangle(row["bbox"], outline=(255, 30, 30), width=4)
                draw.text((row["bbox"][0] + 2, max(0, row["bbox"][1] - 14)), row["recovered_text_id"], fill=(210, 0, 0), stroke_width=1, stroke_fill="white")
            target = args.output / doc_id / page_id / "overlay_text_recovery.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target)
            image.close()
            rel = target.relative_to(args.output).as_posix()
            details = html.escape(json.dumps(candidates, ensure_ascii=False, indent=2))
            cards.append(f"<section><h2>{html.escape(doc_id)} · {page_id}</h2><p>Red: PDF-native text missed inside Dolphin fig.</p><img src='{rel}'><details><summary>Recovered records</summary><pre>{details}</pre></details></section>")
        pdf.close()
        document_summaries.append({
            "document_id": doc_id,
            "pages_with_recovery": recovered_pages,
            "recovered_blocks": recovered_blocks,
            "recovered_lines": recovered_lines,
            "recovered_tokens": recovered_tokens,
            "role_hint_distribution": dict(role_counts),
        })
    jsonl = args.output / "recovered_overlay_text.jsonl"
    jsonl.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in all_rows) + ("\n" if all_rows else ""), encoding="utf-8")
    summary = {
        "experiment": "dolphin_visual_overlay_text_shadow_v1",
        "documents": document_summaries,
        "pages_with_recovery": sum(row["pages_with_recovery"] for row in document_summaries),
        "recovered_blocks": len(all_rows),
        "recovered_tokens": sum(row["word_count"] for row in all_rows),
        "policy": "retain Dolphin visual; add missing PDF-native text as overlapping provenance-preserving layer",
        "fallback_not_run": "targeted OCR is only needed when the PDF native text layer is absent",
        "production_modified": False,
    }
    write_json(args.output / "summary.json", summary)
    report = "<!doctype html><html><head><meta charset='utf-8'><title>Dolphin overlay text recovery</title><style>body{font:14px/1.5 system-ui;background:#111827;color:#eef2ff}header,section{max-width:1600px;margin:20px auto;background:#1f2937;padding:18px}img{width:100%;background:white}pre{white-space:pre-wrap;max-height:600px;overflow:auto}</style></head><body>" + f"<header><h1>Dolphin visual-overlay text recovery</h1><pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre></header>" + "".join(cards) + "</body></html>"
    (args.output / "report.html").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
