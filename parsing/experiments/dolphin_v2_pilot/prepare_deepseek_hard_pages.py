#!/usr/bin/env python3
"""Render the fixed Dolphin-v2 hard-page audit set for DeepSeek-OCR2."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_ROOT = Path(__file__).resolve().parent
INPUT_ROOT = EXPERIMENT_ROOT / "work" / "deepseek_hard_pages_v1" / "render_input"
MANIFEST_PATH = EXPERIMENT_ROOT / "work" / "deepseek_hard_pages_v1" / "selection_manifest.json"

SELECTION = {
    "nist_ai_rmf_1_0": {
        "pdf": PROJECT_ROOT / "data" / "incoming" / "government_reports" / "NIST_AI_100-1_AI_RMF_1.0.pdf",
        "pages": {
            10: "figure-rich mixed text/graphic page",
            27: "dense table and explanatory-text page",
        },
    },
    "nvidia_2026_annual_report": {
        "pdf": PROJECT_ROOT / "data" / "incoming" / "financial_reports" / "NVIDIA_2026_Annual_Report.pdf",
        "pages": {
            5: "known Dolphin distorted_page collapse: full-page background plus overlaid text",
            20: "structured meeting notice with an empty signature/decorative Dolphin element",
            35: "figure-heavy layout: eight figure regions and 29 elements",
            88: "dense financial/table layout with an empty signature/decorative Dolphin element",
            89: "very dense layout: 39 Dolphin elements",
            142: "landscape page with non-standard geometry",
        },
    },
}


def render_page(pdf_path: Path, page_number: int, output_path: Path, max_side: int = 1600) -> tuple[int, int]:
    with fitz.open(pdf_path) as document:
        page = document[page_number - 1]
        scale = max_side / max(page.rect.width, page.rect.height)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return image.size


def main() -> None:
    records = []
    for document_id, spec in SELECTION.items():
        pdf_path = spec["pdf"]
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)
        for page_number, reason in spec["pages"].items():
            output_path = INPUT_ROOT / document_id / "pages" / f"page_{page_number:06d}.png"
            width, height = render_page(pdf_path, page_number, output_path)
            records.append(
                {
                    "document_id": document_id,
                    "source_pdf": str(pdf_path),
                    "page": page_number,
                    "reason": reason,
                    "image": str(output_path),
                    "image_size": [width, height],
                }
            )

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps({"selection_version": "dolphin_hard_pages_v1", "pages": records}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"rendered_pages": len(records), "manifest": str(MANIFEST_PATH)}, indent=2))


if __name__ == "__main__":
    main()
