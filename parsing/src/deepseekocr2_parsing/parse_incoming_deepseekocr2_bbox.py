from pathlib import Path
import argparse
import json
import re
import traceback
import shutil
import ast
import importlib

import torch
from tqdm import tqdm
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF
from transformers import AutoModel, AutoTokenizer


DEFAULT_MODEL_NAME = "deepseek-ai/DeepSeek-OCR-2"

SUPPORTED_IMAGES = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"
}
SUPPORTED_DOCS = {".pdf"} | SUPPORTED_IMAGES

OFFICIAL_BBOX_JSON = "bbox_items_official.json"
OFFICIAL_MATCHES_RAW = "matches_ref_raw.txt"


def safe_name(path: Path) -> str:
    name = path.stem
    for ch in [" ", "/", "\\", ":", "*", "?", '"', "<", ">", "|"]:
        name = name.replace(ch, "_")
    return name


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def save_json(data, path: Path):
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_text(text: str, path: Path):
    ensure_dir(path.parent)
    path.write_text(text or "", encoding="utf-8")


def read_text_if_exists(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


def collect_input_files(incoming_dir: Path):
    files = []
    for p in sorted(incoming_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED_DOCS:
            files.append(p)
    return files


def page_no_from_name(path: Path):
    candidates = [path.stem] + list(path.parts)
    for text in reversed(candidates):
        m = re.search(r"page[_-]?(\d+)", text, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def collect_render_result_docs(render_root: Path, doc_id: str | None = None):
    docs = []

    for doc_dir in sorted(p for p in render_root.iterdir() if p.is_dir()):
        if doc_id and doc_dir.name != doc_id:
            continue

        page_records = []
        flat_pages_dir = doc_dir / "pages"

        if flat_pages_dir.is_dir():
            image_paths = sorted(
                p
                for p in flat_pages_dir.iterdir()
                if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGES
            )
            for image_path in image_paths:
                page_no = page_no_from_name(image_path)
                if page_no is None:
                    continue
                page_records.append({
                    "page_no": page_no,
                    "image_path": image_path,
                })
        else:
            for page_dir in sorted(p for p in doc_dir.glob("page_*") if p.is_dir()):
                page_no = page_no_from_name(page_dir)
                if page_no is None:
                    continue

                image_path = page_dir / "page.png"
                if not image_path.exists():
                    candidates = sorted(
                        p
                        for p in page_dir.iterdir()
                        if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGES
                    )
                    image_path = candidates[0] if candidates else None

                if image_path is None or not image_path.exists():
                    continue

                page_records.append({
                    "page_no": page_no,
                    "image_path": image_path,
                })

        page_records.sort(key=lambda x: x["page_no"])
        if page_records:
            docs.append({
                "doc_name": doc_dir.name,
                "source_dir": doc_dir,
                "pages": page_records,
            })

    return docs


def render_pdf_to_pages(pdf_path: Path, doc_out_dir: Path, dpi: int, overwrite: bool):
    pages = []

    pdf = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)

    for idx in range(len(pdf)):
        page_no = idx + 1
        page_dir = doc_out_dir / f"page_{page_no:04d}"
        ensure_dir(page_dir)

        image_path = page_dir / "page.png"

        if overwrite or not image_path.exists():
            page = pdf[idx]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(str(image_path))

        with Image.open(image_path) as img:
            width, height = img.size

        pages.append({
            "page_no": page_no,
            "page_dir": page_dir,
            "image_path": image_path,
            "width": width,
            "height": height,
        })

    pdf.close()
    return pages


def image_to_page(image_path: Path, doc_out_dir: Path, overwrite: bool):
    page_dir = doc_out_dir / "page_0001"
    ensure_dir(page_dir)

    out_image = page_dir / "page.png"

    if overwrite or not out_image.exists():
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            img.save(out_image)

    with Image.open(out_image) as img:
        width, height = img.size

    return [{
        "page_no": 1,
        "page_dir": page_dir,
        "image_path": out_image,
        "width": width,
        "height": height,
    }]


def rendered_images_to_pages(page_records, doc_out_dir: Path, overwrite: bool):
    pages = []

    for record in page_records:
        page_no = int(record["page_no"])
        source_image = Path(record["image_path"])
        page_dir = doc_out_dir / f"page_{page_no:04d}"
        ensure_dir(page_dir)

        out_image = page_dir / "page.png"
        if overwrite or not out_image.exists():
            with Image.open(source_image) as img:
                img = img.convert("RGB")
                img.save(out_image)

        with Image.open(out_image) as img:
            width, height = img.size

        pages.append({
            "page_no": page_no,
            "page_dir": page_dir,
            "image_path": out_image,
            "source_image": source_image,
            "width": width,
            "height": height,
        })

    return pages


def flatten_strings(obj):
    strings = []

    if isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            strings.extend(flatten_strings(x))

    return strings


def extract_boxes_from_det(det_text: str):
    """
    Extract boxes from:
      [[12, 34, 567, 890]]
      [[12,34,567,890], [1,2,3,4]]
    """
    boxes = []

    # First try literal_eval for clean strings.
    try:
        value = ast.literal_eval(det_text)
        if isinstance(value, list):
            if value and all(isinstance(v, (int, float)) for v in value) and len(value) == 4:
                return [[float(v) for v in value]]

            for item in value:
                if (
                    isinstance(item, (list, tuple))
                    and len(item) == 4
                    and all(isinstance(v, (int, float)) for v in item)
                ):
                    boxes.append([float(v) for v in item])

            if boxes:
                return boxes
    except Exception:
        pass

    # Fallback regex.
    pattern = re.compile(
        r"\[+\s*"
        r"(-?\d+(?:\.\d+)?)\s*,\s*"
        r"(-?\d+(?:\.\d+)?)\s*,\s*"
        r"(-?\d+(?:\.\d+)?)\s*,\s*"
        r"(-?\d+(?:\.\d+)?)"
        r"\s*\]+"
    )

    for m in pattern.finditer(det_text):
        box = [float(m.group(i)) for i in range(1, 5)]
        boxes.append(box)

    return boxes


def raw_box_to_pixel_box(raw_box, width: int, height: int, bbox_scale: str):
    x1, y1, x2, y2 = raw_box
    max_coord = max(abs(x1), abs(y1), abs(x2), abs(y2))

    if bbox_scale == "auto":
        scale_mode = "norm999" if max_coord <= 1000 else "raw"
    else:
        scale_mode = bbox_scale

    if scale_mode == "norm999":
        denom = 999.0
        px = [
            x1 / denom * width,
            y1 / denom * height,
            x2 / denom * width,
            y2 / denom * height,
        ]
    elif scale_mode == "norm1000":
        denom = 1000.0
        px = [
            x1 / denom * width,
            y1 / denom * height,
            x2 / denom * width,
            y2 / denom * height,
        ]
    elif scale_mode == "raw":
        px = [x1, y1, x2, y2]
    else:
        raise ValueError(f"Unknown bbox_scale: {bbox_scale}")

    xa, ya, xb, yb = px

    left = max(0, min(xa, xb))
    top = max(0, min(ya, yb))
    right = min(width, max(xa, xb))
    bottom = min(height, max(ya, yb))

    return [
        int(round(left)),
        int(round(top)),
        int(round(right)),
        int(round(bottom)),
    ]


def make_bbox_item(
    text: str,
    raw_bbox,
    source: str,
    image_width: int,
    image_height: int,
    bbox_scale: str,
    raw_match_repr: str = "",
):
    pixel_bbox = raw_box_to_pixel_box(
        raw_box=raw_bbox,
        width=image_width,
        height=image_height,
        bbox_scale=bbox_scale,
    )

    return {
        "text": text or "",
        "raw_bbox": [float(v) for v in raw_bbox],
        "source": source,
        "image_width": image_width,
        "image_height": image_height,
        "bbox_scale_used": bbox_scale,
        "pixel_bbox": pixel_bbox,
        "raw_match_repr": raw_match_repr,
    }


def parse_deepseek_grounding(text: str, image_width: int, image_height: int, bbox_scale: str):
    """
    Parse:
      <|ref|>text<|/ref|><|det|>[[x1,y1,x2,y2]]<|/det|>
    """
    items = []

    ref_det_pattern = re.compile(
        r"<\|ref\|>(.*?)<\|/ref\|>\s*<\|det\|>(.*?)<\|/det\|>",
        flags=re.DOTALL,
    )

    for m in ref_det_pattern.finditer(text):
        ref_text = m.group(1).strip()
        det_text = m.group(2).strip()
        boxes = extract_boxes_from_det(det_text)

        for box in boxes:
            items.append(make_bbox_item(
                text=ref_text,
                raw_bbox=box,
                source="text_ref_det",
                image_width=image_width,
                image_height=image_height,
                bbox_scale=bbox_scale,
                raw_match_repr=m.group(0),
            ))

    if not items:
        det_pattern = re.compile(
            r"<\|det\|>(.*?)<\|/det\|>",
            flags=re.DOTALL,
        )

        for m in det_pattern.finditer(text):
            det_text = m.group(1).strip()
            boxes = extract_boxes_from_det(det_text)

            for box in boxes:
                items.append(make_bbox_item(
                    text="",
                    raw_bbox=box,
                    source="text_det_only",
                    image_width=image_width,
                    image_height=image_height,
                    bbox_scale=bbox_scale,
                    raw_match_repr=m.group(0),
                ))

    for idx, item in enumerate(items):
        item["id"] = idx

    return items


def parse_one_match_ref(match, image_width: int, image_height: int):
    """
    DeepSeekOCR2 internal matches_ref usually contains regex groups from:
      <|ref|>...<|/ref|><|det|>...</|det|>

    This function is intentionally defensive because different versions may
    represent match tuples slightly differently.
    """
    raw_match_repr = repr(match)
    strings = flatten_strings(match)

    if not strings:
        return []

    combined = "\n".join(strings)

    # Case 1: full tag string is available.
    if "<|ref|>" in combined or "<|det|>" in combined:
        return parse_deepseek_grounding(
            text=combined,
            image_width=image_width,
            image_height=image_height,
            bbox_scale="norm999",
        )

    # Case 2: tuple-like: (..., ref_text, "[[x1,y1,x2,y2], ...]")
    box_text_candidates = [s for s in strings if "[[" in s or re.search(r"\[\s*\d", s)]
    boxes = []

    for s in box_text_candidates:
        boxes.extend(extract_boxes_from_det(s))

    if not boxes:
        boxes = extract_boxes_from_det(combined)

    if not boxes:
        return []

    ref_text = ""

    # Prefer a string that is not box-like.
    non_box_strings = [
        s.strip()
        for s in strings
        if s.strip()
        and "[[" not in s
        and "<|ref|>" not in s
        and "<|det|>" not in s
        and not re.fullmatch(r"[\[\]\d,\.\s-]+", s.strip())
    ]

    if non_box_strings:
        # Often the shortest non-box string is the ref label/text.
        ref_text = min(non_box_strings, key=len)

    items = []
    for box in boxes:
        items.append(make_bbox_item(
            text=ref_text,
            raw_bbox=box,
            source="official_matches_ref",
            image_width=image_width,
            image_height=image_height,
            bbox_scale="norm999",
            raw_match_repr=raw_match_repr,
        ))

    return items


def parse_matches_ref_to_items(matches_ref, image_width: int, image_height: int):
    items = []

    try:
        for match in matches_ref:
            items.extend(parse_one_match_ref(
                match=match,
                image_width=image_width,
                image_height=image_height,
            ))
    except Exception:
        return []

    # Deduplicate by pixel bbox and text.
    seen = set()
    unique = []

    for item in items:
        key = (
            tuple(item.get("pixel_bbox", [])),
            item.get("text", ""),
            item.get("source", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    for idx, item in enumerate(unique):
        item["id"] = idx

    return unique


def get_image_size_safely(image_obj):
    try:
        size = getattr(image_obj, "size", None)
        if isinstance(size, tuple) and len(size) == 2:
            return int(size[0]), int(size[1])
    except Exception:
        pass

    return None, None


def install_official_bbox_capture_patch(model):
    """
    Patch DeepSeekOCR2's process_image_with_refs(...) at runtime.

    DeepSeekOCR2 internally computes matches_ref before writing result.mmd.
    result.mmd has bbox tags removed, so we capture matches_ref here and
    save it as bbox_items_official.json.
    """
    try:
        module_name = model.__class__.__module__
        module = importlib.import_module(module_name)

        if getattr(module, "_bbox_capture_patch_installed", False):
            print("[INFO] DeepSeekOCR2 bbox capture patch already installed.")
            return

        if not hasattr(module, "process_image_with_refs"):
            print("[WARN] process_image_with_refs not found. Official bbox capture patch not installed.")
            return

        original_func = module.process_image_with_refs

        def wrapped_process_image_with_refs(image_draw, matches_ref, output_path, *args, **kwargs):
            output_dir = Path(output_path)
            ensure_dir(output_dir)

            image_width, image_height = get_image_size_safely(image_draw)

            try:
                save_text(repr(matches_ref), output_dir / OFFICIAL_MATCHES_RAW)

                if image_width is not None and image_height is not None:
                    items = parse_matches_ref_to_items(
                        matches_ref=matches_ref,
                        image_width=image_width,
                        image_height=image_height,
                    )
                else:
                    items = []

                save_json(items, output_dir / OFFICIAL_BBOX_JSON)
                print(f"[INFO] Captured official bbox items: {len(items)} -> {output_dir / OFFICIAL_BBOX_JSON}")

            except Exception:
                err = {
                    "status": "error",
                    "traceback": traceback.format_exc(),
                }
                save_json(err, output_dir / "bbox_capture_error.json")
                print("[WARN] Failed to capture official bbox items.")
                print(traceback.format_exc())

            return original_func(image_draw, matches_ref, output_path, *args, **kwargs)

        module.process_image_with_refs = wrapped_process_image_with_refs
        module._bbox_capture_patch_installed = True

        print("[INFO] Installed DeepSeekOCR2 official bbox capture patch.")

    except Exception:
        print("[WARN] Could not install official bbox capture patch.")
        print(traceback.format_exc())


def load_model(model_name: str, use_flash_attn: bool):
    print(f"[INFO] Loading tokenizer from: {model_name}")

    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
    )

    kwargs = {
        "trust_remote_code": True,
        "use_safetensors": True,
    }

    if torch.cuda.is_available() and use_flash_attn:
        kwargs["_attn_implementation"] = "flash_attention_2"

    print(f"[INFO] Loading model from: {model_name}")

    try:
        model = AutoModel.from_pretrained(model_name, **kwargs)
    except Exception as e:
        print("[WARN] Loading with current attention setting failed.")
        print("[WARN] Fallback to normal attention.")
        print(str(e))
        kwargs.pop("_attn_implementation", None)
        model = AutoModel.from_pretrained(model_name, **kwargs)

    model = model.eval()

    if torch.cuda.is_available():
        model = model.cuda().to(torch.bfloat16)
        print("[INFO] Using CUDA + bfloat16")
        print("[INFO] GPU:", torch.cuda.get_device_name(0))
    else:
        model = model.to(torch.float32)
        print("[WARN] CUDA not available. CPU will be extremely slow.")

    install_official_bbox_capture_patch(model)

    return tokenizer, model


def draw_preview(image_path: Path, items, out_path: Path):
    if not items:
        return

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 16)
    except Exception:
        font = None

    for item in items:
        x1, y1, x2, y2 = item["pixel_bbox"]
        idx = item.get("id", "")

        draw.rectangle([x1, y1, x2, y2], outline="red", width=3)
        draw.text((x1 + 2, max(0, y1 - 18)), str(idx), fill="red", font=font)

    ensure_dir(out_path.parent)
    img.save(out_path)


def run_deepseek_ocr_page(
    tokenizer,
    model,
    image_path: Path,
    page_dir: Path,
    base_size: int,
    image_size: int,
):
    prompt = "<image>\n<|grounding|>Convert the document to markdown. "

    res = model.infer(
        tokenizer,
        prompt=prompt,
        image_file=str(image_path),
        output_path=str(page_dir),
        base_size=base_size,
        image_size=image_size,
        crop_mode=True,
        save_results=True,
    )

    if isinstance(res, str):
        raw_text = res
    else:
        raw_text = json.dumps(res, ensure_ascii=False, indent=2)

    return raw_text


def find_best_ocr_text(page_dir: Path, fallback_text: str):
    candidate_names = [
        "raw_response.txt",
        "result.mmd",
        "ocr.md",
        "result.md",
        "output.md",
    ]

    candidates = []

    if fallback_text:
        candidates.append(("return_value", fallback_text))

    for name in candidate_names:
        p = page_dir / name
        if p.exists():
            candidates.append((name, read_text_if_exists(p)))

    if not candidates:
        return ""

    for _, text in candidates:
        if "<|det|>" in text or "<|ref|>" in text:
            return text

    return max(candidates, key=lambda x: len(x[1]))[1]


def load_official_bbox_items(page_dir: Path):
    p = page_dir / OFFICIAL_BBOX_JSON

    if not p.exists():
        return []

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass

    return []


def process_one_page(tokenizer, model, page_info, args):
    page_dir = page_info["page_dir"]
    image_path = page_info["image_path"]
    width = page_info["width"]
    height = page_info["height"]

    bbox_json_path = page_dir / "bbox_items.json"
    ocr_md_path = page_dir / "ocr.md"
    raw_response_path = page_dir / "raw_response.txt"
    preview_path = page_dir / "bboxes_preview.jpg"

    if args.skip_existing and bbox_json_path.exists():
        try:
            existing_items = json.loads(bbox_json_path.read_text(encoding="utf-8"))
        except Exception:
            existing_items = []

        if existing_items or args.allow_empty_bbox:
            return {
                "status": "skipped",
                "bbox_count": len(existing_items),
                "items": existing_items,
            }

        print(f"[WARN] Existing bbox_items.json is empty. Re-running page: {page_dir}")

    try:
        raw_text = run_deepseek_ocr_page(
            tokenizer=tokenizer,
            model=model,
            image_path=image_path,
            page_dir=page_dir,
            base_size=args.base_size,
            image_size=args.image_size,
        )

        save_text(raw_text, raw_response_path)

        best_text = find_best_ocr_text(page_dir, raw_text)
        save_text(best_text, ocr_md_path)

        # 1. Try text tags if they exist.
        items = parse_deepseek_grounding(
            text=best_text,
            image_width=width,
            image_height=height,
            bbox_scale=args.bbox_scale,
        )

        # 2. Official internal bbox capture.
        if not items:
            items = load_official_bbox_items(page_dir)

        for idx, item in enumerate(items):
            item["id"] = idx

        save_json(items, bbox_json_path)
        draw_preview(image_path, items, preview_path)

        if not items and not args.allow_empty_bbox:
            err = {
                "status": "error",
                "error": "No bbox items found. result_with_boxes.jpg may exist, but no official bbox JSON was captured.",
                "page_dir": str(page_dir),
            }
            save_json(err, page_dir / "error.json")
            return {
                "status": "error",
                "bbox_count": 0,
                "items": [],
                "error": err["error"],
            }

        return {
            "status": "ok",
            "bbox_count": len(items),
            "items": items,
        }

    except Exception as e:
        err = {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
        save_json(err, page_dir / "error.json")
        return err


def move_input_file(input_file: Path, incoming_dir: Path, target_dir: Path, label: str):
    ensure_dir(target_dir)

    try:
        rel_path = input_file.relative_to(incoming_dir)
    except ValueError:
        rel_path = Path(input_file.name)

    dst = target_dir / rel_path
    ensure_dir(dst.parent)

    if dst.exists():
        stem = dst.stem
        suffix = dst.suffix
        parent = dst.parent
        i = 1

        while dst.exists():
            dst = parent / f"{stem}__{label}_{i}{suffix}"
            i += 1

    shutil.move(str(input_file), str(dst))
    print(f"[INFO] Moved {label} file: {input_file} -> {dst}")


def save_global_index(output_dir: Path, all_pages):
    save_json(all_pages, output_dir / "all_pages_bbox.json")


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--incoming", type=str, default="data/incoming")
    parser.add_argument("--output", type=str, default="output/render_result")
    parser.add_argument("--model-name", type=str, default=DEFAULT_MODEL_NAME)
    parser.add_argument(
        "--render-result-input",
        action="store_true",
        help=(
            "Treat --incoming as a rendered page root with "
            "<doc_id>/pages/page_000001.png or <doc_id>/page_0001/page.png."
        ),
    )
    parser.add_argument(
        "--doc-id",
        default=None,
        help="Only process one document folder when --render-result-input is set.",
    )

    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--base-size", type=int, default=1024)
    parser.add_argument("--image-size", type=int, default=768)

    parser.add_argument(
        "--bbox-scale",
        type=str,
        default="norm999",
        choices=["norm999", "norm1000", "raw", "auto"],
    )

    parser.add_argument("--overwrite-render", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--no-flash-attn", action="store_true")

    parser.add_argument("--max-docs", type=int, default=None)
    parser.add_argument("--max-pages-per-doc", type=int, default=None)
    parser.add_argument("--max-pages-total", type=int, default=None)

    parser.add_argument("--move-processed", action="store_true")
    parser.add_argument("--processed-dir", type=str, default="data/processed")
    parser.add_argument("--failed-dir", type=str, default="data/failed")

    parser.add_argument(
        "--allow-empty-bbox",
        action="store_true",
        help="Allow pages with empty bbox_items.json. By default, empty bbox is treated as an error.",
    )

    args = parser.parse_args()

    incoming_dir = Path(args.incoming)
    output_dir = Path(args.output)
    processed_dir = Path(args.processed_dir)
    failed_dir = Path(args.failed_dir)

    ensure_dir(output_dir)
    ensure_dir(processed_dir)
    ensure_dir(failed_dir)

    if args.render_result_input:
        input_docs = collect_render_result_docs(incoming_dir, doc_id=args.doc_id)

        if args.max_docs is not None:
            input_docs = input_docs[:args.max_docs]

        if not input_docs:
            print(f"[WARN] No rendered document folders found in {incoming_dir.resolve()}")
            return
    else:
        files = collect_input_files(incoming_dir)

        if args.max_docs is not None:
            files = files[:args.max_docs]

        if not files:
            print(f"[WARN] No PDF/images found in {incoming_dir.resolve()}")
            return

        input_docs = [
            {
                "doc_name": safe_name(input_file),
                "source_file": input_file,
                "input_file": input_file,
            }
            for input_file in files
        ]

    print(f"[INFO] Incoming dir: {incoming_dir.resolve()}")
    print(f"[INFO] Output dir: {output_dir.resolve()}")
    print(f"[INFO] Processed dir: {processed_dir.resolve()}")
    print(f"[INFO] Failed dir: {failed_dir.resolve()}")
    print(f"[INFO] Found {len(input_docs)} document(s)")

    tokenizer, model = load_model(
        args.model_name,
        use_flash_attn=not args.no_flash_attn,
    )

    all_pages = []
    remaining_total_pages = args.max_pages_total

    for doc_input in input_docs:
        source = doc_input.get("source_dir") or doc_input.get("source_file") or doc_input.get("input_file")
        print(f"\n[INFO] Processing: {source}")

        doc_name = doc_input["doc_name"]
        doc_out_dir = output_dir / doc_name
        ensure_dir(doc_out_dir)

        doc_record = {
            "source_file": str(source),
            "output_dir": str(doc_out_dir),
            "pages": [],
        }

        try:
            if args.render_result_input:
                page_records = doc_input["pages"]
            else:
                input_file = doc_input["input_file"]
                if input_file.suffix.lower() == ".pdf":
                    pages = render_pdf_to_pages(
                        pdf_path=input_file,
                        doc_out_dir=doc_out_dir,
                        dpi=args.dpi,
                        overwrite=args.overwrite_render,
                    )
                else:
                    pages = image_to_page(
                        image_path=input_file,
                        doc_out_dir=doc_out_dir,
                        overwrite=args.overwrite_render,
                    )
                page_records = None

            if args.render_result_input:
                if args.max_pages_per_doc is not None:
                    page_records = page_records[:args.max_pages_per_doc]

                if remaining_total_pages is not None:
                    if remaining_total_pages <= 0:
                        break
                    page_records = page_records[:remaining_total_pages]
                    remaining_total_pages -= len(page_records)

                pages = rendered_images_to_pages(
                    page_records=page_records,
                    doc_out_dir=doc_out_dir,
                    overwrite=args.overwrite_render,
                )

            if args.max_pages_per_doc is not None:
                pages = pages[:args.max_pages_per_doc]

            for page_info in tqdm(pages, desc=f"OCR {doc_name}"):
                result = process_one_page(
                    tokenizer=tokenizer,
                    model=model,
                    page_info=page_info,
                    args=args,
                )

                page_source = page_info.get("source_image") or source
                page_record = {
                    "source_file": str(page_source),
                    "page_no": page_info["page_no"],
                    "page_dir": str(page_info["page_dir"]),
                    "image_path": str(page_info["image_path"]),
                    "width": page_info["width"],
                    "height": page_info["height"],
                    "status": result["status"],
                    "bbox_count": result.get("bbox_count", 0),
                    "bbox_json": str(page_info["page_dir"] / "bbox_items.json"),
                    "official_bbox_json": str(page_info["page_dir"] / OFFICIAL_BBOX_JSON),
                    "ocr_md": str(page_info["page_dir"] / "ocr.md"),
                    "raw_response": str(page_info["page_dir"] / "raw_response.txt"),
                    "preview": str(page_info["page_dir"] / "bboxes_preview.jpg"),
                    "result_with_boxes": str(page_info["page_dir"] / "result_with_boxes.jpg"),
                }

                if result["status"] == "error":
                    page_record["error"] = result.get("error")

                doc_record["pages"].append(page_record)
                all_pages.append(page_record)

                save_json(doc_record, doc_out_dir / "document_bbox_manifest.json")
                save_global_index(output_dir, all_pages)

            all_ok = all(
                p.get("status") in {"ok", "skipped"}
                for p in doc_record["pages"]
            )

            if args.move_processed and all_ok:
                if args.render_result_input:
                    print("[WARN] --move-processed is ignored for --render-result-input.")
                else:
                    move_input_file(
                        input_file=doc_input["input_file"],
                        incoming_dir=incoming_dir,
                        target_dir=processed_dir,
                        label="processed",
                    )
            elif args.move_processed:
                if args.render_result_input:
                    print("[WARN] --move-processed is ignored for --render-result-input.")
                else:
                    print(f"[WARN] Some pages failed. Moving to failed: {doc_input['input_file']}")
                    move_input_file(
                        input_file=doc_input["input_file"],
                        incoming_dir=incoming_dir,
                        target_dir=failed_dir,
                        label="failed",
                    )

        except Exception:
            err = {
                "source_file": str(source),
                "status": "error",
                "traceback": traceback.format_exc(),
            }
            save_json(err, doc_out_dir / "document_error.json")
            print(f"[ERROR] Failed document: {source}")
            print(traceback.format_exc())

            if (
                args.move_processed
                and not args.render_result_input
                and doc_input["input_file"].exists()
            ):
                move_input_file(
                    input_file=doc_input["input_file"],
                    incoming_dir=incoming_dir,
                    target_dir=failed_dir,
                    label="failed",
                )

    save_global_index(output_dir, all_pages)

    print("\n[DONE]")
    print(f"Output saved to: {output_dir.resolve()}")
    print(f"Global bbox index: {(output_dir / 'all_pages_bbox.json').resolve()}")


if __name__ == "__main__":
    main()
