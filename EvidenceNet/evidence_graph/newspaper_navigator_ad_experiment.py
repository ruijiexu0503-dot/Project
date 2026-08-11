from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .io_utils import read_jsonl, write_json, write_jsonl
from .non_llm_magazine_experiment import DOCS, _labels, _reference


ADVERTISEMENT_CLASS = "Advertisement"


def _metrics(scores: np.ndarray, labels: np.ndarray, threshold: float) -> dict:
    predicted = scores >= threshold
    true_positive = int(np.sum(predicted & labels))
    false_positive = int(np.sum(predicted & ~labels))
    false_negative = int(np.sum(~predicted & labels))
    precision = true_positive / max(1, true_positive + false_positive)
    recall = true_positive / max(1, true_positive + false_negative)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    return {
        "threshold": threshold,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _page_truth(nodes: list[dict], node_labels: np.ndarray) -> dict[str, dict]:
    page_labels: dict[str, list[bool]] = defaultdict(list)
    for node, label in zip(nodes, node_labels):
        for page in node.get("page_ids") or []:
            page_labels[page].append(bool(label))
    return {
        page: {"reference_has_commercial": any(labels),
               "reference_pure_commercial": bool(labels) and all(labels)}
        for page, labels in page_labels.items()
    }


def _draw_montage(rows: list[dict], page_paths: dict[str, Path], output: Path,
                  box_threshold: float = .10) -> None:
    selected = [row for row in rows if row["reference_commercial_items"] or
                row["max_ad_confidence"] >= .25]
    if not selected:
        return
    tile_width, tile_height, header = 256, 384, 42
    columns = 4
    rows_count = (len(selected) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * tile_width, rows_count * (tile_height + header)), "white")
    for index, row in enumerate(selected):
        image = Image.open(page_paths[row["page"]]).convert("RGB")
        scale = min(tile_width / image.width, tile_height / image.height)
        resized = image.resize((round(image.width * scale), round(image.height * scale)))
        draw = ImageDraw.Draw(resized)
        for box in row["advertisement_boxes"]:
            if box["confidence"] < box_threshold:
                continue
            xyxy = [round(value * scale) for value in box["xyxy"]]
            draw.rectangle(xyxy, outline=(230, 45, 45), width=3)
            draw.text((xyxy[0] + 2, xyxy[1] + 2), f'{box["confidence"]:.2f}',
                      fill=(230, 45, 45), stroke_width=2, stroke_fill="white")
        x = (index % columns) * tile_width
        y = (index // columns) * (tile_height + header)
        canvas.paste(resized, (x, y + header))
        label = (f'{row["page"]}  ref={row["reference_commercial_items"]} '
                 f'det@.10={row["ad_boxes_at_0_10"]}')
        ImageDraw.Draw(canvas).text((x + 4, y + 5), label, fill="black")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=88)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate a YOLO11 Newspaper Navigator/Beyond Words ad detector")
    parser.add_argument("--checkpoint", default="models/newspaper_navigator_yolov11/yolo11n.pt")
    parser.add_argument("--render-root", default="../parsing/output/deepseekocr2_split_render")
    parser.add_argument("--evidence-root", default="output/evidence_graph")
    parser.add_argument("--output-dir", default="output/newspaper_navigator_yolov11_experiment")
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--inference-confidence", type=float, default=.05)
    args = parser.parse_args()

    # Import lazily so the evaluation helpers remain importable without the optional runtime.
    from ultralytics import YOLO

    model = YOLO(args.checkpoint)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    all_rows = []
    for doc in DOCS:
        nodes = sorted(read_jsonl(Path(args.evidence_root) / doc / "evidence_nodes.jsonl"),
                       key=lambda row: row["document_order"])
        _, reference_tuples = _reference(doc, nodes)
        reference_rows, _ = _reference(doc, nodes)
        node_labels = _labels(reference_tuples, len(nodes))
        page_truth = _page_truth(nodes, node_labels)
        commercial_item_counts = Counter(
            row["source_page"] for row in reference_rows if row["kind"] == "commercial")

        page_paths = {
            path.parent.name: path
            for path in sorted((Path(args.render_root) / doc).glob("page_*/page.png"))
        }
        paths = [page_paths[page] for page in sorted(page_paths)]
        results = model.predict(
            [str(path) for path in paths], imgsz=args.image_size,
            conf=args.inference_confidence, device="cpu", verbose=False)
        rows = []
        for path, result in zip(paths, results):
            page = path.parent.name
            height, width = result.orig_shape
            boxes = []
            for xyxy, confidence, class_index in zip(
                    result.boxes.xyxy, result.boxes.conf, result.boxes.cls):
                class_name = model.names[int(class_index)]
                if class_name != ADVERTISEMENT_CLASS:
                    continue
                coordinates = [round(float(value), 2) for value in xyxy]
                box_area = max(0.0, coordinates[2] - coordinates[0]) * max(
                    0.0, coordinates[3] - coordinates[1])
                boxes.append({
                    "xyxy": coordinates,
                    "confidence": round(float(confidence), 6),
                    "page_area_fraction": round(box_area / (width * height), 6),
                })
            boxes.sort(key=lambda box: box["confidence"], reverse=True)
            truth = page_truth.get(page, {"reference_has_commercial": False,
                                          "reference_pure_commercial": False})
            row = {
                "doc_id": doc,
                "page": page,
                "width": width,
                "height": height,
                **truth,
                "reference_commercial_items": commercial_item_counts[page],
                "max_ad_confidence": boxes[0]["confidence"] if boxes else 0.0,
                "ad_boxes_at_0_10": sum(box["confidence"] >= .10 for box in boxes),
                "ad_boxes_at_0_25": sum(box["confidence"] >= .25 for box in boxes),
                "advertisement_boxes": boxes,
            }
            rows.append(row)
        scores = np.asarray([row["max_ad_confidence"] for row in rows])
        any_labels = np.asarray([row["reference_has_commercial"] for row in rows], dtype=bool)
        pure_labels = np.asarray([row["reference_pure_commercial"] for row in rows], dtype=bool)
        thresholds = (.10, .25, .50)
        count_pages = [row for row in rows if row["reference_commercial_items"]]
        count_at_10 = sum(row["ad_boxes_at_0_10"] == row["reference_commercial_items"]
                          for row in count_pages)
        report = {
            "doc_id": doc,
            "pages": len(rows),
            "reference_commercial_items": int(sum(commercial_item_counts.values())),
            "reference_pages_with_commercial": int(np.sum(any_labels)),
            "reference_pure_commercial_pages": int(np.sum(pure_labels)),
            "any_commercial_page_metrics": [_metrics(scores, any_labels, value) for value in thresholds],
            "pure_commercial_page_metrics": [_metrics(scores, pure_labels, value) for value in thresholds],
            "commercial_start_pages_with_exact_box_count_at_0_10": {
                "correct": count_at_10, "total": len(count_pages),
                "accuracy": round(count_at_10 / max(1, len(count_pages)), 4),
            },
        }
        doc_output = output / doc
        doc_output.mkdir(parents=True, exist_ok=True)
        write_jsonl(doc_output / "page_ad_detections.jsonl", rows)
        write_json(doc_output / "evaluation.json", report)
        _draw_montage(rows, page_paths, doc_output / "ad_detection_montage.jpg")
        reports.append(report)
        all_rows.extend(rows)
        print(json.dumps({"doc_id": doc, "pages": len(rows),
                          "ad_pages_at_0.25": int(np.sum(scores >= .25))}), flush=True)

    all_scores = np.asarray([row["max_ad_confidence"] for row in all_rows])
    all_any = np.asarray([row["reference_has_commercial"] for row in all_rows], dtype=bool)
    all_pure = np.asarray([row["reference_pure_commercial"] for row in all_rows], dtype=bool)
    comparison = {
        "method": "yolov11n_beyond_words_newspaper_navigator_ad_detector",
        "uses_llm_or_vlm": False,
        "checkpoint": args.checkpoint,
        "image_size": args.image_size,
        "inference_confidence": args.inference_confidence,
        "documents": reports,
        "combined": {
            "pages": len(all_rows),
            "any_commercial_page_metrics": [
                _metrics(all_scores, all_any, value) for value in (.10, .25, .50)],
            "pure_commercial_page_metrics": [
                _metrics(all_scores, all_pure, value) for value in (.10, .25, .50)],
        },
        "notes": [
            "This is a modern YOLO11 model trained on the same Beyond Words/Newspaper "
            "Navigator seven-class data, not the archived Detectron2 Faster R-CNN checkpoint.",
            "Reference labels are used only for evaluation; inference is fully non-LLM.",
            "The box-count diagnostic compares detections with the number of commercial items "
            "that begin on a page and is not a complete instance-detection ground truth.",
        ],
    }
    write_json(output / "comparison.json", comparison)
    print(json.dumps(comparison["combined"], indent=2))


if __name__ == "__main__":
    main()
