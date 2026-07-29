#!/usr/bin/env python3
"""Render final PDFs into one image per logical page."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def import_fitz():
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for rendering PDFs. Install it with `pip install pymupdf`."
        ) from exc
    return fitz


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_pdf_pages(
    input_pdf: Path,
    out_dir: Path,
    document_id: str,
    render_scale: float,
    image_format: str,
) -> dict[str, Any]:
    if not input_pdf.exists():
        raise FileNotFoundError(f"Input PDF does not exist: {input_pdf}")
    if input_pdf.suffix.lower() != ".pdf":
        raise ValueError(f"Input must be a PDF file: {input_pdf}")

    fitz = import_fitz()
    doc = fitz.open(str(input_pdf))
    if doc.page_count == 0:
        raise ValueError(f"PDF has zero pages: {input_pdf}")

    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    extension = image_format.lower().lstrip(".")
    matrix = fitz.Matrix(render_scale, render_scale)
    rendered_pages: list[dict[str, Any]] = []

    for page_index in range(doc.page_count):
        page = doc[page_index]
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        output_image = pages_dir / f"page_{page_index + 1:06d}.{extension}"
        pix.save(str(output_image))
        rendered_pages.append(
            {
                "page_index": page_index,
                "page_number": page_index + 1,
                "output_image": str(output_image),
                "width": pix.width,
                "height": pix.height,
            }
        )

    doc.close()
    manifest = {
        "document_id": document_id,
        "input_pdf": str(input_pdf),
        "render_source_type": "split_pdf" if input_pdf.stem.endswith("_split") else "original_pdf",
        "output_dir": str(pages_dir),
        "render_scale": render_scale,
        "image_format": extension,
        "page_count": len(rendered_pages),
        "pages": rendered_pages,
    }
    manifest_path = out_dir / "render_manifest.json"
    write_json(manifest_path, manifest)
    manifest["manifest_file"] = str(manifest_path)
    return manifest


def document_id_from_pdf(input_pdf: Path) -> str:
    name = input_pdf.stem
    if name.endswith("_split"):
        return name[: -len("_split")]
    return name


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a final PDF into one image per logical page."
    )
    parser.add_argument("--input", required=True, help="PDF to render.")
    parser.add_argument("--out", required=True, help="Output directory for rendered pages.")
    parser.add_argument("--document-id", default=None, help="Optional document id override.")
    parser.add_argument("--render-scale", type=float, default=1.5, help="PyMuPDF render scale.")
    parser.add_argument(
        "--image-format",
        default="png",
        choices=["png", "jpg", "jpeg"],
        help="Rendered page image format.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.render_scale <= 0:
            raise ValueError("--render-scale must be positive.")

        input_pdf = Path(args.input)
        document_id = args.document_id or document_id_from_pdf(input_pdf)
        manifest = render_pdf_pages(
            input_pdf=input_pdf,
            out_dir=Path(args.out),
            document_id=document_id,
            render_scale=args.render_scale,
            image_format=args.image_format,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
