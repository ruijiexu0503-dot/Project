from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .block_classifier import block_text


AD_TERMS = {
    "advertisement", "advertising", "product", "products", "solution", "solutions",
    "powered crate", "powered crates", "power supply", "power supplies", "high voltage",
    "low voltage", "source measure unit", "digitizer", "fpga", "module", "modules",
    "order now", "contact", "sales", "brochure", "technology", "technologies",
}
NAV_TERMS = {
    "contents", "in this issue", "table of contents", "news", "features", "opinion",
    "reviews", "careers", "people", "events", "bookshelf", "editorial",
}
TEMPLATE_TOKENS = {"→", "←", "↑", "↓", "i", "☐", "□", "■", "●", "•"}


def _text(block: dict[str, Any]) -> str:
    return block_text(block).strip()


def _low(block: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", _text(block)).strip().lower()


def _unmatched(block: dict[str, Any]) -> bool:
    flags = {str(v).lower() for v in (block.get("flags") or [])}
    return block.get("matched_region_id") is None and (
        "no_layout_match" in flags or str(block.get("bbox_source") or "").lower() in {"", "missing", "none"}
    )


def _urlish(text: str) -> bool:
    return bool(re.search(r"(?:https?://|www\.|\b[a-z0-9-]+\.(?:com|org|net|it|de|io)\b|@)", text, re.I))


def _page_reference(text: str) -> bool:
    # Magazine TOC/teaser entries often end with a printed folio.
    return bool(re.search(r"(?:\.|\s)\d{1,3}\s*$", text)) and len(text) <= 180


def _bullet_like(text: str) -> bool:
    return bool(re.match(r"^\s*[•▪◦‣*-]\s*\S", text))


def _tiny_template(text: str) -> bool:
    compact = text.strip()
    if compact in TEMPLATE_TOKENS:
        return True
    visible = re.sub(r"\s+", "", compact)
    return len(visible) <= 2 and not any(ch.isalnum() for ch in visible)


def _ad_term_count(text: str) -> int:
    low = text.lower()
    return sum(term in low for term in AD_TERMS)


def _navigation_page(blocks: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    texts = [_low(block) for block in blocks if _text(block)]
    joined = "\n".join(texts)
    bullet_count = sum(_bullet_like(_text(block)) for block in blocks)
    page_ref_count = sum(_page_reference(_text(block)) for block in blocks)
    nav_heading = any(term in joined for term in NAV_TERMS)
    reasons = []
    if nav_heading:
        reasons.append("navigation_heading_or_section_term")
    if bullet_count >= 3:
        reasons.append("many_bullet_entries")
    if page_ref_count >= 3:
        reasons.append("many_page_reference_entries")
    return bool(nav_heading and (bullet_count >= 2 or page_ref_count >= 2) or bullet_count >= 5 or page_ref_count >= 5), reasons


def _advertisement_page(blocks: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    texts = [_text(block) for block in blocks if _text(block)]
    unmatched = [block for block in blocks if _unmatched(block) and _text(block)]
    url_count = sum(_urlish(text) for text in texts)
    ad_hits = sum(_ad_term_count(text) for text in texts)
    short_unmatched = sum(len(_text(block)) <= 120 for block in unmatched)
    reasons = []
    if url_count:
        reasons.append("commercial_url_or_contact_signal")
    if ad_hits >= 2:
        reasons.append("multiple_product_marketing_terms")
    if short_unmatched >= 4:
        reasons.append("many_short_unmatched_text_blocks")
    # Conservative page-level ad detection: require both commercial content and the fragmented
    # unmatched layout pattern typical of full-page magazine advertisements.
    is_ad = url_count >= 1 and ad_hits >= 2 and short_unmatched >= 4
    return is_ad, reasons


def route_magazine_roles(
    blocks: list[dict[str, Any]],
    classified: list[tuple[dict[str, Any], str]],
) -> tuple[list[tuple[dict[str, Any], str]], list[dict[str, Any]], dict[str, int]]:
    """Reroute obvious non-evidence magazine material using page context.

    This intentionally does not try to solve article segmentation. It only removes high-confidence
    navigation, advertisement, template, and noise material from ordinary Evidence content.
    """
    by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        by_page[str(block.get("_page") or "")].append(block)

    page_modes: dict[str, tuple[str | None, list[str]]] = {}
    for page, page_blocks in by_page.items():
        nav, nav_reasons = _navigation_page(page_blocks)
        ad, ad_reasons = _advertisement_page(page_blocks)
        if nav:
            page_modes[page] = ("navigation", nav_reasons)
        elif ad:
            page_modes[page] = ("advertisement", ad_reasons)
        else:
            page_modes[page] = (None, [])

    routed: list[tuple[dict[str, Any], str]] = []
    review: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)

    for block, base_role in classified:
        role = base_role
        text = _text(block)
        page = str(block.get("_page") or "")
        page_mode, page_reasons = page_modes.get(page, (None, []))
        reasons: list[str] = []

        if base_role == "evidence_content":
            if _tiny_template(text):
                role = "template"
                reasons.append("tiny_nonsemantic_symbol")
            elif page_mode == "navigation" and (
                _bullet_like(text) or _page_reference(text) or len(text) <= 180 or _unmatched(block)
            ):
                role = "navigation"
                reasons.extend(page_reasons)
            elif page_mode == "advertisement" and (
                _unmatched(block) or _urlish(text) or _ad_term_count(text) > 0
            ):
                role = "advertisement"
                reasons.extend(page_reasons)
            elif _urlish(text) and len(text) <= 40 and _unmatched(block):
                role = "template"
                reasons.append("isolated_url_or_wrapper_fragment")

        routed.append((block, role))
        counts[role] += 1
        if role != base_role:
            review.append({
                "page": page,
                "block_id": block.get("block_id"),
                "text": text,
                "base_role": base_role,
                "routed_role": role,
                "reasons": reasons,
                "page_mode": page_mode,
                "matched_region_id": block.get("matched_region_id"),
                "matched_region_label": block.get("matched_region_label"),
                "bbox_source": block.get("bbox_source"),
                "flags": block.get("flags") or [],
            })

    return routed, review, dict(sorted(counts.items()))
