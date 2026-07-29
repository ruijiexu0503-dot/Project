#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Hybrid DeepSeekOCR2 + PP-DocLayout alignment MVP.

Goal:
  - DeepSeekOCR2 ocr.md provides:
      text
      reading order
      optional pixel_bbox from bbox comments

  - PP-DocLayout JSON provides:
      visual regions
      reliable-ish bbox
      layout labels

  - This script aligns DeepSeekOCR2 text blocks to PP-DocLayout regions.

Important:
  - It does NOT run OCR again.
  - It does NOT crop images.
  - It preserves DeepSeekOCR2 order as final_order.
  - It uses layout bbox as preferred spatial evidence.
  - If DeepSeek text is inside a layout image/table/figure container,
    it creates a contains_visible_text relation.

Default output:
  output/hybrid_deepseek_layout_mvp/aligned_json/<doc_id>/page_XXXX.json
  output/hybrid_deepseek_layout_mvp/debug_vis/<doc_id>/page_XXXX.aligned.jpg
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


BBox = List[float]


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

CONTAINER_LABEL_GROUPS = {
    "figure",
    "table",
    "image",
}

CONTAINER_LABELS = {
    "image",
    "figure",
    "table",
    "chart",
    "header_image",
    "cover",
    "logo",
    "seal",
    "icon",
    "footer",
    "background",
}

HEADING_LABELS = {
    "title",
    "paragraph_title",
    "header",
    "header_text",
}

CAPTION_LABELS = {
    "caption",
    "figure_caption",
    "table_caption",
}

TABLE_LABELS = {
    "table",
    "table_title",
    "table_caption",
}


# -----------------------------
# Basic IO
# -----------------------------

def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


# -----------------------------
# Text utils
# -----------------------------

def clean_text(s: Any) -> str:
    if s is None:
        return ""

    s = str(s)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", s)

    def md_link_repl(m: re.Match) -> str:
        return m.group(1)

    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", md_link_repl, s)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def short_text(s: str, n: int = 120) -> str:
    s = clean_text(s)
    return s if len(s) <= n else s[: n - 3] + "..."


# -----------------------------
# BBox utils
# -----------------------------

def bbox_area(b: Optional[BBox]) -> float:
    if not b or len(b) != 4:
        return 0.0
    x1, y1, x2, y2 = b
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def bbox_intersection(a: Optional[BBox], b: Optional[BBox]) -> float:
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 0.0

    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    return max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)


def bbox_iou(a: Optional[BBox], b: Optional[BBox]) -> float:
    inter = bbox_intersection(a, b)
    denom = bbox_area(a) + bbox_area(b) - inter
    return inter / denom if denom > 0 else 0.0


def overlap_frac(inner: Optional[BBox], outer: Optional[BBox]) -> float:
    """
    Fraction of inner covered by outer.
    Used to check whether a DeepSeek text bbox is inside a layout region.
    """
    area = bbox_area(inner)
    if area <= 0:
        return 0.0
    return bbox_intersection(inner, outer) / area


def center_inside(inner: Optional[BBox], outer: Optional[BBox]) -> bool:
    if not inner or not outer or len(inner) != 4 or len(outer) != 4:
        return False

    x1, y1, x2, y2 = inner
    ox1, oy1, ox2, oy2 = outer

    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0

    return ox1 <= cx <= ox2 and oy1 <= cy <= oy2


def union_bbox(boxes: List[BBox]) -> Optional[BBox]:
    boxes = [b for b in boxes if b and len(b) == 4]
    if not boxes:
        return None

    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def clamp_bbox(b: Optional[BBox], width: int, height: int) -> Optional[BBox]:
    if not b or len(b) != 4:
        return None

    x1, y1, x2, y2 = [float(v) for v in b]

    x1 = max(0.0, min(float(width), x1))
    x2 = max(0.0, min(float(width), x2))
    y1 = max(0.0, min(float(height), y1))
    y2 = max(0.0, min(float(height), y2))

    if x2 <= x1 or y2 <= y1:
        return None

    return [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)]


def bbox_valid_for_matching(b: Optional[BBox], page_w: int, page_h: int) -> bool:
    """
    DeepSeekOCR2 bbox can be noisy. This rejects only obviously unusable boxes.
    """
    if not b or len(b) != 4:
        return False

    x1, y1, x2, y2 = b

    if x2 <= x1 or y2 <= y1:
        return False

    if x2 < 0 or y2 < 0 or x1 > page_w or y1 > page_h:
        return False

    area = bbox_area(b)
    page_area = page_w * page_h

    # A text block bbox covering most of the page is suspicious.
    if area > 0.70 * page_area:
        return False

    return True


# -----------------------------
# Type helpers
# -----------------------------

def normalize_type_label(label: str, label_group: str = "") -> str:
    label = (label or "").lower()
    label_group = (label_group or "").lower()

    if label in CAPTION_LABELS:
        return "caption"

    if label in TABLE_LABELS or label_group == "table":
        return "table"

    if label in HEADING_LABELS:
        return "heading"

    if label_group == "figure" or label in CONTAINER_LABELS:
        return "visual"

    if label in TEXT_LIKE_LABELS or label_group == "text":
        return "text"

    return label or label_group or "unknown"


def is_text_like_region(r: Dict[str, Any]) -> bool:
    label = str(r.get("label") or "").lower()
    label_group = str(r.get("label_group") or "").lower()
    role = str(r.get("role") or "").lower()

    if role in {"text", "heading", "caption", "table"}:
        return True

    return label in TEXT_LIKE_LABELS or label_group == "text"


def is_visual_container(r: Dict[str, Any]) -> bool:
    label = str(r.get("label") or "").lower()
    label_group = str(r.get("label_group") or "").lower()
    role = str(r.get("role") or "").lower()

    if role in {"visual", "table"}:
        return True

    if label_group in CONTAINER_LABEL_GROUPS:
        return True

    if label in CONTAINER_LABELS:
        return True

    return False


def block_type_from_md(text: str, bbox_meta: Optional[Dict[str, Any]] = None) -> str:
    raw_type = ""
    if bbox_meta:
        raw_type = str(bbox_meta.get("type") or "").lower()

    stripped = text.strip()

    if "title" in raw_type or stripped.startswith("#"):
        return "heading"

    if "table" in raw_type:
        return "table"

    if "caption" in raw_type:
        return "caption"

    if "|" in stripped and re.search(r"\|[-:\s]+\|", stripped):
        return "table"

    if re.search(r"^(fig\.|figure|table)\s*\d*", stripped, flags=re.I):
        return "caption"

    return "text"


# -----------------------------
# Parse DeepSeekOCR2 ocr.md
# -----------------------------

def parse_bbox_comment(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse lines like:
      <!-- bbox: {"id": 0, "box_index": 0, "type": "sub_title",
                  "raw_bbox": [...],
                  "pixel_bbox": [...],
                  "bbox_scale": "norm999",
                  "image_width": 2560,
                  "image_height": 1920} -->
    """
    m = re.search(r"<!--\s*bbox:\s*(\{.*?\})\s*-->", line.strip())
    if not m:
        return None

    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def parse_ocr_md(md_text: str, page_w: int, page_h: int) -> List[Dict[str, Any]]:
    """
    Parse DeepSeekOCR2 ocr.md with bbox comments.

    Expected pattern:
      <!-- bbox: {... "pixel_bbox": [x1,y1,x2,y2], ...} -->

      markdown text...

      <!-- bbox: {...} -->

      markdown text...
    """
    lines = md_text.splitlines()

    blocks: List[Dict[str, Any]] = []
    buf: List[str] = []
    current_bbox_meta: Optional[Dict[str, Any]] = None
    order = 0

    def flush() -> None:
        nonlocal order, buf, current_bbox_meta

        text = "\n".join(buf).strip()
        buf = []

        if not text:
            return

        order += 1

        bbox = None
        raw_bbox = None
        bbox_scale = None
        box_index = None
        ds_type = None
        ds_id = None

        if current_bbox_meta:
            # In your ocr.md, pixel_bbox is the page-pixel bbox we want.
            if isinstance(current_bbox_meta.get("pixel_bbox"), list):
                bbox = current_bbox_meta.get("pixel_bbox")
            elif isinstance(current_bbox_meta.get("bbox"), list):
                bbox = current_bbox_meta.get("bbox")

            if isinstance(current_bbox_meta.get("raw_bbox"), list):
                raw_bbox = current_bbox_meta.get("raw_bbox")

            bbox_scale = current_bbox_meta.get("bbox_scale")
            box_index = current_bbox_meta.get("box_index")
            ds_type = current_bbox_meta.get("type")
            ds_id = current_bbox_meta.get("id")

        bbox = clamp_bbox(bbox, page_w, page_h) if bbox else None

        flags = []
        if bbox is None:
            flags.append("no_deepseek_bbox")
        elif not bbox_valid_for_matching(bbox, page_w, page_h):
            flags.append("deepseek_bbox_suspicious")

        block_type = block_type_from_md(text, current_bbox_meta)

        blocks.append({
            "block_id": f"ds_md_{order:04d}",
            "deepseek_order": order,
            "block_type": block_type,
            "text": clean_text(text),
            "markdown": text,
            "deepseek_bbox": bbox,
            "source": "ocr.md",
            "flags": flags,
            "raw": {
                "deepseek_id": ds_id,
                "box_index": box_index,
                "deepseek_type": ds_type,
                "raw_bbox": raw_bbox,
                "bbox_scale": bbox_scale,
            },
        })

        current_bbox_meta = None

    for line in lines:
        meta = parse_bbox_comment(line)

        if meta is not None:
            # A new bbox comment starts a new DeepSeek block.
            flush()
            current_bbox_meta = meta
            continue

        if not line.strip():
            # Do not flush immediately after bbox comment.
            # But if we already collected text, blank line means block boundary.
            if buf:
                flush()
            continue

        buf.append(line)

    flush()

    return [b for b in blocks if b.get("text")]


# -----------------------------
# Parse DeepSeek JSON fallback
# -----------------------------

def extract_bbox_from_obj(obj: Dict[str, Any]) -> Optional[BBox]:
    if "bbox" in obj and isinstance(obj["bbox"], list) and len(obj["bbox"]) == 4:
        return [float(v) for v in obj["bbox"]]

    if "pixel_bbox" in obj and isinstance(obj["pixel_bbox"], list) and len(obj["pixel_bbox"]) == 4:
        return [float(v) for v in obj["pixel_bbox"]]

    poly = obj.get("polygon")
    if isinstance(poly, dict):
        bbox = poly.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            return [float(v) for v in bbox]

    if isinstance(poly, list):
        points = []
        for p in poly:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                points.append((float(p[0]), float(p[1])))
            elif isinstance(p, dict) and "x" in p and "y" in p:
                points.append((float(p["x"]), float(p["y"])))

        if points:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            return [min(xs), min(ys), max(xs), max(ys)]

    return None


def extract_text_from_obj(obj: Dict[str, Any]) -> str:
    keys = [
        "text",
        "raw_text",
        "html",
        "markdown",
        "md",
        "block_description",
        "content",
    ]

    vals = []
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            vals.append(v)

    return clean_text("\n".join(vals))


def walk_deepseek_objects(data: Any) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []

    def rec(x: Any) -> None:
        if isinstance(x, dict):
            has_bbox = extract_bbox_from_obj(x) is not None
            text = extract_text_from_obj(x)
            has_text = bool(text)

            if has_bbox or has_text:
                found.append(x)

            for v in x.values():
                rec(v)

        elif isinstance(x, list):
            for item in x:
                rec(item)

    rec(data)
    return found


def load_deepseek_blocks(page_dir: Path, page_w: int, page_h: int) -> List[Dict[str, Any]]:
    """
    Prefer ocr.md because your ocr.md already contains bbox comments.
    Fallback to bbox_items_official.json / bbox_items.json only when needed.
    """
    md_path = page_dir / "ocr.md"
    if md_path.exists():
        blocks = parse_ocr_md(read_text(md_path), page_w, page_h)
        if blocks:
            return blocks

    candidates = [
        page_dir / "bbox_items_official.json",
        page_dir / "bbox_items.json",
    ]

    for path in candidates:
        if not path.exists():
            continue

        try:
            data = load_json(path)
        except Exception as e:
            print(f"[WARN] Cannot read {path}: {e}")
            continue

        objs = walk_deepseek_objects(data)
        blocks = []

        for i, obj in enumerate(objs, start=1):
            text = extract_text_from_obj(obj)
            bbox = clamp_bbox(extract_bbox_from_obj(obj), page_w, page_h)

            if not text:
                continue

            raw_type = str(
                obj.get("block_type")
                or obj.get("type")
                or obj.get("label")
                or ""
            ).lower()

            if "title" in raw_type or text.startswith("#"):
                block_type = "heading"
            elif "table" in raw_type:
                block_type = "table"
            elif "caption" in raw_type or re.match(r"^(fig\.|figure|table)\s*\d*", text, flags=re.I):
                block_type = "caption"
            else:
                block_type = "text"

            flags = []
            if bbox is None:
                flags.append("no_deepseek_bbox")
            elif not bbox_valid_for_matching(bbox, page_w, page_h):
                flags.append("deepseek_bbox_suspicious")

            raw_block_id = obj.get("block_id")
            block_id = str(raw_block_id) if raw_block_id is not None else f"{i:04d}"

            blocks.append({
                "block_id": f"ds_{block_id}",
                "deepseek_order": i,
                "block_type": block_type,
                "text": text,
                "markdown": text,
                "deepseek_bbox": bbox,
                "source": path.name,
                "flags": flags,
                "raw": {
                    k: obj.get(k)
                    for k in ["block_id", "block_type", "type", "label"]
                    if k in obj
                },
            })

        if blocks:
            return blocks

    return []


# -----------------------------
# Load PP-DocLayout regions
# -----------------------------

def normalize_layout_regions(layout_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    page_w = int(layout_json.get("page_width") or 0)
    page_h = int(layout_json.get("page_height") or 0)

    boxes = layout_json.get("boxes") or []
    regions: List[Dict[str, Any]] = []

    for i, box in enumerate(boxes, start=1):
        bbox = clamp_bbox(box.get("bbox"), page_w, page_h)
        if bbox is None:
            continue

        label = str(box.get("label") or "").lower()
        label_group = str(box.get("label_group") or "").lower()
        role = normalize_type_label(label, label_group)

        region_id = str(box.get("layout_id") or f"layout_{i:03d}")

        regions.append({
            "region_id": region_id,
            "layout_order": i,
            "bbox": bbox,
            "label": label,
            "label_group": label_group,
            "role": role,
            "score": box.get("score"),
            "class_id": box.get("class_id"),
            "source": "pp_doclayout",
        })

    # Geometry order is only for debug, not final reading order.
    regions_sorted = sorted(regions, key=lambda r: (r["bbox"][1], r["bbox"][0]))
    for j, r in enumerate(regions_sorted, start=1):
        r["geometry_order"] = j

    return regions


# -----------------------------
# Matching
# -----------------------------

def type_compatibility(block_type: str, region: Dict[str, Any]) -> float:
    label = str(region.get("label") or "").lower()
    role = str(region.get("role") or "").lower()

    if block_type == "heading":
        if label in HEADING_LABELS or role == "heading":
            return 1.0
        if role == "text":
            return 0.55
        return 0.1

    if block_type == "caption":
        if label in CAPTION_LABELS or role == "caption":
            return 1.0
        if role in {"text", "visual"}:
            return 0.35
        return 0.1

    if block_type == "table":
        if role == "table" or label in TABLE_LABELS:
            return 1.0
        if role == "text":
            return 0.25
        return 0.1

    if role == "text":
        return 1.0

    if role == "heading":
        return 0.25

    if role == "caption":
        return 0.25

    return 0.1


def match_to_text_region(
    block: Dict[str, Any],
    text_regions: List[Dict[str, Any]],
    page_w: int,
    page_h: int,
) -> Optional[Dict[str, Any]]:
    ds_bbox = block.get("deepseek_bbox")

    if not bbox_valid_for_matching(ds_bbox, page_w, page_h):
        return None

    candidates = []

    for r in text_regions:
        rb = r["bbox"]

        inside = center_inside(ds_bbox, rb)
        contain = overlap_frac(ds_bbox, rb)
        iou = bbox_iou(ds_bbox, rb)
        type_score = type_compatibility(block.get("block_type", "text"), r)

        # Main signal: DeepSeek text bbox lies inside/overlaps layout text region.
        score = (
            0.60 * contain
            + 0.20 * (1.0 if inside else 0.0)
            + 0.15 * iou
            + 0.05 * type_score
        )

        if contain >= 0.20 or inside:
            candidates.append({
                "region": r,
                "score": score,
                "overlap_frac": contain,
                "iou": iou,
                "center_inside": inside,
                "type_score": type_score,
            })

    if not candidates:
        return None

    candidates.sort(
        key=lambda c: (c["score"], c["overlap_frac"], c["iou"]),
        reverse=True,
    )
    best = candidates[0]

    if best["score"] < 0.25:
        return None

    return best


def match_to_visual_container(
    block: Dict[str, Any],
    containers: List[Dict[str, Any]],
    page_w: int,
    page_h: int,
) -> Optional[Dict[str, Any]]:
    ds_bbox = block.get("deepseek_bbox")

    if not bbox_valid_for_matching(ds_bbox, page_w, page_h):
        return None

    candidates = []

    for r in containers:
        rb = r["bbox"]

        inside = center_inside(ds_bbox, rb)
        contain = overlap_frac(ds_bbox, rb)
        iou = bbox_iou(ds_bbox, rb)
        container_area = bbox_area(rb)

        score = (
            0.75 * contain
            + 0.20 * (1.0 if inside else 0.0)
            + 0.05 * iou
        )

        if contain >= 0.40 or inside:
            candidates.append({
                "region": r,
                "score": score,
                "overlap_frac": contain,
                "iou": iou,
                "center_inside": inside,
                "container_area": container_area,
            })

    if not candidates:
        return None

    # Prefer strong score, then smaller containing container.
    candidates.sort(
        key=lambda c: (c["score"], -c["container_area"]),
        reverse=True,
    )
    best = candidates[0]

    if best["score"] < 0.40:
        return None

    return best


def align_page(
    deepseek_blocks: List[Dict[str, Any]],
    layout_regions: List[Dict[str, Any]],
    page_w: int,
    page_h: int,
) -> Dict[str, Any]:
    text_regions = [r for r in layout_regions if is_text_like_region(r)]
    visual_containers = [r for r in layout_regions if is_visual_container(r)]

    aligned_blocks = []
    relations = []

    stats = {
        "total_deepseek_blocks": len(deepseek_blocks),
        "matched_text_region": 0,
        "matched_visual_container": 0,
        "unmatched": 0,
        "suspicious_deepseek_bbox": 0,
    }

    for block in deepseek_blocks:
        block_out = {
            "block_id": block["block_id"],
            "text": block["text"],
            "markdown": block.get("markdown"),
            "text_preview": short_text(block["text"]),
            "block_type": block.get("block_type", "text"),

            "deepseek_order": block.get("deepseek_order"),
            "final_order": block.get("deepseek_order"),
            "order_source": "deepseekocr2",

            "deepseek_bbox": block.get("deepseek_bbox"),
            "bbox": None,
            "bbox_source": None,
            "bbox_granularity": None,

            "matched_region_id": None,
            "matched_region_label": None,
            "matched_region_role": None,
            "layout_order": None,
            "geometry_order": None,
            "match_score": None,

            "visual_container_id": None,
            "flags": list(block.get("flags") or []),
            "source": block.get("source"),
            "raw": block.get("raw") or {},
        }

        if "deepseek_bbox_suspicious" in block_out["flags"]:
            stats["suspicious_deepseek_bbox"] += 1

        # Phase 1: match to text-like PP-DocLayout region.
        text_match = match_to_text_region(block, text_regions, page_w, page_h)

        if text_match is not None:
            r = text_match["region"]

            block_out.update({
                "bbox": r["bbox"],
                "bbox_source": "pp_doclayout",
                "bbox_granularity": "layout_text_region",
                "matched_region_id": r["region_id"],
                "matched_region_label": r["label"],
                "matched_region_role": r["role"],
                "layout_order": r.get("layout_order"),
                "geometry_order": r.get("geometry_order"),
                "match_score": round(text_match["score"], 4),
            })

            block_out["flags"].append("matched_text_region")
            stats["matched_text_region"] += 1
            aligned_blocks.append(block_out)
            continue

        # Phase 2: unmatched DeepSeek text may be visible text inside image/table/figure.
        container_match = match_to_visual_container(block, visual_containers, page_w, page_h)

        if container_match is not None:
            r = container_match["region"]

            block_out.update({
                "bbox": r["bbox"],
                "bbox_source": "pp_doclayout_container",
                "bbox_granularity": "visual_container",
                "matched_region_id": r["region_id"],
                "matched_region_label": r["label"],
                "matched_region_role": r["role"],
                "visual_container_id": r["region_id"],
                "layout_order": r.get("layout_order"),
                "geometry_order": r.get("geometry_order"),
                "match_score": round(container_match["score"], 4),
            })

            block_out["flags"].extend([
                "container_matched",
                "text_inside_visual_container",
                "no_exact_text_region",
            ])

            relations.append({
                "source_region_id": r["region_id"],
                "target_block_id": block["block_id"],
                "relation_type": "contains_visible_text",
                "confidence": round(container_match["score"], 4),
                "evidence": {
                    "deepseek_bbox": block.get("deepseek_bbox"),
                    "container_bbox": r["bbox"],
                    "overlap_frac": round(container_match["overlap_frac"], 4),
                    "center_inside": container_match["center_inside"],
                },
            })

            stats["matched_visual_container"] += 1
            aligned_blocks.append(block_out)
            continue

        # Phase 3: still unmatched. Preserve it.
        block_out["flags"].append("no_layout_match")

        if bbox_valid_for_matching(block.get("deepseek_bbox"), page_w, page_h):
            block_out.update({
                "bbox": block.get("deepseek_bbox"),
                "bbox_source": "deepseekocr2_unverified",
                "bbox_granularity": "deepseek_text_bbox",
            })
            block_out["flags"].append("kept_deepseek_bbox_as_unverified")
        else:
            block_out.update({
                "bbox": None,
                "bbox_source": "missing",
                "bbox_granularity": "none",
            })

        stats["unmatched"] += 1
        aligned_blocks.append(block_out)

    # This is the important part:
    # aligned_blocks are in DeepSeekOCR2 reading order.
    aligned_blocks.sort(
        key=lambda b: (
            b.get("final_order") is None,
            b.get("final_order") or 10**9,
        )
    )

    return {
        "layout_regions": layout_regions,
        "aligned_blocks": aligned_blocks,
        "relations": relations,
        "stats": stats,
    }


# -----------------------------
# Visualization
# -----------------------------

def draw_debug(
    page_image: Path,
    out_path: Path,
    layout_regions: List[Dict[str, Any]],
    aligned_blocks: List[Dict[str, Any]],
) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("[WARN] PIL not installed. Skip visualization.")
        return

    if not page_image.exists():
        print(f"[WARN] Page image not found: {page_image}")
        return

    img = Image.open(page_image).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
        small = ImageFont.truetype("DejaVuSans.ttf", 14)
    except Exception:
        font = None
        small = None

    # Draw all layout regions.
    for r in layout_regions:
        b = r["bbox"]
        label = r.get("label", "")

        if is_text_like_region(r):
            color = (0, 180, 0)
        elif is_visual_container(r):
            color = (40, 100, 255)
        else:
            color = (170, 170, 170)

        draw.rectangle(b, outline=color, width=2)
        draw.text(
            (b[0] + 3, b[1] + 3),
            f'{r["region_id"]}:{label}',
            fill=color,
            font=small,
        )

    # Draw aligned bboxes.
    for b in aligned_blocks:
        bbox = b.get("bbox")
        if not bbox:
            continue

        flags = set(b.get("flags") or [])

        if "matched_text_region" in flags:
            color = (255, 80, 0)
        elif "container_matched" in flags:
            color = (180, 0, 255)
        else:
            color = (255, 0, 0)

        draw.rectangle(bbox, outline=color, width=4)

        label = (
            f'D:{b.get("deepseek_order")} '
            f'{b.get("block_type")} '
            f'{b.get("matched_region_id") or "unmatched"}'
        )
        draw.text((bbox[0] + 5, bbox[1] + 22), label, fill=color, font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=95)


# -----------------------------
# Runner
# -----------------------------

def page_name_from_int(i: int) -> str:
    return f"page_{i:04d}"


def find_docs(layout_root: Path, deepseek_root: Path, requested_doc: Optional[str]) -> List[str]:
    if requested_doc:
        return [requested_doc]

    docs = set()

    if layout_root.exists():
        docs.update(p.name for p in layout_root.iterdir() if p.is_dir())

    if deepseek_root.exists():
        docs.update(p.name for p in deepseek_root.iterdir() if p.is_dir())

    return sorted(docs)


def run(args: argparse.Namespace) -> None:
    deepseek_root = Path(args.deepseek_root)
    layout_root = Path(args.layout_root)
    out_root = Path(args.out_root)
    vis_root = Path(args.vis_root) if args.vis_root else None

    docs = find_docs(layout_root, deepseek_root, args.doc)

    for doc_id in docs:
        layout_doc_dir = layout_root / doc_id
        deepseek_doc_dir = deepseek_root / doc_id

        if not layout_doc_dir.exists():
            print(f"[WARN] Missing layout doc dir: {layout_doc_dir}")
            continue

        if not deepseek_doc_dir.exists():
            print(f"[WARN] Missing DeepSeek doc dir: {deepseek_doc_dir}")
            continue

        if args.pages:
            page_jsons = [
                layout_doc_dir / f"{page_name_from_int(p)}.json"
                for p in args.pages
            ]
        else:
            page_jsons = sorted(layout_doc_dir.glob("page_*.json"))

        for layout_json_path in page_jsons:
            if not layout_json_path.exists():
                print(f"[WARN] Missing layout json: {layout_json_path}")
                continue

            page_stem = layout_json_path.stem
            deepseek_page_dir = deepseek_doc_dir / page_stem

            if not deepseek_page_dir.exists():
                print(f"[WARN] Missing DeepSeek page dir: {deepseek_page_dir}")
                continue

            layout_data = load_json(layout_json_path)
            page_w = int(layout_data.get("page_width") or 0)
            page_h = int(layout_data.get("page_height") or 0)

            if page_w <= 0 or page_h <= 0:
                print(f"[WARN] Invalid page size in {layout_json_path}")
                continue

            layout_regions = normalize_layout_regions(layout_data)
            deepseek_blocks = load_deepseek_blocks(deepseek_page_dir, page_w, page_h)

            result = align_page(
                deepseek_blocks=deepseek_blocks,
                layout_regions=layout_regions,
                page_w=page_w,
                page_h=page_h,
            )

            page_out = {
                "doc_id": doc_id,
                "page": page_stem,
                "page_width": page_w,
                "page_height": page_h,
                "page_image": str(deepseek_page_dir / "page.png"),
                "deepseek_page_dir": str(deepseek_page_dir),
                "layout_json": str(layout_json_path),

                "stats": result["stats"],

                # This is the DeepSeekOCR2 reading order.
                "aligned_blocks": result["aligned_blocks"],

                # Image/table/figure contains visible text relations.
                "relations": result["relations"],

                # Not reading order. This is the PP-DocLayout visual region inventory.
                "layout_regions": result["layout_regions"],
            }

            out_path = out_root / doc_id / f"{page_stem}.json"
            save_json(page_out, out_path)

            print(f"[OK] {doc_id}/{page_stem} -> {out_path}")
            print(f"     stats: {result['stats']}")

            if vis_root:
                page_image = deepseek_page_dir / "page.png"
                vis_path = vis_root / doc_id / f"{page_stem}.aligned.jpg"
                draw_debug(
                    page_image=page_image,
                    out_path=vis_path,
                    layout_regions=result["layout_regions"],
                    aligned_blocks=result["aligned_blocks"],
                )
                print(f"     vis: {vis_path}")


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()

    p.add_argument(
        "--deepseek-root",
        default="output/render_result",
        help="Root of DeepSeekOCR2 page outputs.",
    )

    p.add_argument(
        "--layout-root",
        default="output/layout_detection",
        help="Root of PP-DocLayout JSON outputs.",
    )

    p.add_argument(
        "--out-root",
        default="output/hybrid_deepseek_layout_mvp/aligned_json",
        help="Output root for aligned JSON.",
    )

    p.add_argument(
        "--vis-root",
        default="output/hybrid_deepseek_layout_mvp/debug_vis",
        help="Output root for debug visualization. Use empty string to disable.",
    )

    p.add_argument(
        "--doc",
        default=None,
        help="Process only one doc_id.",
    )

    p.add_argument(
        "--pages",
        type=int,
        nargs="*",
        default=None,
        help="Process selected page numbers, e.g. --pages 1 2 3.",
    )

    return p


if __name__ == "__main__":
    parser = build_argparser()
    args = parser.parse_args()

    if args.vis_root == "":
        args.vis_root = None

    run(args)