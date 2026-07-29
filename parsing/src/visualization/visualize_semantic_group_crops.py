#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Visualize semantic group crops.

Input:
  data/processed_vlm_md_by_doc/<doc_id>/group_crops_manifest.jsonl

Outputs:
  data/processed_vlm_md_by_doc/<doc_id>/
    ├── group_crops_preview.html
    └── assets/
        └── group_crop_visualization/
            └── page_overlays/
                ├── p0001_overlay.jpg
                └── ...
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from pathlib import Path
from collections import defaultdict

from PIL import Image, ImageDraw, ImageFont


def safe_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("_") or "unknown"


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []

    if not path.exists():
        return rows

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            try:
                rows.append(json.loads(line))
            except Exception:
                pass

    return rows


def rel_path(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path, base)
    except Exception:
        return str(path)


def get_font(size: int = 18):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


def draw_overlay_for_page(
    *,
    page_image: Path,
    rows: list[dict],
    out_path: Path,
) -> None:
    with Image.open(page_image) as im:
        im = im.convert("RGB")
        draw = ImageDraw.Draw(im)
        font = get_font(18)

        for i, row in enumerate(rows, start=1):
            bbox = row.get("pixel_bbox")

            if not bbox or len(bbox) != 4:
                continue

            x1, y1, x2, y2 = [int(v) for v in bbox]

            label = f"{i}: {row.get('group_id', '')}"
            label = label[:80]

            # Rectangle.
            draw.rectangle(
                [x1, y1, x2, y2],
                outline=(255, 0, 0),
                width=4,
            )

            # Label background.
            text_bbox = draw.textbbox((x1, y1), label, font=font)
            tx1, ty1, tx2, ty2 = text_bbox

            draw.rectangle(
                [tx1, ty1, tx2 + 8, ty2 + 6],
                fill=(255, 0, 0),
            )

            draw.text(
                (x1 + 4, y1 + 3),
                label,
                fill=(255, 255, 255),
                font=font,
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(out_path, quality=92)


def make_page_overlays(
    *,
    doc_dir: Path,
    rows: list[dict],
) -> list[tuple[str, Path]]:
    by_page = defaultdict(list)

    for row in rows:
        page_abs = row.get("page_image_abs")

        if not page_abs:
            continue

        page_path = Path(page_abs)

        if not page_path.exists():
            continue

        page_no = row.get("page_no")
        page_id = row.get("page_id") or ""

        key = (str(page_path), page_no, page_id)
        by_page[key].append(row)

    overlay_dir = (
        doc_dir
        / "assets"
        / "group_crop_visualization"
        / "page_overlays"
    )

    overlay_links: list[tuple[str, Path]] = []

    sorted_items = sorted(
        by_page.items(),
        key=lambda item: (
            item[0][1] if item[0][1] is not None else 10**9,
            item[0][2],
            item[0][0],
        ),
    )

    for (page_image_abs, page_no, page_id), page_rows in sorted_items:
        page_image = Path(page_image_abs)

        if page_no is not None:
            page_label = f"p{int(page_no):04d}"
        else:
            page_label = safe_name(page_id) or safe_name(page_image.parent.name)

        out_path = overlay_dir / f"{page_label}_overlay.jpg"

        try:
            draw_overlay_for_page(
                page_image=page_image,
                rows=page_rows,
                out_path=out_path,
            )

            overlay_links.append((page_label, out_path))

        except Exception as e:
            print(f"[WARN] failed overlay for {page_image}: {e}")

    return overlay_links


def write_html_gallery(
    *,
    doc_dir: Path,
    rows: list[dict],
    overlay_links: list[tuple[str, Path]],
) -> None:
    out_html = doc_dir / "group_crops_preview.html"
    doc_name = doc_dir.name

    rows_sorted = sorted(
        rows,
        key=lambda row: (
            row.get("page_no") if row.get("page_no") is not None else 10**9,
            row.get("group_id") or "",
            row.get("region_id") or "",
        ),
    )

    html_lines: list[str] = []

    html_lines.append("<!doctype html>")
    html_lines.append("<html>")
    html_lines.append("<head>")
    html_lines.append("<meta charset='utf-8'>")
    html_lines.append(
        f"<title>Semantic Group Crops - {html.escape(doc_name)}</title>"
    )

    html_lines.append(
        """
<style>
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  margin: 24px;
  background: #f7f7f7;
  color: #222;
}
h1, h2 {
  margin-bottom: 8px;
}
.summary {
  margin-bottom: 24px;
  color: #555;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.card {
  background: white;
  border: 1px solid #ddd;
  border-radius: 10px;
  padding: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.card img {
  max-width: 100%;
  max-height: 260px;
  display: block;
  margin-bottom: 8px;
  border: 1px solid #eee;
}
.meta {
  font-size: 13px;
  line-height: 1.45;
  color: #333;
  word-break: break-word;
}
.badge {
  display: inline-block;
  background: #eee;
  padding: 2px 6px;
  border-radius: 5px;
  margin-right: 4px;
  margin-bottom: 4px;
}
.overlay-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
  margin-bottom: 32px;
}
.overlay-card {
  background: white;
  border: 1px solid #ddd;
  border-radius: 10px;
  padding: 12px;
}
.overlay-card img {
  width: 100%;
  display: block;
  border: 1px solid #eee;
}
a {
  color: #1558d6;
  text-decoration: none;
}
a:hover {
  text-decoration: underline;
}
</style>
"""
    )

    html_lines.append("</head>")
    html_lines.append("<body>")

    html_lines.append(
        f"<h1>Semantic Group Crops - {html.escape(doc_name)}</h1>"
    )

    html_lines.append(
        f"<div class='summary'>"
        f"Crop regions: {len(rows_sorted)} | "
        f"Pages with overlays: {len(overlay_links)}"
        f"</div>"
    )

    html_lines.append("<h2>Page overlays</h2>")
    html_lines.append("<div class='overlay-list'>")

    for label, overlay_path in overlay_links:
        overlay_rel = rel_path(overlay_path, doc_dir)

        html_lines.append("<div class='overlay-card'>")
        html_lines.append(
            f"<div class='meta'><b>{html.escape(label)}</b></div>"
        )
        html_lines.append(
            f"<a href='{html.escape(overlay_rel)}'>"
            f"<img src='{html.escape(overlay_rel)}'>"
            f"</a>"
        )
        html_lines.append("</div>")

    html_lines.append("</div>")

    html_lines.append("<h2>Group crops</h2>")
    html_lines.append("<div class='grid'>")

    for row in rows_sorted:
        crop_rel_str = row.get("crop_path", "")
        crop_path = doc_dir / crop_rel_str

        group_id = row.get("group_id") or ""
        region_id = row.get("region_id") or ""
        group_type = row.get("group_type") or ""
        page_no = row.get("page_no")
        bbox = row.get("pixel_bbox")
        members = row.get("member_block_ids") or []

        html_lines.append("<div class='card'>")

        if crop_path.exists():
            crop_rel = rel_path(crop_path, doc_dir)
            html_lines.append(
                f"<a href='{html.escape(crop_rel)}'>"
                f"<img src='{html.escape(crop_rel)}'>"
                f"</a>"
            )
        else:
            html_lines.append("<div class='meta'>[missing crop image]</div>")

        html_lines.append("<div class='meta'>")
        html_lines.append(f"<div><b>{html.escape(group_id)}</b></div>")
        html_lines.append(f"<div>{html.escape(region_id)}</div>")

        if group_type:
            html_lines.append(
                f"<span class='badge'>{html.escape(group_type)}</span>"
            )

        if page_no is not None:
            html_lines.append(
                f"<span class='badge'>page {html.escape(str(page_no))}</span>"
            )

        html_lines.append(f"<div>bbox: {html.escape(str(bbox))}</div>")

        if members:
            shown = ", ".join(members[:8])
            if len(members) > 8:
                shown += f" ... +{len(members) - 8}"

            html_lines.append(
                f"<div>members: {html.escape(shown)}</div>"
            )

        html_lines.append("</div>")
        html_lines.append("</div>")

    html_lines.append("</div>")
    html_lines.append("</body>")
    html_lines.append("</html>")

    out_html.write_text("\n".join(html_lines), encoding="utf-8")

    print(f"[OK] preview: {out_html}")


def process_doc_dir(doc_dir: Path) -> None:
    manifest_path = doc_dir / "group_crops_manifest.jsonl"

    if not manifest_path.exists():
        print(f"[SKIP] no manifest: {manifest_path}")
        return

    rows = load_jsonl(manifest_path)

    if not rows:
        print(f"[SKIP] empty manifest: {manifest_path}")
        return

    overlay_links = make_page_overlays(
        doc_dir=doc_dir,
        rows=rows,
    )

    write_html_gallery(
        doc_dir=doc_dir,
        rows=rows,
        overlay_links=overlay_links,
    )

    print(
        f"[OK] {doc_dir}: "
        f"{len(rows)} crop regions, "
        f"{len(overlay_links)} page overlays"
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--doc-dir",
        type=Path,
        default=None,
        help="One document directory containing group_crops_manifest.jsonl.",
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Root directory containing per-document folders.",
    )

    args = parser.parse_args()

    if args.doc_dir:
        process_doc_dir(args.doc_dir)

    elif args.root:
        for doc_dir in sorted(args.root.iterdir()):
            if doc_dir.is_dir():
                process_doc_dir(doc_dir)

    else:
        raise SystemExit("Please provide --doc-dir or --root")


if __name__ == "__main__":
    main()