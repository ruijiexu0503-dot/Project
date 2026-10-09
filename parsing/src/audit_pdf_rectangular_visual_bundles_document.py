#!/usr/bin/env python3
"""Document-wide shadow audit of simple rectangular VisualBundles."""
from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

import fitz
import numpy as np
from PIL import Image, ImageChops, ImageDraw

from audit_pdf_object_layers import (
    covered_by_ocr,
    extract_object,
    native_text_segments,
    object_page_mask,
    smask_xref,
    write_json,
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def page_name(index):
    return f"page_{int(index) + 1:04d}"


def intersection(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return [x1, y1, x2, y2] if x2 > x1 and y2 > y1 else None


def area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def placed_rgba(record):
    image = Image.open(record["asset_path"]).convert("RGBA")
    x1, y1, x2, y2 = [int(round(value)) for value in record["rendered_bbox_pixels"]]
    return image.resize((max(1, x2 - x1), max(1, y2 - y1)), Image.Resampling.BILINEAR), [x1, y1, x2, y2]


def same_image_metrics(first, second):
    first_image, first_box = placed_rgba(first)
    second_image, second_box = placed_rgba(second)
    overlap = intersection(first_box, second_box)
    if not overlap:
        return None
    x1, y1, x2, y2 = overlap
    a = np.asarray(first_image.crop((x1 - first_box[0], y1 - first_box[1], x2 - first_box[0], y2 - first_box[1]))).astype(np.float32)
    b = np.asarray(second_image.crop((x1 - second_box[0], y1 - second_box[1], x2 - second_box[0], y2 - second_box[1]))).astype(np.float32)
    valid = (a[:, :, 3] >= 128) & (b[:, :, 3] >= 128)
    valid_pixels = int(valid.sum())
    if valid_pixels < 500:
        return None
    difference = float(np.abs(a[:, :, :3] - b[:, :, :3])[valid].mean() / 255.0)
    smaller_visible = min(
        max(1, int((np.asarray(first_image)[:, :, 3] >= 128).sum())),
        max(1, int((np.asarray(second_image)[:, :, 3] >= 128).sum())),
    )
    return {
        "mean_rgb_difference": round(difference, 6),
        "shared_visible_pixels": valid_pixels,
        "smaller_layer_overlap": round(valid_pixels / smaller_visible, 6),
    }


def union_find_groups(records, max_rgb_difference=0.08, min_smaller_overlap=0.12):
    parent = list(range(len(records)))

    def find(value):
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def join(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    comparisons = []
    for i, first in enumerate(records):
        for j in range(i):
            second = records[j]
            metrics = same_image_metrics(first, second)
            if not metrics:
                continue
            merge = (metrics["mean_rgb_difference"] <= max_rgb_difference
                     and metrics["smaller_layer_overlap"] >= min_smaller_overlap
                     and (first["smask_xref"] or second["smask_xref"]))
            comparisons.append({"xrefs": [second["xref"], first["xref"]], **metrics, "merge": bool(merge)})
            if merge:
                join(i, j)
    groups = defaultdict(list)
    for index, record in enumerate(records):
        groups[find(index)].append(record)
    return list(groups.values()), comparisons


def aligned_text_boxes(payloads, offsets):
    rows = []
    for side, payload in payloads.items():
        dx = offsets[side]
        for block in payload.get("aligned_blocks", []):
            members = block.get("geometry_members") or []
            boxes = [member.get("bbox") or member.get("pixel_bbox") for member in members]
            if not any(boxes):
                boxes = [block.get("deepseek_bbox") or block.get("bbox")]
            for value in boxes:
                if isinstance(value, list) and len(value) == 4:
                    rows.append({"block_id": block.get("block_id"), "side": side,
                                 "bbox": [value[0] + dx, value[1], value[2] + dx, value[3]]})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, required=True)
    ap.add_argument("--render-manifest", type=Path, required=True)
    ap.add_argument("--split-manifest", type=Path, required=True)
    ap.add_argument("--aligned-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    render_manifest = load_json(args.render_manifest)
    split_manifest = load_json(args.split_manifest)
    split_by_source = defaultdict(dict)
    for row in split_manifest["pages"]:
        split_by_source[row["source_page"]][row["side"]] = row
    # The render manifest stores paths relative to the parsing package (for
    # example ``output/split_render_result/...``), not relative to the repo
    # root or to the manifest itself.
    parsing_root = args.render_manifest.parents[3]
    render_by_source = {}
    for row in render_manifest["pages"]:
        rendered_path = Path(row["output_image"])
        if not rendered_path.is_absolute() and not rendered_path.exists():
            rendered_path = parsing_root / rendered_path
        render_by_source[f"page_{row['page_number']:06d}"] = rendered_path
    document = fitz.open(args.pdf)

    all_pages, all_bundles, all_footers, all_residuals, issues = [], [], [], [], []
    total_objects = total_merges = 0
    page_cards = []
    physical_page_cards = []
    palette = [(0, 210, 210), (255, 205, 0), (255, 120, 20), (170, 55, 225), (35, 175, 90), (70, 115, 245)]

    for page_index, pdf_page in enumerate(document):
        source_page = f"page_{page_index + 1:06d}"
        rendered_path = render_by_source[source_page]
        with Image.open(rendered_path) as opened:
            rendered = opened.convert("RGB")
        sx, sy = rendered.width / pdf_page.rect.width, rendered.height / pdf_page.rect.height

        sides = split_by_source.get(source_page, {})
        payloads, offsets, logical_ranges, physical_by_side = {}, {}, [], {}
        for side, row in sides.items():
            physical = page_name(row["output_page_index"])
            physical_by_side[side] = physical
            aligned_path = args.aligned_dir / f"{physical}.json"
            if aligned_path.exists():
                payloads[side] = load_json(aligned_path)
            offsets[side] = int(row["bbox"][0])
            logical_ranges.append((side, int(row["bbox"][0]), int(row["bbox"][2])))
        if not logical_ranges:
            logical_ranges = [("full", 0, rendered.width)]

        page_dir = args.output / source_page
        records = []
        for info in pdf_page.get_image_info(xrefs=True, hashes=True):
            xref = int(info.get("xref") or 0)
            if not xref:
                continue
            bbox_points = list(info["bbox"])
            record = {
                "xref": xref, "display_order": info.get("number"), "page_bbox_points": bbox_points,
                "rendered_bbox_pixels": [round(bbox_points[0] * sx, 2), round(bbox_points[1] * sy, 2),
                                         round(bbox_points[2] * sx, 2), round(bbox_points[3] * sy, 2)],
                "source_width": info.get("width"), "source_height": info.get("height"),
                "smask_xref": smask_xref(document, xref), "has_mask": bool(info.get("has-mask")),
            }
            record.update(extract_object(document, xref, page_dir / "image_objects" / f"xref_{xref}.png"))
            records.append(record)
        total_objects += len(records)
        groups, comparisons = union_find_groups(records)
        total_merges += sum(max(0, len(group) - 1) for group in groups)

        ocr_blocks = [str(block.get("text") or "") for payload in payloads.values()
                      for block in payload.get("aligned_blocks", [])]
        ocr_text = " ".join(ocr_blocks)
        native_segments = native_text_segments(pdf_page)
        footer_rows, residual_rows = [], []
        for segment in native_segments:
            x1, y1, x2, y2 = segment["bbox"]
            pixel_bbox = [round(x1 * sx, 2), round(y1 * sy, 2), round(x2 * sx, 2), round(y2 * sy, 2)]
            center_x = (pixel_bbox[0] + pixel_bbox[2]) / 2
            side = next((name for name, left, right in logical_ranges if left <= center_x <= right), logical_ranges[0][0])
            row = {"source_page": source_page, "logical_page": side, "text": segment["text"],
                   "page_bbox_points": segment["bbox"], "rendered_bbox_pixels": pixel_bbox}
            if y1 / pdf_page.rect.height >= 0.95:
                footer_rows.append({**row, "role": "PAGE_EDGE_FOOTER_CANDIDATE"})
            elif not covered_by_ocr(segment["text"], ocr_text, ocr_blocks):
                residual_rows.append({**row, "role": "PDF_NATIVE_TEXT_RESIDUAL"})

        text_boxes = aligned_text_boxes(payloads, offsets)
        overlay = rendered.copy()
        draw = ImageDraw.Draw(overlay)
        bundle_rows = []
        for group_index, group in enumerate(groups, 1):
            visual_id = f"{source_page}_VIS_{group_index:03d}"
            support = Image.new("L", rendered.size, 0)
            for record in group:
                support = ImageChops.lighter(support, object_page_mask(record, rendered.size))
            color = palette[(group_index - 1) % len(palette)]
            members, suppressed_members = [], []
            for side, left, right in logical_ranges:
                local = support.crop((left, 0, right, rendered.height)).getbbox()
                if not local:
                    continue
                bbox = [local[0] + left, local[1], local[2] + left, local[3]]
                page_area = max(1, (right - left) * rendered.height)
                overlap_blocks = sorted({row["block_id"] for row in text_boxes if intersection(bbox, row["bbox"])})
                member = {"logical_page": side, "bbox_envelope_pixels": bbox,
                          "page_area_ratio": round(area(bbox) / page_area, 6),
                          "overlapping_text_blocks": overlap_blocks}
                member_width = bbox[2] - bbox[0]
                member_height = bbox[3] - bbox[1]
                touches_logical_edge = abs(bbox[0] - left) <= 2 or abs(bbox[2] - right) <= 2
                if (member_width <= 4 and touches_logical_edge
                        and member["page_area_ratio"] < 0.001):
                    member["decision"] = "SUPPRESSED_GUTTER_SLIVER"
                    suppressed_members.append(member)
                    issues.append({"source_page": source_page, "visual_id": visual_id,
                                   "type": "GUTTER_SLIVER_GEOMETRY_MEMBER", "severity": "warning",
                                   **member})
                    continue
                elif (member_width <= 12 and member_height <= 12
                      and member["page_area_ratio"] < 0.0001):
                    member["decision"] = "INTERNAL_COMPONENT"
                    suppressed_members.append(member)
                    issues.append({"source_page": source_page, "visual_id": visual_id,
                                   "type": "MICRO_RASTER_ASSET", "severity": "warning",
                                   **member})
                    continue
                member["decision"] = "RETAINED_VISUAL_GEOMETRY"
                members.append(member)
                draw.rectangle(bbox, outline=color, width=5)
                draw.text((bbox[0] + 3, max(0, bbox[1] - 18)), f"{visual_id} · {side}",
                          fill=color, stroke_width=1, stroke_fill="white")
                if member["page_area_ratio"] >= 0.45 and len(overlap_blocks) >= 3:
                    issues.append({"source_page": source_page, "visual_id": visual_id,
                                   "type": "COARSE_RECTANGLE_OVERLAPS_BODY_TEXT", "severity": "review",
                                   **member})
            bundle = {"source_page": source_page, "visual_id": visual_id,
                      "render_layer_xrefs": [row["xref"] for row in group],
                      "render_layer_count": len(group), "geometry_members": members,
                      "suppressed_geometry_members": suppressed_members,
                      "visual_decision": "VISUAL_BUNDLE" if members else "INTERNAL_COMPONENT_ONLY",
                      "geometry_policy": "page_local_rectangular_envelope",
                      "same_image_merge_evidence": [row for row in comparisons if row["merge"]
                                                    and set(row["xrefs"]) <= {item["xref"] for item in group}]}
            bundle_rows.append(bundle)
            all_bundles.append(bundle)
        for row in footer_rows:
            bbox = row["rendered_bbox_pixels"]
            draw.rectangle(bbox, outline=(220, 30, 30), width=5)
            draw.text((bbox[0] + 2, max(0, bbox[1] - 17)), f"FOOTER · {row['logical_page']}",
                      fill=(220, 30, 30), stroke_width=1, stroke_fill="white")
        overlay_path = page_dir / "simple_rectangular_overlay.png"
        overlay_path.parent.mkdir(parents=True, exist_ok=True)
        overlay.save(overlay_path)

        # On the original, unsplit spread, adjacent page-local members of the
        # same VisualBundle should read as one visual. Keep both members in
        # provenance, but erase only their shared gutter-edge segment from the
        # display so the overlay does not imply two separate images.
        unsplit_overlay = rendered.copy()
        unsplit_draw = ImageDraw.Draw(unsplit_overlay)
        for group_index, bundle in enumerate(bundle_rows, 1):
            color = palette[(group_index - 1) % len(palette)]
            members = bundle["geometry_members"]
            for member in members:
                unsplit_draw.rectangle(member["bbox_envelope_pixels"], outline=color, width=5)
            for first_index, first in enumerate(members):
                first_box = first["bbox_envelope_pixels"]
                for second in members[first_index + 1:]:
                    second_box = second["bbox_envelope_pixels"]
                    gutter = None
                    if abs(first_box[2] - second_box[0]) <= 2:
                        gutter = int(round((first_box[2] + second_box[0]) / 2))
                    elif abs(second_box[2] - first_box[0]) <= 2:
                        gutter = int(round((second_box[2] + first_box[0]) / 2))
                    if gutter is None:
                        continue
                    overlap_top = int(round(max(first_box[1], second_box[1]))) + 5
                    overlap_bottom = int(round(min(first_box[3], second_box[3]))) - 5
                    if overlap_bottom > overlap_top:
                        stripe = (max(0, gutter - 4), overlap_top,
                                  min(rendered.width, gutter + 5), overlap_bottom)
                        unsplit_overlay.paste(rendered.crop(stripe), stripe)
            if members:
                label_box = min((member["bbox_envelope_pixels"] for member in members),
                                key=lambda box: (box[1], box[0]))
                unsplit_draw.text((label_box[0] + 3, max(0, label_box[1] - 18)), bundle["visual_id"],
                                  fill=color, stroke_width=1, stroke_fill="white")
        for row in footer_rows:
            bbox = row["rendered_bbox_pixels"]
            unsplit_draw.rectangle(bbox, outline=(220, 30, 30), width=5)
            unsplit_draw.text((bbox[0] + 2, max(0, bbox[1] - 17)),
                              f"FOOTER · {row['logical_page']}", fill=(220, 30, 30),
                              stroke_width=1, stroke_fill="white")
        unsplit_overlay_path = page_dir / "unsplit_rectangular_overlay.png"
        unsplit_overlay.save(unsplit_overlay_path)

        physical_dir = args.output / "physical_pages"
        physical_dir.mkdir(parents=True, exist_ok=True)
        for side, left, right in logical_ranges:
            physical = physical_by_side.get(side, source_page)
            physical_path = physical_dir / f"{physical}.png"
            overlay.crop((left, 0, right, rendered.height)).save(physical_path)
            physical_page_cards.append(
                f"<section id='{physical}'><h2>{physical} <small>({source_page} · {side})</small></h2>"
                f"<img src='physical_pages/{physical}.png'></section>")

        page_summary = {"source_page": source_page, "logical_pages": [row[0] for row in logical_ranges],
                        "image_objects": len(records), "visual_bundles": len(bundle_rows),
                        "render_layers_merged": sum(max(0, len(group) - 1) for group in groups),
                        "footer_members": len(footer_rows), "native_text_residuals": len(residual_rows),
                        "issues": sum(issue["source_page"] == source_page for issue in issues)}
        all_pages.append(page_summary); all_footers.extend(footer_rows); all_residuals.extend(residual_rows)
        details = html.escape(json.dumps({"summary": page_summary, "bundles": bundle_rows,
                                         "footers": footer_rows, "residuals": residual_rows}, ensure_ascii=False, indent=2))
        page_cards.append(f"<section><h2>{source_page}</h2><img src='{source_page}/unsplit_rectangular_overlay.png'>"
                          f"<details><summary>Page data</summary><pre>{details}</pre></details></section>")

    issue_types = defaultdict(int)
    for issue in issues:
        issue_types[issue["type"]] += 1
    write_json(args.output / "document_summary.json", {
        "document_id": split_manifest["document_id"], "source_pages": len(all_pages),
        "physical_pages": len(physical_page_cards),
        "pdf_image_objects": total_objects, "semantic_visual_bundles": len(all_bundles),
        "retained_visual_bundles": sum(row["visual_decision"] == "VISUAL_BUNDLE" for row in all_bundles),
        "internal_component_only_bundles": sum(row["visual_decision"] == "INTERNAL_COMPONENT_ONLY" for row in all_bundles),
        "render_layers_merged": total_merges, "visual_geometry_members": sum(len(row["geometry_members"]) for row in all_bundles),
        "suppressed_geometry_members": sum(len(row["suppressed_geometry_members"]) for row in all_bundles),
        "footer_geometry_members": len(all_footers), "pdf_native_text_residuals": len(all_residuals),
        "issues": len(issues), "issue_types": dict(sorted(issue_types.items())),
        "production_modified": False,
    })
    (args.output / "page_summary.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in all_pages) + "\n", encoding="utf-8")
    (args.output / "visual_bundles.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in all_bundles) + "\n", encoding="utf-8")
    (args.output / "footer_members.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in all_footers) + ("\n" if all_footers else ""), encoding="utf-8")
    (args.output / "native_text_residuals.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in all_residuals) + ("\n" if all_residuals else ""), encoding="utf-8")
    (args.output / "issues.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in issues) + ("\n" if issues else ""), encoding="utf-8")
    summary = load_json(args.output / "document_summary.json")
    (args.output / "document_rectangular_visual_bundle_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Document rectangular VisualBundle audit</title>"
        "<style>body{font:14px system-ui;background:#111827;color:#eef2ff;margin:24px}section{background:#1f2937;padding:16px;margin:20px 0}"
        "img{max-width:100%}pre{white-space:pre-wrap;max-height:700px;overflow:auto}</style>"
        f"<h1>{html.escape(split_manifest['document_id'])} · clean rectangular VisualBundle result</h1>"
        "<p>Each card is one physical magazine page. Colored boxes are retained visual bundles; red boxes are page-edge/footer candidates. "
        "Gutter slivers and micro raster components are retained in JSON provenance but hidden from the clean overlay.</p>"
        f"<pre>{html.escape(json.dumps(summary, indent=2))}</pre>{''.join(physical_page_cards)}"
        f"<details><summary>Source-spread audit details</summary>{''.join(page_cards)}</details>", encoding="utf-8")
    (args.output / "document_unsplit_spread_visual_bundle_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Unsplit spread VisualBundle audit</title>"
        "<style>body{font:14px system-ui;background:#111827;color:#eef2ff;margin:24px}section{background:#1f2937;padding:16px;margin:20px 0}"
        "img{display:block;width:100%;height:auto}pre{white-space:pre-wrap;max-height:700px;overflow:auto}small{color:#a5b4fc}</style>"
        f"<h1>{html.escape(split_manifest['document_id'])} · original unsplit PDF pages</h1>"
        "<p>Every card below is one original PDF page. Two-page spreads remain intact; no physical-page crop is used. "
        "Colored boxes are retained rectangular VisualBundles and red boxes are page-edge/footer candidates.</p>"
        f"<pre>{html.escape(json.dumps(summary, indent=2))}</pre>{''.join(page_cards)}", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
