#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


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


def round_bbox(b: List[float]) -> List[float]:
    return [round(float(v), 2) for v in b]


def clamp_bbox(b: List[float], w: float, h: float) -> List[float]:
    x1, y1, x2, y2 = b
    x1 = max(0.0, min(w, x1))
    y1 = max(0.0, min(h, y1))
    x2 = max(0.0, min(w, x2))
    y2 = max(0.0, min(h, y2))

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


def cover_ratio(a: List[float], b: List[float]) -> float:
    """
    a 被 b 覆盖的比例。
    """
    aa = box_area(a)
    if aa <= 0:
        return 0.0
    return intersection_area(a, b) / aa


def center(b: List[float]) -> Tuple[float, float]:
    return (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0


def center_inside(inner: List[float], outer: List[float]) -> bool:
    cx, cy = center(inner)
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def block_group(block: Dict[str, Any]) -> str:
    typ = str(block.get("type", "")).lower()
    text = str(block.get("text", ""))[:80].lower()
    s = f"{typ} {text}"

    if "image" in s or "figure" in s:
        return "figure"
    if "table" in s:
        return "table"
    if "caption" in s:
        return "caption"
    if "title" in s or "heading" in s or "header" in s or "sub_title" in s:
        return "title"
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
    return "text"


def is_text_like(block: Dict[str, Any]) -> bool:
    return block_group(block) in {"text", "caption", "title"}


def find_page_image(
    data: Dict[str, Any],
    fused_path: Path,
    render_root: Path,
) -> Optional[Path]:
    candidates: List[Path] = []

    source = data.get("source", {})
    page_dir_raw = source.get("page_dir")

    if page_dir_raw:
        page_dir = Path(str(page_dir_raw))
        candidates.append(page_dir / "page.png")

    doc_name = fused_path.parent.name
    page_name = fused_path.stem

    candidates.append(render_root / doc_name / page_name / "page.png")

    # fallback，不推荐但比没有图好
    if page_dir_raw:
        page_dir = Path(str(page_dir_raw))
        candidates.append(page_dir / "bboxes_preview.jpg")
    candidates.append(render_root / doc_name / page_name / "bboxes_preview.jpg")

    for p in candidates:
        if p.exists():
            return p

    return None


def crop_ink_density(
    image,
    bbox: List[float],
    white_threshold: int = 245,
) -> Dict[str, float]:
    """
    用灰度非白像素比例估计 bbox 内是否真的有内容。
    注意：这里是 validator，不要求 OCR，只判断这个框是不是大概率空白。
    """
    w, h = image.size
    b = clamp_bbox(bbox, float(w), float(h))
    x1, y1, x2, y2 = [int(round(v)) for v in b]

    if x2 <= x1 or y2 <= y1:
        return {
            "ink_density": 0.0,
            "dark_density": 0.0,
            "crop_area": 0.0,
        }

    crop = image.crop((x1, y1, x2, y2)).convert("L")
    hist = crop.histogram()
    total = sum(hist)

    if total <= 0:
        return {
            "ink_density": 0.0,
            "dark_density": 0.0,
            "crop_area": float((x2 - x1) * (y2 - y1)),
        }

    non_white = sum(hist[:white_threshold])
    dark = sum(hist[:180])

    return {
        "ink_density": non_white / total,
        "dark_density": dark / total,
        "crop_area": float((x2 - x1) * (y2 - y1)),
    }


def layout_overlap_stats(
    bbox: List[float],
    layouts: List[Dict[str, Any]],
    min_cover_block: float,
    min_iou: float,
) -> Dict[str, Any]:
    strong = []
    all_overlaps = []

    b_area = box_area(bbox)

    for layout in layouts:
        lb = to_bbox(layout.get("bbox"))
        if lb is None:
            continue

        inter = intersection_area(bbox, lb)
        if inter <= 0:
            continue

        l_area = box_area(lb)
        cover_block = inter / b_area if b_area > 0 else 0.0
        cover_layout = inter / l_area if l_area > 0 else 0.0
        iou_val = iou(bbox, lb)

        item = {
            "layout_id": layout.get("layout_id"),
            "label": layout.get("label"),
            "label_group": layout.get("label_group"),
            "cover_block": round(cover_block, 6),
            "cover_layout": round(cover_layout, 6),
            "iou": round(iou_val, 6),
        }

        all_overlaps.append(item)

        if cover_block >= min_cover_block or iou_val >= min_iou:
            strong.append(item)

    return {
        "num_layout_overlaps": len(all_overlaps),
        "num_strong_layout_overlaps": len(strong),
        "strong_layout_overlaps": strong,
        "layout_overlaps": all_overlaps[:8],
    }


def invalidate(
    block: Dict[str, Any],
    status: str,
    flags: List[str],
    needs_resegment: bool = True,
) -> None:
    block["valid"] = False
    block["validation_status"] = status

    current = block.setdefault("validation_flags", [])
    for f in flags:
        if f not in current:
            current.append(f)

    block["needs_resegment"] = needs_resegment


def warn(
    block: Dict[str, Any],
    flags: List[str],
    needs_resegment: bool = False,
) -> None:
    current = block.setdefault("validation_flags", [])
    for f in flags:
        if f not in current:
            current.append(f)

    if needs_resegment:
        block["needs_resegment"] = True


def initialize_block_validation(
    block: Dict[str, Any],
    page_w: float,
    page_h: float,
    image,
    layouts: List[Dict[str, Any]],
    args,
) -> None:
    bbox = to_bbox(block.get("bbox_corrected"))

    block["valid"] = True
    block["validation_status"] = "ok"
    block["validation_flags"] = []
    block["needs_resegment"] = False

    if bbox is None:
        invalidate(
            block,
            "invalid_missing_bbox",
            ["missing_bbox_corrected"],
            needs_resegment=True,
        )
        block["validation_metrics"] = {}
        return

    bbox = clamp_bbox(bbox, page_w, page_h)
    area = box_area(bbox)
    page_area = page_w * page_h if page_w > 0 and page_h > 0 else 1.0
    page_area_ratio = area / page_area if page_area > 0 else 0.0

    ink = crop_ink_density(
        image=image,
        bbox=bbox,
        white_threshold=args.white_threshold,
    )

    overlaps = layout_overlap_stats(
        bbox=bbox,
        layouts=layouts,
        min_cover_block=args.multi_layout_cover_block,
        min_iou=args.multi_layout_iou,
    )

    kind = block_group(block)
    action = block.get("bbox_repair", {}).get("action", "unknown")

    block["validation_metrics"] = {
        "bbox_area": round(area, 2),
        "page_area_ratio": round(page_area_ratio, 6),
        "width": round(box_w(bbox), 2),
        "height": round(box_h(bbox), 2),
        "ink_density": round(float(ink["ink_density"]), 6),
        "dark_density": round(float(ink["dark_density"]), 6),
        "crop_area": round(float(ink["crop_area"]), 2),
        "block_group": kind,
        "repair_action": action,
        "num_layout_overlaps": overlaps["num_layout_overlaps"],
        "num_strong_layout_overlaps": overlaps["num_strong_layout_overlaps"],
    }

    block["strong_layout_overlaps"] = overlaps["strong_layout_overlaps"]

    # 1. 空白大框：主要针对 text-like
    if is_text_like(block):
        if area >= args.min_empty_area and ink["ink_density"] < args.empty_ink_threshold:
            invalidate(
                block,
                "invalid_empty_region",
                ["low_ink_density", "large_empty_box"],
                needs_resegment=True,
            )
            return

    # 2. 异常大的 text bbox
    if is_text_like(block):
        if page_area_ratio >= args.max_text_page_area_ratio:
            if ink["ink_density"] < args.large_text_ink_threshold:
                invalidate(
                    block,
                    "invalid_suspicious_large_text_box",
                    ["large_text_box", "low_ink_density"],
                    needs_resegment=True,
                )
                return
            else:
                warn(
                    block,
                    ["suspicious_large_text_box"],
                    needs_resegment=True,
                )

    # 3. text bbox 同时强 overlap 多个 layout region
    #    这通常说明 parsing 跨栏、跨区域，后面应 resegment/VLM。
    if is_text_like(block):
        if overlaps["num_strong_layout_overlaps"] >= args.max_strong_layout_overlaps_for_text:
            # 如果这个 block 本来就是 split_from_layout，别误删
            if action not in {"split_from_layout"}:
                invalidate(
                    block,
                    "invalid_multi_layout_overlap",
                    ["text_overlaps_multiple_layout_regions"],
                    needs_resegment=True,
                )
                return


def apply_overlap_conflict_rule(
    blocks: List[Dict[str, Any]],
    args,
) -> None:
    """
    删除/标记那种“中间突然冒出来的大框”：
    一个 text-like 大框与多个较小有效框发生明显重叠，
    并且自身 ink density 更低。
    """
    n = len(blocks)

    for i in range(n):
        a = blocks[i]

        if not a.get("valid", True):
            continue

        if not is_text_like(a):
            continue

        ab = to_bbox(a.get("bbox_corrected"))
        if ab is None:
            continue

        a_area = box_area(ab)
        if a_area <= 0:
            continue

        a_metrics = a.get("validation_metrics", {})
        a_ink = float(a_metrics.get("ink_density", 0.0))

        overlapped_smaller = []

        for j in range(n):
            if i == j:
                continue

            b = blocks[j]

            if not b.get("valid", True):
                continue

            bb = to_bbox(b.get("bbox_corrected"))
            if bb is None:
                continue

            b_area = box_area(bb)
            if b_area <= 0:
                continue

            if b_area >= a_area * args.conflict_smaller_area_ratio:
                continue

            inter = intersection_area(ab, bb)
            if inter <= 0:
                continue

            inter_over_smaller = inter / b_area
            inter_over_a = inter / a_area

            if inter_over_smaller >= args.conflict_cover_smaller or inter_over_a >= args.conflict_cover_large:
                b_ink = float(b.get("validation_metrics", {}).get("ink_density", 0.0))

                overlapped_smaller.append({
                    "block_id": b.get("block_id"),
                    "inter_over_smaller": round(inter_over_smaller, 6),
                    "inter_over_large": round(inter_over_a, 6),
                    "smaller_ink_density": round(b_ink, 6),
                })

        if len(overlapped_smaller) >= args.conflict_min_overlapped_smaller:
            smaller_inks = [
                x["smaller_ink_density"]
                for x in overlapped_smaller
                if x["smaller_ink_density"] > 0
            ]

            if smaller_inks:
                avg_smaller_ink = sum(smaller_inks) / len(smaller_inks)
            else:
                avg_smaller_ink = 0.0

            low_density_against_children = (
                a_ink <= avg_smaller_ink * args.conflict_ink_ratio
                or a_ink <= args.conflict_absolute_ink_threshold
            )

            if low_density_against_children:
                invalidate(
                    a,
                    "invalid_overlap_conflict",
                    ["large_box_overlaps_multiple_smaller_boxes", "lower_ink_density"],
                    needs_resegment=True,
                )
                a["overlap_conflict_with"] = overlapped_smaller[:8]


def collect_resegment_candidates(
    data: Dict[str, Any],
    blocks: List[Dict[str, Any]],
    layouts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    layout_by_id = {
        x.get("layout_id"): x
        for x in layouts
        if x.get("layout_id") is not None
    }

    candidates: Dict[str, Dict[str, Any]] = {}

    def add_layout(layout_id: Optional[str], source: str, block_id: Any = None) -> None:
        if not layout_id:
            return

        layout = layout_by_id.get(layout_id)
        if layout is None:
            return

        if layout_id not in candidates:
            candidates[layout_id] = {
                "layout_id": layout_id,
                "label": layout.get("label"),
                "label_group": layout.get("label_group"),
                "bbox": layout.get("bbox"),
                "sources": [],
                "related_block_ids": [],
            }

        if source not in candidates[layout_id]["sources"]:
            candidates[layout_id]["sources"].append(source)

        if block_id is not None and block_id not in candidates[layout_id]["related_block_ids"]:
            candidates[layout_id]["related_block_ids"].append(block_id)

    for block in blocks:
        if block.get("valid", True) and not block.get("needs_resegment", False):
            continue

        repair = block.get("bbox_repair", {})
        layout_id = (
            block.get("layout_anchor_id")
            or repair.get("target_layout_id")
        )

        if layout_id:
            add_layout(layout_id, "invalid_or_needs_resegment_block", block.get("block_id"))
            continue

        # 没有 anchor，就用 top candidate 的第一个作为候选 parent
        top = block.get("top_layout_candidates", [])
        if isinstance(top, list) and top:
            add_layout(top[0].get("layout_id"), "top_layout_candidate_of_invalid_block", block.get("block_id"))

    # 原 fused 文件里的 orphan layout regions 也进入 resegment candidate
    for layout in data.get("orphan_layout_regions", []):
        add_layout(layout.get("layout_id"), "orphan_layout_region", None)

    # 如果某个 layout region 没有任何 valid block anchor，也可作为候选
    valid_anchor_ids = set()
    for block in blocks:
        if block.get("valid", True):
            anchor = block.get("layout_anchor_id")
            if anchor:
                valid_anchor_ids.add(anchor)

    for layout in layouts:
        layout_id = layout.get("layout_id")
        if layout_id is None:
            continue

        if layout_id not in valid_anchor_ids:
            lg = layout_group(layout)
            if lg in {"text", "caption", "title", "table", "figure"}:
                add_layout(layout_id, "layout_without_valid_anchor", None)

    out = list(candidates.values())
    out.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]) if isinstance(x.get("bbox"), list) else (0, 0))
    return out


def validate_page(
    fused_path: Path,
    out_path: Path,
    report_path: Path,
    render_root: Path,
    args,
) -> bool:
    try:
        from PIL import Image
    except Exception as e:
        raise RuntimeError("Pillow is required. Try: pip install pillow") from e

    data = load_json(fused_path)

    image_path = find_page_image(data, fused_path, render_root)
    if image_path is None:
        print(f"[SKIP] image not found for {fused_path}")
        return False

    image = Image.open(image_path).convert("RGB")
    page_w, page_h = image.size

    data["page_width"] = page_w
    data["page_height"] = page_h

    blocks = data.get("blocks", [])
    layouts = data.get("layout_regions", [])

    if not isinstance(blocks, list):
        blocks = []
        data["blocks"] = blocks

    if not isinstance(layouts, list):
        layouts = []
        data["layout_regions"] = layouts

    # first pass: per-block metrics and obvious invalid boxes
    for block in blocks:
        if not isinstance(block, dict):
            continue

        initialize_block_validation(
            block=block,
            page_w=float(page_w),
            page_h=float(page_h),
            image=image,
            layouts=layouts,
            args=args,
        )

    # second pass: overlap conflict
    apply_overlap_conflict_rule(blocks, args)

    resegment_candidates = collect_resegment_candidates(
        data=data,
        blocks=blocks,
        layouts=layouts,
    )

    summary = {
        "num_blocks": len(blocks),
        "num_valid": sum(1 for b in blocks if isinstance(b, dict) and b.get("valid", True)),
        "num_invalid": sum(1 for b in blocks if isinstance(b, dict) and not b.get("valid", True)),
        "num_needs_resegment": sum(1 for b in blocks if isinstance(b, dict) and b.get("needs_resegment", False)),
        "num_resegment_candidates": len(resegment_candidates),
        "invalid_status_counts": {},
    }

    for b in blocks:
        if not isinstance(b, dict):
            continue

        if not b.get("valid", True):
            status = b.get("validation_status", "invalid_unknown")
            summary["invalid_status_counts"][status] = summary["invalid_status_counts"].get(status, 0) + 1

    data["validation_summary"] = summary
    data["resegment_candidates"] = resegment_candidates

    save_json(data, out_path)

    report = {
        "page": data.get("page"),
        "source": data.get("source"),
        "image_path": str(image_path),
        "summary": summary,
        "invalid_blocks": [
            {
                "block_id": b.get("block_id"),
                "type": b.get("type"),
                "bbox_corrected": b.get("bbox_corrected"),
                "validation_status": b.get("validation_status"),
                "validation_flags": b.get("validation_flags", []),
                "needs_resegment": b.get("needs_resegment", False),
                "layout_anchor_id": b.get("layout_anchor_id"),
                "metrics": b.get("validation_metrics", {}),
                "strong_layout_overlaps": b.get("strong_layout_overlaps", []),
                "overlap_conflict_with": b.get("overlap_conflict_with", []),
            }
            for b in blocks
            if isinstance(b, dict) and not b.get("valid", True)
        ],
        "resegment_candidates": resegment_candidates,
    }

    save_json(report, report_path)

    print(
        f"[OK] {fused_path.parent.name}/{fused_path.stem} "
        f"valid={summary['num_valid']} invalid={summary['num_invalid']} "
        f"needs_resegment={summary['num_needs_resegment']} "
        f"candidates={summary['num_resegment_candidates']} -> {out_path}"
    )

    return True


def iter_fused_pages(
    fused_root: Path,
    doc: Optional[str],
    pages: Optional[List[str]],
) -> Iterable[Tuple[str, str, Path]]:
    if doc:
        doc_dirs = [fused_root / doc]
    else:
        doc_dirs = sorted([p for p in fused_root.iterdir() if p.is_dir()])

    for doc_dir in doc_dirs:
        if not doc_dir.exists():
            continue

        doc_name = doc_dir.name

        if pages:
            fused_paths = [doc_dir / f"{p}.json" for p in pages]
        else:
            fused_paths = sorted(doc_dir.glob("page_*.json"))

        for p in fused_paths:
            if p.exists():
                yield doc_name, p.stem, p


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--fused-root", default="output/fused_layout_parsing")
    parser.add_argument("--render-root", default="output/render_result")
    parser.add_argument("--out-root", default="output/validated_layout_parsing")
    parser.add_argument("--report-root", default="output/validation_reports")

    parser.add_argument("--doc", default=None)
    parser.add_argument("--pages", nargs="*", default=None)

    # ink density
    parser.add_argument("--white-threshold", type=int, default=245)
    parser.add_argument("--min-empty-area", type=float, default=30000.0)
    parser.add_argument("--empty-ink-threshold", type=float, default=0.015)
    parser.add_argument("--large-text-ink-threshold", type=float, default=0.030)

    # large text bbox
    parser.add_argument("--max-text-page-area-ratio", type=float, default=0.080)

    # multi-layout overlap
    parser.add_argument("--multi-layout-cover-block", type=float, default=0.28)
    parser.add_argument("--multi-layout-iou", type=float, default=0.12)
    parser.add_argument("--max-strong-layout-overlaps-for-text", type=int, default=2)

    # block overlap conflict
    parser.add_argument("--conflict-smaller-area-ratio", type=float, default=0.80)
    parser.add_argument("--conflict-cover-smaller", type=float, default=0.45)
    parser.add_argument("--conflict-cover-large", type=float, default=0.20)
    parser.add_argument("--conflict-min-overlapped-smaller", type=int, default=2)
    parser.add_argument("--conflict-ink-ratio", type=float, default=0.75)
    parser.add_argument("--conflict-absolute-ink-threshold", type=float, default=0.030)

    args = parser.parse_args()

    fused_root = Path(args.fused_root)
    render_root = Path(args.render_root)
    out_root = Path(args.out_root)
    report_root = Path(args.report_root)

    total = 0
    ok = 0

    for doc_name, page_name, fused_path in iter_fused_pages(
        fused_root=fused_root,
        doc=args.doc,
        pages=args.pages,
    ):
        total += 1

        out_path = out_root / doc_name / f"{page_name}.json"
        report_path = report_root / doc_name / f"{page_name}_report.json"

        success = validate_page(
            fused_path=fused_path,
            out_path=out_path,
            report_path=report_path,
            render_root=render_root,
            args=args,
        )

        if success:
            ok += 1

    print(f"\nDone. pages={ok}/{total}")


if __name__ == "__main__":
    main()