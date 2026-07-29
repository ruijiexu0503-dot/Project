#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


COMMENT_RE = re.compile(r"<!--\s*bbox:\s*(\{.*?\})\s*-->")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def to_bbox(x: Any) -> Optional[List[float]]:
    if not isinstance(x, (list, tuple)) or len(x) != 4:
        return None
    try:
        return [float(x[0]), float(x[1]), float(x[2]), float(x[3])]
    except Exception:
        return None


def clamp_bbox(b: List[float], w: float, h: float) -> List[float]:
    x1, y1, x2, y2 = b
    x1 = max(0.0, min(float(w), float(x1)))
    y1 = max(0.0, min(float(h), float(y1)))
    x2 = max(0.0, min(float(w), float(x2)))
    y2 = max(0.0, min(float(h), float(y2)))

    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1

    return [x1, y1, x2, y2]


def box_area(b: List[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def box_w(b: List[float]) -> float:
    return max(0.0, b[2] - b[0])


def box_h(b: List[float]) -> float:
    return max(0.0, b[3] - b[1])


def round_bbox(b: List[float]) -> List[float]:
    return [round(float(v), 2) for v in b]


def intersect_box(a: List[float], b: List[float]) -> Optional[List[float]]:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])

    if x2 <= x1 or y2 <= y1:
        return None

    return [x1, y1, x2, y2]


def intersection_area(a: List[float], b: List[float]) -> float:
    ib = intersect_box(a, b)
    if ib is None:
        return 0.0
    return box_area(ib)


def iou(a: List[float], b: List[float]) -> float:
    inter = intersection_area(a, b)
    if inter <= 0:
        return 0.0

    union = box_area(a) + box_area(b) - inter
    if union <= 0:
        return 0.0

    return inter / union


def center(b: List[float]) -> Tuple[float, float]:
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


def center_inside(inner: List[float], outer: List[float]) -> bool:
    cx, cy = center(inner)
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def center_distance(a: List[float], b: List[float]) -> float:
    ax, ay = center(a)
    bx, by = center(b)
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


def overlap_x_ratio(a: List[float], b: List[float]) -> float:
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    aw = box_w(a)
    return inter / aw if aw > 0 else 0.0


def overlap_y_ratio(a: List[float], b: List[float]) -> float:
    inter = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    ah = box_h(a)
    return inter / ah if ah > 0 else 0.0


def raw_to_pixel_bbox(raw_bbox: List[float], w: float, h: float) -> List[float]:
    return [
        raw_bbox[0] / 999.0 * w,
        raw_bbox[1] / 999.0 * h,
        raw_bbox[2] / 999.0 * w,
        raw_bbox[3] / 999.0 * h,
    ]


def parse_ocr_md(md_path: Path) -> List[Dict[str, Any]]:
    if not md_path.exists():
        return []

    lines = md_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    blocks: List[Dict[str, Any]] = []
    current_meta: Optional[Dict[str, Any]] = None
    current_text: List[str] = []

    def flush() -> None:
        nonlocal current_meta, current_text

        if current_meta is None:
            current_text = []
            return

        block = dict(current_meta)
        block["text"] = "\n".join(current_text).strip()
        blocks.append(block)

        current_meta = None
        current_text = []

    for line in lines:
        m = COMMENT_RE.search(line)
        if m:
            flush()
            try:
                current_meta = json.loads(m.group(1))
            except Exception:
                current_meta = None
            current_text = []
        else:
            if current_meta is not None:
                current_text.append(line)

    flush()
    return blocks


def extract_json_items(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if isinstance(data, dict):
        for key in ["items", "blocks", "bbox_items", "boxes", "results"]:
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]

    return []


def find_block_json(page_dir: Path) -> Optional[Path]:
    candidates = [
        page_dir / "bbox_items_official.json",
        page_dir / "bbox_items.json",
    ]

    for p in candidates:
        if p.exists():
            return p

    return None


def normalize_block(
    item: Dict[str, Any],
    page_w: float,
    page_h: float,
    text_by_id: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    block_id = item.get("id", item.get("block_id", item.get("box_index", item.get("index"))))
    if block_id is None:
        block_id = len(text_by_id)

    block_id_str = str(block_id)

    typ = item.get("type", item.get("label", item.get("category", "unknown")))

    bbox = (
        to_bbox(item.get("pixel_bbox"))
        or to_bbox(item.get("bbox_pixel"))
        or to_bbox(item.get("bbox"))
    )

    raw_bbox = to_bbox(item.get("raw_bbox"))
    if bbox is None and raw_bbox is not None:
        bbox = raw_to_pixel_bbox(raw_bbox, page_w, page_h)

    if bbox is None:
        return None

    text = (
        item.get("text")
        or item.get("content")
        or item.get("md")
        or item.get("markdown")
        or text_by_id.get(block_id_str, "")
    )

    return {
        "block_id": block_id,
        "type": str(typ),
        "text": text,
        "bbox_original": clamp_bbox(bbox, page_w, page_h),
        "raw_bbox": raw_bbox,
    }


def load_blocks(page_dir: Path, page_w: float, page_h: float) -> List[Dict[str, Any]]:
    md_blocks = parse_ocr_md(page_dir / "ocr.md")

    text_by_id: Dict[str, str] = {}
    for b in md_blocks:
        bid = b.get("id", b.get("block_id", b.get("box_index")))
        if bid is not None:
            text_by_id[str(bid)] = b.get("text", "")

    json_path = find_block_json(page_dir)
    if json_path is not None:
        items = extract_json_items(load_json(json_path))
    else:
        items = md_blocks

    blocks: List[Dict[str, Any]] = []
    for item in items:
        nb = normalize_block(item, page_w, page_h, text_by_id)
        if nb is not None:
            blocks.append(nb)

    blocks.sort(key=lambda x: (x["bbox_original"][1], x["bbox_original"][0]))
    return blocks


def normalize_layout_box(
    item: Dict[str, Any],
    idx: int,
    page_w: float,
    page_h: float,
) -> Optional[Dict[str, Any]]:
    bbox = to_bbox(item.get("bbox")) or to_bbox(item.get("pixel_bbox"))
    if bbox is None:
        return None

    layout_id = item.get("layout_id", f"layout_{idx:03d}")
    label = str(item.get("label", "unknown"))
    label_group = str(item.get("label_group", label))

    try:
        score = float(item.get("score", 1.0))
    except Exception:
        score = 1.0

    return {
        "layout_id": layout_id,
        "bbox": clamp_bbox(bbox, page_w, page_h),
        "label": label,
        "label_group": label_group,
        "score": score,
        "class_id": item.get("class_id"),
    }


def load_layout(layout_path: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    data = load_json(layout_path)

    page_w = float(data.get("page_width", data.get("image_width", 0)) or 0)
    page_h = float(data.get("page_height", data.get("image_height", 0)) or 0)

    boxes_raw = data.get("boxes", [])
    boxes: List[Dict[str, Any]] = []

    for idx, item in enumerate(boxes_raw):
        if not isinstance(item, dict):
            continue

        nb = normalize_layout_box(item, idx, page_w, page_h)
        if nb is not None:
            boxes.append(nb)

    boxes.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
    return data, boxes


def block_group(block_type: str, text: str = "") -> str:
    s = f"{block_type} {text[:80]}".lower()

    if "image" in s or "figure" in s:
        return "figure"
    if "table" in s:
        return "table"
    if "caption" in s:
        return "caption"
    if "title" in s or "heading" in s or "header" in s or "sub_title" in s:
        return "title"
    if "equation" in s or "formula" in s:
        return "text"

    return "text"


def layout_group(layout: Dict[str, Any]) -> str:
    label = str(layout.get("label", "")).lower()
    group = str(layout.get("label_group", "")).lower()
    s = f"{label} {group}"

    if "image" in s or "figure" in s:
        return "figure"
    if "table" in s:
        return "table"
    if "caption" in s:
        return "caption"
    if "title" in s or "heading" in s:
        return "title"
    if "toc" in s or "contents" in s or "list" in s:
        return "text"
    if "formula" in s or "equation" in s:
        return "text"

    return "text"


def is_text_like(kind: str) -> bool:
    return kind in {"text", "caption", "title"}


def compatibility(block_kind: str, layout_kind: str) -> float:
    if block_kind == layout_kind:
        return 1.0

    if block_kind == "caption" and layout_kind in {"text", "caption"}:
        return 0.85

    if block_kind == "text" and layout_kind in {"text", "caption", "title"}:
        return 0.75

    if block_kind == "title" and layout_kind in {"title", "text"}:
        return 0.75

    if block_kind in {"figure", "table"} and layout_kind != block_kind:
        return 0.0

    return 0.2


def candidate_score(
    block: Dict[str, Any],
    layout: Dict[str, Any],
    page_w: float,
    page_h: float,
) -> Optional[Dict[str, Any]]:
    bb = block["bbox_original"]
    lb = layout["bbox"]

    ba = box_area(bb)
    la = box_area(lb)

    if ba <= 0 or la <= 0:
        return None

    inter = intersection_area(bb, lb)
    iou_val = iou(bb, lb)

    cover_block = inter / ba if ba > 0 else 0.0
    cover_layout = inter / la if la > 0 else 0.0

    c_inside = center_inside(bb, lb)
    dist_px = center_distance(bb, lb)

    diag = math.sqrt(page_w ** 2 + page_h ** 2)
    dist_norm = dist_px / diag if diag > 0 else 1.0

    b_kind = block_group(block.get("type", ""), block.get("text", ""))
    l_kind = layout_group(layout)
    comp = compatibility(b_kind, l_kind)

    area_ratio = la / ba
    sym_ratio = max(area_ratio, ba / la)

    ox = overlap_x_ratio(bb, lb)
    oy = overlap_y_ratio(bb, lb)

    near = dist_px <= max(80.0, 0.05 * min(page_w, page_h))

    if inter <= 0 and not near:
        return None

    if comp <= 0 and inter <= 0:
        return None

    score = (
        2.0 * iou_val
        + 1.1 * cover_block
        + 0.7 * cover_layout
        + 0.4 * float(c_inside)
        + 0.4 * float(layout.get("score", 1.0))
        + 0.8 * comp
        + 0.25 * ox
        + 0.25 * oy
        - 0.25 * math.log(max(1.0, sym_ratio))
        - 1.5 * dist_norm
    )

    return {
        "layout_id": layout["layout_id"],
        "label": layout["label"],
        "label_group": layout["label_group"],
        "bbox": layout["bbox"],
        "score": round(score, 6),
        "layout_score": layout.get("score", 1.0),
        "iou": round(iou_val, 6),
        "cover_block": round(cover_block, 6),
        "cover_layout": round(cover_layout, 6),
        "center_inside": c_inside,
        "center_distance": round(dist_px, 3),
        "area_ratio_layout_over_block": round(area_ratio, 6),
        "width_ratio_layout_over_block": round(box_w(lb) / box_w(bb), 6) if box_w(bb) > 0 else 999.0,
        "height_ratio_layout_over_block": round(box_h(lb) / box_h(bb), 6) if box_h(bb) > 0 else 999.0,
        "overlap_x_ratio": round(ox, 6),
        "overlap_y_ratio": round(oy, 6),
        "compatibility": comp,
        "block_group": b_kind,
        "layout_group": l_kind,
    }


def find_candidates(
    block: Dict[str, Any],
    layouts: List[Dict[str, Any]],
    page_w: float,
    page_h: float,
    top_k: int = 8,
) -> List[Dict[str, Any]]:
    cands: List[Dict[str, Any]] = []

    for layout in layouts:
        c = candidate_score(block, layout, page_w, page_h)
        if c is not None:
            cands.append(c)

    cands.sort(key=lambda x: x["score"], reverse=True)
    return cands[:top_k]


def apply_action(
    original_bbox: List[float],
    action: str,
    target_layout_bbox: Optional[List[float]],
    page_w: float,
    page_h: float,
    max_expand_px: float = 40.0,
) -> List[float]:
    b = list(original_bbox)

    if target_layout_bbox is None:
        return clamp_bbox(b, page_w, page_h)

    if action in {"keep", "anchor_to_layout", "needs_vlm_or_split"}:
        return clamp_bbox(b, page_w, page_h)

    lb = target_layout_bbox

    if action in {"snap_to_layout", "snap_to_layout_safe"}:
        return clamp_bbox(lb, page_w, page_h)

    if action == "clip_to_layout":
        ib = intersect_box(b, lb)
        if ib is not None and box_area(ib) > 0:
            return clamp_bbox(ib, page_w, page_h)
        return clamp_bbox(b, page_w, page_h)

    if action == "snap_x_to_layout":
        return clamp_bbox([lb[0], b[1], lb[2], b[3]], page_w, page_h)

    if action == "snap_y_to_layout":
        return clamp_bbox([b[0], lb[1], b[2], lb[3]], page_w, page_h)

    if action == "expand_within_layout":
        x1 = max(lb[0], b[0] - max_expand_px)
        y1 = max(lb[1], b[1] - max_expand_px)
        x2 = min(lb[2], b[2] + max_expand_px)
        y2 = min(lb[3], b[3] + max_expand_px)
        return clamp_bbox([x1, y1, x2, y2], page_w, page_h)

    return clamp_bbox(b, page_w, page_h)


def has_severe_layout_conflict(candidates: List[Dict[str, Any]]) -> bool:
    if len(candidates) < 2:
        return False

    first = candidates[0]
    second = candidates[1]

    if second["score"] >= first["score"] - 0.25:
        return True

    strong = [
        c for c in candidates
        if c["cover_block"] >= 0.35 or c["iou"] >= 0.18 or c["center_inside"]
    ]

    return len(strong) >= 2


def layout_boxes_overlap_too_much(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    ia = intersection_area(a["bbox"], b["bbox"])
    if ia <= 0:
        return False

    small = min(box_area(a["bbox"]), box_area(b["bbox"]))
    if small <= 0:
        return False

    return ia / small > 0.25


def choose_visual_split_candidates(
    block: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    min_candidates: int = 2,
) -> List[Dict[str, Any]]:
    kind = block_group(block.get("type", ""), block.get("text", ""))

    if kind not in {"figure", "table"}:
        return []

    good: List[Dict[str, Any]] = []

    for c in candidates:
        if c["layout_group"] != kind:
            continue

        if c["compatibility"] < 0.8:
            continue

        if (
            c["cover_layout"] >= 0.35
            or c["cover_block"] >= 0.06
            or c["iou"] >= 0.04
            or c["center_inside"]
        ):
            good.append(c)

    if len(good) < min_candidates:
        return []

    selected: List[Dict[str, Any]] = []
    for c in good:
        duplicate = False
        for s in selected:
            if layout_boxes_overlap_too_much(c, s):
                duplicate = True
                break

        if not duplicate:
            selected.append(c)

    if len(selected) < min_candidates:
        return []

    selected.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
    return selected


def decide_action(
    block: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not candidates:
        return {
            "action": "keep",
            "target_layout_id": None,
            "layout_anchor_id": None,
            "confidence": 0.0,
            "needs_vlm": False,
            "conflict_flags": [],
        }

    best = candidates[0]

    kind = best["block_group"]
    layout_kind = best["layout_group"]

    flags: List[str] = []

    severe = has_severe_layout_conflict(candidates)
    if severe:
        flags.append("multi_layout_conflict")

    iou_val = best["iou"]
    cover_block = best["cover_block"]
    cover_layout = best["cover_layout"]

    ox = best["overlap_x_ratio"]
    oy = best["overlap_y_ratio"]

    area_ratio = best["area_ratio_layout_over_block"]
    width_ratio = best["width_ratio_layout_over_block"]
    height_ratio = best["height_ratio_layout_over_block"]

    comp = best["compatibility"]
    conf = round(max(0.0, min(1.0, best["score"] / 4.0)), 4)

    # -----------------------------
    # image / table
    # -----------------------------
    if kind in {"figure", "table"}:
        if severe:
            return {
                "action": "needs_vlm_or_split",
                "target_layout_id": None,
                "layout_anchor_id": None,
                "confidence": 0.45,
                "needs_vlm": True,
                "conflict_flags": flags,
            }

        if comp >= 0.8 and (
            iou_val >= 0.15
            or cover_block >= 0.40
            or cover_layout >= 0.40
            or best["center_inside"]
        ):
            if 0.20 <= area_ratio <= 8.0 or cover_layout >= 0.15:
                return {
                    "action": "snap_to_layout",
                    "target_layout_id": best["layout_id"],
                    "layout_anchor_id": best["layout_id"],
                    "confidence": conf,
                    "needs_vlm": False,
                    "conflict_flags": flags,
                }

        return {
            "action": "keep",
            "target_layout_id": None,
            "layout_anchor_id": best["layout_id"] if cover_block >= 0.25 or cover_layout >= 0.25 else None,
            "confidence": conf,
            "needs_vlm": True,
            "conflict_flags": flags + ["weak_figure_table_match"],
        }

    # -----------------------------
    # text / caption / title
    # -----------------------------
        # -----------------------------
    # text / caption / title
    # -----------------------------
    if is_text_like(kind):
        if layout_kind not in {"text", "caption", "title"}:
            return {
                "action": "keep",
                "target_layout_id": None,
                "layout_anchor_id": best["layout_id"] if cover_block >= 0.25 else None,
                "confidence": conf,
                "needs_vlm": True,
                "conflict_flags": flags + ["incompatible_layout_kind"],
            }

        anchor_id = None
        if cover_block >= 0.35 or cover_layout >= 0.15 or best["center_inside"] or iou_val >= 0.10:
            anchor_id = best["layout_id"]

        bb = block["bbox_original"]
        lb = best["bbox"]

        x_tol = max(8.0, 0.02 * box_w(bb))
        y_tol = max(8.0, 0.02 * box_h(bb))

        left_mismatch = abs(bb[0] - lb[0]) > x_tol
        right_mismatch = abs(bb[2] - lb[2]) > x_tol
        top_mismatch = abs(bb[1] - lb[1]) > y_tol
        bottom_mismatch = abs(bb[3] - lb[3]) > y_tol

        x_mismatch = left_mismatch or right_mismatch
        y_mismatch = top_mismatch or bottom_mismatch

        width_not_absurd = 0.35 <= width_ratio <= 3.5
        height_not_absurd = 0.25 <= height_ratio <= 3.5

        x_compatible = ox >= 0.50 or best["center_inside"]
        y_compatible = oy >= 0.50 or best["center_inside"]

        # layout 是 atomic 小框：可以整体采用 layout bbox。
        # 这一步解决：
        # 1) parsing 轻微偏移但 layout 完全正确
        # 2) parsing 在 x/y 两个方向都错
        # 3) 只 snap_x 会保留错误 y 导致侵入的问题
        layout_is_atomic_enough = (
            comp >= 0.7
            and width_not_absurd
            and height_not_absurd
            and (
                cover_layout >= 0.45
                or iou_val >= 0.30
                or (best["center_inside"] and cover_layout >= 0.25)
            )
        )

        both_axes_problematic = x_mismatch and y_mismatch
        parsing_intrudes_badly = (
            cover_layout >= 0.45
            and cover_block <= 0.75
            and (x_mismatch or y_mismatch)
        )

        if layout_is_atomic_enough and (both_axes_problematic or parsing_intrudes_badly):
            return {
                "action": "snap_to_layout_safe",
                "target_layout_id": best["layout_id"],
                "layout_anchor_id": anchor_id,
                "confidence": conf,
                "needs_vlm": False,
                "conflict_flags": flags,
            }

        # 如果存在明显多 layout 冲突，且不能安全整体 snap，就不要硬修。
        if severe:
            return {
                "action": "needs_vlm_or_split",
                "target_layout_id": None,
                "layout_anchor_id": None,
                "confidence": 0.40,
                "needs_vlm": True,
                "conflict_flags": flags,
            }

        # 只在 y 方向可靠时，才允许 snap_x。
        # 如果 y 方向也明显错，不要 snap_x，否则会产生第二张图那种纵向侵入。
        if comp >= 0.7 and y_compatible and x_mismatch and not y_mismatch and width_not_absurd:
            return {
                "action": "snap_x_to_layout",
                "target_layout_id": best["layout_id"],
                "layout_anchor_id": anchor_id,
                "confidence": conf,
                "needs_vlm": False,
                "conflict_flags": flags,
            }

        # 只在 x 方向可靠时，才允许 snap_y。
        if comp >= 0.7 and x_compatible and y_mismatch and not x_mismatch and height_not_absurd:
            return {
                "action": "snap_y_to_layout",
                "target_layout_id": best["layout_id"],
                "layout_anchor_id": anchor_id,
                "confidence": conf,
                "needs_vlm": False,
                "conflict_flags": flags,
            }

        # 如果 layout 是同粒度小框，但只有一个方向 mismatch，也可以整体采用 layout。
        # 这个比单轴 snap 更稳，尤其用于 Further reading / caption / short paragraph。
        same_granularity = 0.50 <= area_ratio <= 2.20
        if comp >= 0.75 and same_granularity and (iou_val >= 0.35 or cover_layout >= 0.50):
            if x_mismatch or y_mismatch:
                return {
                    "action": "snap_to_layout_safe",
                    "target_layout_id": best["layout_id"],
                    "layout_anchor_id": anchor_id,
                    "confidence": conf,
                    "needs_vlm": False,
                    "conflict_flags": flags,
                }

        # 如果只是越界，但 layout 不是足够小的 atomic 框，才裁剪。
        if comp >= 0.7 and cover_block >= 0.60 and (ox < 0.98 or oy < 0.98):
            if area_ratio >= 0.35:
                return {
                    "action": "clip_to_layout",
                    "target_layout_id": best["layout_id"],
                    "layout_anchor_id": anchor_id,
                    "confidence": conf,
                    "needs_vlm": False,
                    "conflict_flags": flags,
                }

        # 同粒度 bbox，可以轻微扩张。
        if comp >= 0.75 and 0.70 <= area_ratio <= 1.70 and iou_val >= 0.45:
            return {
                "action": "expand_within_layout",
                "target_layout_id": best["layout_id"],
                "layout_anchor_id": anchor_id,
                "confidence": conf,
                "needs_vlm": False,
                "conflict_flags": flags,
            }

        if anchor_id is not None:
            return {
                "action": "anchor_to_layout",
                "target_layout_id": best["layout_id"],
                "layout_anchor_id": anchor_id,
                "confidence": conf,
                "needs_vlm": False,
                "conflict_flags": flags,
            }

        return {
            "action": "keep",
            "target_layout_id": None,
            "layout_anchor_id": None,
            "confidence": conf,
            "needs_vlm": False,
            "conflict_flags": flags,
        }


def compact_candidates(candidates: List[Dict[str, Any]], k: int = 3) -> List[Dict[str, Any]]:
    out = []
    for c in candidates[:k]:
        out.append({
            "layout_id": c["layout_id"],
            "label": c["label"],
            "label_group": c["label_group"],
            "score": c["score"],
            "iou": c["iou"],
            "cover_block": c["cover_block"],
            "cover_layout": c["cover_layout"],
            "overlap_x_ratio": c["overlap_x_ratio"],
            "overlap_y_ratio": c["overlap_y_ratio"],
            "area_ratio_layout_over_block": c["area_ratio_layout_over_block"],
            "width_ratio_layout_over_block": c["width_ratio_layout_over_block"],
            "height_ratio_layout_over_block": c["height_ratio_layout_over_block"],
        })
    return out


def repair_page(
    page_dir: Path,
    layout_path: Path,
    out_path: Path,
    vis_path: Optional[Path],
) -> Dict[str, Any]:
    layout_data, layouts = load_layout(layout_path)

    page_w = float(layout_data.get("page_width", layout_data.get("image_width", 0)) or 0)
    page_h = float(layout_data.get("page_height", layout_data.get("image_height", 0)) or 0)

    if page_w <= 0 or page_h <= 0:
        page_img = page_dir / "page.png"
        if page_img.exists():
            from PIL import Image
            im = Image.open(page_img)
            page_w, page_h = im.size
        else:
            raise ValueError(f"Cannot infer page size for {page_dir}")

    blocks = load_blocks(page_dir, page_w, page_h)
    layout_by_id = {x["layout_id"]: x for x in layouts}

    repaired_blocks: List[Dict[str, Any]] = []
    used_layout_ids = set()

    for block in blocks:
        candidates = find_candidates(block, layouts, page_w, page_h)

        # one parsing image/table block -> multiple layout image/table regions
        split_candidates = choose_visual_split_candidates(block, candidates)

        if split_candidates:
            parent_id = block["block_id"]

            for idx, c in enumerate(split_candidates):
                layout_id = c["layout_id"]
                layout_bbox = layout_by_id[layout_id]["bbox"]
                used_layout_ids.add(layout_id)

                child_id = f"{parent_id}__{layout_id}"

                repaired_blocks.append({
                    "block_id": child_id,
                    "parent_block_id": parent_id,
                    "split_index": idx,
                    "type": block["type"],
                    "text": block.get("text", ""),
                    "bbox_original": round_bbox(block["bbox_original"]),
                    "bbox_corrected": round_bbox(layout_bbox),
                    "raw_bbox": block.get("raw_bbox"),
                    "layout_anchor_id": layout_id,
                    "bbox_repair": {
                        "action": "split_from_layout",
                        "target_layout_id": layout_id,
                        "decision_source": "rule",
                        "confidence": round(max(0.0, min(1.0, c["score"] / 4.0)), 4),
                        "needs_vlm": False,
                        "conflict_flags": ["one_visual_block_to_multiple_layout_regions"],
                    },
                    "top_layout_candidates": compact_candidates(candidates),
                })

            continue

        decision = decide_action(block, candidates)

        target_layout_id = decision.get("target_layout_id")
        layout_anchor_id = decision.get("layout_anchor_id")

        target_bbox = None
        if target_layout_id is not None and target_layout_id in layout_by_id:
            target_bbox = layout_by_id[target_layout_id]["bbox"]

        corrected = apply_action(
            original_bbox=block["bbox_original"],
            action=decision["action"],
            target_layout_bbox=target_bbox,
            page_w=page_w,
            page_h=page_h,
        )

        if layout_anchor_id is not None:
            used_layout_ids.add(layout_anchor_id)

        if target_layout_id is not None:
            used_layout_ids.add(target_layout_id)

        repaired_blocks.append({
            "block_id": block["block_id"],
            "type": block["type"],
            "text": block.get("text", ""),
            "bbox_original": round_bbox(block["bbox_original"]),
            "bbox_corrected": round_bbox(corrected),
            "raw_bbox": block.get("raw_bbox"),
            "layout_anchor_id": layout_anchor_id,
            "bbox_repair": {
                "action": decision["action"],
                "target_layout_id": target_layout_id,
                "decision_source": "rule",
                "confidence": decision["confidence"],
                "needs_vlm": decision["needs_vlm"],
                "conflict_flags": decision.get("conflict_flags", []),
            },
            "top_layout_candidates": compact_candidates(candidates),
        })

    orphan_layout_regions = []
    for layout in layouts:
        if layout["layout_id"] not in used_layout_ids and float(layout.get("score", 1.0)) >= 0.5:
            orphan_layout_regions.append({
                "layout_id": layout["layout_id"],
                "label": layout["label"],
                "label_group": layout["label_group"],
                "score": layout["score"],
                "bbox": round_bbox(layout["bbox"]),
            })

    result = {
        "page": page_dir.name,
        "page_width": page_w,
        "page_height": page_h,
        "source": {
            "page_dir": str(page_dir),
            "layout_path": str(layout_path),
        },
        "blocks": repaired_blocks,
        "layout_regions": [
            {
                "layout_id": x["layout_id"],
                "label": x["label"],
                "label_group": x["label_group"],
                "score": x["score"],
                "bbox": round_bbox(x["bbox"]),
            }
            for x in layouts
        ],
        "orphan_layout_regions": orphan_layout_regions,
        "summary": {
            "num_blocks": len(repaired_blocks),
            "num_layout_regions": len(layouts),
            "num_orphan_layout_regions": len(orphan_layout_regions),
            "num_repaired": sum(
                1 for b in repaired_blocks
                if b["bbox_repair"]["action"] not in {"keep", "anchor_to_layout"}
            ),
            "num_anchored": sum(1 for b in repaired_blocks if b.get("layout_anchor_id") is not None),
            "num_split_from_layout": sum(
                1 for b in repaired_blocks
                if b["bbox_repair"]["action"] == "split_from_layout"
            ),
            "num_needs_vlm": sum(1 for b in repaired_blocks if b["bbox_repair"]["needs_vlm"]),
        },
    }

    save_json(result, out_path)

    if vis_path is not None:
        make_visualization(page_dir, layout_data, result, vis_path)

    return result


def resolve_image_path(page_dir: Path, layout_data: Dict[str, Any]) -> Optional[Path]:
    candidates: List[Path] = []

    if layout_data.get("image_path"):
        p = Path(str(layout_data["image_path"]))
        candidates.append(p)
        candidates.append(Path.cwd() / p)

    candidates.append(page_dir / "page.png")
    candidates.append(page_dir / "bboxes_preview.jpg")

    for p in candidates:
        if p.exists():
            return p

    return None


def make_visualization(
    page_dir: Path,
    layout_data: Dict[str, Any],
    result: Dict[str, Any],
    vis_path: Path,
) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return

    image_path = resolve_image_path(page_dir, layout_data)
    if image_path is None:
        return

    im = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(im)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    # blue: layout detection
    for layout in result["layout_regions"]:
        b = layout["bbox"]
        draw.rectangle(b, outline=(0, 120, 255), width=1)
        draw.text(
            (b[0], max(0, b[1] - 10)),
            str(layout["layout_id"]),
            fill=(0, 120, 255),
            font=font,
        )

    # red: original parsing bbox
    for block in result["blocks"]:
        b = block["bbox_original"]
        draw.rectangle(b, outline=(255, 0, 0), width=2)
        draw.text(
            (b[0], max(0, b[1] - 12)),
            str(block.get("parent_block_id", block["block_id"])),
            fill=(255, 0, 0),
            font=font,
        )

    # green: corrected bbox
    for block in result["blocks"]:
        b = block["bbox_corrected"]
        action = block["bbox_repair"]["action"]

        if action in {"keep", "anchor_to_layout"}:
            continue

        draw.rectangle(b, outline=(0, 200, 0), width=3)

        show_id = str(block["block_id"])
        if "__" in show_id:
            show_id = show_id.split("__", 1)[0] + "*"

        draw.text(
            (b[0], b[1]),
            f"{show_id}:{action}",
            fill=(0, 200, 0),
            font=font,
        )

    vis_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(vis_path, quality=95)


def iter_pages(
    render_root: Path,
    layout_root: Path,
    doc: Optional[str],
    pages: Optional[List[str]],
) -> Iterable[Tuple[str, str, Path, Path]]:
    if doc:
        doc_dirs = [render_root / doc]
    else:
        doc_dirs = sorted([p for p in render_root.iterdir() if p.is_dir()])

    for doc_dir in doc_dirs:
        if not doc_dir.exists():
            continue

        doc_name = doc_dir.name

        if pages:
            page_dirs = [doc_dir / p for p in pages]
        else:
            page_dirs = sorted([p for p in doc_dir.glob("page_*") if p.is_dir()])

        for page_dir in page_dirs:
            page_name = page_dir.name
            layout_path = layout_root / doc_name / f"{page_name}.json"

            if not page_dir.exists():
                continue

            if not layout_path.exists():
                continue

            yield doc_name, page_name, page_dir, layout_path


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--render-root", default="output/render_result")
    parser.add_argument("--layout-root", default="output/layout_detection")
    parser.add_argument("--out-root", default="output/fused_layout_parsing")
    parser.add_argument("--vis-root", default="output/fusion_vis")

    parser.add_argument("--doc", default=None)
    parser.add_argument("--pages", nargs="*", default=None)

    parser.add_argument("--make-vis", action="store_true")

    args = parser.parse_args()

    render_root = Path(args.render_root)
    layout_root = Path(args.layout_root)
    out_root = Path(args.out_root)
    vis_root = Path(args.vis_root)

    total_pages = 0
    total_blocks = 0
    total_repaired = 0
    total_anchored = 0
    total_split = 0
    total_need_vlm = 0

    for doc_name, page_name, page_dir, layout_path in iter_pages(
        render_root=render_root,
        layout_root=layout_root,
        doc=args.doc,
        pages=args.pages,
    ):
        out_path = out_root / doc_name / f"{page_name}.json"
        vis_path = vis_root / doc_name / f"{page_name}_repair.jpg" if args.make_vis else None

        result = repair_page(
            page_dir=page_dir,
            layout_path=layout_path,
            out_path=out_path,
            vis_path=vis_path,
        )

        s = result["summary"]

        total_pages += 1
        total_blocks += s["num_blocks"]
        total_repaired += s["num_repaired"]
        total_anchored += s["num_anchored"]
        total_split += s["num_split_from_layout"]
        total_need_vlm += s["num_needs_vlm"]

        print(
            f"[OK] {doc_name}/{page_name} "
            f"blocks={s['num_blocks']} "
            f"repaired={s['num_repaired']} "
            f"anchored={s['num_anchored']} "
            f"split={s['num_split_from_layout']} "
            f"needs_vlm={s['num_needs_vlm']} -> {out_path}"
        )

    print(
        f"\nDone. pages={total_pages}, blocks={total_blocks}, "
        f"repaired={total_repaired}, anchored={total_anchored}, "
        f"split={total_split}, needs_vlm={total_need_vlm}"
    )


if __name__ == "__main__":
    main()