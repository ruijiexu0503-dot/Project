#!/usr/bin/env python3
"""Compare rectangular asset geometry with renderer-derived asset shapes.

This is a shadow audit. It consumes the existing DUAL_MASK artifacts and does
not modify parsing, EvidenceNodes, or production routing.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import fitz
from PIL import Image, ImageChops, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2"
ASSETS = SOURCE / "visual_assets.jsonl"
PDF = ROOT / "data/incoming/DLRmagazine_176_EN.pdf"
OUT = ROOT / "parsing/audits/shape_aware_asset_geometry_v1"

CASE_IDS = [
    "page_0007_asset_01",  # transparent/irregular visual with many bbox-only text candidates
    "page_0007_asset_04",  # native non-rectangular clip
    "page_0009_asset_01",  # ship/sea composite crossing the spread boundary
    "page_0009_asset_02",  # circular portrait inset
    "page_0009_asset_03",  # antenna/grass irregular right-page background
    "page_0012_asset_04",  # circular remote-control inset
]

MASK_THRESHOLD = 24
CONFIRMED_TEXT_COVERAGE = 0.01


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_assets(assets_path: Path = ASSETS, case_ids: list[str] = CASE_IDS) -> dict[str, dict]:
    result = {}
    for line in assets_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["asset_id"] in case_ids:
            result[row["asset_id"]] = row
    missing = sorted(set(case_ids) - set(result))
    if missing:
        raise RuntimeError(f"Missing assets: {missing}")
    return result


def text_lines(page: fitz.Page, canvas_size: tuple[int, int]) -> list[dict]:
    sx, sy = canvas_size[0] / page.rect.width, canvas_size[1] / page.rect.height
    rows = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = " ".join("".join(span.get("text", "") for span in line.get("spans", [])).split())
            if not text:
                continue
            box = list(line["bbox"])
            rows.append({
                "text": text,
                "bbox_points": box,
                "bbox_pixels": [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy],
            })
    return rows


def clipped_box(values, size):
    x1, y1, x2, y2 = values
    return [max(0, min(size[0], int(x1))), max(0, min(size[1], int(y1))),
            max(0, min(size[0], int(x2 + .999))), max(0, min(size[1], int(y2 + .999)))]


def union_box(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def intersection_area(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def mask_pixels(mask: Image.Image, box) -> tuple[int, int]:
    x1, y1, x2, y2 = clipped_box(box, mask.size)
    if x2 <= x1 or y2 <= y1:
        return 0, 0
    crop = mask.crop((x1, y1, x2, y2))
    binary = crop.point(lambda value: 255 if value >= MASK_THRESHOLD else 0)
    supported = binary.histogram()[255]
    return supported, crop.width * crop.height


def contour(mask: Image.Image, width=7):
    binary = mask.point(lambda value: 255 if value >= MASK_THRESHOLD else 0)
    return binary.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(width))


def checkerboard(size, cell=18):
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, min(size[0], x + cell), min(size[1], y + cell)), fill="#d9dde3")
    return image


def make_case(doc: fitz.Document, asset: dict, source: Path = SOURCE, out: Path = OUT) -> dict:
    asset_id = asset["asset_id"]
    page_no = asset["source_page"]
    page_dir = source / f"page_{page_no:04d}"
    original = Image.open(page_dir / "original.jpg").convert("RGB")
    layer = Image.open(source / asset["layer_mask"]).convert("L")
    visible = Image.open(source / asset["visible_mask"]).convert("L")
    if layer.size != original.size or visible.size != original.size:
        raise RuntimeError(f"Mask/page size mismatch for {asset_id}")

    member_boxes = [m["rendered_bbox_pixels"] for m in asset["render_layer_members"]]
    asset_bbox = union_box(member_boxes)
    bbox_clip = clipped_box(asset_bbox, original.size)
    bbox_area = max(1, (bbox_clip[2] - bbox_clip[0]) * (bbox_clip[3] - bbox_clip[1]))
    layer_total, _ = mask_pixels(layer, asset_bbox)
    visible_total, _ = mask_pixels(visible, asset_bbox)

    page = doc[page_no - 1]
    lines = text_lines(page, original.size)
    candidates = []
    for row in lines:
        line_box = row["bbox_pixels"]
        line_area = max(1.0, (line_box[2] - line_box[0]) * (line_box[3] - line_box[1]))
        geom_area = intersection_area(asset_bbox, line_box)
        geom_coverage = geom_area / line_area
        if geom_coverage <= 0:
            continue
        layer_count, line_pixel_area = mask_pixels(layer, line_box)
        visible_count, _ = mask_pixels(visible, line_box)
        layer_coverage = layer_count / max(1, line_pixel_area)
        visible_coverage = visible_count / max(1, line_pixel_area)
        candidates.append({
            **row,
            "bbox_coverage": round(geom_coverage, 5),
            "layer_mask_coverage": round(layer_coverage, 5),
            "visible_mask_coverage": round(visible_coverage, 5),
            "shape_confirmed": layer_coverage >= CONFIRMED_TEXT_COVERAGE,
        })

    overlay = original.copy()
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(bbox_clip, outline="#ff2d9a", width=5)
    draw.text((bbox_clip[0] + 4, max(0, bbox_clip[1] - 18)), "asset bbox", fill="#ff2d9a",
              stroke_width=2, stroke_fill="white")
    green = Image.new("RGB", overlay.size, "#00df73")
    cyan = Image.new("RGB", overlay.size, "#00c8ff")
    overlay.paste(green, (0, 0), contour(layer))
    overlay.paste(cyan, (0, 0), contour(visible, 3))
    for row in candidates:
        box = clipped_box(row["bbox_pixels"], original.size)
        color = "#28e070" if row["shape_confirmed"] else "#ff9f0a"
        draw.rectangle(box, outline=color, width=3)

    overlay_path = out / "images" / f"{asset_id}_overlay.jpg"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(overlay_path, quality=92)

    crop_box = tuple(bbox_clip)
    bbox_crop = original.crop(crop_box)
    bbox_crop_path = out / "images" / f"{asset_id}_bbox_crop.jpg"
    bbox_crop.save(bbox_crop_path, quality=92)

    support = layer.point(lambda value: 255 if value >= MASK_THRESHOLD else 0)
    shaped = checkerboard(original.size)
    shaped.paste(original, (0, 0), support)
    shaped_crop = shaped.crop(crop_box)
    shaped_path = out / "images" / f"{asset_id}_shape_crop.jpg"
    shaped_crop.save(shaped_path, quality=92)

    visible_support = visible.point(lambda value: 255 if value >= MASK_THRESHOLD else 0)
    visible_image = checkerboard(original.size)
    visible_image.paste(original, (0, 0), visible_support)
    visible_crop = visible_image.crop(crop_box)
    visible_path = out / "images" / f"{asset_id}_visible_crop.jpg"
    visible_crop.save(visible_path, quality=92)

    return {
        "asset_id": asset_id,
        "page": page_no,
        "xrefs": asset["xrefs"],
        "reasons": asset["reasons"],
        "bbox_pixels": [round(v, 2) for v in asset_bbox],
        "bbox_area_pixels": bbox_area,
        "layer_support_pixels": layer_total,
        "visible_support_pixels": visible_total,
        "layer_support_fraction_of_bbox": round(layer_total / bbox_area, 5),
        "visible_support_fraction_of_bbox": round(visible_total / bbox_area, 5),
        "bbox_text_candidates": len(candidates),
        "shape_confirmed_text": sum(r["shape_confirmed"] for r in candidates),
        "bbox_only_text": sum(not r["shape_confirmed"] for r in candidates),
        "remaining_overlap_requires_paint_order_audit": True,
        "text_candidates": candidates,
        "overlay": str(overlay_path.relative_to(out)),
        "bbox_crop": str(bbox_crop_path.relative_to(out)),
        "shape_crop": str(shaped_path.relative_to(out)),
        "visible_crop": str(visible_path.relative_to(out)),
        "mask_threshold": MASK_THRESHOLD,
        "shape_confirmed_text_coverage_threshold": CONFIRMED_TEXT_COVERAGE,
    }


def build_report(records: list[dict], out: Path = OUT) -> None:
    totals = {
        "assets": len(records),
        "bbox_text_candidates": sum(r["bbox_text_candidates"] for r in records),
        "shape_confirmed_text": sum(r["shape_confirmed_text"] for r in records),
        "bbox_only_text": sum(r["bbox_only_text"] for r in records),
    }
    write_json(out / "shape_comparison.json", {"summary": totals, "assets": records,
                                                "production_modified": False})
    cards = []
    for row in records:
        text_rows = "".join(
            "<tr><td>{}</td><td>{:.1%}</td><td>{:.1%}</td><td>{:.1%}</td><td>{}</td></tr>".format(
                html.escape(x["text"][:150]), x["bbox_coverage"], x["layer_mask_coverage"],
                x["visible_mask_coverage"], "confirmed" if x["shape_confirmed"] else "bbox-only")
            for x in row["text_candidates"]
        )
        cards.append(f"""
        <section>
          <h2>{html.escape(row['asset_id'])} · page {row['page']}</h2>
          <p><b>Bbox support actually occupied by asset shape:</b> {row['layer_support_fraction_of_bbox']:.1%};
             <b>visible now:</b> {row['visible_support_fraction_of_bbox']:.1%}.</p>
          <p><b>Text candidates:</b> bbox {row['bbox_text_candidates']} → mask-confirmed {row['shape_confirmed_text']};
             bbox-only {row['bbox_only_text']}.</p>
          <div class="wide"><figure><img src="{row['overlay']}"><figcaption>Page overlay</figcaption></figure></div>
          <div class="grid">
            <figure><img src="{row['bbox_crop']}"><figcaption>Rectangular bbox crop</figcaption></figure>
            <figure><img src="{row['shape_crop']}"><figcaption>Page pixels inside complete asset support</figcaption></figure>
            <figure><img src="{row['visible_crop']}"><figcaption>Page pixels inside visible support</figcaption></figure>
          </div>
          <details><summary>Text overlap audit</summary><table><thead><tr><th>Text</th><th>bbox</th><th>layer mask</th><th>visible mask</th><th>decision</th></tr></thead><tbody>{text_rows}</tbody></table></details>
        </section>""")
    css = """<style>
    body{font:15px/1.45 system-ui;margin:0;background:#edf1f6;color:#17202a}header,section{max-width:1500px;margin:18px auto;background:white;padding:18px;box-sizing:border-box}h1,h2{margin-top:0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.wide img{max-height:850px}.grid img{width:100%;height:420px;object-fit:contain;background:#29313b}figure{margin:0}figcaption{font-weight:700;padding:5px 0}table{border-collapse:collapse;width:100%;margin-top:10px}th,td{border:1px solid #ccd4df;padding:6px;text-align:left}th{background:#eef2f6}@media(max-width:900px){.grid{grid-template-columns:1fr}.grid img{height:auto}}
    </style>"""
    legend = "<p><b>Overlay:</b> magenta rectangle = bbox; green contour = complete asset shape; cyan contour = currently visible shape; green text boxes = mask-confirmed geometric overlap; orange text boxes = bbox-only overlap. Mask-confirmed overlap still requires paint-order checking before text is assigned to an asset.</p>"
    (out / "shape_aware_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Shape-aware asset geometry</title>" + css +
        f"<header><h1>Shape-aware asset geometry audit</h1>{legend}<p>{totals['bbox_text_candidates']} bbox text candidates → {totals['shape_confirmed_text']} mask-confirmed; {totals['bbox_only_text']} bbox-only.</p></header>" +
        "".join(cards), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    assets = load_assets()
    doc = fitz.open(PDF)
    records = [make_case(doc, assets[asset_id], SOURCE, OUT) for asset_id in CASE_IDS]
    build_report(records, OUT)
    print(json.dumps({"output": str(OUT), "assets": len(records)}, indent=2))


if __name__ == "__main__":
    main()
