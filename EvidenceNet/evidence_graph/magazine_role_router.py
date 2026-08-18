from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .block_classifier import block_text
from .repeated_template_detector import block_key


TEMPLATE_TOKENS = {"→", "←", "↑", "↓", "i", "☐", "□", "■", "●", "•"}


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


def _tiny_template(text: str) -> bool:
    compact = text.strip()
    if compact in TEMPLATE_TOKENS:
        return True
    visible = re.sub(r"\s+", "", compact)
    return len(visible) <= 2 and not any(ch.isalnum() for ch in visible)


def route_magazine_roles(
    blocks: list[dict[str, Any]],
    classified: list[tuple[dict[str, Any], str]],
    page_roles: dict[str, dict[str, Any]] | None = None,
    template_keys: set[tuple[str, str]] | None = None,
) -> tuple[list[tuple[dict[str, Any], str]], list[dict[str, Any]], dict[str, int]]:
    """Reroute high-confidence non-evidence magazine material before Evidence construction.

    Page classification and repeated-template detection are computed upstream. This router does not
    perform article segmentation and does not merge blocks.
    """
    page_roles = page_roles or {}
    template_keys = template_keys or set()
    routed: list[tuple[dict[str, Any], str]] = []
    review: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)

    for block, base_role in classified:
        role = base_role
        text = _text(block)
        page = str(block.get("_page") or "")
        page_info = page_roles.get(page, {})
        page_role = page_info.get("role", "ARTICLE_OR_MIXED")
        reasons: list[str] = []

        if block_key(block) in template_keys and base_role not in {
            "document_title", "author_metadata", "publication_metadata", "identifier_metadata"
        }:
            role = "template"
            reasons.append("document_level_repeated_template")
        elif base_role == "evidence_content":
            if _tiny_template(text):
                role = "template"
                reasons.append("tiny_nonsemantic_symbol")
            elif page_role == "NAVIGATION" and (
                _bullet_like(text) or _page_reference(text) or len(text) <= 180 or _unmatched(block)
            ):
                role = "navigation"
                reasons.extend(page_info.get("reasons") or ["navigation_page"])
            elif page_role == "FULL_AD":
                # Full-ad classification is page-first by design. Once a page meets the conservative
                # FULL_AD threshold, its ordinary evidence-like text is commercial material.
                role = "advertisement"
                reasons.extend(page_info.get("reasons") or ["full_ad_page"])
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
                "page_role": page_role,
                "matched_region_id": block.get("matched_region_id"),
                "matched_region_label": block.get("matched_region_label"),
                "bbox_source": block.get("bbox_source"),
                "flags": block.get("flags") or [],
            })

    return routed, review, dict(sorted(counts.items()))
