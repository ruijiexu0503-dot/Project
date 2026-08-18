from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from .block_classifier import block_text
from .loader import page_number


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


def _split_family(page: str) -> str:
    """Return alternating split-page family.

    Split-render output is ordered page-by-page from each two-page PDF spread. We deliberately call
    these family_a/family_b rather than hard-coding left/right into the algorithm; for CERN Courier,
    visual inspection of the source PDF shows the two families correspond to the two spread sides.
    """
    try:
        number = page_number(page)
    except Exception:
        return "unknown"
    return "family_a" if number % 2 == 1 else "family_b"


def _page_edge_positions(blocks: list[dict[str, Any]], edge_items: int) -> dict[tuple[str, str], str]:
    by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        by_page[str(block.get("_page") or "")].append(block)
    positions: dict[tuple[str, str], str] = {}
    for rows in by_page.values():
        n = len(rows)
        for index, block in enumerate(rows):
            key = block_key(block)
            if index < edge_items:
                positions[key] = "head"
            if index >= max(0, n - edge_items):
                positions[key] = "tail"
    return positions


def detect_repeated_templates(
    blocks: list[dict[str, Any]], config: dict[str, Any] | None = None
) -> tuple[set[tuple[str, str]], list[dict[str, Any]], dict[str, Any]]:
    """Find repeated magazine chrome, allowing alternating left/right spread templates.

    CERN Courier's digital edition uses different footer content on the two sides of a spread. The
    detector therefore clusters repetitions within alternating split-page families instead of
    requiring the same footer fingerprint across all 62 split pages.
    """
    cfg = config or {}
    max_chars = int(cfg.get("max_chars", 180))
    edge_fraction = float(cfg.get("edge_fraction", 0.14))
    edge_items = int(cfg.get("reading_order_edge_items", 4))
    min_pages = int(cfg.get("min_pages", 4))
    min_family_fraction = float(cfg.get("min_family_fraction", 0.30))
    bboxless_edge_min_family_fraction = float(cfg.get("bboxless_edge_min_family_fraction", 0.25))
    bboxless_min_family_fraction = float(cfg.get("bboxless_min_family_fraction", 0.55))

    pages = sorted({str(block.get("_page") or "") for block in blocks})
    family_pages: dict[str, set[str]] = defaultdict(set)
    for page in pages:
        family_pages[_split_family(page)].add(page)

    thresholds: dict[str, dict[str, int]] = {}
    for family, members in family_pages.items():
        count = max(1, len(members))
        thresholds[family] = {
            "spatial": max(min_pages, math.ceil(count * min_family_fraction)),
            "bboxless_edge": max(min_pages, math.ceil(count * bboxless_edge_min_family_fraction)),
            "bboxless": max(min_pages, math.ceil(count * bboxless_min_family_fraction)),
        }

    edge_positions = _page_edge_positions(blocks, edge_items)
    spatial_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    bboxless_edge_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    bboxless_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for block in blocks:
        text = _text(block)
        if not text or len(text) > max_chars:
            continue
        fp = _fingerprint(text)
        if len(fp) < 3:
            continue
        page = str(block.get("_page") or "")
        family = _split_family(page)
        zone = _vertical_zone(block, edge_fraction)
        if zone in {"top", "bottom"}:
            spatial_groups[(family, zone, fp)].append(block)
            continue
        if _bbox(block) is None:
            edge_position = edge_positions.get(block_key(block))
            if edge_position in {"head", "tail"}:
                bboxless_edge_groups[(family, edge_position, fp)].append(block)
            bboxless_groups[(family, fp)].append(block)

    detected: set[tuple[str, str]] = set()
    review: list[dict[str, Any]] = []
    counts = defaultdict(int)

    def accept_group(
        rows: list[dict[str, Any]],
        method: str,
        family: str,
        threshold_kind: str,
        fingerprint: str,
        zone: str | None,
    ) -> None:
        threshold = thresholds.get(family, {}).get(threshold_kind, min_pages)
        distinct_pages = sorted({str(row.get("_page") or "") for row in rows})
        if len(distinct_pages) < threshold:
            return
        counts[method] += 1
        for row in rows:
            detected.add(block_key(row))
        review.append({
            "method": method,
            "family": family,
            "zone": zone,
            "fingerprint": fingerprint,
            "threshold_pages": threshold,
            "page_count": len(distinct_pages),
            "pages": distinct_pages,
            "examples": [
                {
                    "page": row.get("_page"),
                    "block_id": row.get("block_id"),
                    "text": _text(row),
                    "bbox": _bbox(row),
                    "final_order": row.get("final_order"),
                }
                for row in rows[:6]
            ],
        })

    for (family, zone, fp), rows in spatial_groups.items():
        accept_group(rows, "repeated_edge_text", family, "spatial", fp, zone)
    for (family, position, fp), rows in bboxless_edge_groups.items():
        accept_group(rows, "repeated_reading_order_edge_text", family, "bboxless_edge", fp, position)
    for (family, fp), rows in bboxless_groups.items():
        accept_group(rows, "repeated_bboxless_text", family, "bboxless", fp, None)

    stats: dict[str, Any] = {
        "document_pages": len(pages),
        "family_pages": {family: len(members) for family, members in sorted(family_pages.items())},
        "family_thresholds": thresholds,
        "template_clusters": sum(counts.values()),
        "spatial_template_clusters": counts["repeated_edge_text"],
        "bboxless_edge_template_clusters": counts["repeated_reading_order_edge_text"],
        "bboxless_template_clusters": counts["repeated_bboxless_text"],
        "template_blocks": len(detected),
    }
    return detected, review, stats
