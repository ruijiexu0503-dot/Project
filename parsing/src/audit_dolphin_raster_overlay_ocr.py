#!/usr/bin/env python3
"""Audit text hidden inside Dolphin ``fig`` regions using raster input only.

This is intentionally a shadow experiment.  It never replaces or edits a
Dolphin visual element: OCR detections are emitted as overlapping children of
the visual element so that downstream routing can decide whether they are
article prose, captions, or merely labels inside an illustration.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import statistics
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def polygon_bbox(polygon):
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]


def role_hint(text: str, bbox, image_size):
    words = text.split()
    letters = [char for char in text if char.isalpha()]
    uppercase_fraction = sum(char.isupper() for char in letters) / max(1, len(letters))
    # Display headings are commonly short and uppercase.  Height alone is not
    # sufficient: a tightly cropped line of ordinary caption text can occupy a
    # large fraction of a shallow figure crop.
    if 2 <= len(words) <= 12 and uppercase_fraction >= 0.75:
        return "overlay_heading_candidate"
    if len(words) >= 5:
        return "overlay_prose_or_caption_candidate"
    return "visual_internal_label_candidate"


def overlap_1d(a1, a2, b1, b2):
    return max(0.0, min(a2, b2) - max(a1, b1))


def group_lines(records: list[dict], case_id: str, config: dict) -> list[dict]:
    """Conservatively join OCR lines while preserving every source polygon.

    The first pass joins OCR fragments on the same baseline into layout rows.
    The second pass assigns each row to at most one preceding block.  This
    prevents a small OCR fragment from bridging two otherwise separate
    paragraphs. No derived extent is promoted to source geometry.
    """
    if not records:
        return []
    heights = [max(1.0, row["bbox"][3] - row["bbox"][1]) for row in records]
    median_height = statistics.median(heights)
    parent = list(range(len(records)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        a, b = root(left), root(right)
        if a != b:
            parent[b] = a

    # Pass 1: reconstruct physical text rows from same-baseline fragments.
    for left in range(len(records)):
        a = records[left]
        ax1, ay1, ax2, ay2 = a["bbox"]
        ah = max(1.0, ay2 - ay1)
        aw = max(1.0, ax2 - ax1)
        for right in range(left + 1, len(records)):
            b = records[right]
            bx1, by1, bx2, by2 = b["bbox"]
            bh = max(1.0, by2 - by1)
            bw = max(1.0, bx2 - bx1)
            if (a["role_hint"] == "overlay_heading_candidate") != (
                b["role_hint"] == "overlay_heading_candidate"
            ):
                continue
            vertical_overlap = overlap_1d(ay1, ay2, by1, by2) / min(ah, bh)
            horizontal_gap = max(0.0, max(ax1, bx1) - min(ax2, bx2))
            same_baseline = (
                vertical_overlap >= config["same_baseline_min_vertical_overlap"]
                and horizontal_gap <= config["same_baseline_max_gap_line_heights"] * median_height
            )
            if same_baseline:
                union(left, right)

    row_components: dict[int, list[dict]] = {}
    for index, row in enumerate(records):
        row_components.setdefault(root(index), []).append(row)
    physical_rows = []
    for members in row_components.values():
        members.sort(key=lambda row: row["bbox"][0])
        bbox = [
            min(row["bbox"][0] for row in members),
            min(row["bbox"][1] for row in members),
            max(row["bbox"][2] for row in members),
            max(row["bbox"][3] for row in members),
        ]
        physical_rows.append(
            {
                "members": members,
                "bbox": bbox,
                "text": " ".join(row["text"].strip() for row in members),
                "is_heading": any(
                    row["role_hint"] == "overlay_heading_candidate" for row in members
                ),
            }
        )
    physical_rows.sort(key=lambda row: (row["bbox"][1], row["bbox"][0]))

    # Pass 2: append a row only to its single best compatible predecessor.
    block_rows: list[list[dict]] = []
    for current in physical_rows:
        cx1, cy1, cx2, cy2 = current["bbox"]
        cw = max(1.0, cx2 - cx1)
        choices = []
        for block_index, rows in enumerate(block_rows):
            previous = rows[-1]
            px1, py1, px2, py2 = previous["bbox"]
            pw = max(1.0, px2 - px1)
            vertical_gap = cy1 - py2
            horizontal_overlap = overlap_1d(px1, px2, cx1, cx2) / min(pw, cw)
            aligned_left = abs(px1 - cx1) <= config["max_left_shift_line_heights"] * median_height
            first_alpha = next((char for char in current["text"] if char.isalpha()), "")
            explicit_break = (
                vertical_gap >= -0.05 * median_height
                and bool(re.search(r"[.!?:][\"')\]]?$", previous["text"].strip()))
                and first_alpha.isupper()
            )
            compatible = (
                previous["is_heading"] == current["is_heading"]
                and config["min_vertical_gap_line_heights"] * median_height
                <= vertical_gap
                <= config["max_vertical_gap_line_heights"] * median_height
                and horizontal_overlap >= config["min_horizontal_overlap"]
                and aligned_left
                and not explicit_break
            )
            if compatible:
                score = horizontal_overlap - max(0.0, vertical_gap) / median_height
                choices.append((score, block_index))
        if choices:
            _, best_block = max(choices)
            block_rows[best_block].append(current)
        else:
            block_rows.append([current])

    logical_blocks = []
    block_rows.sort(key=lambda rows: (rows[0]["bbox"][1], rows[0]["bbox"][0]))
    for block_index, physical_block_rows in enumerate(block_rows):
        rows = [member for physical_row in physical_block_rows for member in physical_row["members"]]
        rows.sort(key=lambda row: (row["bbox"][1], row["bbox"][0]))
        text = " ".join(row["text"].strip() for row in rows if row["text"].strip())
        text = re.sub(r"(?<=\w)-\s+(?=[a-z])", "", text)
        roles = [row["role_hint"] for row in rows]
        if "overlay_heading_candidate" in roles:
            role = "overlay_heading_candidate"
        elif len(text.split()) >= 8:
            role = "overlay_prose_or_caption_candidate"
        else:
            role = "visual_internal_label_candidate"
        logical_blocks.append(
            {
                "logical_block_id": f"{case_id}_block_{block_index:03d}",
                "text": text,
                "role_hint": role,
                "source_line_ids": [row["recovered_text_id"] for row in rows],
                "geometry_members": [
                    {
                        "bbox": row["bbox"],
                        "polygon": row["polygon"],
                        "source_line_id": row["recovered_text_id"],
                        "bbox_source": "raster_local_ocr",
                    }
                    for row in rows
                ],
                "line_count": len(rows),
                "mean_ocr_confidence": round(
                    sum(row["confidence"] for row in rows) / len(rows), 5
                ),
                "visual_parent": rows[0]["visual_parent"],
                "geometry_policy": "members_preserved_no_fabricated_union",
            }
        )
    return logical_blocks


def run_ocr(image_path: Path, model_dir: Path):
    # Delayed import keeps the report builder usable in lightweight envs.
    import easyocr

    reader = easyocr.Reader(
        ["en"],
        gpu=False,
        model_storage_directory=str(model_dir),
        download_enabled=False,
        verbose=True,
    )
    rows = reader.readtext(
        str(image_path),
        detail=1,
        paragraph=False,
        decoder="greedy",
        beamWidth=1,
        workers=0,
        canvas_size=2560,
        mag_ratio=1.5,
    )
    return [
        {
            "polygon": [[round(float(x), 2), round(float(y), 2)] for x, y in polygon],
            "text": text,
            "confidence": round(float(confidence), 5),
        }
        for polygon, text, confidence in rows
    ]


def draw_overlay(image_path: Path, records: list[dict], output_path: Path):
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 13)
    except OSError:
        font = None
    colors = {
        "overlay_heading_candidate": (0, 220, 120),
        "overlay_prose_or_caption_candidate": (255, 80, 60),
        "visual_internal_label_candidate": (255, 190, 0),
    }
    for index, row in enumerate(records):
        color = colors[row["role_hint"]]
        points = [tuple(point) for point in row["polygon"]]
        draw.line(points + [points[0]], fill=color, width=3)
        x1, y1, _, _ = row["bbox"]
        draw.text(
            (x1 + 2, max(0, y1 - 14)),
            f"R{index:02d} {row['confidence']:.2f}",
            fill=color,
            stroke_width=2,
            stroke_fill=(0, 0, 0),
            font=font,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def draw_group_overlay(image_path: Path, blocks: list[dict], output_path: Path):
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    palette = [
        (0, 220, 120), (255, 80, 60), (80, 170, 255), (255, 190, 0),
        (220, 100, 255), (0, 220, 220), (255, 130, 30), (180, 230, 70),
    ]
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 13)
    except OSError:
        font = None
    for block_index, block in enumerate(blocks):
        color = palette[block_index % len(palette)]
        label = f"B{block_index:02d} ({block['line_count']}L)"
        for member_index, member in enumerate(block["geometry_members"]):
            points = [tuple(point) for point in member["polygon"]]
            draw.line(points + [points[0]], fill=color, width=3)
            if member_index == 0:
                x1, y1, _, _ = member["bbox"]
                draw.text(
                    (x1 + 2, max(0, y1 - 14)), label, fill=color,
                    stroke_width=2, stroke_fill=(0, 0, 0), font=font,
                )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path.home() / ".EasyOCR/model",
    )
    parser.add_argument("--reuse-raw", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    cases = read_json(args.case_manifest)["cases"]
    config = read_json(args.config)
    details = []
    all_blocks = []
    cards = []
    for case in cases:
        image_path = Path(case["image"])
        raw_path = args.output / "raw" / f"{case['case_id']}.json"
        if args.reuse_raw and raw_path.exists():
            rows = read_json(raw_path)
        else:
            rows = run_ocr(image_path, args.model_dir)
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        image_size = Image.open(image_path).size
        enriched = []
        for index, row in enumerate(rows):
            bbox = polygon_bbox(row["polygon"])
            enriched.append(
                {
                    **row,
                    "recovered_text_id": f"{case['case_id']}_raster_{index:03d}",
                    "bbox": bbox,
                    "role_hint": role_hint(row["text"], bbox, image_size),
                    "source": "raster_local_ocr",
                    "visual_parent": case["visual_parent"],
                    "policy": "retain_visual_and_add_overlapping_text_candidate",
                }
            )
        median_detected_height = statistics.median(
            max(1.0, row["bbox"][3] - row["bbox"][1]) for row in enriched
        )
        for row in enriched:
            height = row["bbox"][3] - row["bbox"][1]
            if len(row["text"].split()) <= 12 and height >= 1.55 * median_detected_height:
                row["role_hint"] = "overlay_heading_candidate"
        overlay_path = args.output / "overlays" / f"{case['case_id']}.png"
        draw_overlay(image_path, enriched, overlay_path)
        logical_blocks = group_lines(enriched, case["case_id"], config["line_grouping"])
        group_overlay_path = args.output / "group_overlays" / f"{case['case_id']}.png"
        draw_group_overlay(image_path, logical_blocks, group_overlay_path)
        details.extend({"case_id": case["case_id"], **row} for row in enriched)
        all_blocks.extend({"case_id": case["case_id"], **row} for row in logical_blocks)
        rows_html = "".join(
            "<tr>"
            f"<td>R{index:02d}</td><td>{row['confidence']:.3f}</td>"
            f"<td>{html.escape(row['role_hint'])}</td>"
            f"<td>{html.escape(row['text'])}</td></tr>"
            for index, row in enumerate(enriched)
        )
        cards.append(
            f"<section><h2>{html.escape(case['title'])}</h2>"
            f"<p>{html.escape(case['note'])}</p>"
            f"<h3>Logical blocks (same colour = same block)</h3>"
            f"<img src='group_overlays/{case['case_id']}.png'>"
            f"<h3>Raw OCR lines</h3><img src='overlays/{case['case_id']}.png'>"
            "<table><thead><tr><th>ID</th><th>confidence</th><th>routing hint</th><th>OCR text</th>"
            f"</tr></thead><tbody>{rows_html}</tbody></table></section>"
        )

    output_jsonl = args.output / "raster_overlay_text_candidates.jsonl"
    output_jsonl.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in details) + "\n",
        encoding="utf-8",
    )
    (args.output / "logical_overlay_blocks.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in all_blocks) + "\n",
        encoding="utf-8",
    )
    summary = {
        "experiment": "dolphin_raster_overlay_ocr_shadow_v1",
        "input_policy": "raster figure crops only; no PDF/native text used by OCR",
        "pipeline_version": config["pipeline_version"],
        "config": str(args.config),
        "cases": len(cases),
        "detections": len(details),
        "logical_blocks": len(all_blocks),
        "multi_line_logical_blocks": sum(row["line_count"] > 1 for row in all_blocks),
        "high_confidence_detections": sum(row["confidence"] >= 0.50 for row in details),
        "role_hint_distribution": {
            role: sum(row["role_hint"] == role for row in details)
            for role in sorted({row["role_hint"] for row in details})
        },
        "production_modified": False,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>Dolphin raster overlay OCR audit</title><style>
body{{font:14px/1.45 system-ui;background:#111827;color:#eef2ff;margin:0}}
header,section{{max-width:1600px;margin:20px auto;background:#1f2937;padding:18px}}
img{{width:100%;background:white}} table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #4b5563;padding:6px;text-align:left}}
th{{position:sticky;top:0;background:#374151}}
</style></head><body><header><h1>Dolphin raster-only overlay OCR</h1>
<p>No PDF text layer was supplied to OCR. Green: heading candidate; red: prose/caption candidate; yellow: visual-internal label candidate.</p>
<pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre></header>
{''.join(cards)}</body></html>"""
    (args.output / "report.html").write_text(report, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
