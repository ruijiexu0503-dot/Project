#!/usr/bin/env python3
"""Classify logical page PNGs with a VLM and rename them by inferred page order."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ALLOWED_PAGE_TYPES = {
    "cover",
    "table_of_contents",
    "article_page",
    "advertisement",
    "editorial",
    "masthead",
    "index",
    "back_cover",
    "blank_or_separator",
    "mixed",
    "unknown",
}

TSV_COLUMNS = [
    "logical_index",
    "original_filename",
    "new_filename",
    "page_type",
    "visible_page_number",
    "is_page_number_reliable",
    "inferred_page_number",
    "page_label",
    "status",
    "notes",
]


@dataclass
class PageRecord:
    logical_index: int
    path: Path
    page_type: str = "unknown"
    visible_page_number: str | None = None
    is_page_number_reliable: bool = False
    raw_vlm_response: str = ""
    parse_error: str | None = None
    inferred_page_number: int | None = None
    page_label: str = ""
    status: str = "unknown"
    notes: list[str] = field(default_factory=list)
    new_filename: str = ""


def natural_sort_key(path: Path) -> list[Any]:
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def png_paths(image_dir: Path, limit: int | None) -> list[Path]:
    if not image_dir.exists():
        raise FileNotFoundError(f"Image directory does not exist: {image_dir}")
    if not image_dir.is_dir():
        raise ValueError(f"--image-dir must be a directory: {image_dir}")
    paths = sorted(image_dir.glob("*.png"), key=natural_sort_key)
    if limit is not None:
        paths = paths[:limit]
    if not paths:
        raise ValueError(f"No PNG files found in: {image_dir}")
    return paths


def sanitize_page_type(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    page_type = value.strip().lower()
    return page_type if page_type in ALLOWED_PAGE_TYPES else "unknown"


def parse_visible_page_number(value: Any, reliable: bool) -> tuple[str | None, bool]:
    if not reliable:
        return None, False
    if value is None:
        return None, False
    text = str(value).strip()
    if not re.fullmatch(r"\d{1,5}", text):
        return None, False
    number = int(text)
    if number <= 0:
        return None, False
    return str(number), True


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        obj = json.loads(cleaned[start : end + 1])
        if isinstance(obj, dict):
            return obj

    raise ValueError("Could not parse a JSON object from VLM response.")


def normalize_vlm_response(raw_text: str) -> tuple[dict[str, Any], str | None]:
    try:
        obj = extract_json_object(raw_text)
        page_type = sanitize_page_type(obj.get("page_type"))
        reliable = bool(obj.get("is_page_number_reliable", False))
        visible_page_number, reliable = parse_visible_page_number(
            obj.get("visible_page_number"),
            reliable,
        )
        return (
            {
                "page_type": page_type,
                "visible_page_number": visible_page_number,
                "is_page_number_reliable": reliable,
            },
            None,
        )
    except Exception as exc:
        return (
            {
                "page_type": "unknown",
                "visible_page_number": None,
                "is_page_number_reliable": False,
            },
            str(exc),
        )


def build_prompt() -> str:
    allowed = ", ".join(sorted(ALLOWED_PAGE_TYPES))
    return f"""
You are inspecting exactly one rendered magazine/PDF logical page image.

Return only a compact JSON object with these keys:
{{
  "page_type": "...",
  "visible_page_number": "12",
  "is_page_number_reliable": true
}}

Allowed page_type values:
{allowed}

Rules:
- Only report visible_page_number if it is clearly the actual printed page number on this page.
- Do not confuse years, issue numbers, figure numbers, table numbers, dates, prices, phone numbers, or table-of-contents target page numbers with printed page numbers.
- Do not infer missing page numbers.
- Do not extract titles.
- Do not summarize the page.
- If no reliable printed page number is visible, use null and false:
  "visible_page_number": null,
  "is_page_number_reliable": false

Return JSON only.
""".strip()


def load_qwen_vl(model_path: str, local_files_only: bool):
    import torch
    from transformers import AutoProcessor

    try:
        from transformers import Qwen2_5_VLForConditionalGeneration

        model_cls = Qwen2_5_VLForConditionalGeneration
    except Exception:
        try:
            from transformers import AutoModelForVision2Seq

            model_cls = AutoModelForVision2Seq
        except Exception as exc:
            raise RuntimeError(
                "Could not import Qwen2_5_VLForConditionalGeneration or AutoModelForVision2Seq. "
                "Please check the installed transformers version."
            ) from exc

    model_kwargs: dict[str, Any] = {
        "device_map": "auto",
        "trust_remote_code": True,
        "local_files_only": local_files_only,
    }
    if torch.cuda.is_available():
        model_kwargs["torch_dtype"] = torch.bfloat16
    else:
        model_kwargs["torch_dtype"] = "auto"

    model = model_cls.from_pretrained(model_path, **model_kwargs)
    processor = AutoProcessor.from_pretrained(
        model_path,
        trust_remote_code=True,
        local_files_only=local_files_only,
    )
    model.eval()
    return model, processor


def run_qwen_page(
    model: Any,
    processor: Any,
    image_path: Path,
    prompt: str,
    max_new_tokens: int,
) -> str:
    import torch

    try:
        from qwen_vl_utils import process_vision_info
    except Exception as exc:
        raise RuntimeError(
            "Missing qwen-vl-utils. Install it with `pip install qwen-vl-utils` "
            "or use the project environment that already includes it."
        ) from exc

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": str(image_path)},
                {"type": "text", "text": prompt},
            ],
        }
    ]

    text = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    image_inputs, video_inputs = process_vision_info(messages)

    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    if hasattr(model, "device"):
        inputs = inputs.to(model.device)

    with torch.no_grad():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )

    generated_ids_trimmed = [
        output_ids[len(input_ids) :]
        for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
    ]
    return processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()


def progress_path(args: argparse.Namespace) -> Path:
    if args.progress_jsonl:
        return Path(args.progress_jsonl)
    return Path(args.out_dir) / "vlm_page_annotations.jsonl"


def load_progress(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    completed: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            filename = obj.get("original_filename")
            if isinstance(filename, str):
                completed[filename] = obj
    return completed


def append_progress(path: Path, record: PageRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    item = {
        "logical_index": record.logical_index,
        "original_filename": record.path.name,
        "page_type": record.page_type,
        "visible_page_number": record.visible_page_number,
        "is_page_number_reliable": record.is_page_number_reliable,
        "raw_vlm_response": record.raw_vlm_response,
        "parse_error": record.parse_error,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def annotate_pages(args: argparse.Namespace, paths: list[Path]) -> list[PageRecord]:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    progress_file = progress_path(args)
    completed = load_progress(progress_file) if args.resume else {}
    prompt = build_prompt()

    model = None
    processor = None
    records: list[PageRecord] = []

    for logical_index, path in enumerate(paths):
        record = PageRecord(logical_index=logical_index, path=path)
        cached = completed.get(path.name)
        if cached:
            record.page_type = sanitize_page_type(cached.get("page_type"))
            reliable = bool(cached.get("is_page_number_reliable", False))
            record.visible_page_number, record.is_page_number_reliable = parse_visible_page_number(
                cached.get("visible_page_number"),
                reliable,
            )
            record.raw_vlm_response = str(cached.get("raw_vlm_response", ""))
            record.parse_error = cached.get("parse_error")
            print(f"[resume] {logical_index + 1}/{len(paths)} {path.name}")
            records.append(record)
            continue

        if model is None or processor is None:
            print(f"Loading VLM model: {args.model_path}")
            model, processor = load_qwen_vl(
                args.model_path,
                local_files_only=not args.allow_remote_model_files,
            )

        print(f"[vlm] {logical_index + 1}/{len(paths)} {path.name}")
        raw_text = run_qwen_page(
            model=model,
            processor=processor,
            image_path=path,
            prompt=prompt,
            max_new_tokens=args.max_new_tokens,
        )
        parsed, parse_error = normalize_vlm_response(raw_text)
        record.page_type = parsed["page_type"]
        record.visible_page_number = parsed["visible_page_number"]
        record.is_page_number_reliable = parsed["is_page_number_reliable"]
        record.raw_vlm_response = raw_text
        record.parse_error = parse_error
        if parse_error:
            record.notes.append(f"invalid_vlm_json: {parse_error}")
        append_progress(progress_file, record)
        records.append(record)

    return records


def reliable_number(record: PageRecord) -> int | None:
    if not record.is_page_number_reliable or record.visible_page_number is None:
        return None
    try:
        return int(record.visible_page_number)
    except ValueError:
        return None


def infer_page_numbers(records: list[PageRecord]) -> None:
    anchors = [(idx, reliable_number(record)) for idx, record in enumerate(records)]
    anchors = [(idx, num) for idx, num in anchors if num is not None]

    duplicate_numbers = {
        num
        for num in {num for _, num in anchors}
        if sum(1 for _, other in anchors if other == num) > 1
    }

    for idx, num in anchors:
        record = records[idx]
        record.inferred_page_number = num
        record.status = "visible_anchor"
        if num in duplicate_numbers:
            record.status = "conflict"
            record.notes.append(f"duplicate visible page number {num}")

    page_one_indices = [idx for idx, num in anchors if num == 1]
    first_page_one = min(page_one_indices) if page_one_indices else None
    if first_page_one is not None:
        for idx in range(first_page_one):
            record = records[idx]
            if reliable_number(record) is None:
                record.status = "front_matter"
                record.notes.append("before visible printed page 1")

    for (left_idx, left_num), (right_idx, right_num) in zip(anchors, anchors[1:]):
        if left_num is None or right_num is None:
            continue
        index_gap = right_idx - left_idx
        number_gap = right_num - left_num

        if number_gap <= 0:
            records[left_idx].status = "conflict"
            records[right_idx].status = "conflict"
            records[left_idx].notes.append("visible page anchors are not increasing")
            records[right_idx].notes.append("visible page anchors are not increasing")
            for idx in range(left_idx + 1, right_idx):
                records[idx].status = "conflict"
                records[idx].notes.append(
                    f"between conflicting anchors {left_num} and {right_num}"
                )
            continue

        if index_gap <= 1:
            continue

        missing_indices = list(range(left_idx + 1, right_idx))
        if number_gap == index_gap:
            for idx in missing_indices:
                record = records[idx]
                if reliable_number(record) is None:
                    record.inferred_page_number = left_num + (idx - left_idx)
                    record.status = "inferred"
                    record.notes.append(
                        f"inferred between reliable anchors {left_num} and {right_num}"
                    )
        elif number_gap <= index_gap:
            for idx in missing_indices:
                record = records[idx]
                if reliable_number(record) is None and record.status == "unknown":
                    record.status = "unnumbered"
                    record.notes.append(
                        f"unnumbered insert between anchors {left_num} and {right_num}"
                    )
        else:
            for idx in missing_indices:
                record = records[idx]
                if reliable_number(record) is None and record.status == "unknown":
                    record.status = "unknown"
                    record.notes.append(
                        f"cannot choose a unique number between anchors {left_num} and {right_num}"
                    )

    for record in records:
        if record.inferred_page_number is not None and record.status not in {"conflict"}:
            if record.is_page_number_reliable:
                record.status = "visible_anchor"
            elif record.status != "inferred":
                record.status = "inferred"
        elif record.status == "unknown":
            if record.page_type == "unknown":
                record.status = "unknown"
            else:
                record.status = "unnumbered"


def assign_page_labels(records: list[PageRecord]) -> None:
    counters = {
        "front_matter": 0,
        "unnumbered": 0,
        "unknown": 0,
        "conflict": 0,
    }

    for record in records:
        if record.status in {"visible_anchor", "inferred"} and record.inferred_page_number:
            record.page_label = f"p{record.inferred_page_number:04d}"
        elif record.status == "front_matter":
            counters["front_matter"] += 1
            record.page_label = f"front_{counters['front_matter']:03d}"
        elif record.status == "conflict":
            counters["conflict"] += 1
            record.page_label = f"conflict_{counters['conflict']:03d}"
            record.inferred_page_number = None
        elif record.status == "unknown":
            counters["unknown"] += 1
            record.page_label = f"unknown_{counters['unknown']:03d}"
        else:
            counters["unnumbered"] += 1
            record.page_label = f"unnum_{counters['unnumbered']:03d}"
            record.status = "unnumbered"


def assign_new_filenames(records: list[PageRecord]) -> None:
    counts: dict[str, int] = {}
    for record in records:
        base = f"{record.page_label}__{record.page_type}"
        counts[base] = counts.get(base, 0) + 1
        if counts[base] == 1:
            record.new_filename = f"{base}.png"
        else:
            record.new_filename = f"{base}__{counts[base]:02d}.png"


def copy_or_rename_outputs(records: list[PageRecord], args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.rename_in_place:
        for record in records:
            target = record.path.with_name(record.new_filename)
            if target.exists() and target.resolve() != record.path.resolve():
                raise FileExistsError(f"Target file already exists: {target}")
            record.path.rename(target)
        return

    for record in records:
        target = out_dir / record.new_filename
        shutil.copy2(record.path, target)


def write_tsv(records: list[PageRecord], out_dir: Path) -> Path:
    log_path = out_dir / "rename_log.tsv"
    with log_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TSV_COLUMNS, delimiter="\t")
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "logical_index": record.logical_index,
                    "original_filename": record.path.name,
                    "new_filename": record.new_filename,
                    "page_type": record.page_type,
                    "visible_page_number": record.visible_page_number or "",
                    "is_page_number_reliable": str(record.is_page_number_reliable).lower(),
                    "inferred_page_number": record.inferred_page_number or "",
                    "page_label": record.page_label,
                    "status": record.status,
                    "notes": "; ".join(record.notes),
                }
            )
    return log_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Use a VLM to classify logical page PNGs and rename them by page order."
    )
    parser.add_argument("--image-dir", required=True, help="Directory of already-rendered logical PNG pages.")
    parser.add_argument("--model-path", required=True, help="Local Qwen2.5-VL model path.")
    parser.add_argument("--out-dir", required=True, help="Output directory for renamed PNG copies and logs.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N PNGs.")
    parser.add_argument("--resume", action="store_true", help="Reuse existing VLM progress JSONL.")
    parser.add_argument("--progress-jsonl", default=None, help="Optional path for VLM progress JSONL.")
    parser.add_argument("--max-new-tokens", type=int, default=96)
    parser.add_argument(
        "--copy",
        action="store_true",
        default=True,
        help="Copy renamed PNGs to --out-dir. This is the default.",
    )
    parser.add_argument(
        "--rename-in-place",
        action="store_true",
        help="Rename files inside --image-dir instead of copying. Explicit opt-in only.",
    )
    parser.add_argument(
        "--allow-remote-model-files",
        action="store_true",
        help="Allow transformers to fetch missing model files. Default is local files only.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.limit is not None and args.limit <= 0:
            raise ValueError("--limit must be positive when provided.")
        if args.max_new_tokens <= 0:
            raise ValueError("--max-new-tokens must be positive.")

        paths = png_paths(Path(args.image_dir), args.limit)
        records = annotate_pages(args, paths)
        infer_page_numbers(records)
        assign_page_labels(records)
        assign_new_filenames(records)
        copy_or_rename_outputs(records, args)
        log_path = write_tsv(records, Path(args.out_dir))

        summary = {
            "image_dir": str(Path(args.image_dir)),
            "out_dir": str(Path(args.out_dir)),
            "page_count": len(records),
            "rename_log": str(log_path),
            "copied": not args.rename_in_place,
            "renamed_in_place": bool(args.rename_in_place),
            "status_counts": {
                status: sum(1 for record in records if record.status == status)
                for status in ["front_matter", "visible_anchor", "inferred", "unnumbered", "unknown", "conflict"]
            },
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
