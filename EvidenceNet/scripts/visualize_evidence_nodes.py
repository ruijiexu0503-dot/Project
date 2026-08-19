from __future__ import annotations

import argparse
import colorsys
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def _page_num(value: str) -> int | None:
    match = re.search(r"(\d+)(?!.*\d)", value)
    return int(match.group(1)) if match else None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _load_aligned_lookup(aligned_dir: Path) -> tuple[dict[tuple[int, str], dict[str, Any]], dict[int, tuple[float | None, float | None]]]:
    by_key: dict[tuple[int, str], dict[str, Any]] = {}
    page_dims: dict[int, tuple[float | None, float | None]] = {}
    for path in aligned_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        page = str(data.get("page") or path.stem)
        page_num = _page_num(page)
        if page_num is None:
            continue
        width = data.get("page_width")
        height = data.get("page_height")
        page_dims[page_num] = (
            float(width) if isinstance(width, (int, float)) else None,
            float(height) if isinstance(height, (int, float)) else None,
        )
        for block in data.get("aligned_blocks", []):
            block_id = block.get("block_id")
            if block_id is not None:
                by_key[(page_num, str(block_id))] = block
    return by_key, page_dims


def _image_lookup(images_dir: Path) -> dict[int, Path]:
    result: dict[int, Path] = {}
    for path in images_dir.iterdir():
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        number = _page_num(path.stem)
        if number is not None:
            result[number] = path
    return result


def _node_color(node_id: str) -> tuple[int, int, int]:
    # Deterministic, moderately saturated palette. All boxes from one EvidenceNode share a color.
    value = sum((i + 1) * ord(ch) for i, ch in enumerate(node_id)) % 360
    r, g, b = colorsys.hsv_to_rgb(value / 360.0, 0.72, 0.95)
    return int(r * 255), int(g * 255), int(b * 255)


def _safe_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        box = [float(v) for v in value[:4]]
    except (TypeError, ValueError):
        return None
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return None
    return box


def _resolve_member_bbox(
    member: dict[str, Any],
    aligned_block: dict[str, Any] | None,
) -> tuple[list[float] | None, str | None]:
    # Prefer layout-space bbox because it normally corresponds to page_width/page_height.
    for source, obj in (("member_bbox", member), ("aligned_bbox", aligned_block or {})):
        bbox = _safe_bbox(obj.get("bbox"))
        if bbox is not None:
            return bbox, source

    # DeepSeek boxes are commonly norm999. Keep them as a separate coordinate mode.
    for source, obj in (("member_deepseek_bbox", member), ("aligned_deepseek_bbox", aligned_block or {})):
        bbox = _safe_bbox(obj.get("deepseek_bbox"))
        if bbox is not None:
            return bbox, source
    return None, None


def _scale_bbox(
    bbox: list[float],
    source: str,
    image_size: tuple[int, int],
    page_dims: tuple[float | None, float | None] | None,
) -> list[float]:
    image_w, image_h = image_size
    if "deepseek" in source:
        # DeepSeek raw boxes in this project are normalized to roughly 0..999.
        sx, sy = image_w / 999.0, image_h / 999.0
    else:
        page_w, page_h = page_dims or (None, None)
        if page_w and page_h and page_w > 0 and page_h > 0:
            sx, sy = image_w / page_w, image_h / page_h
        else:
            # Last-resort fallback. If dimensions are unavailable but the bbox already fits
            # the image coordinate system, leave it unchanged.
            sx = sy = 1.0
    x1, y1, x2, y2 = bbox
    return [x1 * sx, y1 * sy, x2 * sx, y2 * sy]


def _short_id(node_id: str) -> str:
    match = re.search(r"EV_(\d+)$", node_id)
    return f"EV_{match.group(1)}" if match else node_id[-18:]


def _draw_label(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, color: tuple[int, int, int], font: ImageFont.ImageFont) -> None:
    x, y = xy
    left, top, right, bottom = draw.textbbox((x, y), text, font=font)
    pad = 3
    draw.rectangle((left - pad, top - pad, right + pad, bottom + pad), fill=color)
    # Pick black/white text according to luminance.
    lum = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
    fg = (0, 0, 0) if lum > 145 else (255, 255, 255)
    draw.text((x, y), text, fill=fg, font=font)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render EvidenceNode membership on split page images. Boxes belonging to the same node share a color."
    )
    parser.add_argument("--evidence", required=True, help="Path to evidence_nodes.jsonl")
    parser.add_argument("--images", required=True, help="Directory containing split page images")
    parser.add_argument("--aligned", required=True, help="Directory containing aligned page JSON files")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--only-multi-member", action="store_true", help="Only draw EvidenceNodes with >1 source member")
    parser.add_argument("--line-width", type=int, default=4)
    parser.add_argument("--fill-alpha", type=int, default=35, help="0..255 translucent box fill")
    args = parser.parse_args()

    evidence_path = Path(args.evidence)
    images_dir = Path(args.images)
    aligned_dir = Path(args.aligned)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes = _load_jsonl(evidence_path)
    aligned_lookup, page_dims = _load_aligned_lookup(aligned_dir)
    images = _image_lookup(images_dir)

    members_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    missing_bbox: list[dict[str, Any]] = []

    for node in nodes:
        members = node.get("source_members") or []
        if args.only_multi_member and len(members) <= 1:
            continue
        node_id = str(node.get("node_id") or "UNKNOWN_NODE")
        preview = str(node.get("plain_text") or node.get("original_markdown") or "").replace("\n", " ")[:180]
        for member_index, member in enumerate(members, 1):
            page_num = _page_num(str(member.get("page") or ""))
            block_id = str(member.get("block_id") or "")
            if page_num is None:
                continue
            aligned_block = aligned_lookup.get((page_num, block_id))
            bbox, source = _resolve_member_bbox(member, aligned_block)
            record = {
                "node_id": node_id,
                "short_id": _short_id(node_id),
                "page": page_num,
                "block_id": block_id,
                "member_index": member_index,
                "member_count": len(members),
                "role": member.get("role"),
                "preview": preview,
                "bbox": bbox,
                "bbox_source": source,
            }
            if bbox is None or source is None:
                missing_bbox.append(record)
            else:
                members_by_page[page_num].append(record)

    manifest: list[dict[str, Any]] = []
    font = ImageFont.load_default()

    for page_num in sorted(members_by_page):
        image_path = images.get(page_num)
        if image_path is None:
            manifest.append({"page": page_num, "status": "missing_image"})
            continue

        base = Image.open(image_path).convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        draw_base = ImageDraw.Draw(base)
        page_rows = members_by_page[page_num]

        for row in page_rows:
            color = _node_color(row["node_id"])
            scaled = _scale_bbox(
                row["bbox"],
                row["bbox_source"],
                base.size,
                page_dims.get(page_num),
            )
            x1, y1, x2, y2 = scaled
            x1 = max(0, min(base.width - 1, x1))
            x2 = max(0, min(base.width - 1, x2))
            y1 = max(0, min(base.height - 1, y1))
            y2 = max(0, min(base.height - 1, y2))
            if x2 <= x1 or y2 <= y1:
                continue

            draw_overlay.rectangle((x1, y1, x2, y2), fill=(*color, max(0, min(255, args.fill_alpha))))
            draw_base.rectangle((x1, y1, x2, y2), outline=color, width=max(1, args.line_width))
            label = row["short_id"]
            if row["member_count"] > 1:
                label += f" [{row['member_index']}/{row['member_count']}]"
            _draw_label(draw_base, (x1 + 4, max(2, y1 + 4)), label, color, font)

            manifest.append({
                **row,
                "image": str(image_path),
                "drawn_bbox": [round(v, 2) for v in (x1, y1, x2, y2)],
                "status": "drawn",
            })

        base = Image.alpha_composite(base, overlay)
        output_path = output_dir / f"page_{page_num:06d}_evidence.png"
        base.convert("RGB").save(output_path, quality=95)

    with (output_dir / "visualization_manifest.jsonl").open("w", encoding="utf-8") as handle:
        for row in manifest:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    with (output_dir / "missing_bbox.jsonl").open("w", encoding="utf-8") as handle:
        for row in missing_bbox:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "evidence_nodes": len(nodes),
        "pages_with_drawn_nodes": len(members_by_page),
        "drawn_members": sum(1 for row in manifest if row.get("status") == "drawn"),
        "missing_bbox_members": len(missing_bbox),
        "only_multi_member": args.only_multi_member,
        "output_dir": str(output_dir),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
