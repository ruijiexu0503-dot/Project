#!/usr/bin/env python3
"""Collect the multi-poster diagnostic views into one browseable report."""
from __future__ import annotations

import argparse
import html
import os
from pathlib import Path

from PIL import Image, ImageDraw

from run_florence_poster_multicase import CASES, ROOT


METHODS = [
    ("Original crop", "poster_grounding_dino_multicase_v1", "source.jpg"),
    ("GraphCut", "poster_graphcut_multicase_v1", "graphcut_overlay.jpg"),
    ("Grounding DINO", "poster_grounding_dino_multicase_v1", "detections.jpg"),
    ("Detector box → SAM, largest region", "poster_grounded_sam_multicase_v2", "mask_0_largest.jpg"),
    ("Florence automatic detection", "poster_florence_multicase_v1", "od.jpg"),
    ("Florence text detection", "poster_florence_multicase_v1", "open_vocab.jpg"),
    ("Florence direct polygon", "poster_florence_multicase_v1", "segmentation.jpg"),
]
REVIEWS = {
    "cosmic_xrism": "The spacecraft is best recovered by combining earlier SAM part masks. Prompted SAM covers most of it but leaks into the XRISM label. Florence returns no polygon.",
    "cosmic_corona": "The solid Sun disk is localized cleanly. None of these methods extracts the surrounding diffuse corona as a complete object.",
    "cosmic_scale": "Florence traces the middle segment of the thick white temperature curve in this crop. The six-tile full-page test failed: the merged mask spills into large background regions (34.75% of the page), and one tile has no polygon. The local success does not generalize to an automatic full curve.",
    "euclid_spacecraft": "Florence gives the cleanest whole-spacecraft silhouette in this crop. Prompted SAM covers the body but also includes scattered background pixels; GraphCut misses dark parts.",
    "spherex_spacecraft": "Grounding DINO plus local SAM gives the most complete spacecraft mask. Florence's polygon selects only lower parts and its automatic class label is wrong.",
    "spherex_beams": "Florence identifies the overall colored beam wedge, but does not separate its individual translucent rays.",
    "milky_center": "The galaxy center and arms do not have a reliable object mask here; the broad boxes and triangle polygon are misleading.",
    "milky_sun": "Grounding DINO can find the small Sun marker, which local SAM segments. Florence misses the marker.",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = args.output.parent
    overviews = []
    for case in CASES:
        if case["poster"] in [name for name, _ in overviews]:
            continue
        source = ROOT / case["image"]
        im = Image.open(source).convert("RGB")
        shown = im.copy()
        shown.thumbnail((900, 1200), Image.Resampling.LANCZOS)
        sx, sy = shown.width / im.width, shown.height / im.height
        draw = ImageDraw.Draw(shown)
        for item in [x for x in CASES if x["poster"] == case["poster"]]:
            x1, y1, x2, y2 = item["crop"]
            draw.rectangle((x1 * sx, y1 * sy, x2 * sx, y2 * sy), outline="#ffc145", width=5)
            draw.text((x1 * sx + 3, y1 * sy + 3), item["target"], fill="#ffc145", stroke_width=2, stroke_fill="black")
        filename = f"overview_{case['id'].split('_', 1)[0]}.jpg"
        shown.save(args.output / filename, quality=89)
        overviews.append((case["poster"], filename))
    overview_html = "".join(f"<figure><img src='{file}'><figcaption>{html.escape(name)}</figcaption></figure>" for name, file in overviews)
    sections = []
    for case in CASES:
        cid = case["id"]
        source = ROOT / case["image"]
        source_href = os.path.relpath(source, args.output)
        views = []
        for label, directory, filename in METHODS:
            target = root / directory / cid / filename
            if target.is_file():
                href = os.path.relpath(target, args.output)
                views.append(f"<figure><a href='{html.escape(href)}'><img src='{html.escape(href)}'></a><figcaption>{html.escape(label)}</figcaption></figure>")
        if cid == "cosmic_xrism":
            union = root / "poster_object_union_diagnostic_v1" / "union_overlay.jpg"
            if union.is_file():
                href = os.path.relpath(union, args.output)
                views.append(f"<figure><a href='{html.escape(href)}'><img src='{html.escape(href)}'></a><figcaption>Earlier SAM part-mask union</figcaption></figure>")
        if cid == "cosmic_scale":
            tiled = root / "poster_florence_curve_tiling_v1" / "full_poster_overlay.jpg"
            tiled_report = root / "poster_florence_curve_tiling_v1" / "report.html"
            if tiled.is_file() and tiled_report.is_file():
                href = os.path.relpath(tiled, args.output)
                report_href = os.path.relpath(tiled_report, args.output)
                views.append(f"<figure><a href='{html.escape(href)}'><img src='{html.escape(href)}'></a><figcaption>Six-tile full-page Florence result: background spill. <a href='{html.escape(report_href)}'>Inspect each tile</a></figcaption></figure>")
        sections.append(f"<section id='{cid}'><h2>{html.escape(case['poster'])}: {html.escape(case['target'])}</h2><p>Source crop {case['crop']} · <a href='{html.escape(source_href)}'>full original poster</a> · Image cards open the saved overlay.</p><p><strong>Visual review:</strong> {html.escape(REVIEWS[cid])}</p><div class='views'>{''.join(views)}</div></section>")
    page = """<!doctype html><html><head><meta charset='utf-8'><title>Poster object extraction comparison</title><style>
body{font:15px system-ui;background:#edf1f4;color:#19252d;margin:1.5rem}section{background:#fff;border-radius:.5rem;padding:1rem;margin:1rem 0}.overviews{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.8rem}.views{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.7rem}figure{margin:0;min-width:0}img{width:100%;height:auto}figcaption{padding:.3rem 0}p{color:#4a5862}a{color:#126f8b}
</style></head><body><h1>Four-poster object extraction comparison</h1><p>Yellow outlines mark hand-selected test crops. GraphCut uses hand-provided coarse rectangles; Grounding DINO uses English object prompts; SAM uses a manually selected detector box. Florence uses the same local crops. All overlays are diagnostic predictions, with no human mask ground truth. Visual reviews below are qualitative.</p><div class='overviews'>""" + overview_html + "</div>" + "".join(sections) + "</body></html>"
    (args.output / "report.html").write_text(page, encoding="utf-8")
    print(args.output / "report.html")


if __name__ == "__main__":
    main()
