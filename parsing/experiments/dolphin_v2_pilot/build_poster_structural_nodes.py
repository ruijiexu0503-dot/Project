#!/usr/bin/env python3
"""Derive poster-scale structure from existing STR and SAM candidates."""
import argparse
import html
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from skimage.morphology import skeletonize


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def center(b): return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--output", type=Path, required=True); args = ap.parse_args()
    text = read_rows(args.output / "str_text.jsonl"); masks = read_rows(args.output / "sam_visual_candidates.jsonl")
    image = np.asarray(Image.open(args.output / "source.jpg").convert("RGB")); h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    # The temperature curve and ticks are bright, low-saturation ink. Text
    # boxes are removed before connected-component and skeleton extraction.
    white = ((hsv[:, :, 1] < 72) & (hsv[:, :, 2] > 185)).astype(np.uint8)
    text_mask = np.zeros((h, w), dtype=np.uint8)
    for row in text:
        x1, y1, x2, y2 = map(int, row["bbox"]); pad = max(10, int((y2-y1) * .16))
        cv2.rectangle(text_mask, (max(0,x1-pad), max(0,y1-pad)), (min(w,x2+pad), min(h,y2+pad)), 1, -1)
    white[text_mask.astype(bool)] = 0
    # Crop to the scale corridor; this avoids unrelated white logos at edges.
    corridor = np.zeros_like(white); corridor[700:7600, 500:4100] = 1
    curve = white & corridor
    curve = cv2.morphologyEx(curve, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17,17)))
    curve = cv2.morphologyEx(curve, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3,3)))
    skeleton = skeletonize(curve.astype(bool))
    ys, xs = np.where(skeleton)
    curve_bbox = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None
    Image.fromarray((curve * 255).astype(np.uint8)).save(args.output / "scale_curve_mask.png")
    Image.fromarray((skeleton * 255).astype(np.uint8)).save(args.output / "scale_curve_skeleton.png")
    distance = cv2.distanceTransform((~skeleton).astype(np.uint8), cv2.DIST_L2, 5)
    ticks = []
    for row in text:
        value = row["text"].replace(" ", "")
        if not value.startswith("10") or row["confidence"] < .55: continue
        cx, cy = center(row["bbox"]); px, py = min(w-1,max(0,round(cx))), min(h-1,max(0,round(cy)))
        d = float(distance[py, px])
        if d <= 430:
            ticks.append({"node_id": "TICK_" + row["id"], "label_text": row["text"], "label_node": row["id"],
                          "bbox": row["bbox"], "distance_to_curve_px": round(d,1), "relation": "LABELS_SCALE_CURVE"})
    solar_label = next((r for r in text if r["text"].strip().lower() == "solar corona"), None)
    solar_children = []
    if solar_label:
        label = solar_label["bbox"]
        # A conservative local grouping hypothesis: masks left of the label
        # and vertically overlapping its illustration band. Child masks remain
        # individually addressable; no destructive geometric union is made.
        solar_children = [r["id"] for r in masks if r["bbox"][2] <= label[0] + 180 and r["bbox"][3] >= label[1] - 900 and r["bbox"][1] <= label[3] + 900]
    nodes = [{"node_id": "SCALE_CURVE_001", "node_type": "scale_curve", "bbox": curve_bbox,
              "geometry": {"mask": "scale_curve_mask.png", "skeleton": "scale_curve_skeleton.png", "skeleton_pixels": int(skeleton.sum())},
              "status": "STRUCTURAL_CANDIDATE"}]
    if solar_label:
        nodes.append({"node_id": "COMPOSITE_SOLAR_CORONA_001", "node_type": "composite_visual", "label_node": solar_label["id"],
                      "label_text": solar_label["text"], "child_mask_nodes": solar_children, "status": "STRUCTURAL_CANDIDATE"})
    edges = [{"source": tick["node_id"], "target": "SCALE_CURVE_001", "type": tick["relation"], "distance_px": tick["distance_to_curve_px"]} for tick in ticks]
    if solar_label:
        edges += [{"source": child, "target": "COMPOSITE_SOLAR_CORONA_001", "type": "PART_OF"} for child in solar_children]
        edges.append({"source": solar_label["id"], "target": "COMPOSITE_SOLAR_CORONA_001", "type": "LABELS"})
    payload = {"nodes": nodes, "edges": edges, "temperature_ticks": ticks, "production_modified": False,
               "limitations": ["Scale curve is a pixel-derived structural candidate; it is not a semantic inference.", "Solar composite grouping is a local geometry hypothesis and retains each SAM child."]}
    (args.output / "poster_structure.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    overlay = Image.open(args.output / "overlay.jpg").convert("RGBA"); draw = ImageDraw.Draw(overlay, "RGBA")
    if curve_bbox: draw.rectangle(curve_bbox, outline=(70, 255, 255, 240), width=8)
    if solar_label:
        x1,y1,x2,y2 = solar_label["bbox"]; draw.rectangle((x1,y1,x2,y2), outline=(255,80,200,240), width=7)
        for child in masks:
            if child["id"] in solar_children: draw.rectangle(child["bbox"], outline=(255,80,200,180), width=5)
    overlay.convert("RGB").save(args.output / "structural_overlay.jpg", quality=92)
    report = "<!doctype html><meta charset=utf-8><style>body{font:15px system-ui;max-width:1600px;margin:auto}img{width:49%;vertical-align:top}pre{white-space:pre-wrap}</style><h1>Poster structural candidates</h1><p>Cyan: scale-curve corridor; magenta: Solar corona label and composite child masks.</p><img src=overlay.jpg><img src=structural_overlay.jpg><h2>Nodes and relations</h2><pre>" + html.escape(json.dumps(payload, ensure_ascii=False, indent=2)) + "</pre>"
    (args.output / "structural_report.html").write_text(report)
    print(json.dumps({"curve_bbox": curve_bbox, "ticks": len(ticks), "solar_children": solar_children}, indent=2))


if __name__ == "__main__": main()
