from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import torch
from tqdm import tqdm
from transformers import AutoProcessor


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    if not path.exists():
        return rows

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    return rows


def append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_done_region_ids(path: Path) -> Set[str]:
    done: Set[str] = set()

    if not path.exists():
        return done

    for row in load_jsonl(path):
        region_id = row.get("region_id")
        if region_id:
            done.add(str(region_id))

    return done


def image_exists(path: Optional[str]) -> bool:
    if not path:
        return False
    return Path(path).exists()


def select_request_images(
    request: Dict[str, Any],
    image_roles: List[str],
    max_images: int,
) -> List[Dict[str, str]]:
    images = request.get("images", [])

    if not isinstance(images, list):
        images = []

    selected: List[Dict[str, str]] = []

    for role in image_roles:
        for item in images:
            if not isinstance(item, dict):
                continue

            if item.get("role") != role:
                continue

            path = item.get("path")
            if not image_exists(path):
                print(f"[WARN] image missing for role={role}: {path}")
                continue

            selected.append(
                {
                    "role": str(role),
                    "path": str(path),
                    "description": str(item.get("description", "")),
                }
            )
            break

        if len(selected) >= max_images:
            break

    return selected


def truncate_text(text: Any, max_chars: int) -> str:
    if text is None:
        return ""

    text = str(text)

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "\n...[truncated]"


def build_prompt(request: Dict[str, Any], max_group_text_chars: int) -> str:
    """
    Build the final textual prompt for Qwen-VL.

    Important:
    This function intentionally avoids a large f-string with nested triple backticks,
    because that can easily cause unterminated string errors when copied into VS Code.
    """
    base_prompt = str(request.get("prompt", ""))

    metadata = {
        "region_id": request.get("region_id"),
        "group_id": request.get("group_id"),
        "page_no": request.get("page_no"),
        "group_type": request.get("group_type"),
        "original_bbox": request.get("original_bbox"),
        "member_bbox_union": request.get("member_bbox_union"),
        "members": request.get("members", []),
        "layout_relations": request.get("layout_relations", []),
        "nearby_layout_only_candidates": request.get("nearby_layout_only_candidates", []),
        "neighbor_region_overlaps": request.get("neighbor_region_overlaps", []),
        "geometry_flags": request.get("geometry_flags", []),
        "group_text": truncate_text(request.get("group_text", ""), max_group_text_chars),
    }

    metadata_json = json.dumps(metadata, ensure_ascii=False, indent=2)

    parts = [
        base_prompt,
        "",
        "Additional structured metadata:",
        "",
        "```json",
        metadata_json,
        "```",
        "",
        "Important reminder:",
        "- Use original_page_image to inspect the real page content.",
        "- Use annotated_page_image to understand target evidence region, layout boxes, member parsing boxes, and neighboring groups.",
        "- Use evidence_crop to judge whether the current crop is complete.",
        "- The semantic group and its original parsing members are the primary structure.",
        "- Layout detection is only a reference.",
        "- Do not delete, reorder, or overwrite parsing members.",
        "- Final bbox must preserve all original member parsing boxes.",
        "- Return JSON only.",
    ]

    return "\n".join(parts).strip()


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    text = text.strip()

    # Remove markdown fences if the model adds them.
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Extract first valid JSON object.
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1

            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    return None

    return None


def normalize_review(
    region_id: str,
    raw_output: str,
    parsed: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    allowed_decisions = {
        "keep",
        "expand_to_include_layouts",
        "shrink_to_selected_layouts",
        "union_original_and_selected_layouts",
        "attach_layout_only",
        "merge_with_neighbor_region",
        "split_region",
        "uncertain",
        "manual_review",
    }

    allowed_crop_quality = {
        "complete",
        "too_small",
        "too_large",
        "intrudes_other_region",
        "misses_related_visual",
        "uncertain",
    }

    if parsed is None:
        return {
            "region_id": region_id,
            "decision": "manual_review",
            "crop_quality": "uncertain",
            "selected_layout_ids": [],
            "excluded_layout_ids": [],
            "merge_with_region_ids": [],
            "split_into": [],
            "final_bbox": None,
            "bbox_padding_px": 12,
            "confidence": 0.0,
            "reason": "Could not parse JSON from VLM output.",
            "raw_model_output": raw_output,
            "parse_ok": False,
        }

    decision = parsed.get("decision", "uncertain")
    if decision not in allowed_decisions:
        decision = "manual_review"

    crop_quality = parsed.get("crop_quality", "uncertain")
    if crop_quality not in allowed_crop_quality:
        crop_quality = "uncertain"

    def safe_list(x: Any) -> List[Any]:
        return x if isinstance(x, list) else []

    final_bbox = parsed.get("final_bbox", None)
    if not (
        isinstance(final_bbox, list)
        and len(final_bbox) >= 4
        and all(isinstance(v, (int, float)) for v in final_bbox[:4])
    ):
        final_bbox = None
    else:
        final_bbox = [float(v) for v in final_bbox[:4]]

    try:
        confidence = float(parsed.get("confidence", 0.0))
    except Exception:
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))

    try:
        bbox_padding_px = int(parsed.get("bbox_padding_px", 12))
    except Exception:
        bbox_padding_px = 12

    return {
        "region_id": str(parsed.get("region_id", region_id)),
        "decision": decision,
        "crop_quality": crop_quality,
        "selected_layout_ids": safe_list(parsed.get("selected_layout_ids", [])),
        "excluded_layout_ids": safe_list(parsed.get("excluded_layout_ids", [])),
        "merge_with_region_ids": safe_list(parsed.get("merge_with_region_ids", [])),
        "split_into": safe_list(parsed.get("split_into", [])),
        "final_bbox": final_bbox,
        "bbox_padding_px": bbox_padding_px,
        "confidence": confidence,
        "reason": str(parsed.get("reason", "")),
        "raw_model_output": raw_output,
        "parse_ok": True,
    }


def load_qwen_model(args: argparse.Namespace):
    try:
        from transformers import Qwen2_5_VLForConditionalGeneration

        model_cls = Qwen2_5_VLForConditionalGeneration
    except Exception:
        from transformers import AutoModelForVision2Seq

        model_cls = AutoModelForVision2Seq

    dtype_map = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }
    torch_dtype = dtype_map[args.dtype]

    print(f"[INFO] Loading model: {args.model_path}")
    print(f"[INFO] dtype={args.dtype}, device_map={args.device_map}")

    model = model_cls.from_pretrained(
        args.model_path,
        torch_dtype=torch_dtype,
        device_map=args.device_map,
        trust_remote_code=True,
        local_files_only=args.local_files_only,
    )

    try:
        processor = AutoProcessor.from_pretrained(
            args.model_path,
            min_pixels=args.min_pixels,
            max_pixels=args.max_pixels,
            trust_remote_code=True,
            local_files_only=args.local_files_only,
        )
    except TypeError:
        processor = AutoProcessor.from_pretrained(
            args.model_path,
            trust_remote_code=True,
            local_files_only=args.local_files_only,
        )

    model.eval()
    return model, processor


def build_qwen_messages(
    request: Dict[str, Any],
    selected_images: List[Dict[str, str]],
    prompt: str,
) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = []

    for img in selected_images:
        role = img["role"]
        path = img["path"]
        description = img.get("description", "")

        # Add a short tag before each image so the model knows which image is which.
        content.append(
            {
                "type": "text",
                "text": f"[Image role: {role}] {description}",
            }
        )

        content.append(
            {
                "type": "image",
                "image": path,
            }
        )

    content.append(
        {
            "type": "text",
            "text": prompt,
        }
    )

    return [
        {
            "role": "user",
            "content": content,
        }
    ]


def run_one_request(
    model,
    processor,
    request: Dict[str, Any],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    from qwen_vl_utils import process_vision_info

    region_id = str(request.get("region_id", "unknown_region"))

    selected_images = select_request_images(
        request=request,
        image_roles=[x.strip() for x in args.image_roles.split(",") if x.strip()],
        max_images=args.max_images,
    )

    if not selected_images:
        return normalize_review(
            region_id=region_id,
            raw_output="",
            parsed={
                "region_id": region_id,
                "decision": "manual_review",
                "crop_quality": "uncertain",
                "selected_layout_ids": [],
                "excluded_layout_ids": [],
                "merge_with_region_ids": [],
                "split_into": [],
                "final_bbox": None,
                "bbox_padding_px": 12,
                "confidence": 0.0,
                "reason": "No valid images found in request.",
            },
        )

    prompt = build_prompt(
        request=request,
        max_group_text_chars=args.max_group_text_chars,
    )

    messages = build_qwen_messages(
        request=request,
        selected_images=selected_images,
        prompt=prompt,
    )

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

    if torch.cuda.is_available():
        inputs = inputs.to("cuda")

    generate_kwargs = {
        "max_new_tokens": args.max_new_tokens,
        "do_sample": args.do_sample,
    }

    if args.do_sample:
        generate_kwargs["temperature"] = args.temperature
        generate_kwargs["top_p"] = args.top_p

    with torch.no_grad():
        generated_ids = model.generate(
            **inputs,
            **generate_kwargs,
        )

    input_len = inputs["input_ids"].shape[1]
    generated_trimmed = generated_ids[:, input_len:]

    output_text = processor.batch_decode(
        generated_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]

    parsed = extract_json_object(output_text)

    review = normalize_review(
        region_id=region_id,
        raw_output=output_text,
        parsed=parsed,
    )

    review["_request_meta"] = {
        "group_id": request.get("group_id"),
        "page_no": request.get("page_no"),
        "group_type": request.get("group_type"),
        "used_images": selected_images,
    }

    return review


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Qwen2.5-VL review for semantic-group evidence regions."
    )

    parser.add_argument("--model-path", required=True)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--output", required=True)

    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--resume", action="store_true")

    parser.add_argument(
        "--image-roles",
        default="original_page_image,annotated_page_image,evidence_crop",
        help="Comma-separated image roles to send to VLM.",
    )
    parser.add_argument("--max-images", type=int, default=3)

    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--max-group-text-chars", type=int, default=1800)

    parser.add_argument("--do-sample", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--top-p", type=float, default=0.9)

    parser.add_argument(
        "--dtype",
        choices=["bfloat16", "float16", "float32"],
        default="bfloat16",
    )
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--local-files-only", action="store_true")

    parser.add_argument("--min-pixels", type=int, default=256 * 28 * 28)
    parser.add_argument("--max-pixels", type=int, default=1280 * 1280)

    args = parser.parse_args()

    request_path = Path(args.requests)
    output_path = Path(args.output)

    requests = load_jsonl(request_path)

    if args.start:
        requests = requests[args.start :]

    if args.limit is not None:
        requests = requests[: args.limit]

    done_ids = load_done_region_ids(output_path) if args.resume else set()

    print(f"[INFO] loaded requests: {len(requests)}")
    print(f"[INFO] done ids: {len(done_ids)}")
    print(f"[INFO] output: {output_path}")

    model, processor = load_qwen_model(args)

    for request in tqdm(requests, desc="VLM evidence review"):
        region_id = str(request.get("region_id", "unknown_region"))

        if args.resume and region_id in done_ids:
            continue

        try:
            review = run_one_request(
                model=model,
                processor=processor,
                request=request,
                args=args,
            )
        except Exception as e:
            review = normalize_review(
                region_id=region_id,
                raw_output="",
                parsed={
                    "region_id": region_id,
                    "decision": "manual_review",
                    "crop_quality": "uncertain",
                    "selected_layout_ids": [],
                    "excluded_layout_ids": [],
                    "merge_with_region_ids": [],
                    "split_into": [],
                    "final_bbox": None,
                    "bbox_padding_px": 12,
                    "confidence": 0.0,
                    "reason": f"Runtime error: {repr(e)}",
                },
            )

        append_jsonl(output_path, review)

    print(f"[OK] saved reviews to: {output_path}")


if __name__ == "__main__":
    main()