#!/usr/bin/env python3
"""Trace a diagram curve as a path, rather than segmenting it as an object.

This diagnostic uses the same sparse anchors as the SAM experiment.  Each
anchor pair is joined by a low-cost path through bright/low-saturation pixels.
The result is a centerline (geometry evidence), never a visual-object mask.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from skimage.graph import route_through_array

POINTS = np.array([
    [5050, 210], [3960, 720], [2680, 1380], [1820, 2460],
    [2350, 3630], [3650, 4540], [3280, 5710], [1740, 6940], [690, 7490],
], dtype=np.float32)


def closest_valid(point: np.ndarray, score: np.ndarray) -> tuple[int, int]:
    x, y = int(round(point[0])), int(round(point[1])); radius = 12
    y1, y2 = max(0, y-radius), min(score.shape[0], y+radius+1)
    x1, x2 = max(0, x-radius), min(score.shape[1], x+radius+1)
    patch = score[y1:y2, x1:x2]; py, px = np.unravel_index(np.argmax(patch), patch.shape)
    return y1 + int(py), x1 + int(px)


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--image", type=Path, required=True); ap.add_argument("--output", type=Path, required=True); ap.add_argument("--scale", type=float, default=.25)
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    native = np.asarray(Image.open(args.image).convert("RGB")); height, width = native.shape[:2]
    small = cv2.resize(native, (round(width * args.scale), round(height * args.scale)), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV); lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB)
    light = lab[:, :, 0].astype(np.float32) / 255.0
    low_sat = 1.0 - hsv[:, :, 1].astype(np.float32) / 255.0
    # Pale cyan/white curve has both high luminance and reduced saturation.
    score = .78 * light + .22 * low_sat
    cost = 1.0 + 28.0 * np.square(1.0 - score)
    points = POINTS * args.scale
    routed: list[tuple[int, int]] = []
    snapped = []
    for start, end in zip(points[:-1], points[1:]):
        src = closest_valid(start, score); dst = closest_valid(end, score)
        snapped.extend([src, dst])
        path, _ = route_through_array(cost, src, dst, fully_connected=True, geometric=True)
        routed.extend(path[:-1])
    routed.append(snapped[-1])
    curve = np.zeros(small.shape[:2], dtype=np.uint8)
    for y, x in routed: curve[y, x] = 255
    curve_native = cv2.resize(curve, (width, height), interpolation=cv2.INTER_NEAREST)
    # A small dilation makes the rendered path visible while retaining a line representation.
    rendered = cv2.dilate(curve_native, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    Image.fromarray(curve_native).save(args.output / "s_curve_traced_skeleton.png")
    Image.fromarray(rendered).save(args.output / "s_curve_traced_render.png")
    overlay = Image.fromarray(native).convert("RGBA")
    rgba = np.zeros((height, width, 4), dtype=np.uint8); rgba[rendered > 0] = (25, 240, 120, 205)
    overlay = Image.alpha_composite(overlay, Image.fromarray(rgba)); draw = ImageDraw.Draw(overlay, "RGBA")
    for x, y in POINTS:
        radius = max(15, width // 230); draw.ellipse((x-radius,y-radius,x+radius,y+radius), fill=(255,65,70,240), outline=(255,255,255,255), width=4)
    overlay.convert("RGB").save(args.output / "s_curve_traced_overlay.jpg", quality=94)
    payload = {"source": str(args.image.resolve()), "method": "anchor-guided minimum-cost path over brightness/saturation field", "representation": "skeleton/polyline, not object mask", "source_dimensions": [width, height], "downsample_scale": args.scale, "anchor_points_px": POINTS.tolist(), "skeleton_pixels_native": int((curve_native > 0).sum()), "production_modified": False}
    (args.output / "summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__": main()
