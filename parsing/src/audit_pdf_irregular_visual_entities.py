#!/usr/bin/env python3
"""Shadow-only extraction of non-rectangular PDF VisualEntities.

The primary geometry is a rendered support mask.  Rectangles are emitted only
as indexing envelopes and are never treated as the visual shape.  Image layers
that existing pixel provenance identifies as the same source image are grouped
into one entity with multiple render-layer members.
"""
from __future__ import annotations

import argparse
import html
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from audit_pdf_object_layers import extract_object, object_page_mask, smask_xref, write_json
from audit_pdf_rectangular_visual_bundles_document import union_find_groups


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def render(page, size):
    sx, sy = size[0] / page.rect.width, size[1] / page.rect.height
    pix = page.get_pixmap(matrix=fitz.Matrix(sx, sy), alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def solid_png(width: int, height: int, value: int) -> bytes:
    image = Image.new("RGB", (max(1, width), max(1, height)), (value, value, value))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def fill_external_support(mask: Image.Image) -> Image.Image:
    """Recover clip support while filling holes caused by later page objects."""
    binary = np.where(np.asarray(mask, dtype=np.uint8) >= 128, 255, 0).astype(np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(binary)
    if contours:
        cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return Image.fromarray(filled, mode="L")


def counterfactual_support(pdf_bytes: bytes, page_index: int, record: dict, size: tuple[int, int]) -> Image.Image:
    """Exact visible support from black-vs-white replacement renders.

    The PDF renderer preserves the page's clipping path and layer occlusion.
    Soft-mask support is intersected separately because replace_image may
    replace the image's original SMask association.
    """
    rendered = []
    for value in (0, 255):
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = document[page_index]
        page.replace_image(
            record["xref"],
            stream=solid_png(int(record["source_width"]), int(record["source_height"]), value),
        )
        rendered.append(render(page, size))
        document.close()
    first = np.asarray(rendered[0], dtype=np.int16)
    second = np.asarray(rendered[1], dtype=np.int16)
    difference = np.max(np.abs(first - second), axis=2)
    mask = Image.fromarray(np.where(difference >= 24, 255, 0).astype(np.uint8), mode="L")

    # One xref can be placed multiple times. Restrict this instance to its own
    # placement envelope; overlapping duplicate placements remain explicit.
    x1, y1, x2, y2 = [int(round(value)) for value in record["rendered_bbox_pixels"]]
    placement = Image.new("L", size, 0)
    ImageDraw.Draw(placement).rectangle(
        (max(0, x1), max(0, y1), min(size[0] - 1, x2), min(size[1] - 1, y2)), fill=255
    )
    mask = ImageChops.multiply(mask, placement)

    # Later text / inset objects occlude pixels in the counterfactual render.
    # They are not holes in the underlying image. Filling each external
    # contour recovers the actual PDF clip support without turning it into a
    # rectangle (a circle remains a circle; an L-shaped clip remains L-shaped).
    clip_support = fill_external_support(mask)

    if record.get("alpha_mask_path") and float(record.get("alpha_coverage_at_128", 1.0)) < 0.98:
        alpha_support = object_page_mask(record, size)
        return ImageChops.multiply(clip_support, alpha_support)
    return clip_support


def mask_geometry(mask: Image.Image):
    array = np.asarray(mask, dtype=np.uint8)
    binary = np.where(array >= 128, 1, 0).astype(np.uint8)
    occupied = int(binary.sum())
    bbox = mask.getbbox()
    if not bbox or not occupied:
        return {"bbox_envelope_pixels": None, "occupied_pixels": 0, "components": [], "contours": []}

    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    components = []
    minimum = max(12, round(occupied * 0.00005))
    for index in range(1, count):
        x, y, width, height, area = [int(v) for v in stats[index]]
        if area >= minimum:
            components.append({"bbox_envelope_pixels": [x, y, x + width, y + height], "area_pixels": area})
    components.sort(key=lambda row: row["area_pixels"], reverse=True)

    raw_contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = []
    for contour in sorted(raw_contours, key=cv2.contourArea, reverse=True):
        area = float(cv2.contourArea(contour))
        if area < minimum:
            continue
        perimeter = cv2.arcLength(contour, True)
        simplified = cv2.approxPolyDP(contour, max(1.0, 0.0025 * perimeter), True)
        points = [[int(point[0][0]), int(point[0][1])] for point in simplified]
        if len(points) >= 3:
            contours.append({"area_pixels": round(area, 1), "polygon_pixels": points})
    bbox_area = max(1, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
    return {
        "bbox_envelope_pixels": list(bbox),
        "bbox_is_index_only": True,
        "occupied_pixels": occupied,
        "occupancy_within_bbox": round(occupied / bbox_area, 6),
        "components": components,
        "contours": contours,
    }


def page_ranges(split_manifest: dict, source_page: str, width: int):
    rows = [row for row in split_manifest.get("pages", []) if row.get("source_page") == source_page]
    if not rows:
        return [("full", 0, width)]
    result = []
    for row in rows:
        left, right = int(row["bbox"][0]), int(row["bbox"][2])
        result.append((str(row.get("side") or "full"), left, right))
    return result


def dashed_rectangle(draw, bbox, color, width=3, dash=12, gap=7):
    x1, y1, x2, y2 = [int(round(value)) for value in bbox]
    for x in range(x1, x2, dash + gap):
        draw.line((x, y1, min(x + dash, x2), y1), fill=color, width=width)
        draw.line((x, y2, min(x + dash, x2), y2), fill=color, width=width)
    for y in range(y1, y2, dash + gap):
        draw.line((x1, y, x1, min(y + dash, y2)), fill=color, width=width)
        draw.line((x2, y, x2, min(y + dash, y2)), fill=color, width=width)


def dolphin_figures(root: Path | None, page_number: int, target_size: tuple[int, int]):
    if root is None:
        return []
    page_id = f"page_{page_number:04d}"
    path = root / "pages" / page_id / "output_json" / f"{page_id}.json"
    layout = root / "pages" / page_id / "layout_visualization" / f"{page_id}_layout.png"
    if not path.exists() or not layout.exists():
        return []
    with Image.open(layout) as image:
        sx, sy = target_size[0] / image.width, target_size[1] / image.height
    return [
        {"reading_order": row.get("reading_order"), "label": row.get("label"),
         "bbox": [round(row["bbox"][0] * sx, 2), round(row["bbox"][1] * sy, 2),
                  round(row["bbox"][2] * sx, 2), round(row["bbox"][3] * sy, 2)]}
        for row in load_json(path) if row.get("label") == "fig" and isinstance(row.get("bbox"), list)
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--render-manifest", type=Path, required=True)
    ap.add_argument("--split-manifest", type=Path, required=True)
    ap.add_argument("--dolphin-root", type=Path)
    ap.add_argument("--pages", nargs="+", type=int, required=True, help="One-based source PDF pages")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    pdf_bytes = args.pdf.read_bytes()
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    render_manifest = load_json(args.render_manifest)
    split_manifest = load_json(args.split_manifest)
    parsing_root = args.render_manifest.parents[3]
    rendered_paths = {}
    for row in render_manifest.get("pages", []):
        path = Path(row["output_image"])
        if not path.is_absolute() and not path.exists():
            path = parsing_root / path
        rendered_paths[int(row["page_number"])] = path

    palette = [(0, 220, 220), (255, 190, 0), (255, 70, 145), (80, 130, 255), (65, 210, 105), (190, 80, 235)]
    all_entities, page_rows, cards = [], [], []
    for page_number in args.pages:
        page_index = page_number - 1
        page = document[page_index]
        rendered_path = rendered_paths[page_number]
        with Image.open(rendered_path) as source:
            base = source.convert("RGB")
        sx, sy = base.width / page.rect.width, base.height / page.rect.height
        source_page = f"page_{page_number:06d}"
        page_dir = args.output / source_page
        page_dir.mkdir(parents=True, exist_ok=True)

        records = []
        occurrences = Counter()
        for info in page.get_image_info(xrefs=True, hashes=True):
            xref = int(info.get("xref") or 0)
            if not xref:
                continue
            occurrences[xref] += 1
            bbox = list(info["bbox"])
            record = {
                "xref": xref,
                "object_instance_id": f"xref_{xref}_occurrence_{occurrences[xref]}",
                "display_order": info.get("number"),
                "page_bbox_points": bbox,
                "rendered_bbox_pixels": [bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy],
                "source_width": info.get("width"), "source_height": info.get("height"),
                "smask_xref": smask_xref(document, xref), "has_mask": bool(info.get("has-mask")),
            }
            record.update(extract_object(document, xref, page_dir / "objects" / f"{record['object_instance_id']}.png"))
            record["_support"] = counterfactual_support(pdf_bytes, page_index, record, base.size)
            records.append(record)

        groups, comparisons = union_find_groups(records)
        overlay = base.copy()
        overlay_draw = ImageDraw.Draw(overlay)
        dolphin = dolphin_figures(args.dolphin_root, page_number, base.size)
        for row in dolphin:
            dashed_rectangle(overlay_draw, row["bbox"], (45, 230, 90), width=3)
            overlay_draw.text((row["bbox"][0] + 3, row["bbox"][1] + 3),
                              f"Dolphin fig #{row['reading_order']}", fill=(20, 130, 55),
                              stroke_width=1, stroke_fill="white")

        page_entities = []
        for group_index, group in enumerate(groups, 1):
            entity_id = f"{source_page}_VISUAL_ENTITY_{group_index:03d}"
            support = Image.new("L", base.size, 0)
            for record in group:
                support = ImageChops.lighter(support, record["_support"])
            geometry = mask_geometry(support)
            if not geometry["bbox_envelope_pixels"]:
                continue
            mask_path = page_dir / "masks" / f"{entity_id}.png"
            mask_path.parent.mkdir(parents=True, exist_ok=True)
            support.save(mask_path)
            color = palette[(group_index - 1) % len(palette)]
            edge = support.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(5))
            color_layer = Image.new("RGB", base.size, color)
            overlay.paste(color_layer, (0, 0), edge)
            bbox = geometry["bbox_envelope_pixels"]
            overlay_draw.text((bbox[0] + 4, max(0, bbox[1] - 20)), entity_id,
                              fill=color, stroke_width=2, stroke_fill="white")

            members = []
            for side, left, right in page_ranges(split_manifest, source_page, base.width):
                clipped = support.crop((left, 0, right, base.height))
                local_geometry = mask_geometry(clipped)
                if not local_geometry["bbox_envelope_pixels"]:
                    continue
                local_bbox = local_geometry["bbox_envelope_pixels"]
                local_geometry["bbox_envelope_pixels"] = [local_bbox[0] + left, local_bbox[1], local_bbox[2] + left, local_bbox[3]]
                for contour in local_geometry["contours"]:
                    contour["polygon_pixels"] = [[x + left, y] for x, y in contour["polygon_pixels"]]
                members.append({"logical_page": side, "clip_x_range": [left, right], **local_geometry})

            group_xrefs = {record["xref"] for record in group}
            entity = {
                "source_page": source_page,
                "visual_entity_id": entity_id,
                "render_layer_members": [
                    {key: value for key, value in record.items() if not key.startswith("_")}
                    for record in group
                ],
                "render_layer_xrefs": sorted(group_xrefs),
                "same_image_merge_evidence": [row for row in comparisons if row.get("merge") and set(row["xrefs"]) <= group_xrefs],
                "geometry_representation": "rendered_support_mask_plus_contours",
                "mask_path": str(mask_path.resolve()),
                "geometry": geometry,
                "geometry_members": members,
                "irregular": geometry["occupancy_within_bbox"] < 0.94 or len(geometry["contours"]) > 1,
                "provenance_method": "black_white_counterfactual_render_intersected_with_original_soft_mask",
                "production_modified": False,
            }
            page_entities.append(entity)
            all_entities.append(entity)

        overlay_path = page_dir / "irregular_visual_entity_overlay.png"
        overlay.save(overlay_path)
        page_summary = {
            "source_page": source_page, "pdf_image_instances": len(records),
            "visual_entities": len(page_entities),
            "multi_layer_entities": sum(len(row["render_layer_members"]) > 1 for row in page_entities),
            "irregular_entities": sum(row["irregular"] for row in page_entities),
            "dolphin_figures": len(dolphin),
        }
        page_rows.append(page_summary)
        details = html.escape(json.dumps({
            "summary": page_summary,
            "entities": [{k: v for k, v in entity.items() if k not in {"render_layer_members"}}
                         for entity in page_entities],
        }, ensure_ascii=False, indent=2))
        cards.append(
            f"<section><h2>{source_page}</h2><p>Cyan/yellow/etc: exact mask contours; green dashed: Dolphin rectangles.</p>"
            f"<img src='{source_page}/irregular_visual_entity_overlay.png'>"
            f"<details><summary>Entity provenance</summary><pre>{details}</pre></details></section>"
        )

    entities_path = args.output / "visual_entities.jsonl"
    entities_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in all_entities) + "\n", encoding="utf-8")
    summary = {
        "experiment": "pdf_irregular_visual_entity_shadow_v1",
        "document": split_manifest.get("document_id"), "pages": page_rows,
        "visual_entities": len(all_entities),
        "multi_layer_entities": sum(len(row["render_layer_members"]) > 1 for row in all_entities),
        "irregular_entities": sum(row["irregular"] for row in all_entities),
        "primary_geometry": "support mask; bbox envelopes are indexing-only",
        "production_modified": False,
    }
    write_json(args.output / "summary.json", summary)
    report = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Irregular VisualEntity audit</title>"
        "<style>body{font:14px/1.5 system-ui;background:#111827;color:#eef2ff;margin:24px}"
        "section{max-width:1500px;margin:22px auto;background:#1f2937;padding:18px}img{width:100%;height:auto}"
        "pre{white-space:pre-wrap;max-height:700px;overflow:auto}</style></head><body>"
        f"<h1>{html.escape(str(summary['document']))} · irregular VisualEntity shadow</h1>"
        "<p>Solid contours are PDF-rendered support masks. Green dashed boxes are Dolphin fig detections. "
        "No union bbox is used as shape and production is unchanged.</p>"
        f"<pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>{''.join(cards)}</body></html>"
    )
    (args.output / "irregular_visual_entity_report.html").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
