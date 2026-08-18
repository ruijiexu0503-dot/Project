from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2


def _page_id(path: Path) -> str:
    return path.stem


def main():
    parser = argparse.ArgumentParser(description="Run RoDLA on split magazine page images and export normalized detections")
    parser.add_argument("--images", required=True, help="Directory containing split page PNG/JPG files")
    parser.add_argument("--config", required=True, help="RoDLA/MMDetection config file")
    parser.add_argument("--checkpoint", required=True, help="RoDLA checkpoint")
    parser.add_argument("--output", required=True, help="Output JSONL path")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--score-threshold", type=float, default=0.20)
    args = parser.parse_args()

    # Import only inside main so this script does not affect the normal EvidenceNet environment.
    from mmdet.apis import inference_detector, init_detector

    model = init_detector(args.config, args.checkpoint, device=args.device)
    class_names = list(getattr(model, "CLASSES", []) or [])

    image_root = Path(args.images)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    images = sorted(
        [p for p in image_root.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    )

    with output.open("w", encoding="utf-8") as handle:
        for index, image_path in enumerate(images, 1):
            image = cv2.imread(str(image_path))
            if image is None:
                raise RuntimeError(f"Unable to read image: {image_path}")
            height, width = image.shape[:2]
            result = inference_detector(model, str(image_path))
            # Some MMDetection models return (bbox_result, segm_result).
            bbox_result = result[0] if isinstance(result, tuple) else result

            detections = []
            for label_id, rows in enumerate(bbox_result):
                label_name = class_names[label_id] if label_id < len(class_names) else str(label_id)
                for row in rows:
                    values = [float(v) for v in row.tolist()]
                    if len(values) < 5:
                        continue
                    x1, y1, x2, y2, score = values[:5]
                    if score < args.score_threshold:
                        continue
                    detections.append({
                        "label_id": label_id,
                        "label": label_name,
                        "score": score,
                        "bbox": [x1, y1, x2, y2],
                    })

            record = {
                "page": _page_id(image_path),
                "image": str(image_path),
                "width": width,
                "height": height,
                "detections": detections,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"[{index}/{len(images)}] {record['page']}: {len(detections)} detections", flush=True)

    print(json.dumps({
        "images": len(images),
        "output": str(output),
        "classes": class_names,
        "score_threshold": args.score_threshold,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
