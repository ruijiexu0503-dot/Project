from __future__ import annotations

import math
import re
from collections import defaultdict
from difflib import SequenceMatcher
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


def _normalize_text(text: str) -> str:
    value = text.lower()
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"\d+", "#", value)
    value = re.sub(r"[^a-zà-öø-ÿ0-9#@./:+_-]+", " ", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(text: str) -> set[str]:
    return {token for token in _normalize_text(text).split() if len(token) >= 3}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _normalized_bbox(block: dict[str, Any]) -> list[float] | None:
    bbox = _bbox(block)
    width = block.get("_page_width")
    height = block.get("_page_height")
    if bbox is None or not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return None
    if width <= 0 or height <= 0:
        return None
    x1, y1, x2, y2 = bbox
    return [x1 / width, y1 / height, x2 / width, y2 / height]


def _candidate_zone(block: dict[str, Any], edge_fraction: float) -> str | None:
    bbox = _normalized_bbox(block)
    if bbox is None:
        return None
    _, y1, _, y2 = bbox
    center = (y1 + y2) / 2.0
    if center <= edge_fraction:
        return "top"
    if center >= 1.0 - edge_fraction:
        return "bottom"
    return None


def _page_bundles(
    blocks: list[dict[str, Any]], edge_fraction: float, reading_order_edge_items: int
) -> list[dict[str, Any]]:
    """Build one top and one bottom template candidate bundle per page.

    Geometry is preferred. Bboxless blocks are admitted only when they occur among the first/last
    few reading-order items, so the bundle can still represent digital-edition chrome whose OCR
    survived without layout geometry.
    """
    by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        by_page[str(block.get("_page") or "")].append(block)

    bundles: list[dict[str, Any]] = []
    for page, rows in by_page.items():
        n = len(rows)
        for zone in ("top", "bottom"):
            members: list[dict[str, Any]] = []
            for index, block in enumerate(rows):
                geometry_zone = _candidate_zone(block, edge_fraction)
                at_reading_edge = (
                    index < reading_order_edge_items if zone == "top"
                    else index >= max(0, n - reading_order_edge_items)
                )
                if geometry_zone == zone or (_bbox(block) is None and at_reading_edge):
                    if _text(block):
                        members.append(block)
            if not members:
                continue
            text = " | ".join(_text(block) for block in members)
            normalized = _normalize_text(text)
            if len(normalized) < 3:
                continue
            normalized_boxes = [box for block in members if (box := _normalized_bbox(block)) is not None]
            if normalized_boxes:
                geometry = [
                    min(box[0] for box in normalized_boxes),
                    min(box[1] for box in normalized_boxes),
                    max(box[2] for box in normalized_boxes),
                    max(box[3] for box in normalized_boxes),
                ]
            else:
                geometry = None
            bundles.append({
                "page": page,
                "zone": zone,
                "members": members,
                "member_keys": {block_key(block) for block in members},
                "text": text,
                "normalized_text": normalized,
                "tokens": _tokens(text),
                "geometry": geometry,
                "block_count": len(members),
            })
    return bundles


def _geometry_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    a, b = left.get("geometry"), right.get("geometry")
    if a is None or b is None:
        return 0.0
    acx, acy = (a[0] + a[2]) / 2.0, (a[1] + a[3]) / 2.0
    bcx, bcy = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
    distance = math.hypot(acx - bcx, acy - bcy)
    size_delta = abs((a[2] - a[0]) - (b[2] - b[0])) + abs((a[3] - a[1]) - (b[3] - b[1]))
    return max(0.0, 1.0 - min(1.0, distance * 3.0 + size_delta))


def _bundle_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    if left["zone"] != right["zone"]:
        return 0.0
    token_score = _jaccard(left["tokens"], right["tokens"])
    sequence_score = SequenceMatcher(None, left["normalized_text"], right["normalized_text"]).ratio()
    geometry_score = _geometry_similarity(left, right)
    count_score = min(left["block_count"], right["block_count"]) / max(left["block_count"], right["block_count"])

    # Text is the strongest signal; geometry/count stabilize OCR-fragmented variants.
    if left["tokens"] and right["tokens"]:
        return 0.45 * token_score + 0.30 * sequence_score + 0.15 * geometry_score + 0.10 * count_score
    return 0.55 * sequence_score + 0.25 * geometry_score + 0.20 * count_score


def _cluster_bundles(bundles: list[dict[str, Any]], similarity_threshold: float) -> list[list[dict[str, Any]]]:
    """Greedy representative clustering with no assumed number of template families."""
    clusters: list[list[dict[str, Any]]] = []
    for bundle in sorted(bundles, key=lambda row: (row["zone"], page_number(row["page"]))):
        best_index = None
        best_score = 0.0
        for index, cluster in enumerate(clusters):
            representative = cluster[0]
            score = _bundle_similarity(bundle, representative)
            if score >= similarity_threshold and score > best_score:
                best_index, best_score = index, score
        if best_index is None:
            clusters.append([bundle])
        else:
            clusters[best_index].append(bundle)
    return clusters


def _pattern_label(pages: list[str], total_pages: int) -> str:
    numbers = sorted(page_number(page) for page in pages)
    if not numbers:
        return "UNKNOWN"
    support = len(numbers) / max(1, total_pages)
    if support >= 0.70:
        return "UNIVERSAL"
    if len(numbers) >= 4:
        parity = {number % 2 for number in numbers}
        if len(parity) == 1:
            return "ALTERNATING"
        span = numbers[-1] - numbers[0] + 1
        density = len(numbers) / max(1, span)
        if density >= 0.70 and span < total_pages * 0.80:
            return "SECTION_SPECIFIC"
    return "REPEATED"


def detect_repeated_templates(
    blocks: list[dict[str, Any]], config: dict[str, Any] | None = None
) -> tuple[set[tuple[str, str]], list[dict[str, Any]], dict[str, Any]]:
    """Discover repeated page-edge template families without assuming magazine layout pattern.

    The detector first creates top/bottom bundles for every page, then clusters similar bundles
    across the document. Only after clustering does it describe the observed page distribution as
    universal, alternating, section-specific, or simply repeated. Parity is therefore diagnostic,
    not a detection rule.
    """
    cfg = config or {}
    edge_fraction = float(cfg.get("edge_fraction", 0.14))
    edge_items = int(cfg.get("reading_order_edge_items", 4))
    similarity_threshold = float(cfg.get("bundle_similarity_threshold", 0.62))
    min_pages = int(cfg.get("min_pages", 4))
    min_page_fraction = float(cfg.get("min_page_fraction", 0.18))
    max_bundle_chars = int(cfg.get("max_bundle_chars", 700))

    pages = sorted({str(block.get("_page") or "") for block in blocks}, key=page_number)
    required_pages = max(min_pages, math.ceil(len(pages) * min_page_fraction))
    bundles = [
        bundle for bundle in _page_bundles(blocks, edge_fraction, edge_items)
        if len(bundle["normalized_text"]) <= max_bundle_chars
    ]
    clusters = _cluster_bundles(bundles, similarity_threshold)

    detected: set[tuple[str, str]] = set()
    review: list[dict[str, Any]] = []
    accepted_clusters = 0
    for cluster_index, cluster in enumerate(clusters):
        distinct_pages = sorted({bundle["page"] for bundle in cluster}, key=page_number)
        if len(distinct_pages) < required_pages:
            continue
        accepted_clusters += 1
        for bundle in cluster:
            detected.update(bundle["member_keys"])
        representative = cluster[0]
        review.append({
            "method": "page_edge_bundle_clustering",
            "cluster_id": f"template_family_{accepted_clusters:02d}",
            "zone": representative["zone"],
            "pattern": _pattern_label(distinct_pages, len(pages)),
            "threshold_pages": required_pages,
            "page_count": len(distinct_pages),
            "support_fraction": round(len(distinct_pages) / max(1, len(pages)), 4),
            "pages": distinct_pages,
            "representative_text": representative["text"][:500],
            "representative_block_count": representative["block_count"],
            "representative_geometry": representative["geometry"],
            "examples": [
                {
                    "page": bundle["page"],
                    "text": bundle["text"][:350],
                    "block_count": bundle["block_count"],
                    "geometry": bundle["geometry"],
                    "member_block_ids": [block.get("block_id") for block in bundle["members"]],
                }
                for bundle in cluster[:6]
            ],
        })

    stats: dict[str, Any] = {
        "document_pages": len(pages),
        "candidate_bundles": len(bundles),
        "raw_clusters": len(clusters),
        "required_pages": required_pages,
        "bundle_similarity_threshold": similarity_threshold,
        "template_clusters": accepted_clusters,
        "template_blocks": len(detected),
        "pattern_counts": dict(sorted({
            pattern: sum(1 for row in review if row["pattern"] == pattern)
            for pattern in {row["pattern"] for row in review}
        }.items())),
    }
    return detected, review, stats
