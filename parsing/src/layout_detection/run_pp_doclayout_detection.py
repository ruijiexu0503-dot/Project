from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from tqdm import tqdm


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}

DEFAULT_EXCLUDE_KEYWORDS = [
    "result_with_boxes",
    "with_boxes",
    "bboxes_preview",
    "bbox_preview",
    "annotated",
    "vis",
    "visual",
    "crop",
    "cropped",
    "layout_vis",
    "bbox_vis",
]


def is_image_file(path: Path, allow_annotated: bool = False) -> bool:
    if path.suffix.lower() not in IMAGE_EXTS:
        return False

    if allow_annotated:
        return True

    name = path.name.lower()
    return not any(k in name for k in DEFAULT_EXCLUDE_KEYWORDS)


def get_image_size(path: Path) -> Tuple[int, int]:
    with Image.open(path) as img:
        return img.size


def find_page_index_from_path(path: Path) -> Optional[int]:
    candidates = [path.stem] + list(path.parts)

    for text in reversed(candidates):
        m = re.search(r"page[_\-]?(\d+)", text, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))

    return None


def infer_doc_id(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    parts = rel.parts

    for i, part in enumerate(parts):
        if re.fullmatch(r"page[_\-]?\d+", part, flags=re.IGNORECASE):
            if i > 0:
                return Path(parts[i - 1]).stem
            return "__default__"

    if len(parts) >= 2:
        return Path(parts[0]).stem

    return "__default__"


def collect_page_images(
    image_root: Path,
    allow_annotated: bool = False,
    min_side: int = 500,
) -> List[Tuple[str, int, Path, Tuple[int, int]]]:
    """
    只优先选择：
        output/render_result/<doc_id>/page_0001/page.png

    避免误选：
        bboxes_preview.jpg
        result_with_boxes.jpg
        images/*.jpg
        crop images
    """
    selected: List[Tuple[str, int, Path, Tuple[int, int]]] = []

    # 第一优先级：严格找 page_xxxx/page.png
    for page_dir in image_root.rglob("page_*"):
        if not page_dir.is_dir():
            continue

        page_index = find_page_index_from_path(page_dir)
        if page_index is None:
            continue

        page_img = page_dir / "page.png"
        if not page_img.exists():
            continue

        try:
            size = get_image_size(page_img)
        except Exception:
            continue

        w, h = size

        if w < min_side or h < min_side:
            continue

        doc_id = infer_doc_id(page_img, image_root)
        selected.append((doc_id, page_index, page_img, size))

    selected.sort(key=lambda x: (x[0], x[1]))

    if selected:
        return selected

    # fallback：如果真的没有 page.png，才允许递归找普通图片
    # 正常情况下你的项目不会走到这里。
    candidates: Dict[Tuple[str, int], List[Tuple[Path, Tuple[int, int]]]] = {}

    for path in image_root.rglob("*"):
        if not path.is_file():
            continue

        if "images" in path.parts:
            continue

        if not is_image_file(path, allow_annotated=allow_annotated):
            continue

        page_index = find_page_index_from_path(path)
        if page_index is None:
            continue

        doc_id = infer_doc_id(path, image_root)

        try:
            size = get_image_size(path)
        except Exception:
            continue

        w, h = size

        if w < min_side or h < min_side:
            continue

        candidates.setdefault((doc_id, page_index), []).append((path, size))

    fallback_selected: List[Tuple[str, int, Path, Tuple[int, int]]] = []

    for (doc_id, page_index), items in candidates.items():
        items = sorted(items, key=lambda x: x[1][0] * x[1][1], reverse=True)
        best_path, best_size = items[0]
        fallback_selected.append((doc_id, page_index, best_path, best_size))

    fallback_selected.sort(key=lambda x: (x[0], x[1]))
    return fallback_selected


def label_group(label: str) -> str:
    label = str(label).lower()

    if "table" in label:
        return "table"

    if any(k in label for k in ["figure", "image", "chart", "diagram", "plot"]):
        return "figure"

    if any(k in label for k in ["formula", "equation"]):
        return "formula"

    if "caption" in label:
        return "caption"

    if any(
        k in label
        for k in [
            "title",
            "header",
            "footer",
            "text",
            "abstract",
            "reference",
            "footnote",
            "aside",
            "paragraph",
        ]
    ):
        return "text"

    return "unknown"


def get_result_dict(res: Any) -> Dict[str, Any]:
    """
    PaddleOCR Result 对象不同版本略有差异。
    优先读 .json；不行就临时 save_to_json 再读。
    """
    if isinstance(res, dict):
        data = res
    elif hasattr(res, "json"):
        data = res.json
    else:
        data = None

    if isinstance(data, str):
        data = json.loads(data)

    if isinstance(data, dict):
        return data

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        res.save_to_json(save_path=str(tmp))
        json_files = list(tmp.rglob("*.json"))

        if not json_files:
            raise RuntimeError("Cannot extract json from PaddleOCR result.")

        return json.loads(json_files[0].read_text(encoding="utf-8"))


def extract_boxes_from_paddle_result(res: Any) -> List[Dict[str, Any]]:
    data = get_result_dict(res)

    if "res" in data and isinstance(data["res"], dict):
        data = data["res"]

    raw_boxes = data.get("boxes", [])

    boxes: List[Dict[str, Any]] = []

    for i, b in enumerate(raw_boxes):
        if not isinstance(b, dict):
            continue

        coord = b.get("coordinate") or b.get("bbox") or b.get("box")

        if coord is None or len(coord) < 4:
            continue

        x1, y1, x2, y2 = [float(v) for v in coord[:4]]

        if x2 <= x1 or y2 <= y1:
            continue

        label = str(b.get("label", "unknown"))
        score = float(b.get("score", 1.0))
        cls_id = b.get("cls_id", b.get("class_id", None))

        boxes.append(
            {
                "layout_id": f"layout_{i:03d}",
                "bbox": [
                    round(x1, 2),
                    round(y1, 2),
                    round(x2, 2),
                    round(y2, 2),
                ],
                "label": label,
                "label_group": label_group(label),
                "score": round(score, 6),
                "class_id": cls_id,
            }
        )

    boxes.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))

    for i, b in enumerate(boxes):
        b["layout_id"] = f"layout_{i:03d}"

    return boxes


def save_layout_json(
    output_path: Path,
    doc_id: str,
    page_index: int,
    image_path: Path,
    page_size: Tuple[int, int],
    boxes: List[Dict[str, Any]],
    model_name: str,
    model_dir: Optional[str],
    device: str,
    threshold: Optional[float],
    layout_nms: bool,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    page_width, page_height = page_size

    data = {
        "doc_id": doc_id,
        "page_index": page_index,
        "page_width": page_width,
        "page_height": page_height,
        "image_path": str(image_path),
        "model_name": model_name,
        "model_dir": model_dir,
        "device": device,
        "threshold": threshold,
        "layout_nms": layout_nms,
        "boxes": boxes,
    }

    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def draw_visualization(
    image_path: Path,
    boxes: List[Dict[str, Any]],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for b in boxes:
        x1, y1, x2, y2 = b["bbox"]
        label = b["label"]
        score = b["score"]

        # 蓝色：PP-DocLayout-L 检测到的 layout 区域
        draw.rectangle([x1, y1, x2, y2], outline="blue", width=4)

        text = f"{label} {score:.2f}"
        draw.text(
            (x1, max(0, y1 - 14)),
            text,
            fill="blue",
            font=font,
        )

    img.save(output_path)


def build_predict_kwargs(args: argparse.Namespace) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}

    if args.batch_size is not None:
        kwargs["batch_size"] = args.batch_size

    if args.threshold is not None:
        kwargs["threshold"] = args.threshold

    if args.layout_nms:
        kwargs["layout_nms"] = True

    if args.layout_merge_bboxes_mode is not None:
        kwargs["layout_merge_bboxes_mode"] = args.layout_merge_bboxes_mode

    return kwargs


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--image-root",
        required=True,
        help="已经 render 好的一页一页 page image 的根目录，例如 output/render_result",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="layout JSON 输出目录，例如 data/layout_detection",
    )
    parser.add_argument(
        "--vis-root",
        default=None,
        help="可选：layout detection 可视化输出目录，例如 output/layout_detection_vis",
    )
    parser.add_argument(
        "--model-name",
        default="PP-DocLayout-L",
        help="默认 PP-DocLayout-L",
    )
    parser.add_argument(
        "--model-dir",
        default=None,
        help="本地模型目录，例如 external/models/PP-DocLayout-L",
    )
    parser.add_argument(
        "--device",
        default="gpu:0",
        help='例如 "gpu:0" 或 "cpu"',
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="过滤低置信度预测。None 表示使用模型默认值。",
    )
    parser.add_argument(
        "--layout-nms",
        action="store_true",
        help="开启 layout NMS。建议开启。",
    )
    parser.add_argument(
        "--layout-merge-bboxes-mode",
        default=None,
        choices=["large", "small", "union"],
        help="重叠框合并策略。默认不设置。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 页，调试用。",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="已经存在的 page json 直接跳过。",
    )
    parser.add_argument(
        "--allow-annotated",
        action="store_true",
        help="允许 fallback 使用 result_with_boxes / annotated 图片。正式不建议。",
    )
    parser.add_argument(
        "--min-side",
        type=int,
        default=500,
        help="过滤太小的图片，默认短边至少 500。",
    )

    args = parser.parse_args()

    image_root = Path(args.image_root)
    output_root = Path(args.output_root)
    vis_root = Path(args.vis_root) if args.vis_root else None

    if not image_root.exists():
        raise FileNotFoundError(f"image-root not found: {image_root}")

    page_images = collect_page_images(
        image_root=image_root,
        allow_annotated=args.allow_annotated,
        min_side=args.min_side,
    )

    if args.limit is not None:
        page_images = page_images[: args.limit]

    print(f"[INFO] image_root = {image_root}")
    print(f"[INFO] found {len(page_images)} page images")

    if not page_images:
        print("[WARN] 没找到 page image。")
        print("[WARN] 你的目标结构应该类似：")
        print("[WARN] output/render_result/<doc_id>/page_0001/page.png")
        print("[WARN] 请检查：")
        print("[WARN] find output/render_result -maxdepth 4 -type f -name 'page.png' | head -20")
        return

    print("[INFO] first few selected page images:")
    for item in page_images[:10]:
        doc_id, page_index, image_path, page_size = item
        print(f"  - {doc_id} page_{page_index:04d} {page_size}: {image_path}")

    # 注意：这里会 import paddle，所以必须在 GPU node / slurm 里运行
    from paddleocr import LayoutDetection

    model_kwargs: Dict[str, Any] = {
        "model_name": args.model_name,
        "device": args.device,
    }

    if args.model_dir is not None:
        model_kwargs["model_dir"] = args.model_dir

    if args.threshold is not None:
        model_kwargs["threshold"] = args.threshold

    if args.layout_nms:
        model_kwargs["layout_nms"] = True

    if args.layout_merge_bboxes_mode is not None:
        model_kwargs["layout_merge_bboxes_mode"] = args.layout_merge_bboxes_mode

    print(f"[INFO] loading LayoutDetection with: {model_kwargs}")
    model = LayoutDetection(**model_kwargs)

    predict_kwargs = build_predict_kwargs(args)

    report: List[Dict[str, Any]] = []

    for doc_id, page_index, image_path, page_size in tqdm(
        page_images,
        desc="layout detection",
    ):
        out_json = output_root / doc_id / f"page_{page_index:04d}.json"

        if args.skip_existing and out_json.exists():
            report.append(
                {
                    "doc_id": doc_id,
                    "page_index": page_index,
                    "image_path": str(image_path),
                    "layout_json": str(out_json),
                    "status": "skipped_existing",
                }
            )
            continue

        try:
            outputs = model.predict(str(image_path), **predict_kwargs)
            outputs = list(outputs)

            if len(outputs) == 0:
                boxes: List[Dict[str, Any]] = []
            else:
                boxes = extract_boxes_from_paddle_result(outputs[0])

            save_layout_json(
                output_path=out_json,
                doc_id=doc_id,
                page_index=page_index,
                image_path=image_path,
                page_size=page_size,
                boxes=boxes,
                model_name=args.model_name,
                model_dir=args.model_dir,
                device=args.device,
                threshold=args.threshold,
                layout_nms=args.layout_nms,
            )

            if vis_root is not None:
                vis_path = vis_root / doc_id / f"page_{page_index:04d}.jpg"
                draw_visualization(image_path, boxes, vis_path)

            report.append(
                {
                    "doc_id": doc_id,
                    "page_index": page_index,
                    "image_path": str(image_path),
                    "layout_json": str(out_json),
                    "num_boxes": len(boxes),
                    "status": "ok",
                }
            )

        except Exception as e:
            print(f"[ERROR] {doc_id} page_{page_index:04d}: {e}")
            report.append(
                {
                    "doc_id": doc_id,
                    "page_index": page_index,
                    "image_path": str(image_path),
                    "status": "error",
                    "error": str(e),
                }
            )

    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "layout_detection_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[OK] layout JSON saved under: {output_root}")
    print(f"[OK] report saved to: {report_path}")

    if vis_root is not None:
        print(f"[OK] visualization saved under: {vis_root}")


if __name__ == "__main__":
    main()