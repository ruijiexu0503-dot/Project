#!/usr/bin/env python3
"""Validate the checkpointed Dolphin-v2 magazine corpus without re-running models."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def valid_bbox(value: Any, width: int, height: int) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    if not all(isinstance(item, (int, float)) for item in value):
        return False
    x1, y1, x2, y2 = (float(item) for item in value)
    return 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height


def validate_document(document: dict[str, Any], work: Path, published: Path) -> dict[str, Any]:
    document_id = document["document_id"]
    doc_work = work / document_id / "pages"
    published_summary_path = published / document_id / "summary.json"
    published_summary = read_json(published_summary_path) if published_summary_path.exists() else {}
    metadata_path = Path(document.get("source_metadata") or "")
    if not metadata_path.is_absolute():
        metadata_path = Path.cwd() / metadata_path
    source_metadata = read_json(metadata_path) if metadata_path.is_file() else {}
    expected_pages = int(source_metadata.get("page_count") or published_summary.get("total_pages") or 0)
    if not expected_pages:
        page_dirs = sorted(doc_work.glob("page_[0-9][0-9][0-9][0-9]"))
        expected_pages = max((int(path.name.rsplit("_", 1)[1]) for path in page_dirs), default=0)

    missing_pages: list[int] = []
    malformed_pages: list[dict[str, Any]] = []
    empty_pages: list[int] = []
    invalid_bbox_elements: list[dict[str, Any]] = []
    duplicate_reading_orders: list[dict[str, Any]] = []
    labels: Counter[str] = Counter()
    element_count = 0

    for page_number in range(1, expected_pages + 1):
        page_id = f"page_{page_number:04d}"
        page_work = doc_work / page_id
        result_path = page_work / "output_json" / f"{page_id}.json"
        run_path = page_work / "run_summary.json"
        if not result_path.exists() or not run_path.exists():
            missing_pages.append(page_number)
            continue
        try:
            elements = read_json(result_path)
            run = read_json(run_path)
        except (OSError, json.JSONDecodeError) as exc:
            malformed_pages.append({"page": page_number, "reason": repr(exc)})
            continue
        if not isinstance(elements, list) or run.get("status") != "complete":
            malformed_pages.append({"page": page_number, "reason": "invalid_result_or_run_status"})
            continue
        image_size = run.get("image_size") or []
        if len(image_size) != 2 or not all(isinstance(item, (int, float)) and item > 0 for item in image_size):
            malformed_pages.append({"page": page_number, "reason": "invalid_image_size"})
            continue
        width, height = int(image_size[0]), int(image_size[1])
        if not elements:
            empty_pages.append(page_number)
        orders: list[int] = []
        for index, element in enumerate(elements):
            if not isinstance(element, dict):
                malformed_pages.append({"page": page_number, "reason": f"element_{index}_not_object"})
                continue
            label = str(element.get("label") or "UNKNOWN")
            labels[label] += 1
            if not valid_bbox(element.get("bbox"), width, height):
                invalid_bbox_elements.append({
                    "page": page_number,
                    "element_index": index,
                    "label": label,
                    "bbox": element.get("bbox"),
                    "image_size": [width, height],
                })
            order = element.get("reading_order")
            if isinstance(order, int):
                orders.append(order)
        duplicates = sorted(order for order, count in Counter(orders).items() if count > 1)
        if duplicates:
            duplicate_reading_orders.append({"page": page_number, "orders": duplicates})
        element_count += len(elements)

    completed_pages = expected_pages - len(missing_pages) - len(malformed_pages)
    hard_valid = expected_pages > 0 and not missing_pages and not malformed_pages and not invalid_bbox_elements
    return {
        "document_id": document_id,
        "expected_pages": expected_pages,
        "completed_pages": completed_pages,
        "element_count": element_count,
        "label_distribution": dict(labels),
        "missing_pages": missing_pages,
        "malformed_pages": malformed_pages,
        "empty_pages": empty_pages,
        "invalid_bbox_elements": invalid_bbox_elements,
        "duplicate_reading_orders": duplicate_reading_orders,
        "hard_valid": hard_valid,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = read_json(args.manifest)
    documents = [validate_document(row, args.work, args.published) for row in manifest["documents"]]
    summary = {
        "experiment": "dolphin_v2_magazine_corpus_validation_v1",
        "documents": documents,
        "document_count": len(documents),
        "expected_pages": sum(row["expected_pages"] for row in documents),
        "completed_pages": sum(row["completed_pages"] for row in documents),
        "element_count": sum(row["element_count"] for row in documents),
        "invalid_bbox_elements": sum(len(row["invalid_bbox_elements"]) for row in documents),
        "missing_pages": sum(len(row["missing_pages"]) for row in documents),
        "malformed_pages": sum(len(row["malformed_pages"]) for row in documents),
        "empty_pages": sum(len(row["empty_pages"]) for row in documents),
        "hard_valid": len(documents) == len(manifest["documents"]) and all(row["hard_valid"] for row in documents),
        "production_modified": False,
    }
    write_json(args.output, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["hard_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
