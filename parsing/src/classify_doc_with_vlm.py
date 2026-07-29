#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
classify_doc_with_vlm_fixed.py

Ask a local VLM, e.g. Qwen2.5-VL, to classify a PDF-derived document type
and write doc_profile.json.

Doc types:
- magazine_issue
- single_paper
- report_or_booklet
- slides_or_poster
- book_chapter
- unknown_mixed
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image


PAGE_RE = re.compile(r"page_(\d+)")
HTML_COMMENT_RE = re.compile(r"^\s*<!--.*?-->\s*$")
META_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?"
    r"(?:block_id|matched_region|matched_region_id|matched_region_ids|bbox|deepseek_bbox|bbox_source|bbox_granularity|layout_type|region_type)"
    r"\s*[:：].*$",
    re.IGNORECASE,
)

DOC_TYPES = [
    "magazine_issue",
    "single_paper",
    "report_or_booklet",
    "slides_or_poster",
    "book_chapter",
    "unknown_mixed",
]


def natural_page_key(value: str) -> Tuple[int, str]:
    match = PAGE_RE.search(str(value))
    if match:
        return int(match.group(1)), str(value)
    return 10**9, str(value)


def find_page_images(image_root: Path) -> Dict[str, Path]:
    image_root = Path(image_root)
    out: Dict[str, Path] = {}

    for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp"]:
        for p in image_root.glob(ext):
            match = PAGE_RE.search(p.stem)
            if match:
                page_id = "page_{:04d}".format(int(match.group(1)))
                out.setdefault(page_id, p)

    for page_dir in sorted(image_root.rglob("page_*")):
        if not page_dir.is_dir():
            continue

        match = PAGE_RE.search(page_dir.name)
        if not match:
            continue

        page_id = "page_{:04d}".format(int(match.group(1)))
        candidates = [
            "page.png", "page.jpg", "page.jpeg",
            "raw.png", "raw.jpg", "raw.jpeg",
            "origin.png", "origin.jpg",
            "result.png", "result.jpg",
            "image.png", "image.jpg",
            "result_with_boxes.jpg",
        ]

        for name in candidates:
            candidate = page_dir / name
            if candidate.exists():
                out.setdefault(page_id, candidate)
                break

    return dict(sorted(out.items(), key=lambda kv: natural_page_key(kv[0])))


def find_page_mds(md_root: Path) -> Dict[str, Path]:
    md_root = Path(md_root)
    out: Dict[str, Path] = {}

    for p in sorted(md_root.rglob("*.md")):
        match = PAGE_RE.search(p.stem)
        if match:
            page_id = "page_{:04d}".format(int(match.group(1)))
            out[page_id] = p

    return dict(sorted(out.items(), key=lambda kv: natural_page_key(kv[0])))


def select_pages(page_ids: List[str], front_pages: int, back_pages: int) -> List[str]:
    page_ids = sorted(set(page_ids), key=natural_page_key)

    selected = page_ids[:front_pages]
    if back_pages > 0:
        selected += page_ids[-back_pages:]

    seen = set()
    final = []
    for page_id in selected:
        if page_id not in seen:
            final.append(page_id)
            seen.add(page_id)

    return final


def clean_md_text(text: str, max_chars: int) -> str:
    lines = []

    for line in text.splitlines():
        if HTML_COMMENT_RE.match(line):
            continue
        if META_LINE_RE.match(line):
            continue

        low = line.lower()
        if (
            "deepseek_bbox" in low
            or "matched_region" in low
            or "bbox_granularity" in low
            or "bbox_source" in low
        ):
            continue

        lines.append(line)

    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()

    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[TRUNCATED]"

    return text


def read_page_snippets(
    md_paths: Dict[str, Path],
    page_ids: List[str],
    max_chars_per_page: int,
) -> Dict[str, str]:
    snippets: Dict[str, str] = {}

    for page_id in page_ids:
        p = md_paths.get(page_id)
        if not p or not p.exists():
            snippets[page_id] = ""
            continue

        raw = p.read_text(encoding="utf-8", errors="replace")
        snippets[page_id] = clean_md_text(raw, max_chars_per_page)

    return snippets


def validate_images(image_paths: List[Path]) -> None:
    for p in image_paths:
        try:
            with Image.open(p) as img:
                img.verify()
        except Exception as exc:
            raise RuntimeError("Cannot open image: {} ({})".format(p, exc)) from exc


def build_prompt(doc_id: str, selected_pages: List[str], snippets: Dict[str, str]) -> str:
    page_text_sections = []

    for page_id in selected_pages:
        txt = snippets.get(page_id, "")
        if not txt:
            txt = "[No OCR snippet available for this page]"
        page_text_sections.append("### {} OCR snippet\n{}".format(page_id, txt))

    page_text = "\n\n".join(page_text_sections)

    schema = {
        "doc_id": doc_id,
        "doc_type": "magazine_issue | single_paper | report_or_booklet | slides_or_poster | book_chapter | unknown_mixed",
        "confidence": "float between 0 and 1",
        "segmentation_strategy": "article_first | section_first | chapter_section_first | page_slide_first | heading_page_fallback",
        "node_strategy": "one_article_one_main_node | section_nodes | chapter_section_nodes | page_nodes | fallback_heading_nodes",
        "expected_node_unit": "article | section | chapter_or_section | page | heading_group",
        "contains_multiple_articles": "boolean",
        "contains_advertisements": "boolean",
        "contains_publication_metadata": "boolean",
        "contains_references": "boolean",
        "contains_cover": "boolean",
        "page_role_hints": [
            {
                "page_id": "page_0001",
                "role": "cover | toc | article_start | article_body | paper_first_page | section_page | references | advertisement | publication_metadata | unknown",
                "reason": "short reason"
            }
        ],
        "exclude_from_main_graph": [
            "advertisement",
            "publication_metadata",
            "imprint",
            "contact_info"
        ],
        "node_budget": {
            "target_nodes": "integer",
            "max_nodes": "integer"
        },
        "evidence": [
            "brief visual/textual evidence supporting the classification"
        ],
        "warnings": [
            "uncertainties or possible failure modes"
        ]
    }

    schema_json = json.dumps(schema, ensure_ascii=False, indent=2)
    selected_json = json.dumps(selected_pages, ensure_ascii=False)

    prompt = """
You are classifying a PDF-derived document for a document-to-wiki graph pipeline.

You are given selected page images and OCR snippets from the first pages and last pages.
The OCR may contain errors or hallucinated text. Use the page images as the primary evidence and OCR snippets only as auxiliary hints.

Task:
Classify the whole document type and recommend the segmentation/node-generation strategy.

Allowed doc_type values:
- magazine_issue: a whole magazine issue, newsletter issue, or periodical containing multiple articles plus possible ads/metadata.
- single_paper: one scientific/academic paper, usually with title/authors/abstract/sections/references.
- report_or_booklet: a report, white paper, booklet, manual-like document with chapters/sections.
- slides_or_poster: slide deck, poster, or page-as-slide document.
- book_chapter: a chapter or section from a book.
- unknown_mixed: unclear or mixed document.

Important decision rule:
- If it is a magazine issue, the main unit should be article.
- If it is a single academic paper, the main unit should be section.
- If it is a report/booklet, the main unit should be chapter or major section.
- If uncertain, choose unknown_mixed and recommend heading_page_fallback.

Return ONLY valid JSON.
Do not use Markdown.
Do not add explanations outside JSON.
Use exactly this schema shape, but fill values with your decision:

SCHEMA_JSON_PLACEHOLDER

Selected page ids:
SELECTED_PAGES_PLACEHOLDER

OCR snippets:
PAGE_TEXT_PLACEHOLDER
""".strip()

    prompt = prompt.replace("SCHEMA_JSON_PLACEHOLDER", schema_json)
    prompt = prompt.replace("SELECTED_PAGES_PLACEHOLDER", selected_json)
    prompt = prompt.replace("PAGE_TEXT_PLACEHOLDER", page_text)

    return prompt


def extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])

    raise ValueError("Could not parse JSON from model output:\n{}".format(text[:2000]))


def normalize_profile(profile: Dict[str, Any], doc_id: str, selected_pages: List[str]) -> Dict[str, Any]:
    profile.setdefault("doc_id", doc_id)
    profile.setdefault("confidence", 0.0)
    profile.setdefault("page_role_hints", [])
    profile.setdefault("evidence", [])
    profile.setdefault("warnings", [])

    if profile.get("doc_type") not in DOC_TYPES:
        profile["warnings"].append("Invalid doc_type from model: {}".format(profile.get("doc_type")))
        profile["doc_type"] = "unknown_mixed"

    try:
        profile["confidence"] = float(profile.get("confidence", 0.0))
    except Exception:
        profile["confidence"] = 0.0

    profile["confidence"] = max(0.0, min(1.0, profile["confidence"]))

    defaults = {
        "magazine_issue": ("article_first", "one_article_one_main_node", "article", 60, 100),
        "single_paper": ("section_first", "section_nodes", "section", 20, 40),
        "report_or_booklet": ("chapter_section_first", "chapter_section_nodes", "chapter_or_section", 40, 80),
        "slides_or_poster": ("page_slide_first", "page_nodes", "page", 20, 80),
        "book_chapter": ("chapter_section_first", "chapter_section_nodes", "section", 25, 60),
        "unknown_mixed": ("heading_page_fallback", "fallback_heading_nodes", "heading_group", 30, 80),
    }

    seg, node, unit, target, max_nodes = defaults[profile["doc_type"]]

    profile.setdefault("segmentation_strategy", seg)
    profile.setdefault("node_strategy", node)
    profile.setdefault("expected_node_unit", unit)

    if not isinstance(profile.get("node_budget"), dict):
        profile["node_budget"] = {}

    profile["node_budget"].setdefault("target_nodes", target)
    profile["node_budget"].setdefault("max_nodes", max_nodes)

    profile["_classification_meta"] = {
        "method": "vlm_doc_profile",
        "selected_pages": selected_pages,
        "allowed_doc_types": DOC_TYPES,
    }

    return profile


def load_qwen_vl(model_path: str):
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
                "Please check transformers version."
            ) from exc

    model_kwargs: Dict[str, Any] = {
        "device_map": "auto",
        "trust_remote_code": True,
    }

    if torch.cuda.is_available():
        model_kwargs["torch_dtype"] = torch.bfloat16
    else:
        model_kwargs["torch_dtype"] = "auto"

    model = model_cls.from_pretrained(model_path, **model_kwargs)
    processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)

    return model, processor


def run_qwen_vl(
    model_path: str,
    image_paths: List[Path],
    prompt: str,
    max_new_tokens: int,
) -> str:
    import torch

    try:
        from qwen_vl_utils import process_vision_info
    except Exception as exc:
        raise RuntimeError(
            "Missing qwen-vl-utils. Try:\n"
            "  pip install qwen-vl-utils\n"
            "or use an environment where qwen_vl_utils is available."
        ) from exc

    model, processor = load_qwen_vl(model_path)

    content = []
    for p in image_paths:
        content.append({"type": "image", "image": str(p)})
    content.append({"type": "text", "text": prompt})

    messages = [{"role": "user", "content": content}]

    chat_text = processor.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    image_inputs, video_inputs = process_vision_info(messages)

    inputs = processor(
        text=[chat_text],
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

    generated_ids_trimmed = []
    for input_ids, output_ids in zip(inputs.input_ids, generated_ids):
        generated_ids_trimmed.append(output_ids[len(input_ids):])

    output_text = processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]

    return output_text


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--image-root", required=True)
    parser.add_argument("--md-root", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--out", required=True)

    parser.add_argument("--front-pages", type=int, default=3)
    parser.add_argument("--back-pages", type=int, default=2)
    parser.add_argument("--max-chars-per-page", type=int, default=2500)
    parser.add_argument("--max-new-tokens", type=int, default=1200)
    parser.add_argument("--save-prompt", default=None)
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()

    image_root = Path(args.image_root)
    md_root = Path(args.md_root)
    out_path = Path(args.out)

    page_images = find_page_images(image_root)
    page_mds = find_page_mds(md_root)

    all_page_ids = sorted(set(page_images.keys()) | set(page_mds.keys()), key=natural_page_key)
    selected_pages = select_pages(all_page_ids, args.front_pages, args.back_pages)

    if not selected_pages:
        raise SystemExit("No pages found from image-root or md-root.")

    selected_image_paths = []
    missing_images = []

    for page_id in selected_pages:
        image_path = page_images.get(page_id)
        if image_path:
            selected_image_paths.append(image_path)
        else:
            missing_images.append(page_id)

    if not selected_image_paths:
        raise SystemExit("No selected page images found. VLM classification requires images.")

    validate_images(selected_image_paths)

    snippets = read_page_snippets(page_mds, selected_pages, args.max_chars_per_page)
    prompt = build_prompt(args.doc_id, selected_pages, snippets)

    if args.save_prompt:
        prompt_path = Path(args.save_prompt)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        print("[OK] wrote prompt: {}".format(prompt_path))

    if args.dry_run:
        print(prompt)
        return

    if missing_images:
        print("[WARN] selected pages missing images: {}".format(missing_images), file=sys.stderr)

    print("[INFO] doc_id: {}".format(args.doc_id))
    print("[INFO] selected pages: {}".format(selected_pages))
    print("[INFO] selected images:")
    for p in selected_image_paths:
        print("  - {}".format(p))

    raw_output = run_qwen_vl(
        model_path=args.model_path,
        image_paths=selected_image_paths,
        prompt=prompt,
        max_new_tokens=args.max_new_tokens,
    )

    try:
        profile = extract_json(raw_output)
        profile = normalize_profile(profile, args.doc_id, selected_pages)
    except Exception as exc:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        failed_path = out_path.with_suffix(".raw_failed.txt")
        failed_path.write_text(raw_output, encoding="utf-8")
        raise RuntimeError(
            "Model output was not valid JSON. Raw output saved to {}".format(failed_path)
        ) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    raw_path = out_path.with_suffix(".raw.txt")
    raw_path.write_text(raw_output, encoding="utf-8")

    print("[OK] wrote doc_profile: {}".format(out_path))
    print("[OK] wrote raw model output: {}".format(raw_path))
    print("")
    print("Summary:")
    print("  doc_type: {}".format(profile.get("doc_type")))
    print("  confidence: {}".format(profile.get("confidence")))
    print("  segmentation_strategy: {}".format(profile.get("segmentation_strategy")))
    print("  node_strategy: {}".format(profile.get("node_strategy")))


if __name__ == "__main__":
    main()
