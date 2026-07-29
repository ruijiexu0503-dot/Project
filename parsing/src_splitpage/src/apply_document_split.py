#!/usr/bin/env python3
"""Apply a document-level split decision to a PDF or rendered page-image folder."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def import_fitz():
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for PDF splitting. Install it with `pip install pymupdf`."
        ) from exc
    return fitz


def import_pil_image():
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for image-folder splitting. Install it with `pip install pillow`."
        ) from exc
    return Image


def natural_sort_key(path: Path) -> list[Any]:
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def read_decision(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Decision JSON does not exist: {path}")
    with path.open("r", encoding="utf-8") as f:
        decision = json.load(f)
    if not isinstance(decision, dict):
        raise ValueError(f"Decision JSON must contain an object: {path}")
    return decision


def validate_split_decision(decision: dict[str, Any]) -> tuple[bool, float]:
    should_split = bool(decision.get("should_split", False))
    if not should_split:
        return False, 0.5

    split_axis = decision.get("split_axis")
    if split_axis != "vertical":
        raise ValueError(f"Only vertical split decisions are supported, got: {split_axis!r}")

    split_position_norm = decision.get("split_position_norm")
    if split_position_norm is None:
        raise ValueError("Split decision is missing split_position_norm.")

    split_position = float(split_position_norm)
    if not 0.0 < split_position < 1.0:
        raise ValueError(f"split_position_norm must be between 0 and 1, got: {split_position}")
    return True, split_position


def document_id_from_input(input_path: Path, decision: dict[str, Any]) -> str:
    document_id = decision.get("document_id")
    if isinstance(document_id, str) and document_id.strip():
        return document_id.strip()
    if input_path.is_file():
        return input_path.stem
    return input_path.name


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_split_to_pdf(
    input_path: Path,
    out_dir: Path,
    document_id: str,
    should_split: bool,
    split_position: float,
    copy_unsplit: bool,
) -> dict[str, Any]:
    fitz = import_fitz()
    src = fitz.open(str(input_path))
    if src.page_count == 0:
        raise ValueError(f"PDF has zero pages: {input_path}")

    out_pdf = out_dir / f"{document_id}_split.pdf"
    manifest_pages: list[dict[str, Any]] = []

    if not should_split:
        if copy_unsplit:
            out_dir.mkdir(parents=True, exist_ok=True)
            out_pdf = out_dir / f"{document_id}.pdf"
            shutil.copy2(input_path, out_pdf)
            operation = "copied_unsplit_pdf"
        else:
            out_pdf = None
            operation = "skipped_no_split_needed"

        return {
            "document_id": document_id,
            "input": str(input_path),
            "operation": operation,
            "should_split": False,
            "output_pdf": str(out_pdf) if out_pdf else None,
            "source_page_count": int(src.page_count),
            "output_page_count": int(src.page_count) if copy_unsplit else 0,
            "pages": manifest_pages,
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    dst = fitz.open()
    for page_index in range(src.page_count):
        page = src[page_index]
        rect = page.rect
        split_x = rect.x0 + rect.width * split_position
        clips = [
            ("left", fitz.Rect(rect.x0, rect.y0, split_x, rect.y1)),
            ("right", fitz.Rect(split_x, rect.y0, rect.x1, rect.y1)),
        ]

        for side, clip in clips:
            out_page = dst.new_page(width=clip.width, height=clip.height)
            out_page.show_pdf_page(out_page.rect, src, page_index, clip=clip)
            manifest_pages.append(
                {
                    "output_page_index": len(manifest_pages),
                    "source_page_index": page_index,
                    "side": side,
                    "clip": {
                        "x0": round(float(clip.x0), 4),
                        "y0": round(float(clip.y0), 4),
                        "x1": round(float(clip.x1), 4),
                        "y1": round(float(clip.y1), 4),
                    },
                }
            )

    dst.save(str(out_pdf), garbage=4, deflate=True)
    dst.close()
    src.close()

    return {
        "document_id": document_id,
        "input": str(input_path),
        "operation": "split_pdf",
        "should_split": True,
        "split_axis": "vertical",
        "split_position_norm": split_position,
        "output_pdf": str(out_pdf),
        "source_page_count": len(manifest_pages) // 2,
        "output_page_count": len(manifest_pages),
        "pages": manifest_pages,
    }


def image_paths(input_path: Path) -> list[Path]:
    images = sorted(
        [p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS],
        key=natural_sort_key,
    )
    if not images:
        raise ValueError(f"No page images found in directory: {input_path}")
    return images


def apply_split_to_image_dir(
    input_path: Path,
    out_dir: Path,
    document_id: str,
    should_split: bool,
    split_position: float,
    copy_unsplit: bool,
    image_format: str,
) -> dict[str, Any]:
    Image = import_pil_image()
    images = image_paths(input_path)
    out_pages_dir = out_dir / "pages"
    manifest_pages: list[dict[str, Any]] = []

    if not should_split:
        if copy_unsplit:
            out_pages_dir.mkdir(parents=True, exist_ok=True)
            for output_index, image_path in enumerate(images):
                suffix = image_path.suffix.lower()
                output_name = f"page_{output_index + 1:06d}{suffix}"
                output_path = out_pages_dir / output_name
                shutil.copy2(image_path, output_path)
                manifest_pages.append(
                    {
                        "output_page_index": output_index,
                        "source_page_index": output_index,
                        "side": "full",
                        "output_image": str(output_path),
                    }
                )
            operation = "copied_unsplit_images"
        else:
            operation = "skipped_no_split_needed"

        return {
            "document_id": document_id,
            "input": str(input_path),
            "operation": operation,
            "should_split": False,
            "output_dir": str(out_pages_dir) if copy_unsplit else None,
            "source_page_count": len(images),
            "output_page_count": len(manifest_pages),
            "pages": manifest_pages,
        }

    out_pages_dir.mkdir(parents=True, exist_ok=True)
    extension = "." + image_format.lower().lstrip(".")

    for page_index, image_path in enumerate(images):
        with Image.open(image_path) as img:
            width, height = img.size
            split_x = int(round(width * split_position))
            crops = [
                ("left", (0, 0, split_x, height)),
                ("right", (split_x, 0, width, height)),
            ]
            for side, box in crops:
                output_index = len(manifest_pages)
                output_path = out_pages_dir / f"page_{output_index + 1:06d}_{side}{extension}"
                cropped = img.crop(box)
                cropped.save(output_path)
                manifest_pages.append(
                    {
                        "output_page_index": output_index,
                        "source_page_index": page_index,
                        "side": side,
                        "output_image": str(output_path),
                        "crop_box": {
                            "left": box[0],
                            "top": box[1],
                            "right": box[2],
                            "bottom": box[3],
                        },
                    }
                )

    return {
        "document_id": document_id,
        "input": str(input_path),
        "operation": "split_images",
        "should_split": True,
        "split_axis": "vertical",
        "split_position_norm": split_position,
        "output_dir": str(out_pages_dir),
        "source_page_count": len(images),
        "output_page_count": len(manifest_pages),
        "pages": manifest_pages,
    }


def apply_split(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input)
    decision_path = Path(args.decision)
    out_dir = Path(args.out)

    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    decision = read_decision(decision_path)
    should_split, split_position = validate_split_decision(decision)
    document_id = args.document_id or document_id_from_input(input_path, decision)

    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        manifest = apply_split_to_pdf(
            input_path=input_path,
            out_dir=out_dir,
            document_id=document_id,
            should_split=should_split,
            split_position=split_position,
            copy_unsplit=args.copy_unsplit,
        )
    elif input_path.is_dir():
        manifest = apply_split_to_image_dir(
            input_path=input_path,
            out_dir=out_dir,
            document_id=document_id,
            should_split=should_split,
            split_position=split_position,
            copy_unsplit=args.copy_unsplit,
            image_format=args.image_format,
        )
    else:
        raise ValueError(f"Input must be a PDF file or image directory: {input_path}")

    manifest["decision_file"] = str(decision_path)
    manifest_path = out_dir / "split_manifest.json"
    write_json(manifest_path, manifest)
    manifest["manifest_file"] = str(manifest_path)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply a split_decision.json file to a PDF or rendered page-image directory."
    )
    parser.add_argument("--input", required=True, help="PDF file or directory of rendered page images.")
    parser.add_argument("--decision", required=True, help="Path to split_decision.json.")
    parser.add_argument("--out", required=True, help="Directory for split output and manifest.")
    parser.add_argument("--document-id", default=None, help="Optional document id override.")
    parser.add_argument(
        "--copy-unsplit",
        action="store_true",
        help="When should_split is false, copy the original PDF/images into the output.",
    )
    parser.add_argument(
        "--image-format",
        default="png",
        choices=["png", "jpg", "jpeg", "webp", "tiff"],
        help="Output format for split images when --input is an image directory.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = apply_split(args)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
