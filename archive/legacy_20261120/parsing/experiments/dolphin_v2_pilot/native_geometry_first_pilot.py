#!/usr/bin/env python3
"""Build native-PDF-geometry guided Dolphin retry crops and an audit report.

The input crops always come from the normally rendered page. Native objects
only propose crop windows and overlap metadata; hidden pixels are never used
as visible parsing evidence.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import math
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "parsing/audits/dolphin_native_geometry_first_v1"
WORK = OUT / "work"

IMAGE_CASES = [
    ("dlr_p09_ship", "data/incoming/DLRmagazine_176_EN.pdf", 9,
     "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2/visual_assets.jsonl", "page_0009_asset_01"),
    ("dlr_p09_right", "data/incoming/DLRmagazine_176_EN.pdf", 9,
     "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2/visual_assets.jsonl", "page_0009_asset_03"),
    ("dlr_p10_photo", "data/incoming/DLRmagazine_176_EN.pdf", 10,
     "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2/visual_assets.jsonl", "page_0010_asset_01"),
    ("dlr_p12_inset", "data/incoming/DLRmagazine_176_EN.pdf", 12,
     "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2/visual_assets.jsonl", "page_0012_asset_04"),
    ("dlr_p22_photo", "data/incoming/DLRmagazine_176_EN.pdf", 22,
     "parsing/audits/gated_background_assets_shadow_v1/DLRmagazine_176_EN_full_v2/visual_assets.jsonl", "page_0022_asset_02"),
    ("nvidia_p04_background", "data/incoming/financial_reports/NVIDIA_2026_Annual_Report.pdf", 4,
     "parsing/audits/gated_background_assets_shadow_v1/NVIDIA_2026_Annual_Report_full_v1/visual_assets.jsonl", "page_0004_asset_01"),
]

VECTOR_CASES = [
    ("nist_p28_table", "data/incoming/government_reports/NIST_AI_100-1_AI_RMF_1.0.pdf", 28),
    ("nvidia_p128_tables", "data/incoming/financial_reports/NVIDIA_2026_Annual_Report.pdf", 128),
]

ASSESSMENTS = {
    "dlr_p09_ship": ("worse", "The crop crosses into the right-page article and the final paragraph becomes truncated/garbled."),
    "dlr_p09_right": ("better", "Local retry preserves the overlaid captions and repairs several corrupted words in the right-page article."),
    "dlr_p10_photo": ("better", "Local retry recovers Cochstedt and equipment-in-the-bus wording that the full-page parse corrupted."),
    "dlr_p12_inset": ("same", "The crop is correctly localized, but Dolphin still emits only a Figure placeholder."),
    "dlr_p22_photo": ("same", "The crop is correctly localized, but Dolphin still emits only a Figure placeholder."),
    "nvidia_p04_background": ("same", "The local output is effectively identical to the already-correct full-page parse."),
    "nist_p28_table": ("worse", "Full-page Dolphin reconstructs the table; the geometry crop loses row/column structure."),
    "nvidia_p128_tables": ("same", "All three tables are recovered, but the full-page parse already recovered them correctly."),
}


def baseline_markdown(row):
    name = Path(row["pdf"]).name
    page = row["page"]
    if name == "DLRmagazine_176_EN.pdf":
        base = ROOT / "parsing/experiments/dolphin_v2_pilot/work/magazine_corpus_v1/dlrmagazine_176_en/pages"
    elif name == "NIST_AI_100-1_AI_RMF_1.0.pdf":
        base = ROOT / "parsing/experiments/dolphin_v2_pilot/work/government_financial_v1/nist_ai_rmf_1_0/pages"
    elif name == "NVIDIA_2026_Annual_Report.pdf":
        base = ROOT / "parsing/experiments/dolphin_v2_pilot/work/government_financial_v1/nvidia_2026_annual_report/pages"
    else:
        return None
    path = base / f"page_{page:04d}" / "markdown" / f"page_{page:04d}.md"
    return path if path.exists() else None


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def intersection(a, b):
    return [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]


def area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def expand(box, page_rect, x_fraction=.015, y_fraction=.015):
    dx, dy = page_rect.width * x_fraction, page_rect.height * y_fraction
    return [max(0, box[0] - dx), max(0, box[1] - dy),
            min(page_rect.width, box[2] + dx), min(page_rect.height, box[3] + dy)]


def render_crop(page, box, output: Path, target_long_side=1600):
    rect = fitz.Rect(box)
    scale = target_long_side / max(rect.width, rect.height)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    pix.save(output)
    return [pix.width, pix.height]


def build_context_overlay(row):
    """Render page context with native geometry, without altering inputs."""
    doc = fitz.open(ROOT / row["pdf"])
    page = doc[row["page"] - 1]
    scale = 1400 / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    draw = ImageDraw.Draw(image)

    def box(values, color, label, width=5):
        raw = [round(v * scale) for v in values]
        coords = (max(0, min(image.width - 1, raw[0])),
                  max(0, min(image.height - 1, raw[1])),
                  max(0, min(image.width - 1, raw[2])),
                  max(0, min(image.height - 1, raw[3])))
        draw.rectangle(coords, outline=color, width=width)
        label_top = max(0, coords[1] - 22)
        label_bottom = max(label_top, coords[1])
        label_right = min(image.width - 1, coords[0] + max(90, 8 * len(label)))
        draw.rectangle((coords[0], label_top, label_right, label_bottom), fill=color)
        draw.text((coords[0] + 3, max(0, coords[1] - 20)), label, fill="black")

    box(row["crop_bbox_points"], "#00e5ff", "Dolphin crop", 6)
    if row["kind"] == "native_image_overlap":
        for index, member in enumerate(row["native_member_bboxes_points"], 1):
            box(member, "#ffd400", f"native image {index}", 5)
        for index, text_row in enumerate(row["overlapping_text_blocks"], 1):
            box(text_row["bbox"], "#ff3b30", f"overlap text {index}", 3)
    else:
        box(row["vector_region_bbox_points"], "#ff9500", "native vector group", 5)
    target = OUT / "context_overlays" / f"{row['case_id']}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target


def text_blocks(page):
    rows = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = " ".join("".join(span.get("text", "") for span in line.get("spans", [])).split())
            if text:
                rows.append({"bbox": list(line["bbox"]), "text": text,
                             "geometry_granularity": "pdf_native_text_line"})
    return rows


def bboxlog_rows(page):
    return [{"sequence": i, "type": kind, "bbox": list(box)}
            for i, (kind, box) in enumerate(page.get_bboxlog())]


def find_asset(path: Path, asset_id: str):
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["asset_id"] == asset_id:
            return row
    raise KeyError(asset_id)


def image_region(case_id, pdf_path, page_number, assets_path, asset_id):
    doc = fitz.open(ROOT / pdf_path)
    page = doc[page_number - 1]
    asset = find_asset(ROOT / assets_path, asset_id)
    source_w, source_h = asset["image_size"]
    sx, sy = page.rect.width / source_w, page.rect.height / source_h
    members = [[b * scale for b, scale in zip(member["rendered_bbox_pixels"], [sx, sy, sx, sy])]
               for member in asset["render_layer_members"]]
    native_box = union(members)
    blocks = text_blocks(page)
    overlapping = []
    for block in blocks:
        overlap = intersection(native_box, block["bbox"])
        coverage = area(overlap) / max(1e-9, area(block["bbox"]))
        cx = (block["bbox"][0] + block["bbox"][2]) / 2
        cy = (block["bbox"][1] + block["bbox"][3]) / 2
        center_inside = native_box[0] <= cx <= native_box[2] and native_box[1] <= cy <= native_box[3]
        if coverage >= .2 or center_inside:
            overlapping.append({**block, "image_coverage": round(coverage, 5)})
    # Include complete blocks that genuinely overlap the image, then add only
    # normalized page-relative padding. The rendered crop retains every layer.
    proposal_box = union([native_box] + [b["bbox"] for b in overlapping])
    crop_box = expand(proposal_box, page.rect)
    logs = bboxlog_rows(page)
    image_log = [row for row in logs if row["type"] == "fill-image" and
                 area(intersection(row["bbox"], native_box)) / max(1e-9, min(area(row["bbox"]), area(native_box))) >= .5]
    later_text = [row for row in logs if row["type"].endswith("text") and image_log and
                  row["sequence"] > min(x["sequence"] for x in image_log) and area(intersection(row["bbox"], native_box)) > 0]
    image_path = OUT / f"{case_id}.png"
    rendered_size = render_crop(page, crop_box, image_path)
    return {
        "case_id": case_id, "kind": "native_image_overlap", "input_image": str(image_path.relative_to(ROOT)),
        "pdf": pdf_path, "page": page_number, "asset_id": asset_id,
        "geometry_source": "PDF image XObject placement transform",
        "native_member_bboxes_points": members, "native_asset_bbox_points": native_box,
        "overlapping_text_blocks": overlapping, "crop_bbox_points": crop_box,
        "rendered_crop_size": rendered_size, "matched_image_paint_events": image_log,
        "later_overlapping_text_paint_events": len(later_text),
        "input_policy": "normal visible page pixels clipped by native geometry",
    }


def vector_regions(page):
    width, height = page.rect.width, page.rect.height
    boxes = []
    for drawing in page.get_drawings():
        box = list(drawing["rect"])
        box_width, box_height = box[2] - box[0], box[3] - box[1]
        # Ignore page backgrounds and isolated rules used as page furniture.
        # These are native-PDF geometry checks, not document-specific pixels.
        if box_width >= .95 * width and box_height >= .95 * height:
            continue
        if box_height <= .003 * height and box_width >= .55 * width and (
                box[1] <= .08 * height or box[1] >= .92 * height):
            continue
        # PDF table rules are frequently zero-height/zero-width strokes.
        if box_width < .002 * width and box_height < .002 * height:
            continue
        if box_width >= .22 * width or box_height >= .08 * height:
            boxes.append(box)
    if not boxes:
        return []
    parent = list(range(len(boxes)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def join(i, j):
        a, b = root(i), root(j)
        if a != b: parent[b] = a
    for i, a in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            b = boxes[j]
            x_overlap = max(0, min(a[2], b[2]) - max(a[0], b[0]))
            x_ratio = x_overlap / max(1e-9, min(a[2]-a[0], b[2]-b[0]))
            y_gap = max(0, max(a[1], b[1]) - min(a[3], b[3]))
            same_horizontal_signature = (
                abs(a[0] - b[0]) <= .025 * width and
                abs(a[2] - b[2]) <= .025 * width and
                min(a[2]-a[0], b[2]-b[0]) >= .35 * width
            )
            if (x_ratio >= .35 and y_gap <= .045 * height) or same_horizontal_signature:
                join(i, j)
    groups = {}
    for i, box in enumerate(boxes): groups.setdefault(root(i), []).append(box)
    regions = []
    for members in groups.values():
        box = union(members)
        if len(members) >= 2 and box[2]-box[0] >= .38*width and box[3]-box[1] >= .04*height:
            regions.append((box, members))
    regions.sort(key=lambda item: area(item[0]), reverse=True)
    kept = []
    for box, members in regions:
        if any(area(intersection(box, prior[0])) / max(1e-9, area(box)) > .9 for prior in kept):
            continue
        kept.append((box, members))
    return kept[:3]


def vector_case(case_id, pdf_path, page_number):
    doc = fitz.open(ROOT / pdf_path); page = doc[page_number - 1]
    regions = vector_regions(page)
    if not regions:
        regions = [(list(page.rect), [])]
    blocks = text_blocks(page)
    cases = []
    for index, (region, members) in enumerate(regions):
        relevant = []
        for block in blocks:
            bb = block["bbox"]
            cy = (bb[1] + bb[3]) / 2
            horizontal_gap = max(0, max(region[0], bb[0]) - min(region[2], bb[2]))
            if (area(intersection(region, bb)) > 0 or
                    (region[1] <= cy <= region[3] and horizontal_gap <= .20 * page.rect.width)):
                relevant.append(block)
        proposal = union([region] + [b["bbox"] for b in relevant])
        crop = expand(proposal, page.rect, .02, .015)
        cid = case_id if len(regions) == 1 else f"{case_id}_region_{index+1:02d}"
        image_path = OUT / f"{cid}.png"
        size = render_crop(page, crop, image_path)
        cases.append({
            "case_id": cid, "kind": "native_vector_region", "input_image": str(image_path.relative_to(ROOT)),
            "pdf": pdf_path, "page": page_number, "geometry_source": "PDF vector drawing path bboxes",
            "vector_member_count": len(members), "vector_region_bbox_points": region,
            "included_text_blocks": relevant, "crop_bbox_points": crop, "rendered_crop_size": size,
            "input_policy": "normal visible page pixels clipped by native geometry",
        })
    return cases


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    records = [image_region(*case) for case in IMAGE_CASES]
    for case in VECTOR_CASES: records.extend(vector_case(*case))
    manifest = {"experiment": "dolphin-native-geometry-first-v1",
                "cases": [{"case_id": r["case_id"], "input_image": r["input_image"]} for r in records]}
    write_json(OUT / "cases.json", manifest)
    write_json(OUT / "geometry_provenance.json", {"records": records, "production_modified": False})
    report()
    print(json.dumps({"cases": len(records), "ids": [r["case_id"] for r in records]}, indent=2))


def report():
    provenance = json.loads((OUT / "geometry_provenance.json").read_text(encoding="utf-8"))
    cards = []
    visual_cards = []
    summary = []
    for row in provenance["records"]:
        cid = row["case_id"]
        md = WORK / cid / "markdown" / f"{cid}.md"
        parsed = md.read_text(encoding="utf-8") if md.exists() else "Waiting for Dolphin inference."
        baseline_path = baseline_markdown(row)
        baseline = baseline_path.read_text(encoding="utf-8") if baseline_path else "Baseline unavailable."
        status = "complete" if md.exists() else "pending"
        verdict, note = ASSESSMENTS.get(cid, ("pending", "Awaiting assessment."))
        data = base64.b64encode((ROOT / row["input_image"]).read_bytes()).decode()
        context_path = build_context_overlay(row)
        crop_rel = Path(row["input_image"]).relative_to(OUT.relative_to(ROOT))
        context_rel = context_path.relative_to(OUT)
        layout_path = WORK / cid / "layout_visualization" / f"{cid}_layout.png"
        layout_rel = layout_path.relative_to(OUT) if layout_path.exists() else None
        summary.append({"case_id": cid, "kind": row["kind"], "status": status,
                        "comparison_verdict": verdict, "comparison_note": note,
                        "baseline_markdown": str(baseline_path.relative_to(ROOT)) if baseline_path else None,
                        "parsed_characters": len(parsed) if md.exists() else None,
                        "table_count": parsed.count("<table") if md.exists() else None})
        cards.append(f"<section><h2>{html.escape(cid)}</h2><p>{row['kind']} · {status} · <b class='{verdict}'>{verdict.upper()}</b></p>"
                     f"<p>{html.escape(note)}</p>"
                     f"<img src='data:image/png;base64,{data}'><details><summary>Native geometry provenance</summary>"
                     f"<pre>{html.escape(json.dumps(row, indent=2, ensure_ascii=False))}</pre></details>"
                     f"<div class='cols'><div><h3>Geometry-first local retry</h3><pre>{html.escape(parsed)}</pre></div>"
                     f"<div><h3>Existing full-page Dolphin</h3><pre>{html.escape(baseline)}</pre></div></div></section>")
        layout_html = f"<img src='{layout_rel.as_posix()}' loading='lazy'>" if layout_rel else "<p>No layout overlay.</p>"
        visual_cards.append(
            f"<section><h2>{html.escape(cid)} · <b class='{verdict}'>{verdict.upper()}</b></h2>"
            f"<p>{html.escape(note)}</p><div class='visuals'>"
            f"<figure><img src='{context_rel.as_posix()}' loading='lazy'><figcaption>1. Full-page native geometry</figcaption></figure>"
            f"<figure><img src='{crop_rel.as_posix()}' loading='lazy'><figcaption>2. Visible crop sent to Dolphin</figcaption></figure>"
            f"<figure>{layout_html}<figcaption>3. Dolphin layout result</figcaption></figure></div></section>")
    verdict_counts = {key: sum(r["comparison_verdict"] == key for r in summary) for key in ("better", "same", "worse", "pending")}
    write_json(OUT / "summary.json", {"cases": summary, "complete": sum(r["status"] == "complete" for r in summary),
                                      "total": len(summary), "verdict_counts": verdict_counts,
                                      "production_modified": False})
    style = "<style>body{font:15px/1.5 system-ui;margin:20px;background:#edf1f6}section,header{max-width:1500px;margin:18px auto;padding:18px;background:white}img{max-width:100%;max-height:850px}.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}.better{color:#08752b}.same{color:#735c00}.worse{color:#b42318}pre{white-space:pre-wrap;max-height:650px;overflow:auto;background:#f5f7fa;padding:10px}@media(max-width:900px){.cols{grid-template-columns:1fr}}</style>"
    (OUT / "report.html").write_text("<!doctype html><meta charset='utf-8'><title>Native geometry first</title>" + style +
        f"<header><h1>Native PDF geometry → visible crop → Dolphin retry</h1><p>All bboxes come from PDF image placements or vector paths. Crops use the normally rendered page and retain visible overlays.</p><p><b>Comparison:</b> {html.escape(json.dumps(verdict_counts))}</p></header>" + "".join(cards), encoding="utf-8")
    visual_style = style.replace(".cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}", ".cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}.visuals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:start}.visuals figure{margin:0}.visuals img{width:100%;height:auto;max-height:760px;object-fit:contain;background:#202733}.visuals figcaption{font-weight:700;padding:6px 0}")
    (OUT / "visual_report.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Geometry-first visual audit</title>" + visual_style +
        f"<header><h1>Geometry-first visual audit</h1><p><b>Legend:</b> cyan = crop; yellow = native image placement; red = overlapping native text; orange = native vector group.</p><p>Each case shows full-page context, the exact visible crop, and Dolphin's resulting layout.</p><p><b>Comparison:</b> {html.escape(json.dumps(verdict_counts))}</p></header>" + "".join(visual_cards), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--report", action="store_true")
    args = parser.parse_args(); report() if args.report else prepare()
