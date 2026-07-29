#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import html
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw


def choose_bbox(block: Dict[str, Any]) -> Optional[List[float]]:
    bbox = block.get("deepseek_bbox") or block.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        return bbox[:4]
    return None


def safe_name(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(s))


def find_page_image(image_root: Path, page_id: str) -> Optional[Path]:
    candidates = []

    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        candidates.append(image_root / f"{page_id}{ext}")

    page_dir = image_root / page_id
    for name in [
        "page.png",
        "page.jpg",
        "raw.png",
        "raw.jpg",
        "origin.png",
        "origin.jpg",
        "result.png",
        "result.jpg",
        "result_with_boxes.jpg",
    ]:
        candidates.append(page_dir / name)

    for p in candidates:
        if p.exists():
            return p

    for hit in image_root.rglob(f"{page_id}.*"):
        if hit.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            return hit

    return None


def ensure_crop(
    block: Dict[str, Any],
    image_root: Path,
    crop_dir: Path,
    padding: int = 12,
) -> Optional[Path]:
    crop_dir.mkdir(parents=True, exist_ok=True)

    # 1) 如果已有 crop，并且存在，就复制进 gallery
    existing_crop = block.get("crop_path")
    if existing_crop:
        existing_crop_path = Path(existing_crop)
        if existing_crop_path.exists():
            dst = crop_dir / existing_crop_path.name
            if not dst.exists():
                shutil.copy2(existing_crop_path, dst)
            return dst

    # 2) 否则重新从 page image + bbox 裁
    page_id = block["page_id"]
    bbox = choose_bbox(block)
    if bbox is None:
        return None

    page_image = find_page_image(image_root, page_id)
    if page_image is None:
        return None

    img = Image.open(page_image).convert("RGB")
    w, h = img.size

    x1, y1, x2, y2 = bbox
    x1 = max(0, int(math.floor(x1 - padding)))
    y1 = max(0, int(math.floor(y1 - padding)))
    x2 = min(w, int(math.ceil(x2 + padding)))
    y2 = min(h, int(math.ceil(y2 + padding)))

    if x2 <= x1 or y2 <= y1:
        return None

    crop = img.crop((x1, y1, x2, y2))
    cw, ch = crop.size
    if max(cw, ch) < 900:
        crop = crop.resize((cw * 2, ch * 2))

    fname = f"{page_id}_{safe_name(block['rid'])}_{safe_name(block.get('block_id', 'block'))}.png"
    out_path = crop_dir / fname
    crop.save(out_path)
    return out_path


def make_item_preview(
    block: Dict[str, Any],
    image_root: Path,
    preview_dir: Path,
    max_width: int = 900,
) -> Optional[Path]:
    preview_dir.mkdir(parents=True, exist_ok=True)

    page_id = block["page_id"]
    bbox = choose_bbox(block)
    if bbox is None:
        return None

    page_image = find_page_image(image_root, page_id)
    if page_image is None:
        return None

    img = Image.open(page_image).convert("RGB")
    draw = ImageDraw.Draw(img)

    x1, y1, x2, y2 = bbox
    draw.rectangle([x1, y1, x2, y2], outline="red", width=6)

    # 缩放成适合浏览的大小
    w, h = img.size
    if w > max_width:
        scale = max_width / w
        img = img.resize((int(w * scale), int(h * scale)))

    fname = f"{page_id}_{safe_name(block['rid'])}_{safe_name(block.get('block_id', 'block'))}_preview.png"
    out_path = preview_dir / fname
    img.save(out_path)
    return out_path


def make_page_overlay(
    page_id: str,
    blocks: List[Dict[str, Any]],
    image_root: Path,
    overlay_dir: Path,
    max_width: int = 1200,
) -> Optional[Path]:
    overlay_dir.mkdir(parents=True, exist_ok=True)

    page_image = find_page_image(image_root, page_id)
    if page_image is None:
        return None

    img = Image.open(page_image).convert("RGB")
    draw = ImageDraw.Draw(img)

    for block in blocks:
        bbox = choose_bbox(block)
        if bbox is None:
            continue
        x1, y1, x2, y2 = bbox
        draw.rectangle([x1, y1, x2, y2], outline="red", width=5)
        label = f"{block['rid']}"
        draw.text((x1 + 4, max(0, y1 - 18)), label, fill="red")

    w, h = img.size
    if w > max_width:
        scale = max_width / w
        img = img.resize((int(w * scale), int(h * scale)))

    out_path = overlay_dir / f"{page_id}_high_risk_overlay.png"
    img.save(out_path)
    return out_path


def relpath_str(path: Optional[Path], base: Path) -> str:
    if path is None:
        return ""
    return path.relative_to(base).as_posix()


def html_escape(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True, help="ocr_verification_blocks.json")
    parser.add_argument("--image-root", required=True, help="root directory of page images")
    parser.add_argument("--out-root", required=True, help="output gallery directory")
    parser.add_argument("--level", choices=["high", "medium", "all-risk"], default="high")
    args = parser.parse_args()

    json_path = Path(args.json)
    image_root = Path(args.image_root)
    out_root = Path(args.out_root)

    crops_dir = out_root / "crops"
    previews_dir = out_root / "item_previews"
    overlays_dir = out_root / "page_overlays"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    blocks = data["blocks"]

    if args.level == "high":
        selected = [b for b in blocks if b.get("risk_level") == "high"]
    elif args.level == "medium":
        selected = [b for b in blocks if b.get("risk_level") == "medium"]
    else:
        selected = [b for b in blocks if b.get("risk_level") in {"medium", "high"}]

    selected = sorted(
        selected,
        key=lambda b: (-float(b.get("risk_score", 0.0)), b.get("page_id", ""), b.get("rid", ""))
    )

    out_root.mkdir(parents=True, exist_ok=True)
    crops_dir.mkdir(parents=True, exist_ok=True)
    previews_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir.mkdir(parents=True, exist_ok=True)

    # 先做 page overlay
    page_to_blocks = defaultdict(list)
    for b in selected:
        page_to_blocks[b["page_id"]].append(b)

    page_overlay_paths: Dict[str, Optional[Path]] = {}
    for page_id, page_blocks in page_to_blocks.items():
        page_overlay_paths[page_id] = make_page_overlay(page_id, page_blocks, image_root, overlays_dir)

    # 再做每个 block 的 crop 和 preview
    enriched = []
    for b in selected:
        crop_path = ensure_crop(b, image_root, crops_dir)
        preview_path = make_item_preview(b, image_root, previews_dir)

        item = dict(b)
        item["_gallery_crop"] = relpath_str(crop_path, out_root)
        item["_gallery_preview"] = relpath_str(preview_path, out_root)
        item["_gallery_page_overlay"] = relpath_str(page_overlay_paths.get(b["page_id"]), out_root)
        enriched.append(item)

    # summary
    risk_counter = Counter(b.get("risk_level", "unknown") for b in selected)
    status_counter = Counter(b.get("verification_status", "unknown") for b in selected)
    flag_counter = Counter()

    for b in selected:
        for f in b.get("flags", []):
            flag_counter[f] += 1

    # HTML
    html_path = out_root / "high_risk_gallery.html"

    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>High Risk OCR Gallery</title>
<style>
body { font-family: Arial, sans-serif; margin: 24px; background: #fafafa; }
h1, h2, h3 { margin-top: 1.2em; }
.summary, .card { background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 16px; margin-bottom: 20px; }
.card { box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
img { max-width: 100%; border: 1px solid #ccc; border-radius: 6px; background: white; }
pre { white-space: pre-wrap; word-break: break-word; background: #f6f6f6; padding: 12px; border-radius: 6px; border: 1px solid #eee; }
.meta { font-size: 14px; line-height: 1.6; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eee; margin-right: 6px; font-size: 12px; }
.high { background: #ffdddd; }
.medium { background: #fff1cc; }
.low { background: #ddffdd; }
code { background: #f2f2f2; padding: 2px 4px; border-radius: 4px; }
ul { margin-top: 0.3em; }
</style>
</head>
<body>
""")

    parts.append(f"<h1>OCR Risk Gallery ({html_escape(args.level)})</h1>")

    parts.append('<div class="summary">')
    parts.append(f"<p><b>Total selected blocks:</b> {len(enriched)}</p>")
    parts.append(f"<p><b>Pages involved:</b> {len(page_to_blocks)}</p>")

    parts.append("<h2>Risk counts</h2><ul>")
    for k, v in risk_counter.items():
        parts.append(f"<li>{html_escape(k)}: {v}</li>")
    parts.append("</ul>")

    parts.append("<h2>Status counts</h2><ul>")
    for k, v in status_counter.items():
        parts.append(f"<li>{html_escape(k)}: {v}</li>")
    parts.append("</ul>")

    parts.append("<h2>Top flags</h2><ul>")
    for k, v in flag_counter.most_common(30):
        parts.append(f"<li>{html_escape(k)}: {v}</li>")
    parts.append("</ul>")
    parts.append("</div>")

    # page overlays
    parts.append("<h2>Page overlays</h2>")
    for page_id in sorted(page_to_blocks.keys()):
        overlay_rel = relpath_str(page_overlay_paths.get(page_id), out_root)
        if overlay_rel:
            parts.append('<div class="summary">')
            parts.append(f"<h3>{html_escape(page_id)}</h3>")
            parts.append(f"<p>high-risk blocks on this page: {len(page_to_blocks[page_id])}</p>")
            parts.append(f'<img src="{html_escape(overlay_rel)}" alt="{html_escape(page_id)} overlay">')
            parts.append("</div>")

    # item cards
    parts.append("<h2>High-risk items</h2>")
    for b in enriched:
        risk_level = b.get("risk_level", "unknown")
        risk_score = b.get("risk_score", 0.0)
        status = b.get("verification_status", "")
        flags = b.get("flags", [])
        crop_rel = b["_gallery_crop"]
        preview_rel = b["_gallery_preview"]
        overlay_rel = b["_gallery_page_overlay"]

        parts.append('<div class="card">')
        parts.append(f"<h3>{html_escape(b.get('page_id'))} · {html_escape(b.get('rid'))} · {html_escape(b.get('block_id'))}</h3>")

        badge_cls = "high" if risk_level == "high" else ("medium" if risk_level == "medium" else "low")
        parts.append('<div class="meta">')
        parts.append(f'<span class="badge {badge_cls}">risk: {html_escape(risk_level)} / {float(risk_score):.2f}</span>')
        parts.append(f'<span class="badge">status: {html_escape(status)}</span>')
        parts.append("</div>")

        parts.append('<div class="meta">')
        parts.append(f"<p><b>title:</b> <code>{html_escape(b.get('title'))}</code></p>")
        parts.append(f"<p><b>kind:</b> <code>{html_escape(b.get('kind'))}</code></p>")
        parts.append(f"<p><b>matched_region:</b> <code>{html_escape(b.get('matched_region'))}</code></p>")
        parts.append(f"<p><b>matched_region_ids:</b> <code>{html_escape(', '.join(b.get('matched_region_ids', [])))}</code></p>")
        parts.append(f"<p><b>matched_region_type:</b> <code>{html_escape(b.get('matched_region_type'))}</code></p>")
        parts.append(f"<p><b>bbox:</b> <code>{html_escape(b.get('bbox'))}</code></p>")
        parts.append(f"<p><b>deepseek_bbox:</b> <code>{html_escape(b.get('deepseek_bbox'))}</code></p>")
        parts.append(f"<p><b>flags:</b> <code>{html_escape(', '.join(flags))}</code></p>")
        parts.append("</div>")

        parts.append('<div class="grid">')
        parts.append("<div>")
        parts.append("<h4>Crop</h4>")
        if crop_rel:
            parts.append(f'<img src="{html_escape(crop_rel)}" alt="crop">')
        else:
            parts.append("<p><i>No crop available</i></p>")
        parts.append("</div>")

        parts.append("<div>")
        parts.append("<h4>Page preview with bbox</h4>")
        if preview_rel:
            parts.append(f'<img src="{html_escape(preview_rel)}" alt="preview">')
        else:
            parts.append("<p><i>No preview available</i></p>")
        parts.append("</div>")
        parts.append("</div>")

        if overlay_rel:
            parts.append("<h4>Whole-page overlay</h4>")
            parts.append(f'<img src="{html_escape(overlay_rel)}" alt="page overlay">')

        parts.append("<h4>OCR text</h4>")
        parts.append(f"<pre>{html_escape(b.get('text', ''))}</pre>")

        raw_before = b.get("raw_text_before_filter", "")
        if raw_before and raw_before != b.get("text", ""):
            parts.append("<h4>Raw text before metadata filter</h4>")
            parts.append(f"<pre>{html_escape(raw_before)}</pre>")

        sec = b.get("secondary_ocr_text", "")
        if sec:
            parts.append("<h4>Secondary OCR text</h4>")
            parts.append(f"<p><b>token overlap:</b> {html_escape(b.get('secondary_token_overlap'))} &nbsp; "
                         f"<b>char similarity:</b> {html_escape(b.get('secondary_char_similarity'))}</p>")
            parts.append(f"<pre>{html_escape(sec)}</pre>")

        parts.append("</div>")

    parts.append("</body></html>")

    html_path.write_text("\n".join(parts), encoding="utf-8")

    print(f"[OK] wrote gallery: {html_path}")
    print(f"[OK] selected blocks: {len(enriched)}")
    print(f"[OK] pages: {len(page_to_blocks)}")


if __name__ == "__main__":
    main()