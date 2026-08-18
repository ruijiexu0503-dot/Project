from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from .block_classifier import block_text


def block_key(block: dict[str, Any]) -> tuple[str, str]:
    return (str(block.get("_page") or ""), str(block.get("block_id") or ""))


def _text(block: dict[str, Any]) -> str:
    return block_text(block).strip()


def _bbox(block: dict[str, Any]) -> list[float] | None:
    raw = block.get("bbox") or block.get("deepseek_bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) < 4:
        return None
    try:
        return [float(v) for v in raw[:4]]
    except (TypeError, ValueError):
        return None


def _fingerprint(text: str, normalize_digits: bool = True) -> str:
    value = text.lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if normalize_digits:
        value = re.sub(r"\d+", "#", value)
    value = re.sub(r"[^a-zà-öø-ÿ0-9#@./:+_-]+", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def _vertical_zone(block: dict[str, Any], edge_fraction: float) -> str | None:
    bbox = _bbox(block)
    height = block.get("_page_height")
    if bbox is None or not isinstance(height, (int, float)) or height <= 0:
        return None
    _, y1, _, y2 = bbox
    center = (y1 + y2) / 2.0 / float(height)
    if center <= edge_fraction:
        return "top"
    if center >= 1.0 - edge_fraction:
        return "bottom"
    return "middle"


def detect_repeated_templates(
    blocks: list[dict[str, Any]], config: dict[str, Any] | None = None
) -> tuple[set[tuple[str, str]], list[dict[str, Any]], dict[str, int]]:
    """Find high-confidence repeated document chrome before Evidence-node construction.

    Two conservative channels are used:
    1. repeated short text at a consistent top/bottom page zone when geometry exists;
    2. very frequent exact-ish short text repetition when geometry is missing.

    The second channel deliberately requires a higher page-frequency threshold so recurring article
    language is not mistaken for template chrome.
    """
    cfg = config or {}
    max_chars = int(cfg.get("max_chars", 180))
    edge_fraction = float(cfg.get("edge_fraction", 0.14))
    min_pages = int(cfg.get("min_pages", 4))
    min_page_fraction = float(cfg.get("min_page_fraction", 0.35))
    bboxless_min_page_fraction = float(cfg.get("bboxless_min_page_fraction", 0.60))

    pages = {str(block.get("_page") or "") for block in blocks}
    page_count = max(1, len(pages))
    spatial_required = max(min_pages, math.ceil(page_count * min_page_fraction))
    bboxless_required = max(min_pages, math.ceil(page_count * bboxless_min_page_fraction))

    spatial_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    bboxless_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for block in blocks:
        text = _text(block)
        if not text or len(text) > max_chars:
            continue
        fp = _fingerprint(text)
        if len(fp) < 3:
            continue
        zone = _vertical_zone(block, edge_fraction)
        if zone in {"top", "bottom"}:
            spatial_groups[(zone, fp)].append(block)
        elif _bbox(block) is None:
            bboxless_groups[fp].append(block)

    detected: set[tuple[str, str]] = set()
    review: list[dict[str, Any]] = []
    spatial_clusters = 0
    bboxless_clusters = 0

    def accept_group(rows: list[dict[str, Any]], method: str, threshold: int, fingerprint: str, zone: str | None):
        nonlocal spatial_clusters, bboxless_clusters
        distinct_pages = sorted({str(row.get("_page") or "") for row in rows})
        if len(distinct_pages) < threshold:
            return
        if method == "repeated_edge_text":
            spatial_clusters += 1
        else:
            bboxless_clusters += 1
        for row in rows:
            detected.add(block_key(row))
        review.append({
            "method": method,
            "zone": zone,
            "fingerprint": fingerprint,
            "page_count": len(distinct_pages),
            "pages": distinct_pages,
            "examples": [
                {"page": row.get("_page"), "block_id": row.get("block_id"), "text": _text(row), "bbox": _bbox(row)}
                for row in rows[:5]
            ],
        })

    for (zone, fp), rows in spatial_groups.items():
        accept_group(rows, "repeated_edge_text", spatial_required, fp, zone)
    for fp, rows in bboxless_groups.items():
        accept_group(rows, "repeated_bboxless_text", bboxless_required, fp, None)

    stats = {
        "document_pages": page_count,
        "spatial_required_pages": spatial_required,
        "bboxless_required_pages": bboxless_required,
        "template_clusters": spatial_clusters + bboxless_clusters,
        "spatial_template_clusters": spatial_clusters,
        "bboxless_template_clusters": bboxless_clusters,
        "template_blocks": len(detected),
    }
    return detected, review, stats
