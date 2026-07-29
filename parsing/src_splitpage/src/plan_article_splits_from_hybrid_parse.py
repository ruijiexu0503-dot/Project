#!/usr/bin/env python3
"""Plan rough article/page-range splits from hybrid layout + DeepSeek OCR output."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


NON_ARTICLE_HEADINGS = {
    "abstract",
    "news",
    "careers",
    "conclusion",
    "conclusions",
    "discussion",
    "events",
    "experiment",
    "experiments",
    "introduction",
    "materials and methods",
    "method",
    "methods",
    "reviews",
    "references",
    "related work",
    "results",
    "results and discussion",
    "bookshelf",
    "opinion",
    "editorial",
    "advertiser index",
    "advertisers index",
    "advertising index",
    "products",
    "buyers guide",
    "calendar",
    "people",
    "appointments",
    "obituaries",
    "archive",
}

SCIENTIFIC_SECTION_HEADINGS = {
    "abstract",
    "introduction",
    "background",
    "related work",
    "method",
    "methods",
    "methodology",
    "materials and methods",
    "experiment",
    "experiments",
    "experimental setup",
    "results",
    "discussion",
    "results and discussion",
    "conclusion",
    "conclusions",
    "acknowledgements",
    "acknowledgments",
    "references",
    "bibliography",
    "appendix",
}

AD_WORDS = {
    "advertisement",
    "advertising",
    "available",
    "brochure",
    "company",
    "contact",
    "digitizer",
    "sales",
    "email",
    "fpga",
    "high precision",
    "low voltage",
    "model",
    "www.",
    ".com",
    "phone",
    "power supplies",
    "product",
    "products",
    "solution",
    "solutions",
    "tel:",
    "technology",
    "booth",
    "order now",
    "subscribe",
}

FRONT_MATTER_WORDS = {
    "welcome",
    "contents",
    "in this issue",
    "table of contents",
    "volume",
    "number",
}

MARKETING_TITLE_PATTERNS = [
    r"^need to\b",
    r"^get to know\b",
    r"^what can you do\b",
    r"^explore your\b",
    r"^new!",
    r"\bbest\b.*\bmodel\b",
    r"\bbest\b.*\bcompact\b",
    r"\bhigh precision\b",
    r"\blow\+?high voltage\b",
    r"\bpower supplies\b",
    r"\bflow metre\b",
    r"\bflow meter\b",
    r"\bactive technologies\b",
    r"\bopen innovation\b",
]


@dataclass
class HeadingCandidate:
    text: str
    score: float
    block_id: str | None
    y0_norm: float | None
    evidence: list[str] = field(default_factory=list)


@dataclass
class PageProfile:
    page_index: int
    page_name: str
    json_path: str
    page_width: float
    page_height: float
    text_blocks: int = 0
    heading_blocks: int = 0
    visual_blocks: int = 0
    text_chars: int = 0
    page_kind: str = "unknown"
    heading_candidates: list[HeadingCandidate] = field(default_factory=list)
    best_heading: HeadingCandidate | None = None
    article_start_score: float = 0.0
    evidence: list[str] = field(default_factory=list)


def natural_sort_key(path: Path) -> list[Any]:
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def page_index_from_name(path: Path, fallback: int) -> int:
    match = re.search(r"page_(\d+)", path.stem)
    if not match:
        return fallback
    return max(int(match.group(1)) - 1, 0)


def clean_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^#+\s*", "", text).strip()
    text = text.strip("*_` ")
    return text


def is_probably_noise_heading(text: str) -> bool:
    low = text.lower().strip()
    if not low:
        return True
    if low in NON_ARTICLE_HEADINGS:
        return True
    if len(text) <= 2:
        return True
    if re.fullmatch(r"[\W\d_]+", text):
        return True
    if re.fullmatch(r"(page\s*)?\d{1,4}", low):
        return True
    if re.match(r"^(figure|fig\.?|table)\s*\d+", low):
        return True
    if "@" in low or low.startswith("www."):
        return True
    return False


def bbox_y0_norm(block: dict[str, Any], page_height: float) -> float | None:
    bbox = block.get("bbox") or block.get("deepseek_bbox")
    if not isinstance(bbox, list) or len(bbox) < 4 or page_height <= 0:
        return None
    try:
        return float(bbox[1]) / page_height
    except Exception:
        return None


def heading_candidate_score(block: dict[str, Any], page_height: float) -> HeadingCandidate | None:
    text = clean_text(block.get("display_text") or block.get("text") or block.get("markdown"))
    if is_probably_noise_heading(text):
        return None

    block_type = str(block.get("block_type") or "").lower()
    role = str(block.get("matched_region_role") or "").lower()
    label = str(block.get("matched_region_label") or "").lower()
    markdown = str(block.get("markdown") or "")
    y0 = bbox_y0_norm(block, page_height)

    score = 0.0
    evidence: list[str] = []
    if block_type == "heading":
        score += 0.42
        evidence.append("DeepSeek block_type=heading")
    if role == "heading":
        score += 0.28
        evidence.append("layout role=heading")
    if label in {"paragraph_title", "doc_title", "title"}:
        score += 0.20
        evidence.append(f"layout label={label}")
    if markdown.lstrip().startswith("#"):
        score += 0.15
        evidence.append("markdown heading marker")
    if y0 is not None and y0 < 0.28:
        score += 0.12
        evidence.append("heading appears near top of page")
    if 18 <= len(text) <= 95:
        score += 0.08
        evidence.append("heading length resembles article title")
    if text.isupper() and len(text.split()) <= 4:
        score -= 0.18
        evidence.append("short all-caps heading may be section label")

    low = text.lower()
    if low in NON_ARTICLE_HEADINGS:
        score -= 0.35
    if any(word in low for word in AD_WORDS):
        score -= 0.20
        evidence.append("contains ad/contact-like text")

    score = max(0.0, min(1.0, score))
    if score < 0.35:
        return None
    return HeadingCandidate(
        text=text,
        score=round(score, 4),
        block_id=block.get("block_id"),
        y0_norm=round(y0, 4) if y0 is not None else None,
        evidence=evidence,
    )


def markdown_heading_candidates(markdown: str) -> list[HeadingCandidate]:
    candidates: list[HeadingCandidate] = []
    non_empty_lines = [line.strip() for line in markdown.splitlines() if line.strip()]

    for idx, line in enumerate(non_empty_lines[:40]):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            level = len(match.group(1))
            text = clean_text(match.group(2))
            if is_probably_noise_heading(text):
                continue
            score = 0.76 if level == 1 else 0.68 if level == 2 else 0.58
            if 18 <= len(text) <= 95:
                score += 0.06
            low = text.lower()
            if low in NON_ARTICLE_HEADINGS:
                score -= 0.35
            if any(word in low for word in AD_WORDS):
                score -= 0.20
            candidates.append(
                HeadingCandidate(
                    text=text,
                    score=round(max(0.0, min(score, 1.0)), 4),
                    block_id=f"markdown_heading_{idx:03d}",
                    y0_norm=None,
                    evidence=[f"markdown h{level} heading"],
                )
            )
            continue

        # DeepSeek sometimes emits strong page/department headings as plain text.
        if idx <= 4:
            text = clean_text(line)
            if is_probably_noise_heading(text):
                continue
            if text.isupper() and 8 <= len(text) <= 80:
                candidates.append(
                    HeadingCandidate(
                        text=text,
                        score=0.42,
                        block_id=f"plain_heading_{idx:03d}",
                        y0_norm=None,
                        evidence=["early all-caps text line"],
                    )
                )

    candidates = [candidate for candidate in candidates if candidate.score >= 0.35]
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def block_text(block: dict[str, Any]) -> str:
    return clean_text(block.get("display_text") or block.get("text") or block.get("markdown"))


def profile_page(path: Path, fallback_index: int) -> PageProfile:
    data = json.loads(path.read_text(encoding="utf-8"))
    page_height = float(data.get("page_height") or 0)
    page_width = float(data.get("page_width") or 0)
    page = PageProfile(
        page_index=page_index_from_name(path, fallback_index),
        page_name=str(data.get("page") or path.stem),
        json_path=str(path),
        page_width=page_width,
        page_height=page_height,
    )

    all_text: list[str] = []
    for block in data.get("aligned_blocks", []):
        if not isinstance(block, dict):
            continue
        text = block_text(block)
        role = str(block.get("matched_region_role") or "").lower()
        label = str(block.get("matched_region_label") or "").lower()
        block_type = str(block.get("block_type") or "").lower()

        if text:
            all_text.append(text)
            page.text_chars += len(text)
        if block_type in {"text", "heading"} or role in {"text", "heading"}:
            page.text_blocks += 1
        if block_type == "heading" or role == "heading" or label in {"paragraph_title", "doc_title", "title"}:
            page.heading_blocks += 1
            candidate = heading_candidate_score(block, page_height)
            if candidate:
                page.heading_candidates.append(candidate)
        if role == "visual" or label in {"image", "figure", "figure_title", "table"}:
            page.visual_blocks += 1

    page.heading_candidates.sort(key=lambda c: c.score, reverse=True)
    page.best_heading = page.heading_candidates[0] if page.heading_candidates else None
    page.article_start_score = page.best_heading.score if page.best_heading else 0.0

    combined = " ".join(all_text).lower()
    ad_hits = sum(1 for word in AD_WORDS if word in combined)
    front_hits = sum(1 for word in FRONT_MATTER_WORDS if word in combined)

    best_heading_text = page.best_heading.text.lower() if page.best_heading else ""
    ad_heading_hits = sum(1 for word in AD_WORDS if word in best_heading_text)
    marketing_title = any(re.search(pattern, best_heading_text) for pattern in MARKETING_TITLE_PATTERNS)

    if page.best_heading and re.match(r"^(figure|fig\.?|table)\s*\d+", best_heading_text):
        page.page_kind = "content_continuation"
        page.evidence.append("figure/table page treated as continuation, not article start")
    elif page.text_chars < 80 and page.visual_blocks >= 2:
        page.page_kind = "advertisement_or_visual"
        page.evidence.append("very little text with visual regions")
    elif ad_hits >= 2 and page.text_chars < 1800:
        page.page_kind = "advertisement_or_visual"
        page.evidence.append("contact/ad-like terms in parsed text")
    elif ad_heading_hits >= 1 and page.visual_blocks >= max(page.text_blocks // 2, 1):
        page.page_kind = "advertisement_or_visual"
        page.evidence.append("best heading contains product/ad-like terms")
    elif marketing_title:
        page.page_kind = "advertisement_or_visual"
        page.evidence.append("best heading matches generic marketing/product-title pattern")
    elif page.page_index <= 2 and front_hits >= 2:
        page.page_kind = "front_matter"
        page.evidence.append("front-matter terms near beginning")
    elif page.page_index <= 1 and page.best_heading and page.best_heading.text.lower().startswith("welcome"):
        page.page_kind = "front_matter"
        page.evidence.append("welcome page near beginning")
    elif page.best_heading:
        page.page_kind = "article_candidate"
        page.evidence.append(f"strong heading candidate: {page.best_heading.text}")
    elif page.text_chars > 500:
        page.page_kind = "content_continuation"
        page.evidence.append("substantial parsed text without strong new title")
    else:
        page.page_kind = "unknown"
        page.evidence.append("weak parsed-text evidence")
    return page


def image_size_from_bbox_items(page_dir: Path) -> tuple[float, float]:
    bbox_path = page_dir / "bbox_items.json"
    if not bbox_path.exists():
        return 0.0, 0.0
    try:
        items = json.loads(bbox_path.read_text(encoding="utf-8"))
    except Exception:
        return 0.0, 0.0
    if not isinstance(items, list):
        return 0.0, 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        width = float(item.get("image_width") or 0)
        height = float(item.get("image_height") or 0)
        if width > 0 and height > 0:
            return width, height
    return 0.0, 0.0


def profile_parse_page(page_dir: Path, fallback_index: int) -> PageProfile:
    page_width, page_height = image_size_from_bbox_items(page_dir)
    md_path = page_dir / "ocr.md"
    markdown = md_path.read_text(encoding="utf-8", errors="ignore") if md_path.exists() else ""
    text_without_images = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", markdown)
    text_lines = [clean_text(line) for line in text_without_images.splitlines()]
    text_lines = [line for line in text_lines if line]
    text = " ".join(text_lines)

    page = PageProfile(
        page_index=page_index_from_name(page_dir, fallback_index),
        page_name=page_dir.name,
        json_path=str(page_dir),
        page_width=page_width,
        page_height=page_height,
        text_blocks=len(text_lines),
        visual_blocks=len(re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown)),
        text_chars=len(text),
    )
    page.heading_candidates = markdown_heading_candidates(markdown)
    page.heading_blocks = len(page.heading_candidates)
    page.best_heading = page.heading_candidates[0] if page.heading_candidates else None
    page.article_start_score = page.best_heading.score if page.best_heading else 0.0

    combined = text.lower()
    ad_hits = sum(1 for word in AD_WORDS if word in combined)
    front_hits = sum(1 for word in FRONT_MATTER_WORDS if word in combined)
    best_heading_text = page.best_heading.text.lower() if page.best_heading else ""
    ad_heading_hits = sum(1 for word in AD_WORDS if word in best_heading_text)
    marketing_title = any(re.search(pattern, best_heading_text) for pattern in MARKETING_TITLE_PATTERNS)

    if page.best_heading and re.match(r"^(figure|fig\.?|table)\s*\d+", best_heading_text):
        page.page_kind = "content_continuation"
        page.evidence.append("figure/table page treated as continuation, not article start")
    elif page.text_chars < 80 and page.visual_blocks >= 2:
        page.page_kind = "advertisement_or_visual"
        page.evidence.append("very little text with image references")
    elif ad_hits >= 2 and page.text_chars < 1800:
        page.page_kind = "advertisement_or_visual"
        page.evidence.append("contact/ad-like terms in parsed text")
    elif ad_heading_hits >= 1 and page.visual_blocks >= max(page.text_blocks // 2, 1):
        page.page_kind = "advertisement_or_visual"
        page.evidence.append("best heading contains product/ad-like terms")
    elif marketing_title:
        page.page_kind = "advertisement_or_visual"
        page.evidence.append("best heading matches generic marketing/product-title pattern")
    elif page.page_index <= 2 and front_hits >= 2:
        page.page_kind = "front_matter"
        page.evidence.append("front-matter terms near beginning")
    elif page.page_index <= 1 and page.best_heading and page.best_heading.text.lower().startswith("welcome"):
        page.page_kind = "front_matter"
        page.evidence.append("welcome page near beginning")
    elif page.best_heading:
        page.page_kind = "article_candidate"
        page.evidence.append(f"strong markdown heading candidate: {page.best_heading.text}")
    elif page.text_chars > 500:
        page.page_kind = "content_continuation"
        page.evidence.append("substantial parsed text without strong new title")
    else:
        page.page_kind = "unknown"
        page.evidence.append("weak parsed-text evidence")
    return page


def load_pages(enriched_dir: Path) -> list[PageProfile]:
    if not enriched_dir.exists():
        raise FileNotFoundError(f"Enriched JSON directory not found: {enriched_dir}")
    paths = sorted(enriched_dir.glob("page_*.json"), key=natural_sort_key)
    if not paths:
        raise ValueError(f"No page_*.json files found in: {enriched_dir}")
    return [profile_page(path, i) for i, path in enumerate(paths)]


def load_parse_pages(parse_dir: Path) -> list[PageProfile]:
    if not parse_dir.exists():
        raise FileNotFoundError(f"Parse result directory not found: {parse_dir}")
    paths = sorted([p for p in parse_dir.glob("page_*") if p.is_dir()], key=natural_sort_key)
    if not paths:
        raise ValueError(f"No page_* folders found in: {parse_dir}")
    return [profile_parse_page(path, i) for i, path in enumerate(paths)]


def should_start_new_article(page: PageProfile, prev_page: PageProfile | None) -> tuple[bool, float, list[str]]:
    if not page.best_heading:
        return False, 0.0, ["no strong heading candidate"]
    if page.page_kind == "front_matter":
        return False, 0.0, ["front matter page"]
    if page.page_kind == "advertisement_or_visual":
        return False, 0.0, ["ad-like page is not treated as article start"]

    score = page.article_start_score
    evidence = list(page.best_heading.evidence)
    if prev_page and prev_page.page_kind == "advertisement_or_visual":
        score += 0.08
        evidence.append("follows ad-like/visual page")
    if prev_page and prev_page.page_kind in {"front_matter", "unknown"}:
        score += 0.05
        evidence.append(f"follows {prev_page.page_kind}")
    if page.best_heading.y0_norm is not None and page.best_heading.y0_norm > 0.45:
        score -= 0.14
        evidence.append("heading appears low on page; may be subsection")
    if page.text_chars < 180 and page.visual_blocks > page.text_blocks:
        score -= 0.15
        evidence.append("sparse visual page; may not be article start")

    score = max(0.0, min(1.0, score))
    return score >= 0.62, round(score, 4), evidence


def page_all_heading_texts(page: PageProfile) -> set[str]:
    return {candidate.text.lower().strip() for candidate in page.heading_candidates}


def classify_document_policy(pages: list[PageProfile]) -> tuple[str, str, list[str]]:
    heading_texts = set()
    for page in pages:
        heading_texts.update(page_all_heading_texts(page))

    section_hits = heading_texts & SCIENTIFIC_SECTION_HEADINGS
    has_abstract = "abstract" in heading_texts
    has_references = bool({"references", "bibliography"} & heading_texts)
    has_intro_or_methods = bool(
        {
            "introduction",
            "method",
            "methods",
            "methodology",
            "materials and methods",
            "experiment",
            "experiments",
        }
        & heading_texts
    )
    ad_like_pages = sum(1 for page in pages if page.page_kind == "advertisement_or_visual")
    front_like_pages = sum(1 for page in pages if page.page_kind == "front_matter")
    article_candidate_pages = sum(1 for page in pages if page.page_kind == "article_candidate")
    heading_pages = sum(1 for page in pages if page.best_heading)
    short_text_pages = sum(1 for page in pages if page.text_chars < 900)
    very_short_text_pages = sum(1 for page in pages if page.text_chars < 250)
    numbered_section_headings = [
        heading
        for heading in heading_texts
        if re.match(r"^\d+(\.\d+)*\s+\S", heading)
    ]

    evidence: list[str] = []
    if section_hits:
        evidence.append(
            "scientific-paper section headings detected: "
            + ", ".join(sorted(section_hits)[:8])
        )
    figure_table_pages = sum(
        1
        for page in pages
        if page.best_heading and re.match(r"^(figure|fig\.?|table)\s*\d+", page.best_heading.text.lower())
    )
    allowed_non_article_pages = max(2, len(pages) // 8) + figure_table_pages

    if has_abstract and has_intro_or_methods and ad_like_pages <= allowed_non_article_pages:
        evidence.append("abstract/introduction-methods/references pattern suggests one scientific paper")
        return "scientific_article", "keep_as_one_document", evidence

    if len(numbered_section_headings) >= 5 and ad_like_pages <= allowed_non_article_pages:
        evidence.append(
            "many numbered section headings suggest one structured paper/report, not separate articles"
        )
        return "scientific_article", "keep_as_one_document", evidence

    if len(pages) >= 8:
        heading_fraction = heading_pages / max(len(pages), 1)
        short_text_fraction = short_text_pages / max(len(pages), 1)
        very_short_text_fraction = very_short_text_pages / max(len(pages), 1)
        avg_text_chars = sum(page.text_chars for page in pages) / max(len(pages), 1)

        if (
            heading_fraction >= 0.65
            and short_text_fraction >= 0.55
            and (avg_text_chars < 1000 or very_short_text_fraction >= 0.30)
        ):
            evidence.append(
                "presentation/slide-like document detected: many titled pages with sparse text"
            )
            evidence.append(
                f"heading_fraction={heading_fraction:.2f}, "
                f"short_text_fraction={short_text_fraction:.2f}, "
                f"avg_text_chars={avg_text_chars:.1f}"
            )
            return "slide_deck_or_lecture_notes", "keep_as_one_document", evidence

    if len(pages) >= 8 and article_candidate_pages >= 4 and (ad_like_pages >= 1 or front_like_pages >= 1):
        evidence.append("multiple article-like title pages with magazine/front/ad-like context")
        return "magazine_or_multi_article", "split_between_pages_only", evidence

    evidence.append("insufficient evidence for multi-article splitting; keep conservative")
    return "unknown_or_single_document", "keep_as_one_document", evidence


def build_whole_document_segment(
    pages: list[PageProfile],
    doc_type_guess: str,
    evidence: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return [
        {
            "subdoc_id": "article_subdoc_001",
            "type": "whole_document",
            "title": pages[0].best_heading.text if pages and pages[0].best_heading else None,
            "page_start": pages[0].page_index,
            "page_end": pages[-1].page_index,
            "export": True,
            "confidence": 0.78 if doc_type_guess == "scientific_article" else 0.45,
            "evidence": evidence,
        }
    ], []


def build_segments(pages: list[PageProfile]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    boundaries: list[dict[str, Any]] = []
    starts: list[dict[str, Any]] = []

    for idx, page in enumerate(pages):
        prev = pages[idx - 1] if idx > 0 else None
        is_start, score, evidence = should_start_new_article(page, prev)
        if is_start:
            starts.append(
                {
                    "page_list_index": idx,
                    "page_index": page.page_index,
                    "confidence": score,
                    "evidence": evidence,
                    "title": page.best_heading.text if page.best_heading else None,
                }
            )
            boundaries.append(
                {
                    "page_index": page.page_index,
                    "boundary_before_page": page.page_index,
                    "confidence": score,
                    "title_candidate": page.best_heading.text if page.best_heading else None,
                    "evidence": evidence,
                }
            )

    starts.sort(key=lambda s: int(s["page_list_index"]))

    if not starts:
        starts = [
            {
                "page_list_index": 0,
                "page_index": pages[0].page_index,
                "confidence": 0.35,
                "evidence": ["no reliable article starts found; keeping whole document"],
                "title": pages[0].best_heading.text if pages[0].best_heading else None,
            }
        ]

    if starts[0]["page_list_index"] != 0:
        starts.insert(
            0,
            {
                "page_list_index": 0,
                "page_index": pages[0].page_index,
                "confidence": 0.45,
                "evidence": ["front matter or leading material before first detected article"],
                "title": pages[0].best_heading.text if pages[0].best_heading else None,
            },
        )

    subdocs: list[dict[str, Any]] = []
    for subdoc_idx, start in enumerate(starts, start=1):
        start_idx = int(start["page_list_index"])
        next_start = starts[subdoc_idx] if subdoc_idx < len(starts) else None
        if next_start:
            next_idx = int(next_start["page_list_index"])
            end_idx = max(start_idx, next_idx - 1)
        else:
            end_idx = len(pages) - 1
        start_page = pages[start_idx]
        end_page = pages[end_idx]
        title = start.get("title") or (start_page.best_heading.text if start_page.best_heading else None)
        if start_page.page_kind == "front_matter":
            subdoc_type = "front_matter"
            export = False
        elif start_page.page_kind == "advertisement_or_visual":
            subdoc_type = "advertisement_or_visual"
            export = False
        elif title:
            subdoc_type = "article_or_content_run"
            export = True
        else:
            subdoc_type = "mixed_or_unknown"
            export = True
        subdocs.append(
            {
                "subdoc_id": f"article_subdoc_{subdoc_idx:03d}",
                "type": subdoc_type,
                "title": title,
                "page_start": start_page.page_index,
                "page_end": end_page.page_index,
                "export": export,
                "confidence": start["confidence"],
                "evidence": start["evidence"],
            }
        )

    return subdocs, boundaries


def page_to_json(page: PageProfile) -> dict[str, Any]:
    return {
        "page_index": page.page_index,
        "page_name": page.page_name,
        "json_path": page.json_path,
        "page_kind": page.page_kind,
        "text_blocks": page.text_blocks,
        "heading_blocks": page.heading_blocks,
        "visual_blocks": page.visual_blocks,
        "text_chars": page.text_chars,
        "article_start_score": round(page.article_start_score, 4),
        "best_heading": {
            "text": page.best_heading.text,
            "score": page.best_heading.score,
            "block_id": page.best_heading.block_id,
            "y0_norm": page.best_heading.y0_norm,
            "evidence": page.best_heading.evidence,
        }
        if page.best_heading
        else None,
        "heading_candidates": [
            {
                "text": candidate.text,
                "score": candidate.score,
                "block_id": candidate.block_id,
                "y0_norm": candidate.y0_norm,
                "evidence": candidate.evidence,
            }
            for candidate in page.heading_candidates[:5]
        ],
        "evidence": page.evidence,
    }


def infer_doc_id(enriched_dir: Path) -> str:
    return enriched_dir.name


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    input_dir = Path(args.parse_root or args.enriched_json_dir)
    doc_id = args.doc_id or infer_doc_id(input_dir)
    if args.input_kind == "parse":
        pages = load_parse_pages(input_dir)
    else:
        pages = load_pages(input_dir)
    doc_type_guess, split_policy, policy_evidence = classify_document_policy(pages)
    if split_policy == "keep_as_one_document":
        subdocs, boundaries = build_whole_document_segment(pages, doc_type_guess, policy_evidence)
    else:
        subdocs, boundaries = build_segments(pages)
    export_count = sum(1 for subdoc in subdocs if subdoc["export"])
    should_split = export_count > 1

    return {
        "doc_id": doc_id,
        "stage": "post_parse_hybrid",
        "method": (
            "heuristic_article_split_from_parse_only_deepseekocr2"
            if args.input_kind == "parse"
            else "heuristic_article_split_from_hybrid_layout_deepseekocr2"
        ),
        "input_dir": str(input_dir),
        "enriched_json_dir": str(input_dir) if args.input_kind == "hybrid" else None,
        "parse_root": str(input_dir) if args.input_kind == "parse" else None,
        "input_kind": args.input_kind,
        "doc_type_guess": doc_type_guess,
        "should_split_file": should_split,
        "split_unit": "page",
        "split_policy": split_policy,
        "confidence": round(
            sum(float(subdoc["confidence"]) for subdoc in subdocs) / max(len(subdocs), 1),
            4,
        ),
        "note": "Heuristic article split plan from parsed hybrid layout/OCR outputs. Review before export.",
        "warnings": [
            "For scientific-paper-like documents, internal section headings are not split into separate files.",
            "Headings may include sections, ads, or recurring departments; confidence is intentionally conservative.",
        ],
        "policy_evidence": policy_evidence,
        "pages": [page_to_json(page) for page in pages],
        "boundaries": boundaries,
        "subdocuments": subdocs,
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a rough article split plan from hybrid DeepSeekOCR2/layout enriched JSON."
    )
    parser.add_argument("--doc-id", default=None)
    parser.add_argument(
        "--enriched-json-dir",
        default=None,
        help="Directory containing page_*.json from output/hybrid_deepseek_layout_mvp/enriched_json/<doc_id>.",
    )
    parser.add_argument(
        "--parse-root",
        default=None,
        help="Directory containing DeepSeek parse page folders, e.g. output/deepseekocr2_split_render/<doc_id>.",
    )
    parser.add_argument(
        "--input-kind",
        choices=["hybrid", "parse"],
        default="hybrid",
        help="Use hybrid enriched page JSON or parse-only DeepSeek page folders.",
    )
    parser.add_argument("--out", required=True, help="Output article_split_plan.json path.")
    args = parser.parse_args(argv)
    if not args.enriched_json_dir and not args.parse_root:
        parser.error("one of --enriched-json-dir or --parse-root is required")
    if args.parse_root and args.input_kind == "hybrid":
        args.input_kind = "parse"
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = build_plan(args)
        write_json(Path(args.out), plan)
        print(
            json.dumps(
                {
                    "doc_id": plan["doc_id"],
                    "doc_type_guess": plan["doc_type_guess"],
                    "should_split_file": plan["should_split_file"],
                    "split_policy": plan["split_policy"],
                    "subdocument_count": len(plan["subdocuments"]),
                    "boundary_count": len(plan["boundaries"]),
                    "out": args.out,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
