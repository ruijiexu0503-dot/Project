#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enrich hybrid aligned JSON and export one Markdown file per page.

Input:
  output/hybrid_deepseek_layout_mvp/aligned_json/<doc_id>/page_XXXX.json

Output:
  output/hybrid_deepseek_layout_mvp/enriched_json/<doc_id>/page_XXXX.json
  output/hybrid_deepseek_layout_mvp/export_md_by_page/<doc_id>/page_XXXX.md
  output/hybrid_deepseek_layout_mvp/visual_region_crops/<doc_id>/page_XXXX/<region_id>.jpg

This script does NOT change alignment logic.
It only adds:
  - visual_regions
  - layout_only_regions
  - page_review_items
  - visual region crops
  - page-level markdown for manual inspection
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VISUAL_LABELS = {
    "image",
    "figure",
    "table",
    "chart",
    "header_image",
    "cover",
    "logo",
    "seal",
    "icon",
    "background",
}

VISUAL_GROUPS = {
    "figure",
    "image",
    "table",
}

TEXT_LIKE_LABELS = {
    "text",
    "paragraph_title",
    "title",
    "header",
    "header_text",
    "footer",
    "footnote",
    "caption",
    "figure_caption",
    "table_caption",
    "table_title",
    "list",
    "formula",
    "reference",
}


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def bbox_to_str(bbox: Any) -> str:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return "null"
    return "[" + ", ".join(str(round(float(x), 2)) for x in bbox) + "]"


def bbox_area(bbox: Any) -> float:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return 0.0
    x1, y1, x2, y2 = [float(x) for x in bbox]
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def x_overlap_frac(a: Any, b: Any) -> float:
    if not isinstance(a, list) or not isinstance(b, list):
        return 0.0
    if len(a) != 4 or len(b) != 4:
        return 0.0

    ax1, _, ax2, _ = [float(x) for x in a]
    bx1, _, bx2, _ = [float(x) for x in b]

    aw = max(0.0, ax2 - ax1)
    bw = max(0.0, bx2 - bx1)
    if aw <= 0 or bw <= 0:
        return 0.0

    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    return inter / min(aw, bw)


def vertical_gap_above_to_below(top_bbox: Any, below_bbox: Any) -> float:
    if not isinstance(top_bbox, list) or not isinstance(below_bbox, list):
        return 999999.0
    if len(top_bbox) != 4 or len(below_bbox) != 4:
        return 999999.0
    return float(below_bbox[1]) - float(top_bbox[3])


def bbox_intersection_area(a: Any, b: Any) -> float:
    if not isinstance(a, list) or not isinstance(b, list):
        return 0.0
    if len(a) != 4 or len(b) != 4:
        return 0.0
    ax1, ay1, ax2, ay2 = [float(x) for x in a]
    bx1, by1, bx2, by2 = [float(x) for x in b]
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    return iw * ih


def bbox_coverage_frac(inner: Any, outer: Any) -> float:
    """Fraction of the inner bbox covered by the outer bbox."""
    area = bbox_area(inner)
    if area <= 0:
        return 0.0
    return bbox_intersection_area(inner, outer) / area


def bbox_center(bbox: Any) -> Tuple[float, float]:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return (0.0, 0.0)
    x1, y1, x2, y2 = [float(x) for x in bbox]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def bbox_center_inside(inner: Any, outer: Any) -> bool:
    if not isinstance(inner, list) or not isinstance(outer, list):
        return False
    if len(inner) != 4 or len(outer) != 4:
        return False
    cx, cy = bbox_center(inner)
    ox1, oy1, ox2, oy2 = [float(x) for x in outer]
    return ox1 <= cx <= ox2 and oy1 <= cy <= oy2


def numeric_order(value: Any, default: float = 10**9) -> float:
    try:
        return float(value)
    except Exception:
        return default


ANCHOR_AVOID_LABELS = {
    "header_image",
    "logo",
    "seal",
    "icon",
}


def is_possible_branding_or_header_visual(region: Dict[str, Any]) -> bool:
    label = str(region.get("label") or "").lower()
    role = str(region.get("role") or "").lower()
    if label in ANCHOR_AVOID_LABELS:
        return True
    if role in {"header", "logo", "branding"}:
        return True
    return False


def is_heading_like_block(block: Dict[str, Any]) -> bool:
    block_type = str(block.get("block_type") or "").lower()
    matched_label = str(block.get("matched_region_label") or "").lower()
    matched_role = str(block.get("matched_region_role") or "").lower()

    if any(k in block_type for k in ["heading", "title"]):
        return True
    if matched_label in {"paragraph_title", "title", "header", "header_text"}:
        return True
    if matched_role in {"heading", "title"}:
        return True
    return False


def strip_markdown_heading_noise(text: Any) -> str:
    """Keep OCR text content but remove Markdown syntax that causes uneven preview rendering."""
    raw = str(text or "")
    out_lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r"[-*_]{3,}", line):
            continue
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        out_lines.append(line)
    return "\n".join(out_lines).strip()


def enrich_text_display_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add display-only fields for Markdown review.
    Raw OCR text / markdown is preserved unchanged.
    """
    for block in data.get("aligned_blocks") or []:
        source_text = block.get("markdown") or block.get("text") or ""
        if is_heading_like_block(block):
            display_text = strip_markdown_heading_noise(source_text)
            if display_text:
                # Use bold text instead of Markdown heading markers so multi-line titles
                # render with a consistent size in VS Code preview.
                display_markdown = "**" + display_text.replace("\n", "  \n") + "**"
            else:
                display_markdown = ""
            flags = block.setdefault("display_flags", [])
            if "heading_markdown_normalized_for_review" not in flags:
                flags.append("heading_markdown_normalized_for_review")
        else:
            display_text = str(block.get("text") or source_text or "").strip()
            display_markdown = str(source_text).strip()

        block["display_text"] = display_text
        block["display_markdown"] = display_markdown

    return data


def detect_visual_parent_child_relations(
    visual_regions: List[Dict[str, Any]],
    page_width: Optional[Any] = None,
    page_height: Optional[Any] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Detect layout-region hierarchy inside visual regions.

    Example: one large composite image region containing three smaller image regions.
    We keep both levels in JSON, but suppress child visuals from the main review flow
    to avoid duplicate display.
    """
    try:
        page_area = float(page_width) * float(page_height)
    except Exception:
        page_area = 0.0

    by_id = {str(v.get("region_id") or ""): v for v in visual_regions if v.get("region_id")}
    parent_for_child: Dict[str, str] = {}
    candidate_evidence: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for child in visual_regions:
        child_id = str(child.get("region_id") or "")
        child_bbox = child.get("bbox")
        child_area = bbox_area(child_bbox)
        if not child_id or child_area <= 0:
            continue

        best_parent_id = None
        best_parent_area = None
        best_evidence: Dict[str, Any] = {}

        for parent in visual_regions:
            parent_id = str(parent.get("region_id") or "")
            if not parent_id or parent_id == child_id:
                continue

            parent_label = str(parent.get("label") or "").lower()
            if parent_label == "background":
                continue

            parent_bbox = parent.get("bbox")
            parent_area = bbox_area(parent_bbox)
            if parent_area <= 0:
                continue

            # Avoid near-duplicates and page-sized background/cover boxes acting as parents.
            if parent_area < child_area * 1.20:
                continue
            if page_area > 0 and parent_area / page_area > 0.92:
                continue

            coverage = bbox_coverage_frac(child_bbox, parent_bbox)
            center_inside = bbox_center_inside(child_bbox, parent_bbox)

            # Conservative containment rule.
            if coverage >= 0.82 or (coverage >= 0.68 and center_inside):
                if best_parent_area is None or parent_area < best_parent_area:
                    best_parent_id = parent_id
                    best_parent_area = parent_area
                    best_evidence = {
                        "child_coverage_by_parent": round(coverage, 4),
                        "center_inside_parent": bool(center_inside),
                        "parent_area": round(parent_area, 2),
                        "child_area": round(child_area, 2),
                    }

        if best_parent_id:
            parent_for_child[child_id] = best_parent_id
            candidate_evidence[(best_parent_id, child_id)] = best_evidence

    child_ids_by_parent: Dict[str, List[str]] = {}
    for child_id, parent_id in parent_for_child.items():
        child_ids_by_parent.setdefault(parent_id, []).append(child_id)

    visual_relations: List[Dict[str, Any]] = []

    for parent_id, child_ids in child_ids_by_parent.items():
        parent = by_id.get(parent_id)
        if not parent:
            continue

        parent_flags = parent.setdefault("flags", [])
        for flag in ["composite_visual_region", "has_child_visual_regions"]:
            if flag not in parent_flags:
                parent_flags.append(flag)

        child_ids = sorted(
            child_ids,
            key=lambda cid: (
                numeric_order(by_id.get(cid, {}).get("geometry_order")),
                bbox_center(by_id.get(cid, {}).get("bbox"))[1],
                bbox_center(by_id.get(cid, {}).get("bbox"))[0],
            ),
        )
        parent["child_visual_region_ids"] = child_ids
        parent["visual_group_type"] = "composite_visual_region"

        for child_id in child_ids:
            child = by_id.get(child_id)
            if not child:
                continue
            child["parent_visual_region_id"] = parent_id
            child_flags = child.setdefault("flags", [])
            for flag in ["child_visual_region", "suppress_in_main_review_flow"]:
                if flag not in child_flags:
                    child_flags.append(flag)

            visual_relations.append(
                {
                    "relation_type": "contains_visual_region",
                    "source_region_id": parent_id,
                    "target_region_id": child_id,
                    "confidence": 0.82,
                    "reason": "child_bbox_mostly_inside_parent_bbox",
                    "evidence": candidate_evidence.get((parent_id, child_id), {}),
                }
            )

    return visual_regions, visual_relations


def geometry_review_anchor(
    visual_region: Dict[str, Any],
    aligned_blocks: List[Dict[str, Any]],
    reason: str = "geometry_order_for_unanchored_visual",
) -> Tuple[float, Optional[str], str]:
    """
    Place an unanchored visual region into the manual review flow by page geometry.
    This keeps logo/header/ad visuals in the visible flow without pretending nearby
    slogan text is a caption.
    """
    visual_bbox = visual_region.get("bbox")
    if not isinstance(visual_bbox, list) or len(visual_bbox) != 4:
        geometry_order = visual_region.get("geometry_order")
        try:
            return 100000.0 + float(geometry_order), None, reason
        except Exception:
            return 199999.0, None, reason

    vx, vy = bbox_center(visual_bbox)

    text_blocks = []
    for block in aligned_blocks:
        bbox = block.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        order = block.get("final_order") or block.get("deepseek_order")
        order_f = numeric_order(order)
        if order_f >= 10**8:
            continue
        bx, by = bbox_center(bbox)
        text_blocks.append((by, bx, order_f, get_block_id(block), bbox))

    if not text_blocks:
        geometry_order = visual_region.get("geometry_order")
        try:
            return 100000.0 + float(geometry_order), None, reason
        except Exception:
            return 199999.0, None, reason

    text_blocks.sort(key=lambda x: (x[0], x[1], x[2]))

    # Find the first text block that starts at or below the visual center.
    for by, bx, order_f, block_id, bbox in text_blocks:
        top_y = float(bbox[1])
        if top_y >= vy or by >= vy:
            return order_f - 0.25, block_id, reason

    last = max(text_blocks, key=lambda x: x[2])
    return last[2] + 0.25, last[3], reason


def short_text(text: Any, n: int = 140) -> str:
    if text is None:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def md_escape(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("|", "\\|").replace("\n", " ")


def safe_meta(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def relpath_for_md(target: Optional[str], md_path: Path) -> Optional[str]:
    if not target:
        return None
    try:
        rel = os.path.relpath(target, start=md_path.parent)
        return rel.replace(os.sep, "/")
    except Exception:
        return target


def is_visual_region(region: Dict[str, Any]) -> bool:
    label = str(region.get("label") or "").lower()
    label_group = str(region.get("label_group") or "").lower()
    role = str(region.get("role") or "").lower()

    if role in {"visual", "table"}:
        return True
    if label in VISUAL_LABELS:
        return True
    if label_group in VISUAL_GROUPS:
        return True
    return False


def is_text_like_region(region: Dict[str, Any]) -> bool:
    label = str(region.get("label") or "").lower()
    label_group = str(region.get("label_group") or "").lower()
    role = str(region.get("role") or "").lower()

    if role in {"text", "heading", "caption"}:
        return True
    if label in TEXT_LIKE_LABELS:
        return True
    if label_group == "text":
        return True
    return False



def bbox_valid(bbox: Any) -> bool:
    return isinstance(bbox, list) and len(bbox) == 4 and bbox_area(bbox) > 0


def bbox_y_overlap_frac(a: Any, b: Any) -> float:
    if not isinstance(a, list) or not isinstance(b, list):
        return 0.0
    if len(a) != 4 or len(b) != 4:
        return 0.0
    _, ay1, _, ay2 = [float(x) for x in a]
    _, by1, _, by2 = [float(x) for x in b]
    ah = max(0.0, ay2 - ay1)
    bh = max(0.0, by2 - by1)
    if ah <= 0 or bh <= 0:
        return 0.0
    inter = max(0.0, min(ay2, by2) - max(ay1, by1))
    return inter / min(ah, bh)


def unique_keep_order(values: List[Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        if value is None:
            continue
        s = str(value)
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def region_geometry_sort_key(region: Dict[str, Any]) -> Tuple[float, float, float]:
    bbox = region.get("bbox")
    if bbox_valid(bbox):
        x1, y1, _, _ = [float(x) for x in bbox]
        return (y1, x1, numeric_order(region.get("geometry_order")))
    return (10**9, 10**9, numeric_order(region.get("geometry_order")))


def block_geometry_sort_key(block: Dict[str, Any]) -> Tuple[float, float, float]:
    bbox = block.get("deepseek_bbox") if bbox_valid(block.get("deepseek_bbox")) else block.get("bbox")
    if bbox_valid(bbox):
        x1, y1, _, _ = [float(x) for x in bbox]
        return (y1, x1, numeric_order(block.get("final_order") or block.get("deepseek_order")))
    return (10**9, 10**9, numeric_order(block.get("final_order") or block.get("deepseek_order")))


def infer_deepseek_block_multi_layout_regions(
    block: Dict[str, Any],
    layout_regions: List[Dict[str, Any]],
    region_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Add a conservative one-to-many text/layout mapping.

    Example:
      DeepSeek block text = "OPEN SCIENCE\nCERN opens new era..."
      PP-DocLayout gives two heading boxes.

    We keep the original matched_region_id as the primary match, but add
    matched_region_ids when the DeepSeek bbox appears to cover several
    text-like layout boxes.
    """
    primary_id = str(block.get("matched_region_id") or "")
    base_ids = unique_keep_order([primary_id])

    # Use the original DeepSeek bbox for span inference. The PP-DocLayout bbox may
    # already be the primary region and can be too narrow for detecting siblings.
    ds_bbox = block.get("deepseek_bbox")
    if not bbox_valid(ds_bbox):
        block["matched_region_ids"] = base_ids
        return base_ids, []

    ds_area = bbox_area(ds_bbox)
    if ds_area <= 0:
        block["matched_region_ids"] = base_ids
        return base_ids, []

    candidates: List[Dict[str, Any]] = []

    for region in layout_regions:
        region_id = str(region.get("region_id") or "")
        if not region_id:
            continue
        if not is_text_like_region(region):
            continue

        rbbox = region.get("bbox")
        if not bbox_valid(rbbox):
            continue

        r_area = bbox_area(rbbox)
        if r_area <= 0:
            continue

        inter = bbox_intersection_area(ds_bbox, rbbox)
        if inter <= 0:
            continue

        region_covered_by_block = inter / r_area
        block_covered_by_region = inter / ds_area
        x_ov = x_overlap_frac(ds_bbox, rbbox)
        y_ov = bbox_y_overlap_frac(ds_bbox, rbbox)
        center_inside = bbox_center_inside(rbbox, ds_bbox)

        is_primary = region_id == primary_id

        # Conservative criterion: accept the primary region; accept siblings only
        # if most of the layout region is covered by the DeepSeek block bbox.
        accept = is_primary or (
            (region_covered_by_block >= 0.58 and center_inside)
            or (region_covered_by_block >= 0.72 and x_ov >= 0.15 and y_ov >= 0.15)
        )
        if not accept:
            continue

        score = (
            0.55 * region_covered_by_block
            + 0.20 * min(1.0, x_ov)
            + 0.20 * min(1.0, y_ov)
            + (0.05 if center_inside else 0.0)
            + (0.10 if is_primary else 0.0)
        )

        candidates.append(
            {
                "region_id": region_id,
                "label": region.get("label"),
                "label_group": region.get("label_group"),
                "role": region.get("role"),
                "bbox": rbbox,
                "is_primary_match": bool(is_primary),
                "region_covered_by_deepseek_block": round(region_covered_by_block, 4),
                "deepseek_block_covered_by_region": round(block_covered_by_region, 4),
                "x_overlap_frac": round(x_ov, 4),
                "y_overlap_frac": round(y_ov, 4),
                "center_inside_deepseek_bbox": bool(center_inside),
                "score": round(score, 4),
            }
        )

    # Make sure the original primary match is preserved even if it is not text-like.
    if primary_id and not any(c.get("region_id") == primary_id for c in candidates):
        primary_region = region_by_id.get(primary_id, {})
        candidates.append(
            {
                "region_id": primary_id,
                "label": primary_region.get("label"),
                "label_group": primary_region.get("label_group"),
                "role": primary_region.get("role"),
                "bbox": primary_region.get("bbox"),
                "is_primary_match": True,
                "score": 1.0,
                "reason": "original_primary_match_preserved",
            }
        )

    # Preserve visual/geometric order for title tag + title lines.
    candidates.sort(key=lambda c: region_geometry_sort_key(region_by_id.get(str(c.get("region_id")), {})))
    matched_ids = unique_keep_order([c.get("region_id") for c in candidates])

    block["matched_region_ids"] = matched_ids

    if len(matched_ids) > 1:
        block["matched_region_relation"] = "deepseek_block_spans_multiple_layout_regions"
        block["matched_region_candidates"] = candidates
        flags = block.setdefault("flags", [])
        for flag in [
            "granularity_mismatch",
            "deepseek_block_spans_multiple_layout_regions",
        ]:
            if flag not in flags:
                flags.append(flag)
    else:
        # Keep the field predictable for downstream code but do not add mismatch flags.
        block["matched_region_candidates"] = candidates[:1]

    return matched_ids, candidates


def enrich_text_layout_granularity(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Explicitly encode text/layout granularity mismatches.

    This does not change the old primary `matched_region_id` field.
    It adds:
      - aligned_blocks[*].matched_region_ids
      - aligned_blocks[*].matched_region_relation for one-to-many cases
      - layout_regions[*].text_block_ids_in_region reverse index
      - layout_region_text_groups
      - text_layout_relations
    """
    layout_regions = data.get("layout_regions") or []
    aligned_blocks = data.get("aligned_blocks") or []

    region_by_id: Dict[str, Dict[str, Any]] = {
        str(r.get("region_id") or ""): r
        for r in layout_regions
        if r.get("region_id")
    }

    # Clear fields from previous runs so rerunning the script is deterministic.
    for region in layout_regions:
        for key in [
            "text_block_ids_in_region",
            "directly_matched_text_block_ids",
            "text_region_granularity_flags",
        ]:
            region.pop(key, None)

    text_layout_relations: List[Dict[str, Any]] = []
    region_to_blocks: Dict[str, List[str]] = {}
    region_to_primary_blocks: Dict[str, List[str]] = {}

    for block in aligned_blocks:
        block_id = get_block_id(block)
        if not block_id:
            continue

        matched_ids, candidates = infer_deepseek_block_multi_layout_regions(
            block=block,
            layout_regions=layout_regions,
            region_by_id=region_by_id,
        )

        primary_id = str(block.get("matched_region_id") or "")
        if primary_id:
            region_to_primary_blocks.setdefault(primary_id, []).append(block_id)

        for region_id in matched_ids:
            region_to_blocks.setdefault(region_id, []).append(block_id)

        if len(matched_ids) > 1:
            text_layout_relations.append(
                {
                    "relation_type": "deepseek_block_spans_multiple_layout_regions",
                    "source_block_id": block_id,
                    "target_region_ids": matched_ids,
                    "primary_region_id": primary_id or None,
                    "evidence": candidates,
                    "confidence": 0.72,
                    "note": "Inferred from DeepSeek bbox covering multiple text-like PP-DocLayout regions; primary matched_region_id is preserved.",
                }
            )

    layout_region_text_groups: List[Dict[str, Any]] = []

    for region_id, block_ids in region_to_blocks.items():
        block_ids = unique_keep_order(block_ids)
        region = region_by_id.get(region_id)
        if not region:
            continue

        primary_block_ids = unique_keep_order(region_to_primary_blocks.get(region_id, []))
        region["text_block_ids_in_region"] = block_ids
        region["directly_matched_text_block_ids"] = primary_block_ids

        flags = region.setdefault("text_region_granularity_flags", [])
        if block_ids:
            if "contains_deepseek_text_blocks" not in flags:
                flags.append("contains_deepseek_text_blocks")
        if len(block_ids) > 1:
            for flag in [
                "granularity_mismatch",
                "layout_region_contains_multiple_deepseek_blocks",
            ]:
                if flag not in flags:
                    flags.append(flag)

            text_layout_relations.append(
                {
                    "relation_type": "layout_region_contains_multiple_deepseek_blocks",
                    "source_region_id": region_id,
                    "target_block_ids": block_ids,
                    "directly_matched_block_ids": primary_block_ids,
                    "confidence": 0.80,
                    "evidence": {
                        "block_count": len(block_ids),
                        "region_label": region.get("label"),
                        "region_label_group": region.get("label_group"),
                        "region_role": region.get("role"),
                    },
                    "note": "Multiple DeepSeek text blocks map to the same PP-DocLayout region. Treat the layout region as a container, not as a reason to merge blocks prematurely.",
                }
            )

        if len(block_ids) > 1 or is_visual_region(region) or str(region.get("label") or "").lower() == "table":
            layout_region_text_groups.append(
                {
                    "region_id": region_id,
                    "bbox": region.get("bbox"),
                    "label": region.get("label"),
                    "label_group": region.get("label_group"),
                    "role": region.get("role"),
                    "score": region.get("score"),
                    "layout_order": region.get("layout_order"),
                    "geometry_order": region.get("geometry_order"),
                    "text_block_ids_in_region": block_ids,
                    "directly_matched_text_block_ids": primary_block_ids,
                    "block_count": len(block_ids),
                    "flags": flags,
                }
            )

    layout_region_text_groups.sort(
        key=lambda g: region_geometry_sort_key(region_by_id.get(str(g.get("region_id")), {}))
    )

    data["layout_region_text_groups"] = layout_region_text_groups
    data["text_layout_relations"] = text_layout_relations

    stats = data.setdefault("stats", {})
    stats["layout_region_text_groups"] = len(layout_region_text_groups)
    stats["layout_regions_with_multiple_deepseek_blocks"] = sum(
        1 for group in layout_region_text_groups if int(group.get("block_count") or 0) > 1
    )
    stats["deepseek_blocks_spanning_multiple_layout_regions"] = sum(
        1
        for block in aligned_blocks
        if "deepseek_block_spans_multiple_layout_regions" in (block.get("flags") or [])
    )
    stats["text_layout_relations"] = len(text_layout_relations)
    stats["text_layout_granularity_mismatches"] = (
        stats["layout_regions_with_multiple_deepseek_blocks"]
        + stats["deepseek_blocks_spanning_multiple_layout_regions"]
    )

    return data

def get_block_id(block: Dict[str, Any]) -> str:
    return str(block.get("block_id") or "")


def find_caption_candidates(
    visual_region: Dict[str, Any],
    aligned_blocks: List[Dict[str, Any]],
    max_candidates: int = 3,
) -> List[Dict[str, Any]]:
    """
    Find possible caption/text blocks near a visual region.
    This is only for manual inspection, not a final semantic decision.
    """
    visual_bbox = visual_region.get("bbox")
    if not isinstance(visual_bbox, list) or len(visual_bbox) != 4:
        return []

    candidates = []

    for block in aligned_blocks:
        block_bbox = block.get("bbox")
        if not isinstance(block_bbox, list) or len(block_bbox) != 4:
            continue

        text = block.get("text") or ""
        block_type = str(block.get("block_type") or "").lower()
        matched_label = str(block.get("matched_region_label") or "").lower()

        gap = vertical_gap_above_to_below(visual_bbox, block_bbox)
        x_overlap = x_overlap_frac(visual_bbox, block_bbox)

        looks_like_caption = (
            "caption" in block_type
            or "caption" in matched_label
            or re.match(r"^\s*(fig\.|figure|table)\s*\d*", str(text), flags=re.I) is not None
        )

        if -25 <= gap <= 160 and x_overlap >= 0.18:
            score = 0.60 * x_overlap + 0.30 * max(0.0, 1.0 - max(gap, 0.0) / 160.0)
            if looks_like_caption:
                score += 0.25

            candidates.append(
                {
                    "block_id": get_block_id(block),
                    "deepseek_order": block.get("deepseek_order"),
                    "final_order": block.get("final_order"),
                    "block_type": block.get("block_type"),
                    "matched_region_id": block.get("matched_region_id"),
                    "matched_region_label": block.get("matched_region_label"),
                    "bbox": block_bbox,
                    "text_preview": short_text(text, 180),
                    "gap": round(gap, 2),
                    "x_overlap_frac": round(x_overlap, 4),
                    "score": round(score, 4),
                    "flags": ["nearby_caption_candidate"],
                }
            )

    candidates.sort(
        key=lambda x: (
            -float(x.get("score") or 0.0),
            abs(float(x.get("gap") or 0.0)),
        )
    )

    return candidates[:max_candidates]


def build_visual_and_layout_only(data: Dict[str, Any]) -> Dict[str, Any]:
    layout_regions = data.get("layout_regions") or []
    aligned_blocks = data.get("aligned_blocks") or []
    relations = data.get("relations") or []

    directly_matched: Dict[str, List[str]] = {}

    for block in aligned_blocks:
        block_id = get_block_id(block)
        if not block_id:
            continue
        region_ids = block.get("matched_region_ids") or [block.get("matched_region_id")]
        for region_id in unique_keep_order(region_ids):
            if region_id:
                directly_matched.setdefault(str(region_id), []).append(block_id)

    contained_by_relation: Dict[str, List[str]] = {}

    for rel in relations:
        if rel.get("relation_type") != "contains_visible_text":
            continue
        region_id = rel.get("source_region_id")
        block_id = rel.get("target_block_id")
        if region_id and block_id:
            contained_by_relation.setdefault(str(region_id), []).append(str(block_id))

    visual_regions = []

    for region in layout_regions:
        if not is_visual_region(region):
            continue

        region_id = str(region.get("region_id") or "")
        direct_ids = directly_matched.get(region_id, [])
        contained_ids = contained_by_relation.get(region_id, [])

        associated_ids = []
        for bid in direct_ids + contained_ids:
            if bid not in associated_ids:
                associated_ids.append(bid)

        flags = ["visual_region", "layout_detected_visual"]

        avoid_caption_anchor = is_possible_branding_or_header_visual(region)
        if avoid_caption_anchor:
            flags.extend(
                [
                    "possible_branding_or_header",
                    "keep_in_review_flow",
                    "avoid_caption_anchor",
                ]
            )
            caption_candidates = []
        else:
            caption_candidates = find_caption_candidates(region, aligned_blocks)

        if direct_ids:
            flags.append("has_direct_deepseek_match")
        if contained_ids:
            flags.append("contains_visible_text")
        if caption_candidates:
            flags.append("has_nearby_caption_candidate")
        if not associated_ids and not caption_candidates:
            flags.append("no_associated_deepseek_text")
            flags.append("needs_manual_review")

        visual_regions.append(
            {
                "region_id": region_id,
                "bbox": region.get("bbox"),
                "label": region.get("label"),
                "label_group": region.get("label_group"),
                "role": region.get("role"),
                "score": region.get("score"),
                "layout_order": region.get("layout_order"),
                "geometry_order": region.get("geometry_order"),
                "source": region.get("source", "pp_doclayout"),
                "directly_matched_block_ids": direct_ids,
                "contained_text_block_ids": contained_ids,
                "associated_block_ids": associated_ids,
                "nearby_caption_candidates": caption_candidates,
                "crop_path": None,
                "parent_visual_region_id": None,
                "child_visual_region_ids": [],
                "visual_group_type": None,
                "flags": flags,
            }
        )

    visual_regions, visual_relations = detect_visual_parent_child_relations(
        visual_regions,
        page_width=data.get("page_width"),
        page_height=data.get("page_height"),
    )

    layout_only_regions = []

    for region in layout_regions:
        region_id = str(region.get("region_id") or "")
        if not region_id:
            continue

        if directly_matched.get(region_id):
            continue

        flags = [
            "layout_only_region",
            "no_deepseek_block_directly_matched",
        ]

        if is_visual_region(region):
            flags.append("layout_only_visual_region")
            if contained_by_relation.get(region_id):
                flags.append("has_contained_visible_text_relation")
            else:
                flags.append("visual_region_without_direct_text")

        elif is_text_like_region(region):
            flags.extend(
                [
                    "layout_only_text_candidate",
                    "no_deepseek_text",
                    "needs_crop_ocr_or_vlm",
                    "needs_manual_review",
                ]
            )

        else:
            flags.append("layout_only_non_text_region")

        layout_only_regions.append(
            {
                "region_id": region_id,
                "bbox": region.get("bbox"),
                "label": region.get("label"),
                "label_group": region.get("label_group"),
                "role": region.get("role"),
                "score": region.get("score"),
                "layout_order": region.get("layout_order"),
                "geometry_order": region.get("geometry_order"),
                "source": region.get("source", "pp_doclayout"),
                "associated_contained_text_block_ids": contained_by_relation.get(region_id, []),
                "flags": flags,
            }
        )

    data["visual_regions"] = visual_regions
    data["visual_relations"] = visual_relations
    data["layout_only_regions"] = layout_only_regions

    stats = data.setdefault("stats", {})
    stats["visual_regions"] = len(visual_regions)
    stats["visual_relations"] = len(visual_relations)
    stats["composite_visual_regions"] = sum(
        1 for region in visual_regions if "has_child_visual_regions" in region.get("flags", [])
    )
    stats["child_visual_regions"] = sum(
        1 for region in visual_regions if "child_visual_region" in region.get("flags", [])
    )
    stats["visual_regions_suppressed_in_main_flow"] = sum(
        1 for region in visual_regions if "suppress_in_main_review_flow" in region.get("flags", [])
    )
    stats["possible_branding_or_header_visual_regions"] = sum(
        1 for region in visual_regions if "possible_branding_or_header" in region.get("flags", [])
    )
    stats["layout_only_regions"] = len(layout_only_regions)
    stats["layout_only_text_candidates"] = sum(
        1
        for region in layout_only_regions
        if "layout_only_text_candidate" in region.get("flags", [])
    )
    stats["visual_regions_without_associated_text"] = sum(
        1
        for region in visual_regions
        if "no_associated_deepseek_text" in region.get("flags", [])
    )

    return data

def crop_visual_regions(data: Dict[str, Any], crop_page_dir: Path) -> Dict[str, Any]:
    page_image = data.get("page_image")
    if not page_image:
        return data

    image_path = Path(page_image)
    if not image_path.exists():
        print(f"[WARN] page image not found: {image_path}")
        return data

    try:
        from PIL import Image
    except Exception:
        print("[WARN] PIL is not installed. Skip visual crops.")
        return data

    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        print(f"[WARN] cannot open page image {image_path}: {e}")
        return data

    page_w, page_h = img.size
    crop_page_dir.mkdir(parents=True, exist_ok=True)

    for visual_region in data.get("visual_regions") or []:
        bbox = visual_region.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue

        x1, y1, x2, y2 = [float(x) for x in bbox]

        pad = 4
        x1 = max(0, int(x1) - pad)
        y1 = max(0, int(y1) - pad)
        x2 = min(page_w, int(x2) + pad)
        y2 = min(page_h, int(y2) + pad)

        if x2 <= x1 or y2 <= y1:
            continue

        region_id = str(visual_region.get("region_id") or "region")
        safe_region_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", region_id)
        out_path = crop_page_dir / f"{safe_region_id}.jpg"

        try:
            crop = img.crop((x1, y1, x2, y2))
            crop.save(out_path, quality=95)
            visual_region["crop_path"] = str(out_path)
        except Exception as e:
            print(f"[WARN] cannot crop {region_id}: {e}")
            continue

    return data


def build_page_review_items(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a human-inspection flow that mixes:
      - visual regions
      - DeepSeek text blocks

    This is NOT the canonical reading order.
    It is only a review view.

    Rule:
      - Child visual regions are preserved in JSON but suppressed from main flow.
      - If visual has caption candidates, place image before first caption.
      - Else if visual contains / associates text blocks, place image before first associated text.
      - Else place it by geometry relative to text blocks.
      - Logo/header-like visuals are kept in flow, but do not use caption anchoring.
    """
    aligned_blocks = data.get("aligned_blocks") or []
    visual_regions = data.get("visual_regions") or []

    block_by_id = {get_block_id(b): b for b in aligned_blocks if get_block_id(b)}

    items = []

    for block in aligned_blocks:
        final_order = block.get("final_order")
        key = numeric_order(final_order)

        items.append(
            {
                "item_type": "text_block",
                "review_order_key": key,
                "block_id": get_block_id(block),
                "deepseek_order": block.get("deepseek_order"),
                "final_order": block.get("final_order"),
                "block_type": block.get("block_type"),
                "text_preview": short_text(block.get("display_text") or block.get("text"), 180),
                "bbox": block.get("bbox"),
                "matched_region_id": block.get("matched_region_id"),
                "flags": block.get("flags") or [],
                "display_flags": block.get("display_flags") or [],
            }
        )

    for visual_region in visual_regions:
        flags = visual_region.get("flags") or []
        if "suppress_in_main_review_flow" in flags:
            continue

        caption_candidates = visual_region.get("nearby_caption_candidates") or []
        associated_ids = visual_region.get("associated_block_ids") or []

        anchor_order = None
        anchor_reason = None
        anchor_block_id = None

        avoid_caption_anchor = "avoid_caption_anchor" in flags

        if caption_candidates and not avoid_caption_anchor:
            c = caption_candidates[0]
            anchor_order = c.get("final_order") or c.get("deepseek_order")
            anchor_reason = "before_nearby_caption_candidate"
            anchor_block_id = c.get("block_id")

        elif associated_ids:
            orders = []
            for bid in associated_ids:
                block = block_by_id.get(bid)
                if not block:
                    continue
                order = block.get("final_order") or block.get("deepseek_order")
                order_f = numeric_order(order)
                if order_f < 10**8:
                    orders.append((order_f, bid))
            if orders:
                orders.sort()
                anchor_order = orders[0][0]
                anchor_reason = "before_associated_text_block"
                anchor_block_id = orders[0][1]

        if anchor_order is not None:
            key = float(anchor_order) - 0.35
        else:
            if avoid_caption_anchor:
                reason = "geometry_order_for_possible_branding_or_header_visual"
            else:
                reason = "geometry_order_for_unanchored_visual"
            key, anchor_block_id, anchor_reason = geometry_review_anchor(
                visual_region,
                aligned_blocks,
                reason=reason,
            )

        items.append(
            {
                "item_type": "visual_region",
                "review_order_key": key,
                "region_id": visual_region.get("region_id"),
                "label": visual_region.get("label"),
                "label_group": visual_region.get("label_group"),
                "role": visual_region.get("role"),
                "bbox": visual_region.get("bbox"),
                "score": visual_region.get("score"),
                "crop_path": visual_region.get("crop_path"),
                "associated_block_ids": associated_ids,
                "contained_text_block_ids": visual_region.get("contained_text_block_ids") or [],
                "nearby_caption_candidates": caption_candidates,
                "anchor_reason": anchor_reason,
                "anchor_block_id": anchor_block_id,
                "parent_visual_region_id": visual_region.get("parent_visual_region_id"),
                "child_visual_region_ids": visual_region.get("child_visual_region_ids") or [],
                "visual_group_type": visual_region.get("visual_group_type"),
                "flags": flags,
            }
        )

    items.sort(
        key=lambda x: (
            float(x.get("review_order_key") or 10**9),
            0 if x.get("item_type") == "visual_region" else 1,
        )
    )

    for idx, item in enumerate(items, start=1):
        item["review_order"] = idx

    data["page_review_items"] = items
    data.setdefault("stats", {})["page_review_items"] = len(items)
    return data

def render_header(data: Dict[str, Any]) -> str:
    lines = []
    lines.append(f"# {data.get('doc_id', '')} / {data.get('page', '')}")
    lines.append("")
    lines.append("## Sources")
    lines.append(f"- Page image: `{data.get('page_image')}`")
    lines.append(f"- DeepSeek page dir: `{data.get('deepseek_page_dir')}`")
    lines.append(f"- Layout JSON: `{data.get('layout_json')}`")
    lines.append(f"- Page size: `{data.get('page_width')} × {data.get('page_height')}`")
    lines.append("")
    return "\n".join(lines)


def render_stats(data: Dict[str, Any]) -> str:
    stats = data.get("stats") or {}

    keys = [
        "total_deepseek_blocks",
        "matched_text_region",
        "matched_visual_container",
        "unmatched",
        "suspicious_deepseek_bbox",
        "visual_regions",
        "visual_relations",
        "composite_visual_regions",
        "child_visual_regions",
        "visual_regions_suppressed_in_main_flow",
        "possible_branding_or_header_visual_regions",
        "layout_region_text_groups",
        "layout_regions_with_multiple_deepseek_blocks",
        "deepseek_blocks_spanning_multiple_layout_regions",
        "text_layout_relations",
        "text_layout_granularity_mismatches",
        "layout_only_regions",
        "layout_only_text_candidates",
        "visual_regions_without_associated_text",
        "page_review_items",
    ]

    lines = []
    lines.append("## Alignment stats")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")

    for key in keys:
        lines.append(f"| `{key}` | {stats.get(key, 0)} |")

    lines.append("")
    return "\n".join(lines)


def render_page_review_items(data: Dict[str, Any], md_path: Path) -> str:
    items = data.get("page_review_items") or []
    block_by_id = {get_block_id(b): b for b in data.get("aligned_blocks") or []}

    lines = []
    lines.append("## Page review flow")
    lines.append("")
    lines.append(
        "> This section is for manual inspection. It mixes DeepSeekOCR2 text blocks "
        "and PP-DocLayout visual regions. It is not the canonical source of truth."
    )
    lines.append("")

    if not items:
        lines.append("_No review items._")
        lines.append("")
        return "\n".join(lines)

    for item in items:
        item_type = item.get("item_type")
        idx = int(item.get("review_order") or 0)

        if item_type == "visual_region":
            region_id = item.get("region_id")
            label = item.get("label")
            flags = item.get("flags") or []

            lines.append(f"### R{idx:04d} · VISUAL · {label} · {region_id}")
            lines.append(f"<!-- review_visual_item: {safe_meta(item)} -->")
            lines.append("")

            crop_rel = relpath_for_md(item.get("crop_path"), md_path)
            if crop_rel:
                lines.append(f"![](<{crop_rel}>)")
                lines.append("")
            else:
                lines.append("_No crop generated._")
                lines.append("")

            lines.append(f"- region_id: `{region_id}`")
            lines.append(f"- label: `{item.get('label')}` / `{item.get('label_group')}` / `{item.get('role')}`")
            lines.append(f"- bbox: `{bbox_to_str(item.get('bbox'))}`")
            lines.append(f"- score: `{item.get('score')}`")
            lines.append(f"- anchor reason: `{item.get('anchor_reason')}`")
            lines.append(f"- anchor block: `{item.get('anchor_block_id')}`")
            lines.append(f"- parent visual region: `{item.get('parent_visual_region_id')}`")
            lines.append(f"- child visual regions: `{', '.join(item.get('child_visual_region_ids') or [])}`")
            lines.append(f"- visual group type: `{item.get('visual_group_type')}`")
            lines.append(f"- associated blocks: `{', '.join(item.get('associated_block_ids') or [])}`")
            lines.append(f"- contained text blocks: `{', '.join(item.get('contained_text_block_ids') or [])}`")
            lines.append(f"- flags: `{', '.join(flags)}`")
            lines.append("")

            candidates = item.get("nearby_caption_candidates") or []
            if candidates:
                lines.append("Possible nearby caption/text candidates:")
                for c in candidates:
                    lines.append(
                        f"- `{c.get('block_id')}` "
                        f"(D{c.get('deepseek_order')}, score={c.get('score')}, "
                        f"gap={c.get('gap')}, x_overlap={c.get('x_overlap_frac')}): "
                        f"{c.get('text_preview')}"
                    )
                lines.append("")

            child_ids = item.get("child_visual_region_ids") or []
            if child_ids:
                visual_by_id = {
                    str(v.get("region_id") or ""): v
                    for v in data.get("visual_regions") or []
                    if v.get("region_id")
                }
                lines.append("Child visual regions suppressed from main flow:")
                for child_id in child_ids:
                    child = visual_by_id.get(str(child_id), {})
                    lines.append(
                        f"- `{child_id}` "
                        f"label=`{child.get('label')}`, "
                        f"bbox=`{bbox_to_str(child.get('bbox'))}`, "
                        f"crop=`{relpath_for_md(child.get('crop_path'), md_path)}`"
                    )
                lines.append("")

        elif item_type == "text_block":
            block_id = item.get("block_id")
            block = block_by_id.get(str(block_id), {})
            flags = block.get("flags") or []
            ds_order = block.get("deepseek_order")

            try:
                d_str = f"D{int(ds_order):04d}"
            except Exception:
                d_str = "D????"

            lines.append(f"### R{idx:04d} · TEXT · {d_str} · {block.get('block_type')}")
            lines.append(f"<!-- review_text_item: {safe_meta(item)} -->")
            lines.append("")

            lines.append(f"- block_id: `{block_id}`")
            lines.append(
                f"- matched region: `{block.get('matched_region_id')}` / "
                f"`{block.get('matched_region_label')}` / `{block.get('matched_region_role')}`"
            )
            lines.append(f"- bbox: `{bbox_to_str(block.get('bbox'))}`")
            lines.append(f"- DeepSeek bbox: `{bbox_to_str(block.get('deepseek_bbox'))}`")
            lines.append(f"- bbox source: `{block.get('bbox_source')}`")
            lines.append(f"- bbox granularity: `{block.get('bbox_granularity')}`")
            matched_region_ids = block.get("matched_region_ids") or []
            if matched_region_ids:
                lines.append(f"- matched region ids: `{', '.join(str(x) for x in matched_region_ids)}`")
            if block.get("matched_region_relation"):
                lines.append(f"- matched region relation: `{block.get('matched_region_relation')}`")
            candidates = block.get("matched_region_candidates") or []
            if len(candidates) > 1:
                lines.append("- matched region candidates:")
                for c in candidates:
                    primary_mark = " primary" if c.get("is_primary_match") else ""
                    lines.append(
                        f"  - `{c.get('region_id')}`{primary_mark}: "
                        f"`{c.get('label')}` / `{c.get('role')}`, "
                        f"covered_by_block={c.get('region_covered_by_deepseek_block')}, "
                        f"bbox=`{bbox_to_str(c.get('bbox'))}`"
                    )
            lines.append(f"- flags: `{', '.join(flags)}`")
            display_flags = block.get("display_flags") or []
            if display_flags:
                lines.append(f"- display flags: `{', '.join(display_flags)}`")
            lines.append("")

            text = block.get("display_markdown") or block.get("markdown") or block.get("text") or ""
            text = str(text).strip()
            lines.append(text if text else "_EMPTY TEXT_")
            lines.append("")

    return "\n".join(lines)



def render_text_layout_granularity(data: Dict[str, Any]) -> str:
    groups = data.get("layout_region_text_groups") or []
    relations = data.get("text_layout_relations") or []

    lines = []
    lines.append("## Text-layout granularity")
    lines.append("")
    lines.append(
        "> This section records mismatches between DeepSeekOCR2 text-block granularity "
        "and PP-DocLayout region granularity. It preserves both levels instead of "
        "forcing premature splitting or merging."
    )
    lines.append("")

    if not groups and not relations:
        lines.append("_No explicit text-layout granularity mismatch recorded._")
        lines.append("")
        return "\n".join(lines)

    if groups:
        lines.append("### Layout regions containing text blocks")
        lines.append("")
        lines.append("| Region | Label | BBox | Blocks | Flags |")
        lines.append("|---|---|---|---|---|")
        for group in groups:
            block_ids = group.get("text_block_ids_in_region") or []
            flags = group.get("flags") or []
            lines.append(
                "| "
                f"`{md_escape(group.get('region_id'))}` | "
                f"`{md_escape(group.get('label'))}` / `{md_escape(group.get('role'))}` | "
                f"`{md_escape(bbox_to_str(group.get('bbox')))}` | "
                f"`{md_escape(', '.join(block_ids))}` | "
                f"`{md_escape(', '.join(flags))}` |"
            )
        lines.append("")

    span_rels = [
        rel for rel in relations
        if rel.get("relation_type") == "deepseek_block_spans_multiple_layout_regions"
    ]
    if span_rels:
        lines.append("### DeepSeek blocks spanning multiple layout regions")
        lines.append("")
        lines.append("| Block | Primary region | Matched regions |")
        lines.append("|---|---|---|")
        for rel in span_rels:
            lines.append(
                "| "
                f"`{md_escape(rel.get('source_block_id'))}` | "
                f"`{md_escape(rel.get('primary_region_id'))}` | "
                f"`{md_escape(', '.join(rel.get('target_region_ids') or []))}` |"
            )
        lines.append("")

    return "\n".join(lines)

def render_layout_only_regions(data: Dict[str, Any]) -> str:
    regions = data.get("layout_only_regions") or []

    lines = []
    lines.append("## Layout-only regions")
    lines.append("")
    lines.append(
        "> These PP-DocLayout regions have no DeepSeek block directly matched to them. "
        "Text-like ones may indicate text missed by DeepSeekOCR2."
    )
    lines.append("")

    if not regions:
        lines.append("_No layout-only regions._")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Region | Label | Role | BBox | Score | Flags |")
    lines.append("|---|---|---|---|---:|---|")

    for region in regions:
        flags = ", ".join(region.get("flags") or [])
        lines.append(
            "| "
            f"`{md_escape(region.get('region_id'))}` | "
            f"`{md_escape(region.get('label'))}` / `{md_escape(region.get('label_group'))}` | "
            f"`{md_escape(region.get('role'))}` | "
            f"`{md_escape(bbox_to_str(region.get('bbox')))}` | "
            f"{region.get('score', '')} | "
            f"`{md_escape(flags)}` |"
        )

    lines.append("")
    return "\n".join(lines)


def render_visual_relations(data: Dict[str, Any]) -> str:
    visual_relations = data.get("visual_relations") or []

    lines = []
    lines.append("## Visual relations")
    lines.append("")

    if not visual_relations:
        lines.append("_No visual relations._")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Source visual region | Relation | Target visual region | Confidence | Reason | Evidence |")
    lines.append("|---|---|---|---:|---|---|")

    for relation in visual_relations:
        evidence = relation.get("evidence") or {}
        evidence_text = ", ".join(f"{k}={v}" for k, v in evidence.items())
        lines.append(
            "| "
            f"`{md_escape(relation.get('source_region_id'))}` | "
            f"`{md_escape(relation.get('relation_type'))}` | "
            f"`{md_escape(relation.get('target_region_id'))}` | "
            f"{relation.get('confidence', '')} | "
            f"`{md_escape(relation.get('reason'))}` | "
            f"{md_escape(evidence_text)} |"
        )

    lines.append("")
    return "\n".join(lines)


def render_relations(data: Dict[str, Any]) -> str:
    relations = data.get("relations") or []

    lines = []
    lines.append("## Relations")
    lines.append("")

    if not relations:
        lines.append("_No relations._")
        lines.append("")
        return "\n".join(lines)

    lines.append("| Source region | Relation | Target block | Confidence | Evidence |")
    lines.append("|---|---|---|---:|---|")

    for relation in relations:
        evidence = relation.get("evidence") or {}
        evidence_text = (
            f"overlap={evidence.get('overlap_frac')}, "
            f"center_inside={evidence.get('center_inside')}"
        )

        lines.append(
            "| "
            f"`{md_escape(relation.get('source_region_id'))}` | "
            f"`{md_escape(relation.get('relation_type'))}` | "
            f"`{md_escape(relation.get('target_block_id'))}` | "
            f"{relation.get('confidence', '')} | "
            f"{md_escape(evidence_text)} |"
        )

    lines.append("")
    return "\n".join(lines)


def render_raw_aligned_blocks(data: Dict[str, Any]) -> str:
    """
    Kept after Page review flow for debugging.
    This section is pure DeepSeekOCR2 reading order.
    """
    blocks = data.get("aligned_blocks") or []

    lines = []
    lines.append("## Raw aligned text blocks")
    lines.append("")
    lines.append("> This section contains only DeepSeekOCR2 text blocks, ordered by `final_order`.")
    lines.append("")

    for block in blocks:
        ds_order = block.get("deepseek_order")
        try:
            d_str = f"D{int(ds_order):04d}"
        except Exception:
            d_str = "D????"

        flags = block.get("flags") or []

        lines.append(f"### {d_str} · {block.get('block_type')}")
        meta = {
            "block_id": block.get("block_id"),
            "deepseek_order": block.get("deepseek_order"),
            "final_order": block.get("final_order"),
            "matched_region_id": block.get("matched_region_id"),
            "matched_region_ids": block.get("matched_region_ids"),
            "matched_region_relation": block.get("matched_region_relation"),
            "matched_region_label": block.get("matched_region_label"),
            "bbox": block.get("bbox"),
            "bbox_source": block.get("bbox_source"),
            "deepseek_bbox": block.get("deepseek_bbox"),
            "flags": flags,
        }
        lines.append(f"<!-- hybrid_block: {safe_meta(meta)} -->")
        lines.append("")
        lines.append(f"- block_id: `{block.get('block_id')}`")
        lines.append(f"- matched region: `{block.get('matched_region_id')}` / `{block.get('matched_region_label')}`")
        if block.get("matched_region_ids"):
            lines.append(f"- matched region ids: `{', '.join(str(x) for x in (block.get('matched_region_ids') or []))}`")
        if block.get("matched_region_relation"):
            lines.append(f"- matched region relation: `{block.get('matched_region_relation')}`")
        lines.append(f"- bbox: `{bbox_to_str(block.get('bbox'))}`")
        lines.append(f"- flags: `{', '.join(flags)}`")
        lines.append("")
        text = block.get("markdown") or block.get("text") or ""
        lines.append(str(text).strip() if str(text).strip() else "_EMPTY TEXT_")
        lines.append("")

    return "\n".join(lines)


def render_page_md(data: Dict[str, Any], md_path: Path) -> str:
    parts = [
        render_header(data),
        render_stats(data),
        render_page_review_items(data, md_path),
        render_text_layout_granularity(data),
        render_layout_only_regions(data),
        render_visual_relations(data),
        render_relations(data),
        render_raw_aligned_blocks(data),
    ]
    return "\n\n".join(parts).rstrip() + "\n"


def sort_page_paths(paths: List[Path]) -> List[Path]:
    def key(path: Path):
        try:
            return int(path.stem.split("_")[-1])
        except Exception:
            return path.name

    return sorted(paths, key=key)


def find_doc_dirs(input_root: Path, doc: Optional[str]) -> List[Path]:
    if doc:
        doc_dir = input_root / doc
        return [doc_dir] if doc_dir.exists() else []
    return sorted([p for p in input_root.iterdir() if p.is_dir()])


def process_page(
    page_json: Path,
    out_json_root: Path,
    out_md_root: Path,
    crop_root: Path,
    make_crops: bool,
) -> Tuple[Path, Path]:
    data = load_json(page_json)

    doc_id = data.get("doc_id") or page_json.parent.name
    page = data.get("page") or page_json.stem

    data = enrich_text_display_fields(data)
    data = enrich_text_layout_granularity(data)
    data = build_visual_and_layout_only(data)

    crop_page_dir = crop_root / doc_id / page
    if make_crops:
        data = crop_visual_regions(data, crop_page_dir)

    data = build_page_review_items(data)

    enriched_json_path = out_json_root / doc_id / f"{page}.json"
    save_json(data, enriched_json_path)

    md_path = out_md_root / doc_id / f"{page}.md"
    md_text = render_page_md(data, md_path)
    write_text(md_path, md_text)

    return enriched_json_path, md_path


def run(args: argparse.Namespace) -> None:
    input_root = Path(args.input_root)
    out_json_root = Path(args.out_json_root)
    out_md_root = Path(args.out_md_root)
    crop_root = Path(args.crop_root)

    if not input_root.exists():
        raise FileNotFoundError(f"Input root does not exist: {input_root}")

    doc_dirs = find_doc_dirs(input_root, args.doc)

    if not doc_dirs:
        print("[WARN] No document directories found.")
        return

    total = 0

    for doc_dir in doc_dirs:
        page_jsons = sort_page_paths(list(doc_dir.glob("page_*.json")))

        if args.pages:
            wanted = {f"page_{int(p):04d}.json" for p in args.pages}
            page_jsons = [p for p in page_jsons if p.name in wanted]

        if not page_jsons:
            print(f"[WARN] No page JSONs for {doc_dir.name}")
            continue

        for page_json in page_jsons:
            enriched_path, md_path = process_page(
                page_json=page_json,
                out_json_root=out_json_root,
                out_md_root=out_md_root,
                crop_root=crop_root,
                make_crops=not args.no_crops,
            )

            print(f"[OK] enriched: {enriched_path}")
            print(f"[OK] md:       {md_path}")
            total += 1

    print(f"[DONE] processed pages: {total}")


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input-root",
        default="output/hybrid_deepseek_layout_mvp/aligned_json",
        help="Input root of hybrid aligned JSON.",
    )

    parser.add_argument(
        "--out-json-root",
        default="output/hybrid_deepseek_layout_mvp/enriched_json",
        help="Output root for enriched JSON.",
    )

    parser.add_argument(
        "--out-md-root",
        default="output/hybrid_deepseek_layout_mvp/export_md_by_page",
        help="Output root for page-level Markdown.",
    )

    parser.add_argument(
        "--crop-root",
        default="output/hybrid_deepseek_layout_mvp/visual_region_crops",
        help="Output root for visual region crops.",
    )

    parser.add_argument(
        "--doc",
        default=None,
        help="Only process one doc_id.",
    )

    parser.add_argument(
        "--pages",
        type=int,
        nargs="*",
        default=None,
        help="Only process selected pages, e.g. --pages 1 2 3.",
    )

    parser.add_argument(
        "--no-crops",
        action="store_true",
        help="Do not crop visual regions or embed images in Markdown.",
    )

    return parser


if __name__ == "__main__":
    parser = build_argparser()
    args = parser.parse_args()
    run(args)