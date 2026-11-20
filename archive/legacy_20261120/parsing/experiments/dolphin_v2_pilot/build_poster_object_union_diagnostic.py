#!/usr/bin/env python3
"""Show whether complementary SAM proposals recover one poster illustration.

This is a curated diagnostic, not an automatic object detector or ground truth.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--mask-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    # Native pixel coordinates, selected by visual inspection of the XRISM entry.
    box = (0, 5100, 1650, 6400)
    ids = ("SAM_0039", "SAM_0053")
    source = Image.open(args.source).convert("RGB").crop(box)
    source.save(args.output / "source_crop.jpg", quality=94)
    masks = []
    for mask_id in ids:
        mask = np.asarray(Image.open(args.mask_dir / f"{mask_id}.png").crop(box).convert("L")) > 0
        masks.append(mask)
        render(source, mask, args.output / f"{mask_id}_overlay.jpg")
    union = np.logical_or.reduce(masks)
    render(source, union, args.output / "union_overlay.jpg")
    Image.fromarray((union * 255).astype(np.uint8)).save(args.output / "union_mask.png")

    summary = {
        "object": "XRISM spacecraft illustration",
        "source_crop_xyxy": box,
        "member_mask_ids": ids,
        "member_pixels_in_crop": [int(mask.sum()) for mask in masks],
        "union_pixels_in_crop": int(union.sum()),
        "method": "manually selected union of existing automatic SAM masks",
        "ground_truth_available": False,
        "production_modified": False,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    cards = [
        ("Original", "source_crop.jpg"),
        ("SAM_0039: mainly spacecraft body", "SAM_0039_overlay.jpg"),
        ("SAM_0053: mainly solar panels", "SAM_0053_overlay.jpg"),
        ("Union: whole-object proposal", "union_overlay.jpg"),
    ]
    body = "\n".join(f"<figure><img src='{name}'><figcaption>{title}</figcaption></figure>" for title, name in cards)
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>XRISM object union diagnostic</title>
<style>body{{font:16px system-ui;margin:2rem;max-width:1400px}}main{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}}figure{{margin:0}}img{{width:100%;height:auto}}figcaption{{padding:.4rem 0}}</style></head>
<body><h1>XRISM spacecraft: combining two existing masks</h1><p>Green shows the selected mask pixels on the original poster crop. The mask IDs were chosen manually for this diagnostic; the union has no measured IoU against a human annotation.</p><main>{body}</main></body></html>"""
    (args.output / "report.html").write_text(html)


def render(source: Image.Image, mask: np.ndarray, target: Path) -> None:
    base = np.asarray(source, dtype=np.float32)
    color = np.array([30, 230, 110], dtype=np.float32)
    base[mask] = base[mask] * 0.52 + color * 0.48
    Image.fromarray(base.astype(np.uint8)).save(target, quality=93)


if __name__ == "__main__":
    main()
