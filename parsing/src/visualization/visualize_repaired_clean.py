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
    fused_json: Dict[str, Any],
    fused_path: Path,
    render_root: Path,
) -> Optional[Path]:
    source = fused_json.get("source", {})
    page_dir_raw = source.get("page_dir")

    candidates: List[Path] = []

    if page_dir_raw:
        page_dir = Path(str(page_dir_raw))
        candidates.append(page_dir / "page.png")
        candidates.append(page_dir / "bboxes_preview.jpg")

    doc_name = fused_path.parent.name
    page_name = fused_path.stem

    candidates.append(render_root / doc_name / page_name / "page.png")
    candidates.append(render_root / doc_name / page_name / "bboxes_preview.jpg")

    for p in candidates:
        if p.exists():
            return p

    return None


def short_block_id(block: Dict[str, Any]) -> str:
    bid = str(block.get("block_id", ""))
    if "__" in bid:
        parent = str(block.get("parent_block_id", bid.split("__", 1)[0]))
        return parent + "*"
    return bid


def should_draw_block(
    block: Dict[str, Any],
    only_repaired: bool,
    actions: Optional[set],
) -> bool:
    repair = block.get("bbox_repair", {})
    action = repair.get("action", "keep")

    if actions is not None and action not in actions:
        return False

    if only_repaired and action in {"keep", "anchor_to_layout"}:
        return False

    return True


def visualize_one(
    fused_path: Path,
    out_path: Path,
    render_root: Path,
    only_repaired: bool,
    show_labels: bool,
    actions: Optional[set],
    line_width: int,
) -> bool:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception as e:
        raise RuntimeError("PIL/Pillow is required. Try: pip install pillow") from e

    data = load_json(fused_path)

    image_path = find_page_image(data, fused_path, render_root)
    if image_path is None:
        print(f"[SKIP] image not found for {fused_path}")
        return False

    im = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(im)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    blocks = data.get("blocks", [])
    drawn = 0

    for block in blocks:
        if not isinstance(block, dict):
            continue

        if not should_draw_block(block, only_repaired=only_repaired, actions=actions):
            continue

        bbox = to_bbox(block.get("bbox_corrected"))
        if bbox is None:
            continue

        repair = block.get("bbox_repair", {})
        action = repair.get("action", "keep")

        # clean final result: only corrected bbox
        draw.rectangle(bbox, outline=(0, 200, 0), width=line_width)

        if show_labels:
            label = short_block_id(block)
            if action not in {"keep", "anchor_to_layout"}:
                label = f"{label}:{action}"

            x, y = bbox[0], max(0, bbox[1] - 12)
            draw.text((x, y), label, fill=(0, 160, 0), font=font)

        drawn += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path, quality=95)

    print(f"[OK] {fused_path.parent.name}/{fused_path.stem} drawn={drawn} -> {out_path}")
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
    parser.add_argument("--out-root", default="output/fusion_clean_vis")

    parser.add_argument("--doc", default=None)
    parser.add_argument("--pages", nargs="*", default=None)

    parser.add_argument(
        "--only-repaired",
        action="store_true",
        help="Only draw blocks whose action is not keep/anchor_to_layout.",
    )
    parser.add_argument(
        "--show-labels",
        action="store_true",
        help="Show block id and repair action labels.",
    )
    parser.add_argument(
        "--actions",
        nargs="*",
        default=None,
        help="Only draw selected repair actions, e.g. snap_to_layout_safe snap_x_to_layout split_from_layout.",
    )
    parser.add_argument("--line-width", type=int, default=3)

    args = parser.parse_args()

    fused_root = Path(args.fused_root)
    render_root = Path(args.render_root)
    out_root = Path(args.out_root)

    action_set = set(args.actions) if args.actions else None

    total = 0
    ok = 0

    for doc_name, page_name, fused_path in iter_fused_pages(
        fused_root=fused_root,
        doc=args.doc,
        pages=args.pages,
    ):
        total += 1
        out_path = out_root / doc_name / f"{page_name}_clean.jpg"

        success = visualize_one(
            fused_path=fused_path,
            out_path=out_path,
            render_root=render_root,
            only_repaired=args.only_repaired,
            show_labels=args.show_labels,
            actions=action_set,
            line_width=args.line_width,
        )

        if success:
            ok += 1

    print(f"\nDone. pages={ok}/{total}")


if __name__ == "__main__":
    main()