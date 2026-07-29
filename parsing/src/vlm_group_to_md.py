#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
VLM-first semantic grouping for DeepSeekOCR2 outputs.

Input example:
output/render_result/<doc_name>/page_0006/
  ├── ocr.md
  ├── page.png
  ├── images/0.jpg
  ├── result_with_boxes.jpg
  └── ...

Your ocr.md format:
<!-- bbox: {"id": 0, "bbox_index": 0, "type": "image", "raw_bbox": [...], "pixel_bbox": [...], ...} -->
![](images/0.jpg)

<!-- bbox: {"id": 0, "bbox_index": 0, "type": "figure_title", ...} -->
Figure 1: ...

What this script does:
1. Parse raw blocks from ocr.md.
2. Preserve full bbox metadata and raw markdown.
3. Send full page image + visual block crop images + block list to Qwen2.5-VL.
4. Qwen2.5-VL only outputs markdown group assignment:
   - type
   - members
5. No reason/explanation field.
6. Python reconstructs semantic_groups.md from original blocks.
7. Every raw block is guaranteed to appear in exactly one semantic group.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
from qwen_vl_utils import process_vision_info


# ============================================================
# Basic utilities
# ============================================================

def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "doc"


def stable_hash(text: str, n: int = 6) -> str:
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:n]


def clean_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def simple_token_count(text: str) -> int:
    if not text:
        return 0

    cjk = len(re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text))
    words = len(re.findall(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)?", text))
    return cjk + words


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def is_valid_ocr_md(path: Path) -> bool:
    if not path.exists():
        return False

    text = read_text(path).strip()
    return bool(text) and text.lower() != "none"


def parse_page_no(page_dir: Path) -> int:
    m = re.search(r"page[_-]?(\d+)", page_dir.name, flags=re.IGNORECASE)
    return int(m.group(1)) if m else 0


def union_bbox(bboxes: List[Optional[List[float]]]) -> Optional[List[float]]:
    valid = [b for b in bboxes if b and len(b) == 4]

    if not valid:
        return None

    return [
        min(b[0] for b in valid),
        min(b[1] for b in valid),
        max(b[2] for b in valid),
        max(b[3] for b in valid),
    ]


def md_escape_code_fence(text: Any) -> str:
    if text is None:
        return ""

    return str(text).replace("```", "``\\`")


# ============================================================
# Discover input files
# ============================================================

def discover_documents(render_dir: Path) -> List[Path]:
    docs: List[Path] = []

    for child in sorted(render_dir.iterdir()):
        if child.is_dir() and list(child.glob("page_*/ocr.md")):
            docs.append(child)

    # Fallback: render_dir itself is one document.
    if not docs and list(render_dir.glob("page_*/ocr.md")):
        docs.append(render_dir)

    return docs


def discover_pages(doc_dir: Path) -> List[Path]:
    pages = [p for p in doc_dir.glob("page_*") if p.is_dir()]
    return sorted(pages, key=parse_page_no)


def find_page_image(page_dir: Path) -> Optional[str]:
    page_png = page_dir / "page.png"

    if page_png.exists():
        return str(page_png.resolve())

    candidates = []
    for pat in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
        candidates.extend(page_dir.glob(pat))

    if not candidates:
        return None

    preferred = [
        p for p in candidates
        if "box" not in p.name.lower()
        and "result" not in p.name.lower()
        and "preview" not in p.name.lower()
    ]

    chosen = preferred[0] if preferred else candidates[0]
    return str(chosen.resolve())


def source_files_for_page(page_dir: Path) -> Dict[str, Optional[str]]:
    files = {
        "ocr_md": page_dir / "ocr.md",
        "page_image": page_dir / "page.png",
        "result_mmd": page_dir / "result.mmd",
        "raw_response": page_dir / "raw_response.txt",
        "result_with_boxes": page_dir / "result_with_boxes.jpg",
        "bboxes_preview": page_dir / "bboxes_preview.jpg",
        "bbox_items": page_dir / "bbox_items.json",
        "bbox_items_official": page_dir / "bbox_items_official.json",
        "matches_ref_raw": page_dir / "matches_ref_raw.txt",
    }

    return {
        k: str(v.resolve()) if v.exists() else None
        for k, v in files.items()
    }


# ============================================================
# Parse ocr.md
# ============================================================

def parse_bbox_comment(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse:
    <!-- bbox: {"id": 0, "bbox_index": 0, "type": "image", ...} -->
    """
    m = re.search(r"<!--\s*bbox:\s*(\{.*?\})\s*-->", line)

    if not m:
        return None

    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def extract_image_path_from_markdown(raw_markdown: str, page_dir: Path) -> Optional[str]:
    """
    Parse:
    ![](images/0.jpg)
    """
    m = re.search(r"!\[[^\]]*\]\(([^)]+)\)", raw_markdown)

    if not m:
        return None

    rel_path = m.group(1).strip()

    if rel_path.startswith("http://") or rel_path.startswith("https://"):
        return rel_path

    path = page_dir / rel_path

    if path.exists():
        return str(path.resolve())

    return str(path.resolve())


def markdown_to_text(raw_markdown: str, block_type: str) -> str:
    raw_markdown = raw_markdown.strip()

    if block_type == "image":
        return ""

    # Remove markdown image links.
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", raw_markdown)
    return text.strip()


def parse_ocr_md_blocks(
    *,
    md_path: Path,
    doc_id: str,
    page_id: str,
    page_no: int,
) -> List[Dict[str, Any]]:
    """
    Each bbox comment starts a new block.
    Everything until the next bbox comment belongs to this block.
    """
    page_dir = md_path.parent
    page_image = find_page_image(page_dir)
    source_files = source_files_for_page(page_dir)

    lines = md_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    blocks: List[Dict[str, Any]] = []

    current_bbox_meta: Optional[Dict[str, Any]] = None
    current_lines: List[str] = []
    order = 0

    def flush_current() -> None:
        nonlocal current_bbox_meta, current_lines, order, blocks

        if current_bbox_meta is None:
            current_lines = []
            return

        raw_markdown = "\n".join(current_lines).strip()
        block_type = current_bbox_meta.get("type", "unknown")

        short_id = f"b{order:04d}"
        block_id = f"{page_id}_{short_id}"

        image_path = None
        if block_type == "image":
            image_path = extract_image_path_from_markdown(raw_markdown, page_dir)

        block = {
            "block_id": block_id,
            "short_id": short_id,
            "doc_id": doc_id,
            "page_id": page_id,
            "page_no": page_no,
            "order": order,

            # DeepSeekOCR2 type from bbox comment.
            "type": block_type,

            # Full bbox metadata from ocr.md. Do not drop anything.
            "bbox_meta": current_bbox_meta,

            # Convenient aliases.
            "raw_bbox": current_bbox_meta.get("raw_bbox"),
            "pixel_bbox": current_bbox_meta.get("pixel_bbox"),
            "bbox": current_bbox_meta.get("pixel_bbox") or current_bbox_meta.get("raw_bbox"),
            "bbox_index": current_bbox_meta.get("bbox_index"),
            "bbox_scale": current_bbox_meta.get("bbox_scale"),
            "image_width": current_bbox_meta.get("image_width"),
            "image_height": current_bbox_meta.get("image_height"),

            # Original parsing content.
            "raw_markdown": raw_markdown,
            "text": markdown_to_text(raw_markdown, block_type),

            # Crop image for visual block.
            "image_path": image_path,

            # Provenance.
            "page_dir": str(page_dir.resolve()),
            "page_image": page_image,
            "source_files": source_files,
        }

        blocks.append(block)

        order += 1
        current_bbox_meta = None
        current_lines = []

    for line in lines:
        meta = parse_bbox_comment(line)

        if meta is not None:
            flush_current()
            current_bbox_meta = meta
            current_lines = []
        else:
            current_lines.append(line)

    flush_current()
    return blocks


# ============================================================
# Prompt
# ============================================================

def truncate_for_prompt(text: str, max_chars: int = 1200) -> str:
    text = text.strip()

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "\n...[TRUNCATED]"


def build_grouping_prompt(blocks: List[Dict[str, Any]]) -> str:
    """
    VLM receives:
    - full page image
    - crop images for visual blocks
    - this block list

    VLM output:
    Markdown only, type + members.
    No reason.
    """
    block_sections = []

    for b in blocks:
        content = b.get("text") or b.get("raw_markdown") or ""
        content = truncate_for_prompt(content, 1200)

        block_sections.append(
            f"""### {b["short_id"]}
full_block_id: {b["block_id"]}
order: {b["order"]}
type: {b["type"]}
bbox: {b.get("bbox")}
image_path: {b.get("image_path")}

content:
{content}
"""
        )

    blocks_text = "\n".join(block_sections)

    return f"""
You are given:
1. A full document page image.
2. Optional crop images for visual blocks.
3. Existing DeepSeek-OCR-2 parsing blocks.

Your task is ONLY to group the existing blocks into semantic groups.

Do NOT perform OCR.
Do NOT rewrite block text.
Do NOT create new text.
Do NOT invent block IDs.
Use only the provided short block IDs, such as b0000, b0001.

Every block must appear in exactly one group.
When uncertain, keep blocks separate.
Preserve reading order.
Visual blocks with type=image may represent a figure, diagram, chart, table crop, or other visual element.
Group a visual block with caption/title text only when they clearly belong together.
Do not merge unrelated text just because it is nearby.

Output Markdown only.
Output only this structure:

# Semantic Groups

## group_0001
type: figure
members:
- b0000
- b0001

## group_0002
type: text_chunk
members:
- b0002

Allowed group types:
- text_chunk
- figure
- table
- visual_asset
- caption
- formula
- list
- metadata
- unknown

DeepSeek-OCR-2 parsing blocks:

{blocks_text}
""".strip()


# ============================================================
# Multimodal message construction
# ============================================================

def build_qwen_messages(
    *,
    page_image: Optional[str],
    blocks: List[Dict[str, Any]],
    max_visual_crops: int,
) -> List[Dict[str, Any]]:
    """
    We explicitly give images to VLM:
    - full page image
    - visual crop images for type=image blocks
    """
    content: List[Dict[str, Any]] = []

    if page_image and Path(page_image).exists():
        content.append({"type": "text", "text": "Full page image:"})
        content.append({"type": "image", "image": page_image})

    visual_blocks = [
        b for b in blocks
        if b.get("type") == "image"
        and b.get("image_path")
        and Path(str(b["image_path"])).exists()
    ]

    for b in visual_blocks[:max_visual_crops]:
        content.append({
            "type": "text",
            "text": f"Crop image for visual block {b['short_id']}:"
        })
        content.append({
            "type": "image",
            "image": b["image_path"],
        })

    if len(visual_blocks) > max_visual_crops:
        content.append({
            "type": "text",
            "text": (
                f"Note: only the first {max_visual_crops} visual crop images "
                f"are attached. Remaining visual blocks are still listed in text."
            ),
        })

    content.append({
        "type": "text",
        "text": build_grouping_prompt(blocks),
    })

    return [
        {
            "role": "user",
            "content": content,
        }
    ]


# ============================================================
# Parse VLM Markdown output
# ============================================================

def normalize_group_type(group_type: str) -> str:
    group_type = group_type.strip().lower()
    group_type = group_type.replace("-", "_").replace(" ", "_")

    allowed = {
        "text_chunk",
        "figure",
        "table",
        "visual_asset",
        "caption",
        "formula",
        "list",
        "metadata",
        "unknown",
    }

    if group_type in allowed:
        return group_type

    return "unknown"


def extract_member_ids_from_line(line: str) -> List[str]:
    line = line.strip()
    line = line.strip("-").strip()
    line = line.replace("`", "").strip()

    ids = []

    # short IDs like b0000
    for m in re.finditer(r"\bb\d{4}\b", line):
        ids.append(m.group(0))

    # full IDs ending with _p0006_b0000
    if not ids:
        m = re.search(r"([A-Za-z0-9_]+_p\d{4}_b\d{4})", line)
        if m:
            ids.append(m.group(1))

    return ids


def parse_vlm_group_markdown(md: str) -> List[Dict[str, Any]]:
    """
    Parse:

    # Semantic Groups

    ## group_0001
    type: figure
    members:
    - b0000
    - b0001
    """
    groups: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    md = md.strip()
    md = re.sub(r"^```(?:markdown|md)?", "", md, flags=re.IGNORECASE).strip()
    md = re.sub(r"```$", "", md).strip()

    for raw_line in md.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("## "):
            if current is not None:
                groups.append(current)

            current = {
                "group_type": "unknown",
                "member_ids": [],
            }
            continue

        if current is None:
            continue

        if line.lower().startswith("type:"):
            group_type = line.split(":", 1)[1].strip()
            current["group_type"] = normalize_group_type(group_type)
            continue

        if line.startswith("- "):
            mids = extract_member_ids_from_line(line)
            current["member_ids"].extend(mids)

    if current is not None:
        groups.append(current)

    return groups


# ============================================================
# Qwen-VL
# ============================================================

def load_qwen_model(model_path: str):
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_path,
        torch_dtype="auto",
        device_map="auto",
        local_files_only=True,
    )

    processor = AutoProcessor.from_pretrained(
        model_path,
        local_files_only=True,
    )

    model.eval()
    return model, processor


def run_qwen_page(
    *,
    model,
    processor,
    page_image: Optional[str],
    blocks: List[Dict[str, Any]],
    max_new_tokens: int,
    max_visual_crops: int,
) -> str:
    messages = build_qwen_messages(
        page_image=page_image,
        blocks=blocks,
        max_visual_crops=max_visual_crops,
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

    with torch.no_grad():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )

    generated_ids_trimmed = [
        output_ids[len(input_ids):]
        for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
    ]

    output_text = processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]

    return output_text.strip()


# ============================================================
# Validate and reconstruct semantic groups
# ============================================================

def fallback_group_type_for_block(block: Dict[str, Any]) -> str:
    t = block.get("type")

    if t == "image":
        return "visual_asset"

    if t in {"figure_title", "table_title"}:
        return "caption"

    if t == "table":
        return "table"

    if t == "formula":
        return "formula"

    if t == "list":
        return "list"

    return "text_chunk"


def resolve_member_id(
    mid: str,
    *,
    short_to_full: Dict[str, str],
    full_id_set: set,
) -> Optional[str]:
    mid = mid.strip().replace("`", "")

    if mid in short_to_full:
        return short_to_full[mid]

    if mid in full_id_set:
        return mid

    m = re.search(r"\bb\d{4}\b", mid)
    if m and m.group(0) in short_to_full:
        return short_to_full[m.group(0)]

    return None


def validate_group_assignments(
    *,
    vlm_groups: List[Dict[str, Any]],
    blocks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Guarantee:
    - every block appears exactly once
    - invalid IDs are ignored
    - duplicate IDs are ignored after first use
    - missing blocks become singleton groups
    """
    block_ids = [b["block_id"] for b in blocks]
    full_id_set = set(block_ids)
    short_to_full = {b["short_id"]: b["block_id"] for b in blocks}
    block_map = {b["block_id"]: b for b in blocks}
    order_map = {b["block_id"]: b["order"] for b in blocks}

    used = set()
    cleaned: List[Dict[str, Any]] = []

    for g in vlm_groups:
        gtype = normalize_group_type(g.get("group_type", "unknown"))
        member_ids: List[str] = []

        for raw_mid in g.get("member_ids", []):
            full_id = resolve_member_id(
                raw_mid,
                short_to_full=short_to_full,
                full_id_set=full_id_set,
            )

            if full_id is None:
                continue

            if full_id in used:
                continue

            member_ids.append(full_id)
            used.add(full_id)

        if member_ids:
            cleaned.append(
                {
                    "group_type": gtype,
                    "member_ids": member_ids,
                }
            )

    # Missing blocks become singleton groups.
    for bid in block_ids:
        if bid not in used:
            b = block_map[bid]
            cleaned.append(
                {
                    "group_type": fallback_group_type_for_block(b),
                    "member_ids": [bid],
                }
            )
            used.add(bid)

    cleaned.sort(key=lambda g: min(order_map[mid] for mid in g["member_ids"]))

    return cleaned


def build_text_for_group(members: List[Dict[str, Any]]) -> str:
    parts = []

    for m in members:
        if m.get("type") == "image":
            continue

        t = m.get("text")
        if t:
            parts.append(t)

    return "\n\n".join(parts).strip()


def build_raw_markdown_for_group(members: List[Dict[str, Any]]) -> str:
    parts = []

    for m in members:
        raw = m.get("raw_markdown")
        if raw:
            parts.append(raw)

    return "\n\n".join(parts).strip()


def make_semantic_group(
    *,
    page_id: str,
    group_index: int,
    group_type: str,
    member_ids: List[str],
    block_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Reconstruct semantic group from original raw blocks.
    Full member dictionaries are copied.
    """
    members = [dict(block_map[mid]) for mid in member_ids if mid in block_map]

    text = build_text_for_group(members)
    raw_markdown = build_raw_markdown_for_group(members)

    has_visual = any(m.get("type") == "image" for m in members)

    if has_visual and not text:
        # Preserve VLM's visual group type if it says figure/table.
        if group_type not in {"figure", "table", "visual_asset"}:
            group_type = "visual_asset"

        text_for_embedding = ""
        should_text_embed = False
        embedding_policy = "skip_text_embedding_until_vlm_description"

    elif text:
        text_for_embedding = text
        should_text_embed = True

        if has_visual:
            embedding_policy = "text_embedding_with_visual_context"
        else:
            embedding_policy = "text_embedding"

    else:
        text_for_embedding = ""
        should_text_embed = False
        embedding_policy = "skip_text_embedding_empty"

    pixel_bbox = union_bbox([m.get("pixel_bbox") for m in members])
    raw_bbox = union_bbox([m.get("raw_bbox") for m in members])

    return {
        "group_id": f"{page_id}_g{group_index:04d}",
        "group_type": group_type,

        "doc_id": members[0].get("doc_id") if members else None,
        "page_id": members[0].get("page_id") if members else None,
        "page_no": members[0].get("page_no") if members else None,
        "group_index": group_index,

        "member_ids": [m["block_id"] for m in members],

        # Full original parsing information.
        "members": members,

        # Derived fields.
        "text": text,
        "raw_markdown": raw_markdown,
        "text_for_embedding": text_for_embedding,
        "should_text_embed": should_text_embed,
        "embedding_policy": embedding_policy,
        "token_estimate": simple_token_count(text_for_embedding or text),

        "pixel_bbox": pixel_bbox,
        "raw_bbox": raw_bbox,
        "bbox": pixel_bbox or raw_bbox,

        "page_image": members[0].get("page_image") if members else None,
        "page_dir": members[0].get("page_dir") if members else None,
        "source_files": members[0].get("source_files") if members else {},
    }


def add_group_adjacency(groups: List[Dict[str, Any]]) -> None:
    for i, g in enumerate(groups):
        g["local_order"] = i
        g["prev_group_id"] = groups[i - 1]["group_id"] if i > 0 else None
        g["next_group_id"] = groups[i + 1]["group_id"] if i + 1 < len(groups) else None


# ============================================================
# Markdown writers
# ============================================================

def block_to_markdown(block: Dict[str, Any]) -> str:
    lines = []

    lines.append(f"## {block['block_id']}")
    lines.append("")
    lines.append(f"short_id: {block.get('short_id')}")
    lines.append(f"type: {block.get('type')}")
    lines.append(f"doc_id: {block.get('doc_id')}")
    lines.append(f"page_id: {block.get('page_id')}")
    lines.append(f"page_no: {block.get('page_no')}")
    lines.append(f"order: {block.get('order')}")
    lines.append(f"raw_bbox: {block.get('raw_bbox')}")
    lines.append(f"pixel_bbox: {block.get('pixel_bbox')}")
    lines.append(f"image_path: {block.get('image_path')}")
    lines.append(f"page_image: {block.get('page_image')}")
    lines.append("")
    lines.append("### Text")
    lines.append("")
    lines.append(block.get("text") or "[NO TEXT]")
    lines.append("")
    lines.append("### Raw Markdown")
    lines.append("")
    lines.append("```markdown")
    lines.append(md_escape_code_fence(block.get("raw_markdown") or ""))
    lines.append("```")
    lines.append("")
    lines.append("### bbox_meta")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(block.get("bbox_meta"), ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("### source_files")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(block.get("source_files"), ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    return "\n".join(lines).strip()


def group_to_markdown(group: Dict[str, Any]) -> str:
    lines = []

    lines.append(f"# {group['group_id']}")
    lines.append("")
    lines.append(f"type: {group.get('group_type')}")
    lines.append(f"doc_id: {group.get('doc_id')}")
    lines.append(f"page_id: {group.get('page_id')}")
    lines.append(f"page_no: {group.get('page_no')}")
    lines.append(f"local_order: {group.get('local_order')}")
    lines.append(f"prev_group_id: {group.get('prev_group_id')}")
    lines.append(f"next_group_id: {group.get('next_group_id')}")
    lines.append(f"raw_bbox: {group.get('raw_bbox')}")
    lines.append(f"pixel_bbox: {group.get('pixel_bbox')}")
    lines.append(f"page_image: {group.get('page_image')}")
    lines.append(f"should_text_embed: {group.get('should_text_embed')}")
    lines.append(f"embedding_policy: {group.get('embedding_policy')}")
    lines.append(f"token_estimate: {group.get('token_estimate')}")
    lines.append("")
    lines.append("## Member IDs")
    lines.append("")

    for mid in group.get("member_ids", []):
        lines.append(f"- {mid}")

    lines.append("")
    lines.append("## Text")
    lines.append("")
    lines.append(group.get("text") or "[NO TEXT]")

    lines.append("")
    lines.append("## Text for embedding")
    lines.append("")
    lines.append(group.get("text_for_embedding") or "[SKIP TEXT EMBEDDING]")

    lines.append("")
    lines.append("## Raw Markdown")
    lines.append("")
    lines.append("```markdown")
    lines.append(md_escape_code_fence(group.get("raw_markdown") or ""))
    lines.append("```")

    lines.append("")
    lines.append("## source_files")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(group.get("source_files"), ensure_ascii=False, indent=2))
    lines.append("```")

    lines.append("")
    lines.append("## Members")
    lines.append("")

    for m in group.get("members", []):
        lines.append(f"### {m['block_id']}")
        lines.append("")
        lines.append(f"short_id: {m.get('short_id')}")
        lines.append(f"type: {m.get('type')}")
        lines.append(f"order: {m.get('order')}")
        lines.append(f"raw_bbox: {m.get('raw_bbox')}")
        lines.append(f"pixel_bbox: {m.get('pixel_bbox')}")
        lines.append(f"image_path: {m.get('image_path')}")
        lines.append(f"page_image: {m.get('page_image')}")
        lines.append("")
        lines.append("#### Raw Markdown")
        lines.append("")
        lines.append("```markdown")
        lines.append(md_escape_code_fence(m.get("raw_markdown") or ""))
        lines.append("```")
        lines.append("")
        lines.append("#### bbox_meta")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(m.get("bbox_meta"), ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines).strip()


def write_md_file(path: Path, title: str, sections: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")

        for section in sections:
            f.write(section)
            f.write("\n\n---\n\n")


# ============================================================
# Page processing
# ============================================================

def process_page(
    *,
    page_dir: Path,
    doc_id: str,
    model,
    processor,
    max_new_tokens: int,
    max_visual_crops: int,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    page_no = parse_page_no(page_dir)
    page_id = f"{doc_id}_p{page_no:04d}"
    md_path = page_dir / "ocr.md"

    blocks = parse_ocr_md_blocks(
        md_path=md_path,
        doc_id=doc_id,
        page_id=page_id,
        page_no=page_no,
    )

    if not blocks:
        return [], [], ""

    page_image = find_page_image(page_dir)

    print(f"[VLM] {page_id}: {len(blocks)} blocks")

    try:
        raw_vlm_md = run_qwen_page(
            model=model,
            processor=processor,
            page_image=page_image,
            blocks=blocks,
            max_new_tokens=max_new_tokens,
            max_visual_crops=max_visual_crops,
        )
    except Exception as e:
        raw_vlm_md = (
            "# Semantic Groups\n\n"
            "<!-- VLM failed. Fallback singleton groups will be used. -->\n\n"
            f"<!-- ERROR: {repr(e)} -->\n"
        )
        print(f"[WARN] VLM failed on {page_id}: {e}")

    vlm_groups = parse_vlm_group_markdown(raw_vlm_md)

    cleaned_assignments = validate_group_assignments(
        vlm_groups=vlm_groups,
        blocks=blocks,
    )

    block_map = {b["block_id"]: b for b in blocks}

    groups = []
    for gi, assignment in enumerate(cleaned_assignments):
        group = make_semantic_group(
            page_id=page_id,
            group_index=gi,
            group_type=assignment["group_type"],
            member_ids=assignment["member_ids"],
            block_map=block_map,
        )
        groups.append(group)

    add_group_adjacency(groups)

    return blocks, groups, raw_vlm_md


# ============================================================
# Main
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--render-dir",
        type=Path,
        default=Path("output/render_result"),
        help="DeepSeekOCR2 output render directory.",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/processed_vlm_md"),
        help="Output directory for markdown files.",
    )

    parser.add_argument(
        "--model-path",
        type=str,
        default="external/models/Qwen2.5-VL-7B-Instruct",
        help="Local Qwen2.5-VL model path.",
    )

    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=1024,
        help="Max new tokens for Qwen grouping output.",
    )

    parser.add_argument(
        "--max-visual-crops",
        type=int,
        default=8,
        help="Maximum number of visual crop images attached per page.",
    )

    parser.add_argument(
        "--limit-pages",
        type=int,
        default=0,
        help="For testing. 0 means no limit.",
    )

    parser.add_argument(
        "--only-doc",
        type=str,
        default="",
        help="Only process document directory whose name contains this string.",
    )

    parser.add_argument(
        "--only-page",
        type=int,
        default=0,
        help="Only process one page number, e.g. 6 means page_0006.",
    )

    args = parser.parse_args()

    if not args.render_dir.exists():
        raise FileNotFoundError(f"render-dir not found: {args.render_dir}")

    docs = discover_documents(args.render_dir)

    if args.only_doc:
        docs = [d for d in docs if args.only_doc in d.name]

    if not docs:
        raise RuntimeError(f"No documents found under {args.render_dir}")

    print(f"Loading Qwen model from: {args.model_path}")
    model, processor = load_qwen_model(args.model_path)

    all_blocks: List[Dict[str, Any]] = []
    all_groups: List[Dict[str, Any]] = []
    vlm_assignment_sections: List[str] = []

    processed_pages = 0

    for doc_dir in docs:
        doc_id = f"{slugify(doc_dir.name)}_{stable_hash(str(doc_dir.resolve()), 6)}"

        for page_dir in discover_pages(doc_dir):
            page_no = parse_page_no(page_dir)

            if args.only_page and page_no != args.only_page:
                continue

            md_path = page_dir / "ocr.md"

            if not is_valid_ocr_md(md_path):
                continue

            if args.limit_pages and processed_pages >= args.limit_pages:
                break

            blocks, groups, raw_vlm_md = process_page(
                page_dir=page_dir,
                doc_id=doc_id,
                model=model,
                processor=processor,
                max_new_tokens=args.max_new_tokens,
                max_visual_crops=args.max_visual_crops,
            )

            all_blocks.extend(blocks)
            all_groups.extend(groups)

            page_id = f"{doc_id}_p{page_no:04d}"

            vlm_assignment_sections.append(
                f"# {page_id}\n\n"
                f"source_page_dir: {page_dir.resolve()}\n\n"
                f"```markdown\n{md_escape_code_fence(raw_vlm_md)}\n```"
            )

            processed_pages += 1

            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        if args.limit_pages and processed_pages >= args.limit_pages:
            break

    args.out_dir.mkdir(parents=True, exist_ok=True)

    write_md_file(
        args.out_dir / "blocks_raw.md",
        "Raw DeepSeekOCR2 Blocks",
        [block_to_markdown(b) for b in all_blocks],
    )

    write_md_file(
        args.out_dir / "vlm_group_assignments.md",
        "VLM Group Assignments",
        vlm_assignment_sections,
    )

    write_md_file(
        args.out_dir / "semantic_groups.md",
        "Semantic Groups",
        [group_to_markdown(g) for g in all_groups],
    )

    print()
    print(f"Saved: {args.out_dir / 'blocks_raw.md'}")
    print(f"Saved: {args.out_dir / 'vlm_group_assignments.md'}")
    print(f"Saved: {args.out_dir / 'semantic_groups.md'}")
    print(f"Processed pages: {processed_pages}")
    print(f"Raw blocks: {len(all_blocks)}")
    print(f"Semantic groups: {len(all_groups)}")


if __name__ == "__main__":
    main()