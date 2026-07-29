from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from tqdm import tqdm


Box = List[float]


# 注意：pixel_bbox 必须放最前面
# raw_bbox 是 DeepSeek 的 norm999 坐标，不适合直接画在 page.png 上
BBOX_KEYS = [
    "pixel_bbox",
    "bbox",
    "bbox_2d",
    "bbox_xyxy",
    "box",
    "coordinate",
    "coordinates",
    "xyxy",
    "rect",
    "region",
    "page_bbox",
    "page_box",
    "official_bbox",
    "det_bbox",
    "abs_bbox",
    "raw_bbox",
]


def find_page_index_from_path(path: Path) -> Optional[int]:
    candidates = [path.stem] + list(path.parts)

    for text in reversed(candidates):
        m = re.search(r"page[_\-]?(\d+)", text, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))

    return None


def infer_doc_id_from_page_dir(page_dir: Path, render_root: Path) -> str:
    rel = page_dir.relative_to(render_root)
    parts = rel.parts

    for i, part in enumerate(parts):
        if re.fullmatch(r"page[_\-]?\d+", part, flags=re.IGNORECASE):
            if i > 0:
                return Path(parts[i - 1]).stem

    if len(parts) >= 1:
        return Path(parts[0]).stem

    return "__default__"


def collect_page_dirs(render_root: Path) -> List[Tuple[str, int, Path, Path]]:
    """
    返回：
      doc_id, page_index, page_dir, page_png
    """
    out: List[Tuple[str, int, Path, Path]] = []

    for page_dir in render_root.rglob("page_*"):
        if not page_dir.is_dir():
            continue

        page_index = find_page_index_from_path(page_dir)
        if page_index is None:
            continue

        page_png = page_dir / "page.png"
        if not page_png.exists():
            continue

        doc_id = infer_doc_id_from_page_dir(page_dir, render_root)
        out.append((doc_id, page_index, page_dir, page_png))

    out.sort(key=lambda x: (x[0], x[1]))
    return out


def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def is_box_list(x: Any) -> bool:
    return (
        isinstance(x, list)
        and len(x) >= 4
        and all(is_number(v) for v in x[:4])
    )


def normalize_box_candidate(x: Any) -> Optional[Any]:
    if is_box_list(x):
        return x[:4]

    if isinstance(x, dict):
        if all(k in x for k in ["x1", "y1", "x2", "y2"]):
            return [x["x1"], x["y1"], x["x2"], x["y2"]]

        if all(k in x for k in ["xmin", "ymin", "xmax", "ymax"]):
            return [x["xmin"], x["ymin"], x["xmax"], x["ymax"]]

        if all(k in x for k in ["left", "top", "right", "bottom"]):
            return [x["left"], x["top"], x["right"], x["bottom"]]

        if all(k in x for k in ["x", "y", "w", "h"]):
            return [x["x"], x["y"], x["x"] + x["w"], x["y"] + x["h"]]

        if all(k in x for k in ["x", "y", "width", "height"]):
            return [x["x"], x["y"], x["x"] + x["width"], x["y"] + x["height"]]

    return None


def normalize_box(box: Any, page_size: Tuple[int, int]) -> Optional[Box]:
    if box is None:
        return None

    box = normalize_box_candidate(box)
    if box is None:
        return None

    w, h = page_size
    x1, y1, x2, y2 = [float(v) for v in box[:4]]

    # 兼容 normalized bbox，例如 [0.1, 0.2, 0.5, 0.8]
    if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
        x1, x2 = x1 * w, x2 * w
        y1, y2 = y1 * h, y2 * h

    # 如果看起来是 xywh，就转成 xyxy
    if x2 <= x1 or y2 <= y1:
        if x2 > 0 and y2 > 0:
            x2 = x1 + x2
            y2 = y1 + y2

    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1

    x1 = max(0.0, min(float(w), x1))
    y1 = max(0.0, min(float(h), y1))
    x2 = max(0.0, min(float(w), x2))
    y2 = max(0.0, min(float(h), y2))

    if x2 <= x1 or y2 <= y1:
        return None

    area = (x2 - x1) * (y2 - y1)
    if area < 4:
        return None

    return [x1, y1, x2, y2]


def get_label(obj: Dict[str, Any], default: str = "unknown") -> str:
    for key in [
        "label",
        "type",
        "category",
        "class",
        "block_type",
        "layout_type",
        "tag",
        "name",
        "kind",
        "role",
        "text",
    ]:
        if key in obj and obj[key] is not None:
            value = str(obj[key])
            if len(value) <= 40:
                return value
            return default
    return default


def get_score(obj: Dict[str, Any]) -> Optional[float]:
    for key in ["score", "confidence", "prob"]:
        if key in obj and obj[key] is not None:
            try:
                return float(obj[key])
            except Exception:
                pass
    return None


def get_text(obj: Dict[str, Any]) -> str:
    for key in ["content", "html", "markdown", "md", "raw_text", "raw_match_repr"]:
        if key in obj and obj[key] is not None:
            return str(obj[key]).replace("\n", " ").strip()
    return ""


def find_box_in_obj(obj: Dict[str, Any]) -> Optional[Any]:
    # 优先按 BBOX_KEYS 顺序找，pixel_bbox 会先于 raw_bbox 被使用
    for key in BBOX_KEYS:
        if key in obj:
            box = normalize_box_candidate(obj[key])
            if box is not None:
                return box

    # 有些结构可能包在 position / geometry 里
    for key in ["position", "location", "geometry", "box_info"]:
        if key in obj and isinstance(obj[key], dict):
            nested = find_box_in_obj(obj[key])
            if nested is not None:
                return nested

    # polygon / points
    for key in ["polygon", "points"]:
        if key in obj and isinstance(obj[key], list):
            pts = []
            for p in obj[key]:
                if (
                    isinstance(p, list)
                    and len(p) >= 2
                    and is_number(p[0])
                    and is_number(p[1])
                ):
                    pts.append((float(p[0]), float(p[1])))

            if pts:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                return [min(xs), min(ys), max(xs), max(ys)]

    # 直接在 obj 上的 x1/y1/x2/y2 等格式
    direct = normalize_box_candidate(obj)
    if direct is not None:
        return direct

    return None


def extract_boxes_recursive(
    data: Any,
    page_size: Tuple[int, int],
    default_label: str = "unknown",
) -> List[Dict[str, Any]]:
    boxes: List[Dict[str, Any]] = []
    seen = set()

    def add_box(raw_box: Any, obj: Dict[str, Any], parent_label: str) -> None:
        box = normalize_box(raw_box, page_size)
        if box is None:
            return

        label = get_label(obj, default=parent_label)
        dedup_key = (tuple(round(v, 2) for v in box), label)

        if dedup_key in seen:
            return

        seen.add(dedup_key)

        boxes.append(
            {
                "bbox": box,
                "label": label,
                "score": get_score(obj),
                "text": get_text(obj),
            }
        )

    def visit(obj: Any, parent_label: str = default_label) -> None:
        if isinstance(obj, dict):
            raw_box = find_box_in_obj(obj)
            if raw_box is not None:
                add_box(raw_box, obj, parent_label)

            next_label = get_label(obj, default=parent_label)

            for v in obj.values():
                visit(v, parent_label=next_label)

        elif isinstance(obj, list):
            # 如果这个 list 本身就是 bbox，不递归
            if is_box_list(obj):
                return

            for item in obj:
                visit(item, parent_label=parent_label)

    visit(data)
    return boxes


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_parsing_boxes(
    page_dir: Path,
    page_size: Tuple[int, int],
    parsing_json_names: List[str],
) -> Tuple[List[Dict[str, Any]], Optional[Path]]:
    for name in parsing_json_names:
        p = page_dir / name
        if not p.exists():
            continue

        try:
            data = load_json(p)
            boxes = extract_boxes_recursive(
                data=data,
                page_size=page_size,
                default_label="parse",
            )
            return boxes, p
        except Exception as e:
            print(f"[WARN] failed to read parsing json {p}: {e}")

    return [], None


def load_layout_boxes(
    layout_root: Path,
    doc_id: str,
    page_index: int,
    page_size: Tuple[int, int],
) -> Tuple[List[Dict[str, Any]], Optional[Path]]:
    candidates = [
        layout_root / doc_id / f"page_{page_index:04d}.json",
        layout_root / doc_id / f"page_{page_index:03d}.json",
        layout_root / doc_id / f"page_{page_index}.json",
        layout_root / f"{doc_id}_page_{page_index:04d}.json",
        layout_root / f"page_{page_index:04d}.json",
    ]

    for p in candidates:
        if not p.exists():
            continue

        try:
            data = load_json(p)

            if isinstance(data, dict) and isinstance(data.get("boxes"), list):
                boxes = extract_boxes_recursive(
                    data=data["boxes"],
                    page_size=page_size,
                    default_label="layout",
                )
            else:
                boxes = extract_boxes_recursive(
                    data=data,
                    page_size=page_size,
                    default_label="layout",
                )

            return boxes, p
        except Exception as e:
            print(f"[WARN] failed to read layout json {p}: {e}")

    return [], None


def short_text(text: str, max_len: int = 28) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def draw_boxes(
    draw: ImageDraw.ImageDraw,
    boxes: List[Dict[str, Any]],
    color: str,
    width: int,
    prefix: str,
    draw_labels: bool,
    font: Optional[ImageFont.ImageFont],
    max_label_chars: int,
) -> None:
    for i, item in enumerate(boxes):
        x1, y1, x2, y2 = item["bbox"]

        draw.rectangle([x1, y1, x2, y2], outline=color, width=width)

        if not draw_labels:
            continue

        label = str(item.get("label", "unknown"))
        score = item.get("score", None)

        if score is not None:
            tag = f"{prefix}{i}:{label} {score:.2f}"
        else:
            tag = f"{prefix}{i}:{label}"

        tag = short_text(tag, max_label_chars)

        tx = x1
        ty = max(0, y1 - 14)

        try:
            text_bbox = draw.textbbox((tx, ty), tag, font=font)
            draw.rectangle(text_bbox, fill="white")
        except Exception:
            pass

        draw.text((tx, ty), tag, fill=color, font=font)


def draw_legend(
    draw: ImageDraw.ImageDraw,
    font: Optional[ImageFont.ImageFont],
    parsing_count: int,
    layout_count: int,
    parsing_json: Optional[Path],
    layout_json: Optional[Path],
) -> None:
    lines = [
        "RED = DeepSeekOCR2 parsing pixel_bbox",
        "BLUE = PP-DocLayout-L layout bbox",
        f"parsing boxes: {parsing_count}",
        f"layout boxes: {layout_count}",
        f"parse: {parsing_json.name if parsing_json else 'NOT FOUND'}",
        f"layout: {layout_json.name if layout_json else 'NOT FOUND'}",
    ]

    x, y = 20, 20
    line_h = 18

    for line in lines:
        try:
            text_bbox = draw.textbbox((x, y), line, font=font)
            draw.rectangle(text_bbox, fill="white")
        except Exception:
            pass

        draw.text((x, y), line, fill="black", font=font)
        y += line_h


def visualize_one_page(
    page_png: Path,
    parsing_boxes: List[Dict[str, Any]],
    layout_boxes: List[Dict[str, Any]],
    out_path: Path,
    parsing_json: Optional[Path],
    layout_json: Optional[Path],
    draw_labels: bool = True,
    max_label_chars: int = 32,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.open(page_png).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    # 先画 layout 粗框：蓝色
    draw_boxes(
        draw=draw,
        boxes=layout_boxes,
        color="blue",
        width=5,
        prefix="L",
        draw_labels=draw_labels,
        font=font,
        max_label_chars=max_label_chars,
    )

    # 再画 parsing 细框：红色，保证红框在最上面
    draw_boxes(
        draw=draw,
        boxes=parsing_boxes,
        color="red",
        width=2,
        prefix="P",
        draw_labels=draw_labels,
        font=font,
        max_label_chars=max_label_chars,
    )

    draw_legend(
        draw=draw,
        font=font,
        parsing_count=len(parsing_boxes),
        layout_count=len(layout_boxes),
        parsing_json=parsing_json,
        layout_json=layout_json,
    )

    img.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--render-root",
        default="output/render_result",
        help="DeepSeekOCR2 render_result 根目录",
    )
    parser.add_argument(
        "--layout-root",
        default="data/layout_detection",
        help="PP-DocLayout-L layout JSON 根目录",
    )
    parser.add_argument(
        "--output-root",
        default="output/layout_compare_vis",
        help="对比可视化输出目录",
    )
    parser.add_argument(
        "--parsing-json",
        nargs="+",
        default=["bbox_items_official.json", "bbox_items.json"],
        help="优先读取的 parsing bbox json 文件名",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="只处理前 N 页",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
    )
    parser.add_argument(
        "--no-labels",
        action="store_true",
        help="只画框，不画标签文字",
    )
    parser.add_argument(
        "--max-label-chars",
        type=int,
        default=32,
    )

    args = parser.parse_args()

    render_root = Path(args.render_root)
    layout_root = Path(args.layout_root)
    output_root = Path(args.output_root)

    if not render_root.exists():
        raise FileNotFoundError(f"render-root not found: {render_root}")

    page_items = collect_page_dirs(render_root)

    if args.limit is not None:
        page_items = page_items[: args.limit]

    print(f"[INFO] found {len(page_items)} page dirs under {render_root}")

    if not page_items:
        print("[WARN] no page dirs found.")
        print("[WARN] Expected: output/render_result/<doc_id>/page_0001/page.png")
        return

    report: List[Dict[str, Any]] = []

    for doc_id, page_index, page_dir, page_png in tqdm(
        page_items,
        desc="compare vis",
    ):
        out_path = output_root / doc_id / f"page_{page_index:04d}.jpg"

        if args.skip_existing and out_path.exists():
            continue

        with Image.open(page_png) as img:
            page_size = img.size

        parsing_boxes, parsing_json = load_parsing_boxes(
            page_dir=page_dir,
            page_size=page_size,
            parsing_json_names=args.parsing_json,
        )

        layout_boxes, layout_json = load_layout_boxes(
            layout_root=layout_root,
            doc_id=doc_id,
            page_index=page_index,
            page_size=page_size,
        )

        print(
            f"[PAGE] {doc_id} page_{page_index:04d} "
            f"parse={len(parsing_boxes)} "
            f"layout={len(layout_boxes)} "
            f"parse_json={parsing_json.name if parsing_json else None} "
            f"layout_json={layout_json.name if layout_json else None}"
        )

        visualize_one_page(
            page_png=page_png,
            parsing_boxes=parsing_boxes,
            layout_boxes=layout_boxes,
            out_path=out_path,
            parsing_json=parsing_json,
            layout_json=layout_json,
            draw_labels=not args.no_labels,
            max_label_chars=args.max_label_chars,
        )

        report.append(
            {
                "doc_id": doc_id,
                "page_index": page_index,
                "page_png": str(page_png),
                "parsing_json": str(parsing_json) if parsing_json else None,
                "layout_json": str(layout_json) if layout_json else None,
                "output": str(out_path),
                "num_parsing_boxes": len(parsing_boxes),
                "num_layout_boxes": len(layout_boxes),
            }
        )

    output_root.mkdir(parents=True, exist_ok=True)
    report_path = output_root / "layout_compare_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[OK] compare visualization saved under: {output_root}")
    print(f"[OK] report saved to: {report_path}")


if __name__ == "__main__":
    main()