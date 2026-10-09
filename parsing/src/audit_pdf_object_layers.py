#!/usr/bin/env python3
"""Shadow audit of born-digital PDF image layers and OCR text residuals."""
from __future__ import annotations

import argparse
import html
import io
import json
import re
from pathlib import Path

import fitz
from PIL import Image, ImageChops, ImageDraw, ImageFilter


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalized(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def covered_by_ocr(native_text, ocr_text, ocr_blocks):
    key = normalized(native_text)
    if key and key in normalized(ocr_text):
        return True
    tokens = set(re.findall(r"[a-z0-9]+", native_text.lower()))
    if not tokens:
        return False
    # Tolerate a small OCR spelling error inside an otherwise recovered block.
    return any(len(tokens & set(re.findall(r"[a-z0-9]+", block.lower()))) / len(tokens) >= 0.88
               for block in ocr_blocks)


def native_text_segments(page):
    """Recover text regions without merging distant same-baseline left/right furniture."""
    segments = []
    for block in page.get_text("dict", sort=True).get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            text = " ".join(text.split())
            if text:
                lines.append({"bbox": list(line["bbox"]), "text": text})
        clusters = []
        for line in sorted(lines, key=lambda row: (row["bbox"][1], row["bbox"][0])):
            x1, y1, x2, y2 = line["bbox"]
            best = None
            for cluster in clusters:
                cx1, cy1, cx2, cy2 = cluster["bbox"]
                overlap = max(0, min(x2, cx2) - max(x1, cx1))
                min_width = max(1, min(x2 - x1, cx2 - cx1))
                vertical_gap = max(0, y1 - cy2)
                line_height = max(1, y2 - y1, cy2 - cy1)
                if overlap / min_width >= 0.12 and vertical_gap <= 1.8 * line_height:
                    best = cluster
                    break
            if best is None:
                clusters.append({"bbox": [x1, y1, x2, y2], "texts": [line["text"]]})
            else:
                best["bbox"] = [min(best["bbox"][0], x1), min(best["bbox"][1], y1),
                                max(best["bbox"][2], x2), max(best["bbox"][3], y2)]
                best["texts"].append(line["text"])
        for cluster in clusters:
            segments.append({"bbox": cluster["bbox"], "text": " ".join(cluster["texts"])})
    return sorted(segments, key=lambda row: (row["bbox"][1], row["bbox"][0]))


def smask_xref(doc, xref):
    kind, value = doc.xref_get_key(xref, "SMask")
    if kind != "xref":
        return 0
    match = re.match(r"(\d+)\s+0\s+R", value)
    return int(match.group(1)) if match else 0


def extract_object(doc, xref, target):
    base = fitz.Pixmap(doc, xref)
    # PNG cannot encode PDF CMYK / DeviceN pixmaps. Convert only the colour
    # channels before applying the original soft mask; geometry and alpha
    # provenance remain unchanged.
    # A DeviceN colourspec may expose three channels while still being
    # unwritable as PNG. Normalize by the actual colourspec, not channel count.
    if (base.colorspace is None or
            base.colorspace.name not in {"DeviceRGB", "DeviceGray"}):
        base = fitz.Pixmap(fitz.csRGB, base)
    smask = smask_xref(doc, xref)
    target.parent.mkdir(parents=True, exist_ok=True)
    if smask:
        # Some PDFs store the colour image and SMask at different raster
        # resolutions. PyMuPDF's direct Pixmap(base, mask) rejects that valid
        # construction, so compose them after a geometry-preserving resize.
        mask = fitz.Pixmap(doc, smask)
        if mask.colorspace is not None and mask.colorspace.n != 1:
            mask = fitz.Pixmap(fitz.csGRAY, mask)
        color_image = Image.open(io.BytesIO(base.tobytes("png"))).convert("RGB")
        alpha_image = Image.open(io.BytesIO(mask.tobytes("png"))).convert("L")
        if alpha_image.size != color_image.size:
            alpha_image = alpha_image.resize(color_image.size, Image.Resampling.BILINEAR)
        color_image.putalpha(alpha_image)
        color_image.save(target, format="PNG")
    else:
        base.save(str(target))
    with Image.open(target) as image:
        alpha = image.getchannel("A") if "A" in image.getbands() else None
        if alpha:
            strong = alpha.point(lambda value: 255 if value >= 128 else 0)
            alpha_coverage = strong.histogram()[255] / (image.width * image.height)
            strong_bbox = list(strong.getbbox()) if strong.getbbox() else None
            alpha_target = target.with_name(target.stem + "_alpha.png")
            alpha.save(alpha_target)
        else:
            alpha_coverage, strong_bbox, alpha_target = 1.0, [0, 0, image.width, image.height], None
        return {
            "asset_path": str(target.resolve()),
            "alpha_mask_path": str(alpha_target.resolve()) if alpha_target else None,
            "alpha_coverage_at_128": round(alpha_coverage, 6),
            "strong_alpha_bbox": strong_bbox,
        }


def dashed_rectangle(draw, bbox, fill, width=3, dash=14, gap=8):
    x1, y1, x2, y2 = [int(round(value)) for value in bbox]
    for x in range(x1, x2, dash + gap):
        draw.line((x, y1, min(x + dash, x2), y1), fill=fill, width=width)
        draw.line((x, y2, min(x + dash, x2), y2), fill=fill, width=width)
    for y in range(y1, y2, dash + gap):
        draw.line((x1, y, x1, min(y + dash, y2)), fill=fill, width=width)
        draw.line((x2, y, x2, min(y + dash, y2)), fill=fill, width=width)


def draw_mask_contour(image, alpha_path, rendered_bbox, color):
    if not alpha_path or not Path(alpha_path).exists():
        return
    x1, y1, x2, y2 = [int(round(value)) for value in rendered_bbox]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.width, x2), min(image.height, y2)
    if x2 <= x1 or y2 <= y1:
        return
    with Image.open(alpha_path) as opened:
        alpha = opened.convert("L").resize((x2 - x1, y2 - y1), Image.Resampling.BILINEAR)
    solid = alpha.point(lambda value: 255 if value >= 128 else 0)
    edge = solid.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(7))
    layer = Image.new("RGB", (x2 - x1, y2 - y1), color)
    image.paste(layer, (x1, y1), edge)


def object_page_mask(record, canvas_size):
    """Place one PDF object's alpha support into rendered-page coordinates."""
    result = Image.new("L", canvas_size, 0)
    x1, y1, x2, y2 = [int(round(value)) for value in record["rendered_bbox_pixels"]]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(canvas_size[0], x2), min(canvas_size[1], y2)
    if x2 <= x1 or y2 <= y1:
        return result
    alpha_path = record.get("alpha_mask_path")
    if alpha_path and Path(alpha_path).exists() and record.get("alpha_coverage_at_128", 1) < 0.95:
        with Image.open(alpha_path) as opened:
            alpha = opened.convert("L").resize((x2 - x1, y2 - y1), Image.Resampling.BILINEAR)
        member = alpha.point(lambda value: 255 if value >= 128 else 0)
    else:
        member = Image.new("L", (x2 - x1, y2 - y1), 255)
    result.paste(member, (x1, y1), member)
    return result


def draw_semantic_group(image, records, color):
    """Draw one contour for a semantic image composed from one or more PDF render layers."""
    support = Image.new("L", image.size, 0)
    for record in records:
        support = ImageChops.lighter(support, object_page_mask(record, image.size))
    edge = support.filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(7))
    layer = Image.new("RGB", image.size, color)
    image.paste(layer, (0, 0), edge)
    return support.getbbox()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--page-index", type=int, required=True, help="Zero-based PDF source page index")
    ap.add_argument("--rendered-page", type=Path, required=True)
    ap.add_argument("--aligned-json", type=Path, nargs="+", required=True,
                    help="One or more physical-page aligned JSON files represented by the source PDF page")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--interpretation", type=Path,
                    help="Optional human-audited semantic groups over the source PDF objects")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    document = fitz.open(args.pdf)
    page = document[args.page_index]
    aligned_payloads = [json.loads(path.read_text(encoding="utf-8")) for path in args.aligned_json]
    ocr_blocks = [str(block.get("text") or "") for aligned in aligned_payloads
                  for block in aligned.get("aligned_blocks", [])]
    ocr_text = " ".join(ocr_blocks)

    object_dir = args.output / "image_objects"
    objects = []
    for info in page.get_image_info(xrefs=True, hashes=True):
        xref = int(info.get("xref") or 0)
        if not xref:
            continue
        bbox = list(info["bbox"])
        record = {
            "display_order": info.get("number"),
            "xref": xref,
            "source_width": info.get("width"),
            "source_height": info.get("height"),
            "page_bbox_points": bbox,
            "transform": list(info["transform"]),
            "digest": info.get("digest").hex() if isinstance(info.get("digest"), bytes) else info.get("digest"),
            "smask_xref": smask_xref(document, xref),
            "has_mask": bool(info.get("has-mask")),
        }
        record.update(extract_object(document, xref, object_dir / f"xref_{xref}.png"))
        objects.append(record)

    residuals = []
    for segment in native_text_segments(page):
        x1, y1, x2, y2 = segment["bbox"]
        text = segment["text"]
        key = normalized(text)
        if len(key) < 8 or covered_by_ocr(text, ocr_text, ocr_blocks):
            continue
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        overlapping_objects = [row["xref"] for row in objects
                               if row["page_bbox_points"][0] <= center[0] <= row["page_bbox_points"][2]
                               and row["page_bbox_points"][1] <= center[1] <= row["page_bbox_points"][3]]
        residuals.append({
            "text": text,
            "page_bbox_points": [x1, y1, x2, y2],
            "normalized_y": y1 / page.rect.height,
            "inside_image_objects": overlapping_objects,
            "audit_role": "POSSIBLE_FOOTER" if y1 / page.rect.height >= 0.95 else
                          "POSSIBLE_VISUAL_CAPTION" if overlapping_objects else "UNRESOLVED_NATIVE_TEXT",
            "source": "pdf_native_text_residual",
            "logical_page": "left" if (x1 + x2) / 2 < page.rect.width / 2 else "right",
        })

    with Image.open(args.rendered_page) as opened:
        overlay = opened.convert("RGB")
    draw = ImageDraw.Draw(overlay)
    sx, sy = overlay.width / page.rect.width, overlay.height / page.rect.height
    palette = [(237, 55, 120), (33, 180, 100), (255, 145, 25), (75, 110, 255), (170, 70, 225)]
    for index, record in enumerate(objects):
        x1, y1, x2, y2 = record["page_bbox_points"]
        scaled = [x1 * sx, y1 * sy, x2 * sx, y2 * sy]
        color = palette[index % len(palette)]
        draw.rectangle(scaled, outline=color, width=4)
        draw.text((scaled[0] + 3, scaled[1] + 3), f"xref {record['xref']} z={record['display_order']}",
                  fill=color, stroke_width=1, stroke_fill="white")
        record["rendered_bbox_pixels"] = [round(value, 2) for value in scaled]
    for residual in residuals:
        x1, y1, x2, y2 = residual["page_bbox_points"]
        scaled = [x1 * sx, y1 * sy, x2 * sx, y2 * sy]
        draw.rectangle(scaled, outline=(255, 0, 0), width=4)
        draw.text((scaled[0] + 3, max(0, scaled[1] - 16)), "PDF TEXT RESIDUAL", fill=(255, 0, 0),
                  stroke_width=1, stroke_fill="white")
        residual["rendered_bbox_pixels"] = [round(value, 2) for value in scaled]
    overlay_path = args.output / "pdf_object_layer_overlay_v2.png"
    overlay.save(overlay_path)

    footer_rows = [row for row in residuals if row["audit_role"] == "POSSIBLE_FOOTER"]
    footer_overlay_path = args.output / "footer_members_overlay.png"
    with Image.open(args.rendered_page) as opened:
        footer_overlay = opened.convert("RGB")
    footer_draw = ImageDraw.Draw(footer_overlay)
    for index, row in enumerate(footer_rows, 1):
        bbox = row["rendered_bbox_pixels"]
        footer_draw.rectangle(bbox, outline=(220, 30, 30), width=6)
        footer_draw.text((bbox[0] + 4, max(0, bbox[1] - 20)),
                         f"FOOTER MEMBER {index} · {row['logical_page']}",
                         fill=(220, 30, 30), stroke_width=1, stroke_fill="white")
    footer_overlay.save(footer_overlay_path)
    footer_crop_path = args.output / "footer_members_crop.png"
    if footer_rows:
        y1 = max(0, int(min(row["rendered_bbox_pixels"][1] for row in footer_rows) - 45))
        y2 = min(footer_overlay.height, int(max(row["rendered_bbox_pixels"][3] for row in footer_rows) + 45))
        footer_overlay.crop((0, y1, footer_overlay.width, y2)).save(footer_crop_path)

    interpretation = json.loads(args.interpretation.read_text(encoding="utf-8")) if args.interpretation else {}
    object_labels = {int(key): value for key, value in interpretation.get("object_labels", {}).items()}
    semantic_overlay_path = None
    simple_overlay_path = None
    simple_visual_rows = []
    if interpretation:
        with Image.open(args.rendered_page) as opened:
            semantic_overlay = opened.convert("RGB")
        semantic_draw = ImageDraw.Draw(semantic_overlay)
        by_xref = {row["xref"]: row for row in objects}
        grouped_xrefs = {int(xref) for group in interpretation.get("semantic_groups", [])
                         for xref in group.get("render_layer_xrefs", group.get("member_xrefs", []))}
        # Only ungrouped PDF objects appear separately. Grouped render layers are collapsed into one semantic shape.
        for record in objects:
            object_config = object_labels.get(record["xref"]) or {}
            if record["xref"] in grouped_xrefs or object_config.get("show_in_semantic_overlay", True) is False:
                continue
            color = tuple(object_config.get("color", [120, 120, 120]))
            label = object_config.get("label", f"PDF object xref {record['xref']}")
            if record.get("alpha_mask_path") and record.get("alpha_coverage_at_128", 1) < 0.95:
                draw_mask_contour(semantic_overlay, record["alpha_mask_path"], record["rendered_bbox_pixels"], color)
            else:
                dashed_rectangle(semantic_draw, record["rendered_bbox_pixels"], color, width=2)
            x1, y1 = record["rendered_bbox_pixels"][:2]
            semantic_draw.text((max(0, x1 + 3), max(0, y1 + 3)), f"LAYER xref {record['xref']}: {label}",
                               fill=color, stroke_width=1, stroke_fill="white")
        # This is a display-time composition of exact PDF layer supports, not a fabricated geometry bbox.
        for group in interpretation.get("semantic_groups", []):
            layer_xrefs = [int(value) for value in group.get("render_layer_xrefs", group.get("member_xrefs", []))]
            records = [by_xref[value] for value in layer_xrefs if value in by_xref]
            if not records:
                continue
            color = tuple(group.get("color", [0, 220, 220]))
            bbox = draw_semantic_group(semantic_overlay, records, color)
            if not bbox:
                continue
            semantic_draw.text((max(0, bbox[0] + 4), max(0, bbox[1] - 22)),
                               f"ONE SEMANTIC IMAGE {group['group_id']}: {group['label']} · render layers {layer_xrefs}",
                               fill=color, stroke_width=2, stroke_fill="white")
        for residual in residuals:
            if residual["audit_role"] != "POSSIBLE_VISUAL_CAPTION":
                continue
            bbox = residual["rendered_bbox_pixels"]
            semantic_draw.rectangle(bbox, outline=(255, 0, 0), width=5)
            semantic_draw.text((bbox[0] + 3, max(0, bbox[1] - 18)), "OCR-MISSING NATIVE CAPTION",
                               fill=(255, 0, 0), stroke_width=1, stroke_fill="white")
        semantic_overlay_path = args.output / "semantic_visual_group_overlay_v2.png"
        semantic_overlay.save(semantic_overlay_path)

        # Production-shaped shadow: page-local rectangular members only. No masks or PDF-layer boxes are shown.
        with Image.open(args.rendered_page) as opened:
            simple_overlay = opened.convert("RGB")
        simple_draw = ImageDraw.Draw(simple_overlay)
        gutter_x = simple_overlay.width // 2
        for group in interpretation.get("semantic_groups", []):
            layer_xrefs = [int(value) for value in group.get("render_layer_xrefs", group.get("member_xrefs", []))]
            records = [by_xref[value] for value in layer_xrefs if value in by_xref]
            if not records:
                continue
            support = Image.new("L", simple_overlay.size, 0)
            for record in records:
                support = ImageChops.lighter(support, object_page_mask(record, simple_overlay.size))
            color = tuple(group.get("color", [0, 220, 220]))
            for logical_page, left, right in (("left", 0, gutter_x), ("right", gutter_x, simple_overlay.width)):
                local_bbox = support.crop((left, 0, right, simple_overlay.height)).getbbox()
                if not local_bbox:
                    continue
                bbox = [local_bbox[0] + left, local_bbox[1], local_bbox[2] + left, local_bbox[3]]
                simple_draw.rectangle(bbox, outline=color, width=6)
                simple_draw.text((bbox[0] + 4, max(0, bbox[1] - 20)),
                                 f"{group['group_id']} · {logical_page} member",
                                 fill=color, stroke_width=1, stroke_fill="white")
                simple_visual_rows.append({
                    "visual_id": group["group_id"], "label": group["label"],
                    "logical_page": logical_page, "bbox_envelope_pixels": bbox,
                    "render_layer_xrefs": layer_xrefs,
                    "geometry_policy": "page_local_rectangular_envelope",
                })
        for index, row in enumerate(footer_rows, 1):
            bbox = row["rendered_bbox_pixels"]
            simple_draw.rectangle(bbox, outline=(220, 30, 30), width=5)
            simple_draw.text((bbox[0] + 3, max(0, bbox[1] - 18)),
                             f"FOOTER · {row['logical_page']} member", fill=(220, 30, 30),
                             stroke_width=1, stroke_fill="white")
        for row in residuals:
            if row["audit_role"] != "POSSIBLE_VISUAL_CAPTION":
                continue
            bbox = row["rendered_bbox_pixels"]
            simple_draw.rectangle(bbox, outline=(180, 40, 220), width=5)
            simple_draw.text((bbox[0] + 3, max(0, bbox[1] - 18)), "RECOVERED CAPTION",
                             fill=(180, 40, 220), stroke_width=1, stroke_fill="white")
        simple_overlay_path = args.output / "simple_rectangular_visual_bundle_overlay.png"
        simple_overlay.save(simple_overlay_path)
        write_json(args.output / "simple_rectangular_visual_bundles.json", {
            "schema_version": "simple_rectangular_visual_bundle_shadow_v1",
            "visual_geometry_members": simple_visual_rows,
            "footer_geometry_members": footer_rows,
            "production_modified": False,
        })

    write_json(args.output / "pdf_image_objects.json", objects)
    (args.output / "pdf_text_residuals.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in residuals) + ("\n" if residuals else ""), encoding="utf-8")
    summary = {
        "pdf": str(args.pdf.resolve()), "page_index": args.page_index, "page_number": args.page_index + 1,
        "page_size_points": [page.rect.width, page.rect.height], "rendered_size_pixels": [overlay.width, overlay.height],
        "image_objects": len(objects), "masked_image_objects": sum(bool(row["smask_xref"]) for row in objects),
        "native_text_residuals": len(residuals),
        "possible_visual_captions": sum(row["audit_role"] == "POSSIBLE_VISUAL_CAPTION" for row in residuals),
        "production_modified": False,
        "semantic_groups": len(interpretation.get("semantic_groups", [])),
    }
    write_json(args.output / "summary.json", summary)

    cards = []
    for record in objects:
        rel = Path(record["asset_path"]).relative_to(args.output.resolve())
        cards.append(f"<article><h3>xref {record['xref']} · display order {record['display_order']}</h3>"
                     f"<p>page bbox: {html.escape(str(record['page_bbox_points']))}<br>"
                     f"soft mask: {record['smask_xref'] or 'none'} · alpha coverage: {record['alpha_coverage_at_128']}</p>"
                     f"<div class='checker'><img src='{html.escape(str(rel))}'></div></article>")
    residual_cards = "".join(
        f"<li><b>{html.escape(row['audit_role'])}</b> · {html.escape(row['text'])}<br>"
        f"bbox {html.escape(str(row['page_bbox_points']))} · inside xrefs {html.escape(str(row['inside_image_objects']))}</li>"
        for row in residuals)
    footer_cards = "".join(
        f"<tr><td>FOOTER MEMBER {index}</td><td>{html.escape(row['logical_page'])}</td>"
        f"<td>{html.escape(row['text'])}</td><td>{html.escape(str(row['page_bbox_points']))}</td>"
        f"<td>{html.escape(str(row['rendered_bbox_pixels']))}</td></tr>"
        for index, row in enumerate(footer_rows, 1))
    footer_section = (
        "<h2>Footer-only view</h2>"
        "<p>Each red box is an independent footer member. The center gap is intentionally not part of either member.</p>"
        f"<img src='{footer_overlay_path.name}'><br><img src='{footer_crop_path.name}' style='max-height:260px'>"
        "<table><tr><th>Member</th><th>Logical page</th><th>Text</th><th>PDF bbox</th><th>Rendered bbox</th></tr>"
        f"{footer_cards}</table>"
    )
    group_cards = "".join(
        f"<article><h3>{html.escape(group['group_id'])}: {html.escape(group['label'])}</h3>"
        f"<p>one semantic image · anchor xref {group['anchor_xref']} · PDF render layers "
        f"{html.escape(str(group.get('render_layer_xrefs', group.get('member_xrefs', []))))}<br>"
        f"geometry policy: {html.escape(group.get('geometry_policy', 'layer_members_no_union'))}</p>"
        f"<p>{html.escape(group.get('description', ''))}</p></article>"
        for group in interpretation.get("semantic_groups", []))
    semantic_section = (f"<h2>Default semantic view</h2>"
                        f"<p>One contour means one semantic image. Multiple PDF render layers are collapsed inside it.</p>"
                        f"<section class='hero'><img src='{semantic_overlay_path.name}'></section>"
                        f"<section class='grid'>{group_cards}</section>") if semantic_overlay_path else ""
    simple_rows_html = "".join(
        f"<tr><td>{html.escape(row['visual_id'])}</td><td>{html.escape(row['logical_page'])}</td>"
        f"<td>{html.escape(str(row['bbox_envelope_pixels']))}</td><td>{html.escape(str(row['render_layer_xrefs']))}</td></tr>"
        for row in simple_visual_rows)
    simple_section = (f"<h2>Recommended simple EvidenceNet view</h2>"
                      f"<p>Only semantic VisualBundles with page-local rectangular members are shown. Overlap is allowed; masks are audit metadata only.</p>"
                      f"<section class='hero'><img src='{simple_overlay_path.name}'></section>"
                      f"<table><tr><th>Visual ID</th><th>Logical page</th><th>Rectangular member</th><th>PDF provenance</th></tr>"
                      f"{simple_rows_html}</table>") if simple_overlay_path else ""
    (args.output / "pdf_object_layer_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>PDF object-layer audit</title>"
        "<style>body{font:14px system-ui;background:#111827;color:#eef2ff;margin:24px}img{max-width:100%}"
        ".hero{background:#1f2937;padding:16px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}"
        "article{background:#1f2937;padding:14px}.checker{background-color:#ddd;background-image:linear-gradient(45deg,#aaa 25%,transparent 25%),linear-gradient(-45deg,#aaa 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#aaa 75%),linear-gradient(-45deg,transparent 75%,#aaa 75%);background-size:24px 24px;background-position:0 0,0 12px,12px -12px,-12px 0}"
        "li{margin:10px 0}</style>"
        f"<h1>PDF object-layer audit · source page {args.page_index + 1}</h1>"
        f"{simple_section}"
        f"{semantic_section}"
        f"<h2>Raw PDF render-object diagnostics — not semantic image boxes</h2>"
        f"<section class='hero'><img src='{overlay_path.name}'><pre>{html.escape(json.dumps(summary, indent=2))}</pre></section>"
        f"<h2>Native PDF image objects</h2><section class='grid'>{''.join(cards)}</section>"
        f"{footer_section}"
        f"<h2>Native text missing from OCR/aligned blocks</h2><ul>{residual_cards}</ul>", encoding="utf-8")
    (args.output / "footer_members_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Footer member audit</title>"
        "<style>body{font:14px system-ui;background:#111827;color:#eef2ff;margin:24px}img{max-width:100%}"
        "table{border-collapse:collapse;width:100%;margin-top:18px}td,th{border:1px solid #526075;padding:8px;text-align:left}"
        "th{background:#263449}</style>"
        f"<h1>Footer member audit · source page {args.page_index + 1}</h1>{footer_section}", encoding="utf-8")
    if simple_overlay_path:
        (args.output / "simple_rectangular_visual_bundle_report.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Simple rectangular VisualBundle audit</title>"
            "<style>body{font:14px system-ui;background:#111827;color:#eef2ff;margin:24px}img{max-width:100%}"
            "table{border-collapse:collapse;width:100%;margin-top:18px}td,th{border:1px solid #526075;padding:8px;text-align:left}"
            "th{background:#263449}.hero{background:#1f2937;padding:16px}</style>"
            f"<h1>Simple rectangular VisualBundle audit · source page {args.page_index + 1}</h1>"
            f"{simple_section}{footer_section}", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
