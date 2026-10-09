#!/usr/bin/env python3
"""Prepare page images while splitting only landscape (spread-like) pages.

Portrait pages are copied unchanged; landscape pages are split at their
normalized center. This is a generic mixed-orientation preparatory stage and
does not use document names, text, or fixed pixel coordinates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--document-id", required=True)
    ap.add_argument("--aspect-threshold", type=float, default=1.15)
    args = ap.parse_args()
    src = args.input / "pages"
    out = args.output / args.document_id / "pages"
    out.mkdir(parents=True, exist_ok=True)
    records = []
    output_index = 0
    for image_path in sorted(src.iterdir()):
        if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}:
            continue
        with Image.open(image_path) as im:
            width, height = im.size
            is_spread = width / height >= args.aspect_threshold
            crops = [("full", (0, 0, width, height))]
            if is_spread:
                split_x = round(width / 2)
                crops = [("left", (0, 0, split_x, height)), ("right", (split_x, 0, width, height))]
            for side, box in crops:
                output_index += 1
                target = out / f"page_{output_index:06d}.png"
                im.crop(box).save(target)
                records.append({"output_page_index": output_index - 1,
                                "source_file": str(image_path), "source_page": image_path.stem,
                                "side": side, "bbox": list(box), "width": box[2] - box[0], "height": box[3] - box[1]})
    manifest = {"document_id": args.document_id, "method": "mixed_orientation_center_split",
                "aspect_threshold": args.aspect_threshold, "source_page_count": len({r["source_page"] for r in records}),
                "output_page_count": len(records), "pages": records}
    (args.output / args.document_id).mkdir(parents=True, exist_ok=True)
    (args.output / args.document_id / "split_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("document_id", "method", "source_page_count", "output_page_count")}, indent=2))


if __name__ == "__main__":
    main()
