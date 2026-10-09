#!/usr/bin/env python3
"""Diagnostic only: use sparse point prompts to test SAM on the S-scale curve.

The points are not production annotations.  They establish whether an object
mask model can represent this thin connected diagram element at all, without
using the inaccurate VLM group bbox as a hard boundary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw
from segment_anything import SamPredictor, sam_model_registry


# Points sampled from visible, unoccluded portions of the white scale curve.
# They deliberately cover both turns and endpoints, not any Qwen bbox.
POSITIVE_POINTS = np.array([
    [5050, 210], [3960, 720], [2680, 1380], [1820, 2460],
    [2350, 3630], [3650, 4540], [3280, 5710], [1740, 6940], [690, 7490],
], dtype=np.float32)


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--image", type=Path, required=True); ap.add_argument("--checkpoint", type=Path, required=True); ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    image = np.asarray(Image.open(args.image).convert("RGB")); height, width = image.shape[:2]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = sam_model_registry["vit_b"](checkpoint=str(args.checkpoint)); model.to(device=device); model.eval()
    predictor = SamPredictor(model); predictor.set_image(image)
    masks, scores, logits = predictor.predict(point_coords=POSITIVE_POINTS, point_labels=np.ones(len(POSITIVE_POINTS), dtype=np.int32), multimask_output=True)
    chosen = int(np.argmax(scores)); mask = masks[chosen]
    Image.fromarray((mask * 255).astype(np.uint8)).save(args.output / "s_curve_prompted_sam_mask.png")
    overlay = Image.fromarray(image).convert("RGBA")
    color = np.zeros((height, width, 4), dtype=np.uint8); color[mask] = (30, 224, 180, 105)
    overlay = Image.alpha_composite(overlay, Image.fromarray(color))
    draw = ImageDraw.Draw(overlay, "RGBA")
    for x, y in POSITIVE_POINTS:
        radius = max(15, width // 230); draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=(255, 60, 70, 240), outline=(255,255,255,255), width=4)
    overlay.convert("RGB").save(args.output / "s_curve_prompted_sam_overlay.jpg", quality=94)
    payload = {"source": str(args.image.resolve()), "source_dimensions": [width, height], "prompt_type": "manual sparse positive points for diagnostic only", "point_count": len(POSITIVE_POINTS), "positive_points_px": POSITIVE_POINTS.tolist(), "mask_area_pixels": int(mask.sum()), "sam_scores": [round(float(x), 5) for x in scores], "selected_mask": chosen, "production_modified": False}
    (args.output / "summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__": main()
