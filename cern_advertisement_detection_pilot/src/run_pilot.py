from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

from utils import collect_page_images
from transdlanet_adapter import TransDLANetAdapter


def page_area(bbox: List[float]) -> float:
    x1, y1, x2, y2 = bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def compute_page_label(detections: List[Dict[str, Any]], page_size: Tuple[int, int], ad_classes: List[str], ad_conf_threshold: float = 0.5) -> str:
    W, H = page_size
    page_area_total = W * H

    ad_dets = [d for d in detections if (d.get("class") in ad_classes and d.get("confidence", 0.0) >= ad_conf_threshold)]

    if not ad_dets:
        return "NO_AD"

    # compute max coverage
    max_cov = 0.0
    for d in ad_dets:
        bbox = d.get("bbox")
        if not bbox:
            continue
        cov = page_area(bbox) / page_area_total
        max_cov = max(max_cov, cov)

    if max_cov >= 0.9:
        return "FULL_PAGE_AD"

    # partial if significant ad area exists
    if any((page_area(d.get("bbox", [0,0,0,0])) / page_area_total) >= 0.05 for d in ad_dets):
        return "PARTIAL_AD"

    # otherwise uncertain
    return "UNCERTAIN"


def draw_detections(image_path: Path, detections: List[Dict[str, Any]], out_path: Path, ad_classes: List[str]):
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for d in detections:
        bbox = d.get("bbox")
        if not bbox:
            continue
        x1, y1, x2, y2 = bbox
        cls = d.get("class") or "?"
        score = d.get("confidence", 0.0)

        color = "red" if cls in ad_classes else "blue"
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
        text = f"{cls} {score:.2f}"
        draw.text((x1, max(0, y1 - 12)), text, fill=color, font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def build_contact_sheet(items: List[Dict[str, Any]], out_html: Path):
    out_html.parent.mkdir(parents=True, exist_ok=True)
    lines = ["<html><head><meta charset=\"utf-8\"></head><body>"]
    for it in items:
        vis = it["vis_path"]
        doc = it["doc_id"]
        page = it["page_index"]
        label = it["page_label"]
        lines.append(f"<div style='margin:8px;display:inline-block'>")
        lines.append(f"<div>{doc} page_{page:04d} {label}</div>")
        lines.append(f"<img src=\"{vis}\" style=\"width:360px;border:1px solid #ccc\"/>")
        lines.append("</div>")
    lines.append("</body></html>")
    out_html.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-root", default="../parsing/output/deepseekocr2_split_render/CERNCourier2022NovDec-digitaledition", help="root of split page images")
    parser.add_argument("--model-dir", default=None)
    parser.add_argument("--checkpoint", default="")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--output-root", default="../cern_advertisement_detection_pilot/outputs")
    parser.add_argument("--visual-root", default="../cern_advertisement_detection_pilot/visualizations")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ad-classes", nargs="*", default=["advertisement", "ad", "commercial"], help="class names to treat as advertisement (model-specific)")
    parser.add_argument("--ad-conf-threshold", type=float, default=0.5)
    args = parser.parse_args()

    image_root = Path(args.image_root).resolve()
    output_root = Path(args.output_root).resolve()
    visual_root = Path(args.visual_root).resolve()

    pages = collect_page_images(image_root)
    if not pages:
        raise RuntimeError(f"No page images found under: {image_root}")

    # sample representative pages by stratified sampling across document
    pages_by_index = sorted(pages, key=lambda x: x[1])
    total = len(pages_by_index)
    n = min(args.limit, total)
    random.seed(args.seed)
    # pick approximately evenly distributed indices
    indices = sorted({min(total-1, math.floor(i * total / n)) for i in range(n)})
    selected = [pages_by_index[i] for i in indices]

    adapter = TransDLANetAdapter(model_dir=Path(args.model_dir) if args.model_dir else None, checkpoint=args.checkpoint, device=args.device)
    adapter.load()

    predictions_path = Path("predictions.jsonl")
    predictions_path = Path("../cern_advertisement_detection_pilot/predictions.jsonl").resolve()
    out_items = []
    counts = {"FULL_PAGE_AD": 0, "PARTIAL_AD": 0, "NO_AD": 0, "UNCERTAIN": 0}

    with predictions_path.open("w", encoding="utf-8") as pf:
        for doc_id, page_index, image_path, page_size in selected:
            dets = adapter.predict(str(image_path))

            # normalize bbox to float list if needed
            norm_dets = []
            for d in dets:
                cls = d.get("class") or d.get("label") or d.get("category")
                score = float(d.get("confidence") or d.get("score") or 0.0)
                bbox = d.get("bbox")
                if bbox is None:
                    bbox = d.get("box")
                norm_dets.append({"class": cls, "confidence": score, "bbox": bbox, "mask": d.get("mask"), "raw": d.get("raw")})

            page_label = compute_page_label(norm_dets, page_size, args.ad_classes, args.ad_conf_threshold)
            counts[page_label] += 1

            rec = {
                "document": str(image_root),
                "source_pdf_page": f"page_{page_index:04d}",
                "split_side": "unknown",
                "split_page_id": f"{doc_id}_page_{page_index:04d}",
                "image_path": str(image_path),
                "page_label": page_label,
                "detections": [ {"class": d["class"], "confidence": d["confidence"], "bbox": d["bbox"], "mask": d.get("mask")} for d in norm_dets ],
            }

            pf.write(json.dumps(rec, ensure_ascii=False) + "\n")

            vis_path = visual_root / doc_id / f"page_{page_index:04d}.jpg"
            draw_detections(image_path, norm_dets, vis_path, args.ad_classes)

            out_items.append({"doc_id": doc_id, "page_index": page_index, "vis_path": str(vis_path), "page_label": page_label})

    # write contact sheet
    contact_html = Path("../cern_advertisement_detection_pilot/visualizations/index.html").resolve()
    build_contact_sheet(out_items, contact_html)

    # write summary
    summary = {
        "model_dir": str(args.model_dir),
        "checkpoint": args.checkpoint,
        "num_pages_tested": len(selected),
        "counts": counts,
        "predictions_path": str(predictions_path),
        "contact_html": str(contact_html),
    }

    summary_path = Path("../cern_advertisement_detection_pilot/summary.md").resolve()
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Pilot complete. Summary:")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
