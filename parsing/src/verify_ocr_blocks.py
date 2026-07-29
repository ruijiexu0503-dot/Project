#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
verify_ocr_blocks_v3.py

Conservative OCR-risk verification for DeepSeekOCR/layout-enriched markdown.

Compared with v2, this version further reduces false positives for figure/image/caption blocks:
1. Metadata/comment lines are stripped from block text before risk scoring.
2. Phone detection is much stricter and will not match bbox coordinates.
3. Text-density risk is relative, not based on aggressive absolute bbox thresholds.
4. "Complex layout container" is only a verification trigger, not a high-risk reason by itself.
5. Secondary OCR disagreement only affects blocks that were actually re-OCRed.

Outputs:
- ocr_verification_blocks.json
- ocr_verification_report.md
- optional crops/
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image
except Exception:
    Image = None


HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*$")
RID_RE = re.compile(r"\bR\d{3,}\b|\bR\d+\b")
DID_RE = re.compile(r"\bD\d{3,}\b|\bD\d+\b")
LAYOUT_ID_RE = re.compile(r"\blayout_\d+\b")
FLOAT_RE = re.compile(r"[-+]?\d*\.\d+|[-+]?\d+")

# bullet metadata, normal key-value metadata, and HTML-comment metadata
BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<key>[^:：]+)\s*[:：]\s*(?P<value>.+?)\s*$")
KV_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_\s\-]{1,40})\s*[:：]\s*(?P<value>.+?)\s*$")
HTML_COMMENT_RE = re.compile(r"^\s*<!--\s*(?P<body>.*?)\s*-->\s*$")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>()]+", re.IGNORECASE)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
ISBN_RE = re.compile(
    r"\b(?:ISBN(?:-1[03])?:?\s*)?(?:97[89][-\s]?)?"
    r"\d[-\s]?\d{2,5}[-\s]?\d{2,7}[-\s]?\d[-\s]?[0-9X]\b",
    re.IGNORECASE,
)

METADATA_KEYS = {
    "block_id",
    "matched_region",
    "matched_region_id",
    "matched_region_ids",
    "matched_region_type",
    "region_type",
    "layout_type",
    "bbox",
    "layout_bbox",
    "deepseek_bbox",
    "deepseekbbox",
    "deepseek_b_box",
    "ocr_bbox",
    "bbox_source",
    "bbox_granularity",
    "risk",
    "flags",
    "index_text",
}

METADATA_KEYWORDS = [
    "produced for",
    "published by",
    "printed by",
    "advertisement",
    "advertising",
    "marketing and circulation",
    "general distribution",
    "head of media",
    "head of development",
    "content and production",
    "technical illustrator",
    "advertising sales",
    "recruitment sales",
    "issn",
    "iop publishing",
    "tel:",
    "fax:",
    "email:",
    "e-mail",
]


@dataclass
class OCRBlock:
    page_id: str
    md_path: str

    rid: str
    title: str
    kind: str = ""
    did: str = ""

    block_id: str = ""
    matched_region: str = ""
    matched_region_ids: List[str] = field(default_factory=list)
    matched_region_type: str = ""

    bbox: Optional[List[float]] = None
    deepseek_bbox: Optional[List[float]] = None

    text: str = ""
    raw_text_before_filter: str = ""
    raw_meta: Dict[str, str] = field(default_factory=dict)

    text_len: int = 0
    token_count: int = 0
    density: Optional[float] = None

    entities: Dict[str, List[str]] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)

    risk_score: float = 0.0
    risk_level: str = "low"
    verification_status: str = "accepted"

    index_text: str = ""
    use_for_embedding: bool = True
    use_for_node_generation: bool = True
    keep_as_evidence: bool = True

    crop_path: Optional[str] = None
    secondary_ocr_text: str = ""
    secondary_token_overlap: Optional[float] = None
    secondary_char_similarity: Optional[float] = None


@dataclass
class RegionSummary:
    page_id: str
    region_id: str
    region_type: str = ""
    block_ids: List[str] = field(default_factory=list)
    rids: List[str] = field(default_factory=list)
    num_blocks: int = 0
    complex_layout_container: bool = False
    flags: List[str] = field(default_factory=list)


def clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def norm_key(key: str) -> str:
    key = key.strip().lower()
    key = key.replace("-", "_")
    key = re.sub(r"\s+", "_", key)
    return key


def parse_bbox(value: str) -> Optional[List[float]]:
    nums = [float(x) for x in FLOAT_RE.findall(value)]
    if len(nums) >= 4:
        return nums[:4]
    return None


def bbox_area(bbox: Optional[List[float]]) -> Optional[float]:
    if not bbox or len(bbox) < 4:
        return None
    x1, y1, x2, y2 = bbox[:4]
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    if width <= 0 or height <= 0:
        return None
    return width * height


def choose_bbox(block: OCRBlock) -> Optional[List[float]]:
    return block.deepseek_bbox or block.bbox


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text.lower())


def digits_only(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * p / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return values[int(k)]
    return values[lo] * (hi - k) + values[hi] * (k - lo)


def parse_matched_region(value: str) -> Tuple[List[str], str]:
    parts = [p.strip() for p in value.split("/") if p.strip()]
    ids = [p for p in parts if LAYOUT_ID_RE.fullmatch(p)]
    region_type = parts[1].lower() if len(parts) >= 2 else ""
    return ids, region_type


def infer_from_heading(title: str) -> Tuple[str, str, str]:
    rid_match = RID_RE.search(title)
    did_match = DID_RE.search(title)
    rid = rid_match.group(0) if rid_match else ""
    did = did_match.group(0) if did_match else ""

    kind = ""
    parts = [p.strip() for p in re.split(r"[·|]", title) if p.strip()]
    for p in parts:
        if p != rid and p != did and not LAYOUT_ID_RE.search(p):
            kind = p
            break

    return rid, did, kind


def is_metadata_key(key: str) -> bool:
    k = norm_key(key)
    return k in METADATA_KEYS or "bbox" in k or "matched_region" in k


def parse_metadata_line(line: str) -> Optional[Tuple[str, str]]:
    """
    Parses metadata lines in several possible forms:
    - - bbox: [...]
    - bbox: [...]
    - <!-- bbox: [...] -->
    - <!-- matched_region: layout_020 / table / table -->
    """
    stripped = line.strip()

    comment = HTML_COMMENT_RE.match(stripped)
    if comment:
        body = comment.group("body").strip()
        # Some comments can contain multiple fields; handle the common single-field case.
        kv = KV_RE.match(body)
        if kv:
            return kv.group("key"), kv.group("value")
        return None

    bullet = BULLET_RE.match(stripped)
    if bullet:
        return bullet.group("key"), bullet.group("value")

    kv = KV_RE.match(stripped)
    if kv and is_metadata_key(kv.group("key")):
        return kv.group("key"), kv.group("value")

    return None


def apply_meta(block: OCRBlock, key: str, value: str) -> None:
    k = norm_key(key)
    v = value.strip()
    block.raw_meta[k] = v

    if k == "block_id":
        block.block_id = v

    elif k == "matched_region":
        block.matched_region = v
        ids, region_type = parse_matched_region(v)
        block.matched_region_ids = ids
        block.matched_region_type = region_type

    elif k in {"matched_region_id", "matched_region_ids"}:
        block.matched_region_ids = LAYOUT_ID_RE.findall(v)

    elif k in {"bbox", "layout_bbox"}:
        block.bbox = parse_bbox(v)

    elif k in {"deepseek_bbox", "deepseekbbox", "deepseek_b_box", "ocr_bbox"}:
        block.deepseek_bbox = parse_bbox(v)

    elif k in {"matched_region_type", "layout_type", "region_type"}:
        block.matched_region_type = v.strip().lower()


def filter_text_line(line: str) -> Optional[str]:
    """
    Removes metadata/comment lines from text.
    This prevents bbox coordinates from being detected as phone numbers.
    """
    stripped = line.strip()

    if not stripped:
        return ""

    # Drop HTML comments entirely.
    if HTML_COMMENT_RE.match(stripped):
        return None

    meta = parse_metadata_line(line)
    if meta and is_metadata_key(meta[0]):
        return None

    # Drop obvious serialized metadata lines.
    low = stripped.lower()
    if any(k in low for k in ["matched_region", "deepseek_bbox", "bbox_granularity", "bbox_source"]):
        return None

    return line


def strict_extract_phones(text: str) -> List[str]:
    """
    Conservative phone extraction.

    It avoids matching bbox-like coordinates:
    - Requires an explicit phone cue nearby, OR an international '+' form.
    - Rejects candidates with too many decimal points.
    - Requires 7-16 digits.
    """
    candidates: List[str] = []

    # Explicit phone cues.
    cue_pattern = re.compile(
        r"(?i)\b(?:tel|telephone|phone|fax|mobile|mob)\.?\s*[:：]?\s*"
        r"(?P<num>\+?\d[\d\s().\-]{5,}\d)"
    )
    for m in cue_pattern.finditer(text):
        candidates.append(m.group("num"))

    # International + form without cue.
    plus_pattern = re.compile(r"(?<!\w)(?P<num>\+\d[\d\s().\-]{6,}\d)(?!\w)")
    for m in plus_pattern.finditer(text):
        candidates.append(m.group("num"))

    out: List[str] = []
    seen = set()

    for c in candidates:
        digits = digits_only(c)

        if not (7 <= len(digits) <= 16):
            continue

        # bbox coordinates often contain several decimals.
        if c.count(".") >= 2:
            continue

        # Reject pure coordinate-looking strings with many comma-separated decimals.
        if re.search(r"\d+\.\d+\s*,\s*\d+\.\d+", c):
            continue

        norm = clean_ws(c)
        if norm not in seen:
            out.append(norm)
            seen.add(norm)

    return out


def extract_entities(text: str) -> Dict[str, List[str]]:
    return {
        "phone": strict_extract_phones(text),
        "email": EMAIL_RE.findall(text),
        "url": URL_RE.findall(text),
        "doi": DOI_RE.findall(text),
        "isbn": ISBN_RE.findall(text),
    }


def mask_entities(text: str) -> str:
    for phone in strict_extract_phones(text):
        text = text.replace(phone, "[UNVERIFIED_PHONE]")
    text = EMAIL_RE.sub("[UNVERIFIED_EMAIL]", text)
    text = URL_RE.sub("[UNVERIFIED_URL]", text)
    text = DOI_RE.sub("[UNVERIFIED_DOI]", text)
    text = ISBN_RE.sub("[UNVERIFIED_ISBN]", text)
    return text


def has_metadata_keyword(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in METADATA_KEYWORDS)


def parse_md_file(md_path: Path) -> List[OCRBlock]:
    page_id = md_path.stem
    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()

    blocks: List[OCRBlock] = []
    current: Optional[OCRBlock] = None
    text_lines: List[str] = []
    in_meta = False

    def flush_current() -> None:
        nonlocal current, text_lines

        if current is None:
            return

        raw = "\n".join(text_lines)
        filtered_lines = []
        for line in text_lines:
            kept = filter_text_line(line)
            if kept is not None:
                filtered_lines.append(kept)

        current.raw_text_before_filter = clean_ws(raw)
        current.text = clean_ws("\n".join(filtered_lines))
        current.text_len = len(current.text)
        current.token_count = len(tokenize(current.text))

        if not current.block_id:
            current.block_id = current.did or current.rid

        if current.matched_region and not current.matched_region_ids:
            ids, region_type = parse_matched_region(current.matched_region)
            current.matched_region_ids = ids
            current.matched_region_type = region_type

        blocks.append(current)
        current = None
        text_lines = []

    for line in lines:
        heading = HEADING_RE.match(line)

        if heading:
            title = heading.group("title").strip()
            rid, did, kind = infer_from_heading(title)

            if rid:
                flush_current()
                current = OCRBlock(
                    page_id=page_id,
                    md_path=str(md_path),
                    rid=rid,
                    did=did,
                    kind=kind,
                    title=title,
                )
                in_meta = True
                continue

        if current is None:
            continue

        meta = parse_metadata_line(line)

        if meta and is_metadata_key(meta[0]):
            key, value = meta
            apply_meta(current, key, value)
            continue

        if line.strip() == "" and in_meta:
            in_meta = False
            continue

        in_meta = False
        text_lines.append(line)

    flush_current()
    return blocks


def load_blocks(md_root: Path) -> List[OCRBlock]:
    md_files = sorted(md_root.rglob("page_*.md"))
    if not md_files:
        md_files = sorted(md_root.rglob("*.md"))

    blocks: List[OCRBlock] = []
    for md_file in md_files:
        blocks.extend(parse_md_file(md_file))
    return blocks


def build_region_index(blocks: List[OCRBlock]) -> Dict[str, RegionSummary]:
    regions: Dict[str, RegionSummary] = {}

    for block in blocks:
        for region_id in block.matched_region_ids:
            region_key = f"{block.page_id}::{region_id}"

            if region_key not in regions:
                regions[region_key] = RegionSummary(
                    page_id=block.page_id,
                    region_id=region_id,
                    region_type=block.matched_region_type,
                )

            region = regions[region_key]
            region.block_ids.append(block.block_id)
            region.rids.append(block.rid)

            if block.matched_region_type and not region.region_type:
                region.region_type = block.matched_region_type

    for region in regions.values():
        region.num_blocks = len(region.block_ids)

        if region.num_blocks >= 2:
            region.complex_layout_container = True
            region.flags.append("layout_region_contains_multiple_ocr_blocks")

        if region.region_type in {"table", "figure", "picture", "image"} and region.num_blocks >= 2:
            region.flags.append(f"multi_block_{region.region_type}_container")

    return regions


def repetition_flags(text: str) -> List[str]:
    flags: List[str] = []
    toks = tokenize(text)

    if len(toks) < 12:
        return flags

    unique_ratio = len(set(toks)) / max(len(toks), 1)

    if unique_ratio < 0.35:
        flags.append("low_unique_token_ratio")

    token_counts = Counter(toks)
    _, most_count = token_counts.most_common(1)[0]

    if most_count >= 6 and most_count / len(toks) >= 0.25:
        flags.append("single_token_repeated_many_times")

    bigrams = list(zip(toks, toks[1:]))

    if bigrams:
        bigram_counts = Counter(bigrams)
        _, max_bigram_count = bigram_counts.most_common(1)[0]

        if max_bigram_count >= 4:
            flags.append("repeated_bigram_loop")

    for n in (2, 3):
        phrases = [" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)]

        if not phrases:
            continue

        phrase_counts = Counter(phrases)
        _, max_phrase_count = phrase_counts.most_common(1)[0]

        if max_phrase_count >= 4:
            flags.append(f"repeated_{n}gram_loop")
            break

    return flags


def abnormal_char_flags(text: str) -> List[str]:
    flags: List[str] = []

    if not text:
        return flags

    allowed_extra = ".,;:!?()[]{}+-–—_/\\'\"%&@#€$£°=<>"
    weird = sum(
        1
        for ch in text
        if not (ch.isalnum() or ch.isspace() or ch in allowed_extra)
    )

    if len(text) >= 50 and weird / len(text) > 0.10:
        flags.append("abnormal_character_distribution")

    if any(len(tok) >= 45 for tok in text.split()):
        flags.append("very_long_unspaced_token")

    return flags


def compute_initial_flags(blocks: List[OCRBlock], regions: Dict[str, RegionSummary]) -> None:
    densities: List[float] = []

    for block in blocks:
        block.entities = extract_entities(block.text)

        area = bbox_area(choose_bbox(block))
        if area and block.text_len > 0:
            block.density = block.text_len / area
            densities.append(block.density)

    density_median = statistics.median(densities) if densities else 0.0
    density_q95 = percentile(densities, 95) if densities else 0.0
    density_q99 = percentile(densities, 99) if densities else 0.0

    for block in blocks:
        flags: List[str] = []

        for region_id in block.matched_region_ids:
            region_key = f"{block.page_id}::{region_id}"
            region = regions.get(region_key)

            if not region:
                continue

            if region.complex_layout_container:
                flags.append("inside_complex_layout_container")

            if region.region_type:
                flags.append(f"layout_type_{region.region_type}")

            if region.region_type in {"picture", "image", "figure"}:
                flags.append("text_inside_visual_region_possible_valid")

        if block.matched_region_type == "table":
            flags.append("inside_table_like_region")

        if block.matched_region_type in {"picture", "image", "figure"}:
            flags.append("inside_visual_region_possible_valid")

        if has_metadata_keyword(block.text):
            flags.append("metadata_or_advertisement_keyword")

        if block.entities["phone"]:
            flags.append("phone_number_detected")
        if block.entities["email"]:
            flags.append("email_detected")
        if block.entities["url"]:
            flags.append("url_detected")
        if block.entities["doi"]:
            flags.append("doi_detected")
        if block.entities["isbn"]:
            flags.append("isbn_detected")

        flags.extend(repetition_flags(block.text))
        flags.extend(abnormal_char_flags(block.text))

        area = bbox_area(choose_bbox(block))

        # Less aggressive text-density checks.
        # Absolute small-bbox rules are removed because coordinate systems vary.
        if area is not None and block.text_len >= 120 and block.density is not None:
            if density_q99 > 0 and block.density > max(density_q99 * 1.25, density_median * 8):
                flags.append("text_density_extreme_outlier_for_bbox")
            elif density_q95 > 0 and block.density > max(density_q95 * 2.5, density_median * 6):
                flags.append("text_density_outlier_for_bbox")

        if block.text_len == 0:
            flags.append("empty_text")

        block.flags = sorted(set(flags))


def score_and_decide(block: OCRBlock, allow_medium_index: bool = False) -> None:
    weights = {
        # weak trigger
        "inside_complex_layout_container": 0.02,
        "inside_table_like_region": 0.03,
        "text_inside_visual_region_possible_valid": 0.00,
        "inside_visual_region_possible_valid": 0.00,

        # content risk
        "metadata_or_advertisement_keyword": 0.28,
        "phone_number_detected": 0.25,
        "email_detected": 0.12,
        "url_detected": 0.10,
        "doi_detected": 0.10,
        "isbn_detected": 0.10,

        # hallucination-like signals
        "low_unique_token_ratio": 0.22,
        "single_token_repeated_many_times": 0.35,
        "repeated_bigram_loop": 0.40,
        "repeated_2gram_loop": 0.45,
        "repeated_3gram_loop": 0.45,
        "abnormal_character_distribution": 0.18,
        "very_long_unspaced_token": 0.18,
        "text_density_outlier_for_bbox": 0.25,
        "text_density_extreme_outlier_for_bbox": 0.40,

        # secondary OCR
        # Empty secondary OCR is common on figures/crops and should not make a block high-risk.
        "secondary_ocr_empty": 0.00,
        "secondary_ocr_partial_disagreement": 0.15,
        "secondary_ocr_strong_disagreement": 0.40,
        "phone_not_supported_by_secondary_ocr": 0.35,
        "phone_digit_sequence_disagreement": 0.55,
    }

    flagset = set(block.flags)
    score = sum(weights.get(flag, 0.0) for flag in flagset)

    # Interactions
    if "inside_complex_layout_container" in flagset and "phone_number_detected" in flagset:
        score += 0.08

    if "inside_complex_layout_container" in flagset and "metadata_or_advertisement_keyword" in flagset:
        score += 0.12

    if "phone_number_detected" in flagset and (
        "repeated_bigram_loop" in flagset
        or "repeated_2gram_loop" in flagset
        or "low_unique_token_ratio" in flagset
    ):
        score += 0.20

    # Text inside image/figure should not be punished by itself.
    if "text_inside_visual_region_possible_valid" in flagset:
        strong_flags = {
            "phone_number_detected",
            "email_detected",
            "url_detected",
            "doi_detected",
            "isbn_detected",
            "metadata_or_advertisement_keyword",
            "text_density_extreme_outlier_for_bbox",
            "repeated_bigram_loop",
            "repeated_2gram_loop",
            "repeated_3gram_loop",
            "secondary_ocr_strong_disagreement",
            "phone_digit_sequence_disagreement",
        }

        if not (flagset & strong_flags):
            score = 0.0
        else:
            # Figure/caption blocks should be demoted unless they have truly strong evidence.
            score = max(0.0, score - 0.12)

    # Caption-like blocks are usually useful for retrieval. Do not over-penalize them
    # unless they contain structured entities, metadata/ad cues, repetition, or OCR disagreement.
    title_low = (block.title or "").lower()
    text_low = (block.text or "").lower()
    caption_like = (
        "caption" in title_low
        or text_low.startswith("fig.")
        or text_low.startswith("figure ")
        or "top notch" in text_low[:80]
    )
    if caption_like:
        caption_strong = {
            "phone_number_detected",
            "email_detected",
            "url_detected",
            "doi_detected",
            "isbn_detected",
            "metadata_or_advertisement_keyword",
            "repeated_bigram_loop",
            "repeated_2gram_loop",
            "repeated_3gram_loop",
            "secondary_ocr_strong_disagreement",
            "phone_digit_sequence_disagreement",
        }
        if not (flagset & caption_strong):
            score = min(score, 0.20)

    block.risk_score = min(1.0, score)

    if block.risk_score >= 0.70:
        block.risk_level = "high"
    elif block.risk_score >= 0.35:
        block.risk_level = "medium"
    else:
        block.risk_level = "low"

    structured_entity = bool(
        flagset
        & {
            "phone_number_detected",
            "email_detected",
            "url_detected",
            "doi_detected",
            "isbn_detected",
        }
    )

    repetition_loop = bool(
        flagset
        & {
            "single_token_repeated_many_times",
            "repeated_bigram_loop",
            "repeated_2gram_loop",
            "repeated_3gram_loop",
        }
    )

    strong_hallucination_signal = bool(
        flagset
        & {
            "secondary_ocr_strong_disagreement",
            "phone_digit_sequence_disagreement",
            "text_density_extreme_outlier_for_bbox",
        }
    )

    metadata_like = "metadata_or_advertisement_keyword" in flagset

    block.index_text = block.text
    block.use_for_embedding = True
    block.use_for_node_generation = True
    block.keep_as_evidence = True

    if block.text_len == 0:
        block.verification_status = "empty"
        block.index_text = ""
        block.use_for_embedding = False
        block.use_for_node_generation = False

    elif metadata_like and "inside_complex_layout_container" in flagset and block.risk_level in {"medium", "high"}:
        block.verification_status = "metadata_only"
        block.index_text = ""
        block.use_for_embedding = False
        block.use_for_node_generation = False

    elif block.risk_level == "high" and (strong_hallucination_signal or repetition_loop):
        block.verification_status = "quarantined"
        block.index_text = ""
        block.use_for_embedding = False
        block.use_for_node_generation = False

    elif structured_entity and block.risk_level in {"medium", "high"}:
        block.verification_status = "entity_masked"
        block.index_text = mask_entities(block.text)
        block.use_for_embedding = allow_medium_index and block.risk_level == "medium"
        block.use_for_node_generation = False

    elif block.risk_level == "medium":
        block.verification_status = "needs_review"
        block.index_text = mask_entities(block.text) if structured_entity else block.text
        block.use_for_embedding = allow_medium_index
        block.use_for_node_generation = False

    elif block.risk_level == "high":
        block.verification_status = "quarantined"
        block.index_text = ""
        block.use_for_embedding = False
        block.use_for_node_generation = False

    else:
        block.verification_status = "accepted"
        block.index_text = block.text
        block.use_for_embedding = True
        block.use_for_node_generation = True


def find_page_image(image_root: Path, page_id: str) -> Optional[Path]:
    candidates: List[Path] = []

    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        candidates.append(image_root / f"{page_id}{ext}")

    page_dir = image_root / page_id
    for name in [
        "page.png",
        "page.jpg",
        "raw.png",
        "raw.jpg",
        "origin.png",
        "origin.jpg",
        "result.png",
        "result.jpg",
        "result_with_boxes.jpg",
    ]:
        candidates.append(page_dir / name)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    for hit in image_root.rglob(f"{page_id}.*"):
        if hit.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            return hit

    return None


def crop_block(
    block: OCRBlock,
    image_path: Path,
    out_dir: Path,
    padding: int = 12,
) -> Optional[Path]:
    if Image is None:
        return None

    bbox = choose_bbox(block)
    if not bbox:
        return None

    try:
        image = Image.open(image_path).convert("RGB")
    except Exception:
        return None

    width, height = image.size

    x1, y1, x2, y2 = bbox[:4]
    x1 = max(0, int(math.floor(x1 - padding)))
    y1 = max(0, int(math.floor(y1 - padding)))
    x2 = min(width, int(math.ceil(x2 + padding)))
    y2 = min(height, int(math.ceil(y2 + padding)))

    if x2 <= x1 or y2 <= y1:
        return None

    crop = image.crop((x1, y1, x2, y2))
    crop_width, crop_height = crop.size

    if max(crop_width, crop_height) < 900:
        crop = crop.resize((crop_width * 2, crop_height * 2))

    out_dir.mkdir(parents=True, exist_ok=True)

    safe_block_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", block.block_id)
    crop_path = out_dir / f"{block.page_id}_{block.rid}_{safe_block_id}.png"
    crop.save(crop_path)

    return crop_path


def run_tesseract(crop_path: Path) -> str:
    try:
        proc = subprocess.run(
            ["tesseract", str(crop_path), "stdout", "--psm", "6", "-l", "eng"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return ""
        return clean_ws(proc.stdout)
    except Exception:
        return ""


def char_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    a = clean_ws(a.lower())
    b = clean_ws(b.lower())
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def token_overlap(a: str, b: str) -> float:
    tokens_a = set(tokenize(a))
    tokens_b = set(tokenize(b))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a), 1)


def needs_crop_or_secondary_ocr(block: OCRBlock) -> bool:
    flags = set(block.flags)

    # Complex container alone is only a layout warning, not a reason to crop/re-OCR.
    # Figure/image text is common and should not be re-OCRed unless it also has
    # structured entities, metadata/ad cues, repetition loops, or density outliers.
    strong_triggers = {
        "phone_number_detected",
        "email_detected",
        "url_detected",
        "doi_detected",
        "isbn_detected",
        "text_density_outlier_for_bbox",
        "text_density_extreme_outlier_for_bbox",
        "repeated_bigram_loop",
        "repeated_2gram_loop",
        "repeated_3gram_loop",
        "metadata_or_advertisement_keyword",
    }

    return bool(flags & strong_triggers) and block.text_len > 0


def apply_secondary_ocr_check(block: OCRBlock, second_text: str) -> None:
    block.secondary_ocr_text = second_text

    if not second_text:
        block.flags.append("secondary_ocr_empty")
        block.flags = sorted(set(block.flags))
        return

    sim = char_similarity(block.text, second_text)
    overlap = token_overlap(block.text, second_text)

    block.secondary_char_similarity = sim
    block.secondary_token_overlap = overlap

    if block.text_len >= 40:
        if overlap < 0.20 and sim < 0.30:
            block.flags.append("secondary_ocr_strong_disagreement")
        elif overlap < 0.35:
            block.flags.append("secondary_ocr_partial_disagreement")

    ds_entities = extract_entities(block.text)
    second_entities = extract_entities(second_text)

    ds_phones = [
        digits_only(phone)
        for phone in ds_entities["phone"]
        if len(digits_only(phone)) >= 7
    ]

    second_phones = [
        digits_only(phone)
        for phone in second_entities["phone"]
        if len(digits_only(phone)) >= 7
    ]

    if ds_phones:
        if not second_phones:
            block.flags.append("phone_not_supported_by_secondary_ocr")
        else:
            verified = False
            for a in ds_phones:
                for b in second_phones:
                    if a == b or a in b or b in a:
                        verified = True
            if not verified:
                block.flags.append("phone_digit_sequence_disagreement")

    block.flags = sorted(set(block.flags))


def write_outputs(
    blocks: List[OCRBlock],
    regions: Dict[str, RegionSummary],
    out_root: Path,
) -> None:
    out_root.mkdir(parents=True, exist_ok=True)

    data = {
        "blocks": [asdict(block) for block in blocks],
        "regions": {key: asdict(region) for key, region in regions.items()},
    }

    json_path = out_root / "ocr_verification_blocks.json"
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    risky = [
        block
        for block in blocks
        if block.risk_level in {"medium", "high"}
        or block.verification_status not in {"accepted", "empty"}
    ]

    risky = sorted(risky, key=lambda b: (-b.risk_score, b.page_id, b.rid))

    lines: List[str] = []
    lines.append("# OCR Verification Report")
    lines.append("")
    lines.append(f"- total blocks: {len(blocks)}")
    lines.append(f"- risky blocks: {len(risky)}")
    lines.append(f"- high risk: {sum(1 for b in blocks if b.risk_level == 'high')}")
    lines.append(f"- medium risk: {sum(1 for b in blocks if b.risk_level == 'medium')}")
    lines.append("")

    status_counts = Counter(block.verification_status for block in blocks)

    lines.append("## Status counts")
    lines.append("")
    for status, count in status_counts.most_common():
        lines.append(f"- {status}: {count}")

    lines.append("")
    lines.append("## Top risky blocks")
    lines.append("")

    for block in risky[:300]:
        lines.append(f"### {block.page_id} · {block.rid} · {block.block_id}")
        lines.append("")
        lines.append(f"- risk: **{block.risk_level}** / {block.risk_score:.2f}")
        lines.append(f"- status: `{block.verification_status}`")
        lines.append(f"- title: `{block.title}`")
        lines.append(f"- kind: `{block.kind}`")
        lines.append(f"- matched_region: `{block.matched_region}`")
        lines.append(f"- matched_region_ids: `{', '.join(block.matched_region_ids)}`")
        lines.append(f"- matched_region_type: `{block.matched_region_type}`")
        lines.append(f"- bbox: `{block.bbox}`")
        lines.append(f"- deepseek_bbox: `{block.deepseek_bbox}`")
        lines.append(f"- flags: `{', '.join(block.flags)}`")

        if block.crop_path:
            lines.append(f"- crop: `{block.crop_path}`")

        if block.secondary_ocr_text:
            lines.append(f"- secondary token overlap: `{block.secondary_token_overlap}`")
            lines.append(f"- secondary char similarity: `{block.secondary_char_similarity}`")
            lines.append("")
            lines.append("Secondary OCR:")
            lines.append("```text")
            lines.append(block.secondary_ocr_text[:800])
            lines.append("```")

        lines.append("")
        lines.append("Raw OCR used for scoring:")
        lines.append("```text")
        lines.append(block.text[:1200])
        lines.append("```")

        if block.raw_text_before_filter and block.raw_text_before_filter != block.text:
            lines.append("")
            lines.append("Raw text before metadata filter:")
            lines.append("```text")
            lines.append(block.raw_text_before_filter[:800])
            lines.append("```")

        lines.append("")

    report_path = out_root / "ocr_verification_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"[OK] wrote {json_path}")
    print(f"[OK] wrote {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--md-root", required=True)
    parser.add_argument("--image-root", default=None)
    parser.add_argument("--out-root", required=True)

    parser.add_argument("--save-crops", action="store_true")
    parser.add_argument("--secondary-ocr", choices=["none", "tesseract"], default="none")
    parser.add_argument("--max-secondary", type=int, default=200)
    parser.add_argument("--allow-medium-index", action="store_true")

    args = parser.parse_args()

    md_root = Path(args.md_root)
    out_root = Path(args.out_root)
    image_root = Path(args.image_root) if args.image_root else None

    blocks = load_blocks(md_root)
    if not blocks:
        raise SystemExit(f"No markdown blocks found under: {md_root}")

    regions = build_region_index(blocks)
    compute_initial_flags(blocks, regions)

    for block in blocks:
        score_and_decide(block, allow_medium_index=args.allow_medium_index)

    if args.save_crops or args.secondary_ocr != "none":
        if image_root is None:
            print("[WARN] --image-root not provided, skip crops / secondary OCR.")
        elif Image is None:
            print("[WARN] pillow not available, skip crops / secondary OCR.")
        else:
            candidates = [block for block in blocks if needs_crop_or_secondary_ocr(block)]
            candidates = sorted(candidates, key=lambda b: (-b.risk_score, b.page_id, b.rid))
            candidates = candidates[:args.max_secondary]

            print(f"[INFO] crop / secondary candidates: {len(candidates)}")

            for i, block in enumerate(candidates, start=1):
                image_path = find_page_image(image_root, block.page_id)

                if image_path is None:
                    block.flags.append("page_image_not_found")
                    block.flags = sorted(set(block.flags))
                    score_and_decide(block, allow_medium_index=args.allow_medium_index)
                    continue

                crop_dir = out_root / "crops" / block.page_id
                crop_path = crop_block(block, image_path, crop_dir)

                if crop_path is None:
                    block.flags.append("crop_failed")
                    block.flags = sorted(set(block.flags))
                    score_and_decide(block, allow_medium_index=args.allow_medium_index)
                    continue

                block.crop_path = str(crop_path)

                if args.secondary_ocr == "tesseract":
                    second_text = run_tesseract(crop_path)
                    apply_secondary_ocr_check(block, second_text)
                    score_and_decide(block, allow_medium_index=args.allow_medium_index)

                if i % 25 == 0:
                    print(f"[INFO] processed {i}/{len(candidates)}")

    write_outputs(blocks, regions, out_root)

    print("")
    print("Summary:")
    print(f"  total blocks: {len(blocks)}")
    print(f"  high risk:    {sum(1 for b in blocks if b.risk_level == 'high')}")
    print(f"  medium risk:  {sum(1 for b in blocks if b.risk_level == 'medium')}")
    print(f"  accepted:     {sum(1 for b in blocks if b.verification_status == 'accepted')}")
    print(f"  empty:        {sum(1 for b in blocks if b.verification_status == 'empty')}")


if __name__ == "__main__":
    main()
