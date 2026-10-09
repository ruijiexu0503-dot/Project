"""Preserve DeepSeekOCR2 grounding groups without flattening multi-box blocks."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any


GROUNDING_GROUPS_FILENAME = "bbox_groups_official.json"
GROUNDING_GROUPS_SCHEMA = "deepseekocr2_grounding_groups_v1"


def _valid_box(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    if not all(isinstance(item, (int, float)) for item in value):
        return None
    x1, y1, x2, y2 = [float(item) for item in value]
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _boxes(value: Any) -> list[list[float]]:
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value.strip())
        except (SyntaxError, ValueError):
            return []
    single = _valid_box(value)
    if single is not None:
        return [single]
    if not isinstance(value, (list, tuple)):
        return []
    output: list[list[float]] = []
    for item in value:
        box = _valid_box(item)
        if box is not None:
            output.append(box)
    return output


def _match_parts(match: Any) -> tuple[str, str, list[list[float]]] | None:
    if isinstance(match, (list, tuple)) and len(match) >= 3:
        full_match = str(match[0])
        label = str(match[1]).strip()
        boxes = _boxes(match[2])
        if label and boxes:
            return full_match, label, boxes

    full_match = str(match)
    parsed = re.search(
        r"<\|ref\|>(.*?)<\|/ref\|>\s*<\|det\|>(.*?)<\|/det\|>",
        full_match,
        flags=re.DOTALL,
    )
    if parsed is None:
        return None
    label = parsed.group(1).strip()
    boxes = _boxes(parsed.group(2))
    if not label or not boxes:
        return None
    return full_match, label, boxes


def _pixel_box(raw_box: list[float], width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = raw_box
    scaled = [
        x1 / 999.0 * width,
        y1 / 999.0 * height,
        x2 / 999.0 * width,
        y2 / 999.0 * height,
    ]
    xa, ya, xb, yb = scaled
    return [
        int(round(max(0.0, min(float(width), min(xa, xb))))),
        int(round(max(0.0, min(float(height), min(ya, yb))))),
        int(round(max(0.0, min(float(width), max(xa, xb))))),
        int(round(max(0.0, min(float(height), max(ya, yb))))),
    ]


def matches_ref_to_grounding_manifest(
    matches_ref: Any,
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    """Convert DeepSeek matches_ref into group-preserving provenance.

    One match is one logical grounding group. A group may contain several exact
    bbox members. No block-level union bbox is generated here.
    """
    groups: list[dict[str, Any]] = []
    content_index = 0
    invalid_matches = 0

    if not isinstance(matches_ref, (list, tuple)):
        matches_ref = []

    for sequence_index, match in enumerate(matches_ref):
        parts = _match_parts(match)
        if parts is None:
            invalid_matches += 1
            continue
        full_match, label, raw_boxes = parts
        group_id = f"grounding_group_{sequence_index:04d}"
        is_image = label.strip().lower() == "image"
        group_content_index = None
        if not is_image:
            group_content_index = content_index
            content_index += 1

        members = []
        for box_index, raw_box in enumerate(raw_boxes):
            pixel_bbox = _pixel_box(raw_box, image_width, image_height)
            if pixel_bbox[2] <= pixel_bbox[0] or pixel_bbox[3] <= pixel_bbox[1]:
                continue
            members.append({
                "member_id": f"{group_id}_member_{box_index:04d}",
                "box_index": box_index,
                "raw_bbox": raw_box,
                "pixel_bbox": pixel_bbox,
                "bbox_scale": "norm999",
                "image_width": image_width,
                "image_height": image_height,
                "bbox_source": "deepseekocr2_matches_ref",
                "bbox_granularity": "grounding_group_member",
            })
        if not members:
            invalid_matches += 1
            continue
        groups.append({
            "group_id": group_id,
            "sequence_index": sequence_index,
            "content_sequence_index": group_content_index,
            "label": label,
            "is_image": is_image,
            "members": members,
            "raw_match": full_match,
        })

    return {
        "schema_version": GROUNDING_GROUPS_SCHEMA,
        "source": "matches_ref_raw",
        "image_width": int(image_width),
        "image_height": int(image_height),
        "group_count": len(groups),
        "content_group_count": sum(not group["is_image"] for group in groups),
        "bbox_member_count": sum(len(group["members"]) for group in groups),
        "multi_member_group_count": sum(len(group["members"]) > 1 for group in groups),
        "invalid_match_count": invalid_matches,
        "groups": groups,
    }


def grounding_manifest_from_raw_file(
    path: Path,
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    matches_ref = ast.literal_eval(path.read_text(encoding="utf-8", errors="ignore"))
    return matches_ref_to_grounding_manifest(matches_ref, image_width, image_height)
