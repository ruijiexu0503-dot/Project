from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .block_classifier import block_text
from .repeated_template_detector import block_key


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


def _text(block: dict[str, Any]) -> str:
    return block_text(block).strip()


def _unmatched(block: dict[str, Any]) -> bool:
    flags = {str(value).lower() for value in (block.get("flags") or [])}
    return block.get("matched_region_id") is None and (
        "no_layout_match" in flags
        or str(block.get("bbox_source") or "").lower() in {"", "missing", "none"}
    )


def _urlish(text: str) -> bool:
    return bool(re.search(r"(?:https?://|www\.|\b[a-z0-9-]+\.(?:com|org|net|it|de|io)\b|@)", text, re.I))


def _page_reference(text: str) -> bool:
    return bool(re.search(r"(?:\.|\s)\d{1,3}\s*$", text)) and len(text) <= 180


def _bullet_like(text: str) -> bool:
    return bool(re.match(r"^\s*[•▪◦‣*-]\s*\S", text))


def _ad_hits(text: str) -> int:
    low = text.lower()
    return sum(term in low for term in AD_TERMS)


def classify_magazine_pages(
    blocks: list[dict[str, Any]],
    template_keys: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Assign conservative page roles for routing, not article segmentation.

    Roles are ARTICLE_OR_MIXED, NAVIGATION, FULL_AD, and TEMPLATE_HEAVY. The classifier is designed
    to prefer ARTICLE_OR_MIXED when evidence is ambiguous.
    """
    template_keys = template_keys or set()
    by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        by_page[str(block.get("_page") or "")].append(block)

    report: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = defaultdict(int)

    for page, page_blocks in by_page.items():
        content_blocks = [block for block in page_blocks if block_key(block) not in template_keys and _text(block)]
        texts = [_text(block) for block in content_blocks]
        joined = "\n".join(texts).lower()
        bullet_count = sum(_bullet_like(text) for text in texts)
        page_ref_count = sum(_page_reference(text) for text in texts)
        url_count = sum(_urlish(text) for text in texts)
        ad_term_hits = sum(_ad_hits(text) for text in texts)
        short_unmatched = sum(_unmatched(block) and len(_text(block)) <= 120 for block in content_blocks)
        template_count = sum(block_key(block) in template_keys for block in page_blocks)
        nav_heading = any(term in joined for term in NAV_TERMS)

        role = "ARTICLE_OR_MIXED"
        reasons: list[str] = []

        if page_blocks and template_count / len(page_blocks) >= 0.65:
            role = "TEMPLATE_HEAVY"
            reasons.append("template_blocks_dominate_page")
        elif (
            (nav_heading and (bullet_count >= 2 or page_ref_count >= 2))
            or bullet_count >= 5
            or page_ref_count >= 5
        ):
            role = "NAVIGATION"
            if nav_heading:
                reasons.append("navigation_heading_or_section_term")
            if bullet_count >= 2:
                reasons.append("multiple_bullet_entries")
            if page_ref_count >= 2:
                reasons.append("multiple_page_reference_entries")
        elif url_count >= 1 and ad_term_hits >= 2 and short_unmatched >= 4:
            role = "FULL_AD"
            reasons.extend([
                "commercial_url_or_contact_signal",
                "multiple_product_marketing_terms",
                "many_short_unmatched_blocks",
            ])

        report[page] = {
            "page": page,
            "role": role,
            "reasons": reasons,
            "block_count": len(page_blocks),
            "content_block_count": len(content_blocks),
            "template_block_count": template_count,
            "bullet_count": bullet_count,
            "page_reference_count": page_ref_count,
            "url_count": url_count,
            "ad_term_hits": ad_term_hits,
            "short_unmatched_count": short_unmatched,
        }
        counts[role] += 1

    return report, dict(sorted(counts.items()))
