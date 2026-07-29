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


def to_bbox(x: Any) -> Optional[List[float]]:
    if not isinstance(x, (list, tuple)) or len(x) != 4:
        return None
    try:
        return [float(x[0]), float(x[1]), float(x[2]), float(x[3])]
    except Exception:
        return None


def find_page_image(
    data: Dict[str, Any],
    json_path: Path,
    render_root: Path,
) -> Optional[Path]:
    candidates: List[Path] = []

    source = data.get("source", {})
    page_dir_raw = source.get("page_dir")

    if page_dir_raw:
        page_dir = Path(str(page_dir_raw))
        candidates.append(page_dir / "page.png")
        candidates.append(page_dir / "bboxes_preview.jpg")

    doc_name = json_path.parent.name
    page_name = json_path.stem

    candidates.append(render_root / doc_name / page_name / "page.png")
    candidates.append(render_root / doc_name / page_name / "bboxes_preview.jpg")

    for p in candidates:
        if p.exists():
            return p

    return None


def short_id(block: Dict[str, Any]) -> str:
    bid = str(block.get("block_id", ""))
    if "__" in bid:
        parent = str(block.get("parent_block_id", bid.split("__", 1)[0]))
        return parent + "*"
    return bid


def draw_label(draw, xy, text: str, fill, font=None) -> None:
    x, y = xy
    draw.text((x, max(0, y - 12)), text, fill=fill, font=font)


def draw_blocks(
    draw,
    blocks: List[Dict[str, Any]],
    show_labels: bool,
    draw_valid: bool,
    draw_invalid: bool,
    only_invalid: bool,
    font=None,
) -> Dict[str, int]:
    counts = {
        "valid": 0,
        "invalid": 0,
        "skipped": 0,
    }

    for block in blocks:
        if not isinstance(block, dict):
            continue

        valid = bool(block.get("valid", True))

        if only_invalid and valid:
            counts["skipped"] += 1
            continue

        if valid and not draw_valid:
            counts["skipped"] += 1
            continue

        if (not valid) and not draw_invalid:
            counts["skipped"] += 1
            continue

        bbox = to_bbox(block.get("bbox_corrected"))
        if bbox is None:
            counts["skipped"] += 1
            continue

        if valid:
            color = (0, 190, 0)
            width = 2
            counts["valid"] += 1
        else:
            color = (255, 0, 0)
            width = 4
            counts["invalid"] += 1

        draw.rectangle(bbox, outline=color, width=width)

        if show_labels:
            label = short_id(block)

            if not valid:
                status = str(block.get("validation_status", "invalid"))
                label = f"{label}:{status}"
            else:
                action = block.get("bbox_repair", {}).get("action", "ok")
                if action not in {"keep", "anchor_to_layout"}:
                    label = f"{label}:{action}"

            draw_label(draw, (bbox[0], bbox[1]), label, fill=color, font=font)

    return counts


def draw_resegment_candidates(
    draw,
    candidates: List[Dict[str, Any]],
    show_labels: bool,
    font=None,
) -> int:
    count = 0

    for cand in candidates:
        if not isinstance(cand, dict):
            continue

        bbox = to_bbox(cand.get("bbox"))
        if bbox is None:
            continue

        color = (255, 145, 0)
        draw.rectangle(bbox, outline=color, width=3)

        if show_labels:
            layout_id = str(cand.get("layout_id", "layout"))
            sources = cand.get("sources", [])
            if isinstance(sources, list) and sources:
                label = f"{layout_id}:{sources[0]}"
            else:
                label = layout_id

            draw_label(draw, (bbox[0], bbox[1]), label, fill=color, font=font)

        count += 1

    return count


def visualize_one(
    json_path: Path,
    out_path: Path,
    render_root: Path,
    show_labels: bool,
    draw_valid: bool,
    draw_invalid: bool,
    draw_resegment: bool,
    only_invalid: bool,
) -> Optional[Dict[str, int]]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        raise RuntimeError("Pillow is required. Try: pip install pillow") from e

    data = load_json(json_path)

    image_path = find_page_image(
        data=data,
        json_path=json_path,
        render_root=render_root,
    )

    if image_path is None:
        print(f"[SKIP] image not found for {json_path}")
        return None

    im = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(im)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    blocks = data.get("blocks", [])
    if not isinstance(blocks, list):
        blocks = []

    stats = draw_blocks(
        draw=draw,
        blocks=blocks,
        show_labels=show_labels,
        draw_valid=draw_valid,
        draw_invalid=draw_invalid,
        only_invalid=only_invalid,
        font=font,
    )

    if draw_resegment:
        candidates = data.get("resegment_candidates", [])
        if not isinstance(candidates, list):
            candidates = []

        stats["resegment_candidates"] = draw_resegment_candidates(
            draw=draw,
            candidates=candidates,
            show_labels=show_labels,
            font=font,
        )
    else:
        stats["resegment_candidates"] = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, quality=95)

    print(
        f"[OK] {json_path.parent.name}/{json_path.stem} "
        f"valid={stats['valid']} invalid={stats['invalid']} "
        f"resegment={stats['resegment_candidates']} -> {out_path}"
    )

    return stats


def iter_pages(
    validated_root: Path,
    doc: Optional[str],
    pages: Optional[List[str]],
) -> Iterable[Tuple[str, str, Path]]:
    if doc:
        doc_dirs = [validated_root / doc]
    else:
        doc_dirs = sorted([p for p in validated_root.iterdir() if p.is_dir()])

    for doc_dir in doc_dirs:
        if not doc_dir.exists():
            continue

        doc_name = doc_dir.name

        if pages:
            json_paths = [doc_dir / f"{p}.json" for p in pages]
        else:
            json_paths = sorted(doc_dir.glob("page_*.json"))

        for p in json_paths:
            if p.exists():
                yield doc_name, p.stem, p


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--validated-root", default="output/validated_layout_parsing")
    parser.add_argument("--render-root", default="output/render_result")
    parser.add_argument("--out-root", default="output/validated_vis")

    parser.add_argument("--doc", default=None)
    parser.add_argument("--pages", nargs="*", default=None)

    parser.add_argument("--show-labels", action="store_true")
    parser.add_argument("--hide-valid", action="store_true")
    parser.add_argument("--hide-invalid", action="store_true")
    parser.add_argument("--hide-resegment", action="store_true")
    parser.add_argument(
        "--only-invalid",
        action="store_true",
        help="Only draw invalid blocks, useful for debugging validator mistakes.",
    )

    args = parser.parse_args()

    validated_root = Path(args.validated_root)
    render_root = Path(args.render_root)
    out_root = Path(args.out_root)

    total_pages = 0
    ok_pages = 0
    total_valid = 0
    total_invalid = 0
    total_resegment = 0

    for doc_name, page_name, json_path in iter_pages(
        validated_root=validated_root,
        doc=args.doc,
        pages=args.pages,
    ):
        total_pages += 1

        out_path = out_root / doc_name / f"{page_name}_validated.jpg"

        stats = visualize_one(
            json_path=json_path,
            out_path=out_path,
            render_root=render_root,
            show_labels=args.show_labels,
            draw_valid=not args.hide_valid,
            draw_invalid=not args.hide_invalid,
            draw_resegment=not args.hide_resegment,
            only_invalid=args.only_invalid,
        )

        if stats is not None:
            ok_pages += 1
            total_valid += stats["valid"]
            total_invalid += stats["invalid"]
            total_resegment += stats["resegment_candidates"]

    print(
        f"\nDone. pages={ok_pages}/{total_pages}, "
        f"valid={total_valid}, invalid={total_invalid}, "
        f"resegment_candidates={total_resegment}"
    )


if __name__ == "__main__":
    main()