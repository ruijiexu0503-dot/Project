#!/usr/bin/env python3
"""Audit multi-member DeepSeek geometry without changing aligned/production data."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_ROOT))

from hybrid_align_deepseek_layout import (  # noqa: E402
    is_visual_container,
    is_text_like_region,
    match_to_text_region,
    match_to_visual_container,
    normalize_layout_regions,
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    region = row.get("region") or {}
    return {
        "region_id": region.get("region_id"),
        "label": region.get("label"),
        "role": region.get("role"),
        "bbox": region.get("bbox"),
        "score": row.get("score"),
        "overlap_frac": row.get("overlap_frac"),
        "iou": row.get("iou"),
        "center_inside": row.get("center_inside"),
    }


def _member_candidates(
    member: dict[str, Any],
    block: dict[str, Any],
    regions: list[dict[str, Any]],
    page_w: int,
    page_h: int,
) -> dict[str, Any]:
    bbox = member.get("pixel_bbox") or member.get("bbox")
    temporary = {
        "deepseek_bbox": bbox,
        "block_type": block.get("block_type") or "text",
    }
    text_regions = [region for region in regions if is_text_like_region(region)]
    containers = [region for region in regions if is_visual_container(region)]
    text_match = match_to_text_region(temporary, text_regions, page_w, page_h)
    container_match = match_to_visual_container(temporary, containers, page_w, page_h)
    candidates = [item for item in (text_match, container_match) if item is not None]
    candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return {
        "text_region": _candidate(text_match),
        "visual_container": _candidate(container_match),
        "best": _candidate(candidates[0]) if candidates else None,
    }


def _draw_overlay(
    image_path: Path,
    output_path: Path,
    regions: list[dict[str, Any]],
    item: dict[str, Any],
) -> None:
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
        small_font = ImageFont.truetype("DejaVuSans.ttf", 14)
    except OSError:
        font = None
        small_font = None

    # Thin cyan boxes show the complete PP-DocLayout inventory.
    for region in regions:
        bbox = region.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            draw.rectangle(bbox, outline=(50, 190, 220), width=1)

    # Highlight the audit-only member candidates in yellow.
    member_rows = item.get("members") or []
    colors = [(230, 40, 40), (255, 130, 20), (180, 40, 190), (20, 150, 70)]
    for index, member in enumerate(member_rows):
        bbox = member.get("bbox")
        color = colors[index % len(colors)]
        if isinstance(bbox, list) and len(bbox) == 4:
            draw.rectangle(bbox, outline=color, width=5)
            label = f"M{index}"
            x, y = float(bbox[0]) + 3, max(0.0, float(bbox[1]) - 22)
            draw.rectangle((x, y, x + 38, y + 21), fill=(255, 255, 255))
            draw.text((x + 3, y + 2), label, fill=color, font=small_font)

        best = (member.get("audit_layout_candidates") or {}).get("best") or {}
        candidate_bbox = best.get("bbox")
        if isinstance(candidate_bbox, list) and len(candidate_bbox) == 4:
            draw.rectangle(candidate_bbox, outline=(255, 215, 0), width=4)
            label = f"M{index}->{best.get('region_id')}"
            x, y = float(candidate_bbox[0]) + 3, float(candidate_bbox[1]) + 2
            draw.rectangle((x, y, x + max(90, len(label) * 8), y + 21), fill=(255, 255, 220))
            draw.text((x + 3, y + 2), label, fill=(120, 90, 0), font=small_font)

    title = f"{item['page']} {item['block_id']} · {item['audit_type']}"
    draw.rectangle((0, 0, image.width, 30), fill=(255, 255, 255))
    draw.text((6, 5), title, fill=(0, 0, 0), font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, quality=95)


def audit(args: argparse.Namespace) -> dict[str, Any]:
    aligned_root = Path(args.aligned_root) / args.doc_id
    layout_root = Path(args.layout_root) / args.doc_id
    image_root = Path(args.image_root) / args.doc_id
    output_root = Path(args.output_root)
    overlay_root = output_root / "overlays"

    items: list[dict[str, Any]] = []
    for aligned_path in sorted(aligned_root.glob("page_*.json")):
        page_data = _json(aligned_path)
        targets = [
            block for block in page_data.get("aligned_blocks", [])
            if len(block.get("geometry_members") or []) > 1
            or "deepseek_bbox_suspicious" in (block.get("flags") or [])
        ]
        if not targets:
            continue

        page = str(page_data.get("page") or aligned_path.stem)
        layout_path = layout_root / f"{page}.json"
        image_path = image_root / page / "page.png"
        layout_data = _json(layout_path)
        regions = normalize_layout_regions(layout_data)
        page_w = int(layout_data.get("page_width") or page_data.get("page_width") or 0)
        page_h = int(layout_data.get("page_height") or page_data.get("page_height") or 0)

        for block in targets:
            members = []
            for member in block.get("geometry_members") or []:
                audit_candidates = _member_candidates(member, block, regions, page_w, page_h)
                members.append({
                    "member_id": member.get("member_id"),
                    "box_index": member.get("box_index"),
                    "bbox": member.get("pixel_bbox") or member.get("bbox"),
                    "raw_bbox": member.get("raw_bbox"),
                    "audit_layout_candidates": audit_candidates,
                })

            audit_type = "multi_member_cross_column_candidate"
            if "deepseek_bbox_suspicious" in (block.get("flags") or []):
                audit_type = "oversized_suspicious_single_member"
            item = {
                "page": page,
                "block_id": block.get("block_id"),
                "block_type": block.get("block_type"),
                "audit_type": audit_type,
                "text": block.get("text") or "",
                "current_layout_match": {
                    "matched_region_id": block.get("matched_region_id"),
                    "matched_region_label": block.get("matched_region_label"),
                    "matched_region_role": block.get("matched_region_role"),
                    "matched_region_ids": block.get("matched_region_ids"),
                    "match_score": block.get("match_score"),
                },
                "grounding_group": block.get("grounding_group"),
                "flags": block.get("flags") or [],
                "members": members,
                "page_image": str(image_path),
                "layout_json": str(layout_path),
            }
            overlay_name = f"{page}_{block.get('block_id')}.jpg"
            overlay_path = overlay_root / overlay_name
            _draw_overlay(image_path, overlay_path, regions, item)
            item["overlay"] = str(overlay_path)
            items.append(item)

    report = {
        "schema_version": "bbox_member_geometry_audit_v1",
        "doc_id": args.doc_id,
        "production_modified": False,
        "aligned_root": str(aligned_root),
        "layout_root": str(layout_root),
        "items": items,
        "summary": {
            "target_blocks": len(items),
            "multi_member_blocks": sum(item["audit_type"].startswith("multi_member") for item in items),
            "oversized_suspicious_blocks": sum(item["audit_type"].startswith("oversized") for item in items),
            "member_count": sum(len(item["members"]) for item in items),
        },
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "audit_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    rows = []
    for item in items:
        rows.append(
            "<section><h2>" + html.escape(f"{item['page']} · {item['block_id']} · {item['audit_type']}") + "</h2>"
            + f"<p>{html.escape(item['text'][:700])}</p>"
            + f"<p>Current layout match: <code>{html.escape(json.dumps(item['current_layout_match'], ensure_ascii=False))}</code></p>"
            + f"<img src='overlays/{html.escape(Path(item['overlay']).name)}' style='max-width:720px'><pre>"
            + html.escape(json.dumps(item["members"], ensure_ascii=False, indent=2))
            + "</pre></section>"
        )
    html_text = "<!doctype html><meta charset='utf-8'><title>BBox member geometry audit</title>"
    html_text += "<style>body{font-family:Arial;max-width:1100px;margin:2em auto}section{border-top:1px solid #aaa;padding:1em 0}pre{white-space:pre-wrap;background:#f5f5f5;padding:1em}</style>"
    html_text += f"<h1>BBox member geometry audit: {html.escape(args.doc_id)}</h1><p>{len(items)} target blocks. Audit-only; production unchanged.</p>"
    html_text += "".join(rows)
    (output_root / "audit_report.html").write_text(html_text, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id", default="gw150914_detection")
    parser.add_argument("--aligned-root", required=True)
    parser.add_argument("--layout-root", required=True)
    parser.add_argument("--image-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
