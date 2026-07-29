#!/usr/bin/env python3
"""Build structured element JSON from DeepSeekOCR2 markdown + bbox outputs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def natural_sort_key(path: Path) -> list[Any]:
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def page_number_from_dir(page_dir: Path, fallback: int) -> int:
    match = re.search(r"page_(\d+)", page_dir.name)
    if match:
        return int(match.group(1))
    return fallback


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def markdown_type_for_heading(level: int) -> str:
    return "title" if level == 1 else "sub_title"


def parse_markdown_blocks(markdown: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    paragraph_lines: list[str] = []
    pending_heading: dict[str, Any] | None = None

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        text = clean_text(" ".join(paragraph_lines))
        paragraph_lines.clear()
        if text:
            blocks.append({"type": "text", "text": text})

    def flush_heading() -> None:
        nonlocal pending_heading
        if pending_heading:
            blocks.append(pending_heading)
            pending_heading = None

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flush_heading()
            flush_paragraph()
            continue

        image_match = re.fullmatch(r"!\[[^\]]*\]\(([^)]+)\)", line)
        if image_match:
            flush_heading()
            flush_paragraph()
            blocks.append(
                {
                    "type": "image",
                    "text": "",
                    "image_path": image_match.group(1),
                }
            )
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match:
            flush_heading()
            flush_paragraph()
            level = len(heading_match.group(1))
            pending_heading = {
                "type": markdown_type_for_heading(level),
                "text": clean_text(heading_match.group(2)),
                "markdown_level": level,
            }
            continue

        if pending_heading and len(line) <= 80:
            pending_heading["text"] = clean_text(f"{pending_heading['text']} {line}")
            continue

        flush_heading()
        paragraph_lines.append(line)

    flush_heading()
    flush_paragraph()
    return blocks


def normalize_element_type(label: Any) -> str:
    value = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
    if value in {"title", "doc_title", "paragraph_title"}:
        return "title"
    if value in {"subtitle", "sub_title", "section_title", "heading"}:
        return "sub_title"
    if value in {"figure", "fig", "picture", "photo"}:
        return "image"
    if value in {"table", "table_body"}:
        return "table"
    if value in {"formula", "equation"}:
        return "formula"
    return value or "unknown"


def compatible(markdown_block: dict[str, Any], bbox_type: str) -> bool:
    md_type = markdown_block.get("type")
    if bbox_type == "image":
        return md_type == "image"
    if bbox_type in {"title", "sub_title"}:
        return md_type in {"title", "sub_title"}
    if bbox_type in {"text", "table", "formula", "unknown"}:
        return md_type not in {"image"}
    return True


def bbox_norm(pixel_bbox: Any, width: float, height: float) -> list[float] | None:
    if not isinstance(pixel_bbox, list) or len(pixel_bbox) < 4 or width <= 0 or height <= 0:
        return None
    try:
        x0, y0, x1, y1 = [float(value) for value in pixel_bbox[:4]]
    except Exception:
        return None
    return [
        round(max(0.0, min(1.0, x0 / width)), 6),
        round(max(0.0, min(1.0, y0 / height)), 6),
        round(max(0.0, min(1.0, x1 / width)), 6),
        round(max(0.0, min(1.0, y1 / height)), 6),
    ]


def page_size_from_bbox_items(items: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    for item in items:
        width = item.get("image_width")
        height = item.get("image_height")
        if width and height:
            return int(width), int(height)
    return None, None


def sorted_bbox_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[int, float, float]:
        pixel_bbox = item.get("pixel_bbox")
        if isinstance(pixel_bbox, list) and len(pixel_bbox) >= 2:
            y0 = float(pixel_bbox[1])
            x0 = float(pixel_bbox[0])
        else:
            y0 = 0.0
            x0 = 0.0
        item_id = item.get("id")
        return (int(item_id) if isinstance(item_id, int) else 10**9, y0, x0)

    return sorted(items, key=key)


def build_page_elements(doc_id: str, page_dir: Path, fallback_page_no: int) -> dict[str, Any]:
    bbox_path = page_dir / "bbox_items.json"
    md_path = page_dir / "ocr.md"

    bbox_items: list[dict[str, Any]] = []
    if bbox_path.exists():
        raw_items = json.loads(bbox_path.read_text(encoding="utf-8"))
        if isinstance(raw_items, list):
            bbox_items = [item for item in raw_items if isinstance(item, dict)]

    markdown = md_path.read_text(encoding="utf-8", errors="ignore") if md_path.exists() else ""
    markdown_blocks = parse_markdown_blocks(markdown)

    page_width, page_height = page_size_from_bbox_items(bbox_items)
    page_no = page_number_from_dir(page_dir, fallback_page_no)
    page_name = page_dir.name
    md_cursor = 0
    consumed_md: set[int] = set()
    elements: list[dict[str, Any]] = []

    for item in sorted_bbox_items(bbox_items):
        element_type = normalize_element_type(item.get("text"))
        matched_block: dict[str, Any] | None = None
        matched_idx: int | None = None

        for idx in range(md_cursor, len(markdown_blocks)):
            if idx in consumed_md:
                continue
            if compatible(markdown_blocks[idx], element_type):
                matched_block = markdown_blocks[idx]
                matched_idx = idx
                break

        if matched_idx is not None:
            consumed_md.add(matched_idx)
            md_cursor = matched_idx + 1

        pixel_bbox = item.get("pixel_bbox")
        if isinstance(pixel_bbox, list) and len(pixel_bbox) >= 4:
            bbox = [int(round(float(value))) for value in pixel_bbox[:4]]
        else:
            bbox = None

        element: dict[str, Any] = {
            "element_id": f"{page_name}_el_{len(elements) + 1:04d}",
            "order": len(elements) + 1,
            "type": element_type,
            "text": clean_text(str(matched_block.get("text") or "")) if matched_block else "",
            "bbox": bbox,
            "bbox_norm": bbox_norm(pixel_bbox, float(page_width or 0), float(page_height or 0)),
        }
        if matched_block:
            if "markdown_level" in matched_block:
                element["markdown_level"] = matched_block["markdown_level"]
            if "image_path" in matched_block:
                element["image_path"] = matched_block["image_path"]
        if item.get("raw_bbox") is not None:
            element["raw_bbox"] = item["raw_bbox"]

        elements.append(element)

    for idx, block in enumerate(markdown_blocks):
        if idx in consumed_md:
            continue
        element = {
            "element_id": f"{page_name}_el_{len(elements) + 1:04d}",
            "order": len(elements) + 1,
            "type": block.get("type") or "text",
            "text": clean_text(str(block.get("text") or "")),
            "bbox": None,
            "bbox_norm": None,
        }
        if "markdown_level" in block:
            element["markdown_level"] = block["markdown_level"]
        if "image_path" in block:
            element["image_path"] = block["image_path"]
        elements.append(element)

    return {
        "doc_id": doc_id,
        "page": page_no,
        "page_name": page_name,
        "page_width": page_width,
        "page_height": page_height,
        "elements": elements,
    }


def iter_doc_dirs(input_root: Path, doc_id: str | None) -> list[Path]:
    if doc_id:
        return [input_root / doc_id]
    return sorted([path for path in input_root.iterdir() if path.is_dir()], key=natural_sort_key)


def build_for_doc(doc_dir: Path, output_name: str, overwrite: bool) -> tuple[int, int]:
    page_dirs = sorted([path for path in doc_dir.glob("page_*") if path.is_dir()], key=natural_sort_key)
    written = 0
    skipped = 0
    for fallback_idx, page_dir in enumerate(page_dirs, start=1):
        out_path = page_dir / output_name
        if out_path.exists() and not overwrite:
            skipped += 1
            continue
        data = build_page_elements(doc_dir.name, page_dir, fallback_idx)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written += 1
    return written, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create per-page elements.json from DeepSeekOCR2 ocr.md and bbox_items.json."
    )
    parser.add_argument("--input-root", default="output/deepseekocr2_split_render")
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--output-name", default="elements.json")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_root = Path(args.input_root)
    if not input_root.exists():
        raise SystemExit(f"Input root not found: {input_root}")

    total_written = 0
    total_skipped = 0
    for doc_dir in iter_doc_dirs(input_root, args.doc_id):
        if not doc_dir.exists():
            print(f"[WARN] missing doc dir: {doc_dir}")
            continue
        written, skipped = build_for_doc(doc_dir, args.output_name, args.overwrite)
        total_written += written
        total_skipped += skipped
        print(f"[OK] {doc_dir.name}: wrote {written}, skipped {skipped}")

    print(f"[DONE] wrote {total_written}, skipped {total_skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
