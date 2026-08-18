from __future__ import annotations

import re
from typing import Any


SKIP_TYPES = {"caption", "formula", "reference", "table", "figure"}


def _text(node: dict[str, Any]) -> str:
    return str(node.get("plain_text") or node.get("original_markdown") or "").strip()


def _bbox(node: dict[str, Any]) -> list[float] | None:
    members = node.get("source_members") or []
    if not members:
        return None
    bbox = members[0].get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        return [float(v) for v in bbox]
    except (TypeError, ValueError):
        return None


def _page(node: dict[str, Any]) -> Any:
    pages = node.get("page_ids") or []
    return pages[0] if len(pages) == 1 else None


def _title_like(node: dict[str, Any], text: str) -> bool:
    metadata = node.get("metadata") or {}
    block_type = str(metadata.get("block_type") or node.get("evidence_type") or "").lower()
    if "title" in block_type or "heading" in block_type:
        return True
    if text.startswith("#"):
        return True
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", text)
    if not words or len(words) > 10:
        return False
    alpha = [c for c in text if c.isalpha()]
    if alpha and sum(c.isupper() for c in alpha) / len(alpha) >= 0.75:
        return True
    title_words = sum(word[:1].isupper() for word in words if word)
    return len(words) >= 2 and title_words / len(words) >= 0.8 and not re.search(r"[.!?;,:]$", text)


def _fragmentary(node: dict[str, Any], max_chars: int) -> bool:
    text = _text(node)
    if not text or len(text) > max_chars:
        return False
    evidence_type = str(node.get("evidence_type") or "").lower()
    if evidence_type in SKIP_TYPES or _title_like(node, text):
        return False

    # The provisional Evidence builder already records incompleteness/continuation cues.
    # For magazine parsing these are stronger signals than punctuation alone.
    if node.get("possible_continuation") or not node.get("is_complete", True):
        return True
    if text[0].islower() or text[0] in ",.;:)]}–—-":
        return True
    if text.endswith((",", ";", ":", "-", "–", "—")):
        return True
    if len(text) <= 40 and len(text.split()) <= 8 and not re.search(r"[.!?]$", text):
        return True
    return False


def _target_eligible(node: dict[str, Any], min_target_chars: int) -> bool:
    text = _text(node)
    evidence_type = str(node.get("evidence_type") or "").lower()
    if len(text) < min_target_chars or evidence_type in SKIP_TYPES:
        return False
    return not _title_like(node, text)


def _overlap(a1: float, a2: float, b1: float, b2: float) -> float:
    return max(0.0, min(a2, b2) - max(a1, b1))


def _geometry_score(fragment: dict[str, Any], target: dict[str, Any], min_axis_overlap: float,
                    max_vertical_gap_px: float, max_horizontal_gap_px: float) -> float | None:
    a = _bbox(fragment)
    b = _bbox(target)
    if a is None or b is None or _page(fragment) != _page(target):
        return None
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    aw, ah = max(ax2 - ax1, 1e-6), max(ay2 - ay1, 1e-6)
    bw, bh = max(bx2 - bx1, 1e-6), max(by2 - by1, 1e-6)

    x_overlap = _overlap(ax1, ax2, bx1, bx2) / max(min(aw, bw), 1e-6)
    y_overlap = _overlap(ay1, ay2, by1, by2) / max(min(ah, bh), 1e-6)

    vertical_gap = max(0.0, max(ay1, by1) - min(ay2, by2))
    horizontal_gap = max(0.0, max(ax1, bx1) - min(ax2, bx2))

    scores = []
    if x_overlap >= min_axis_overlap and vertical_gap <= max_vertical_gap_px:
        scores.append(vertical_gap / max_vertical_gap_px + (1.0 - x_overlap))
    if y_overlap >= min_axis_overlap and horizontal_gap <= max_horizontal_gap_px:
        scores.append(horizontal_gap / max_horizontal_gap_px + (1.0 - y_overlap))
    return min(scores) if scores else None


def detect_micro_fragment_attachments(
    evidence: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return conservative fragment -> host attachments without mutating Evidence nodes.

    This pass is aimed at layout/parsing shards in multi-item magazine pages. It considers a short
    fragment and a small local reading-order window on the same page, requires compatible geometry,
    and records an auditable attachment hypothesis only. Standalone headings, captions, formulas,
    references, tables and figures are never attached here.
    """
    cfg = config or {}
    max_chars = int(cfg.get("max_chars", 120))
    min_target_chars = int(cfg.get("min_target_chars", 40))
    neighbour_window = int(cfg.get("neighbour_window", 2))
    min_axis_overlap = float(cfg.get("min_axis_overlap", 0.30))
    max_vertical_gap_px = float(cfg.get("max_vertical_gap_px", 120.0))
    max_horizontal_gap_px = float(cfg.get("max_horizontal_gap_px", 100.0))

    ordered = sorted(evidence, key=lambda n: n.get("document_order", 0))
    attachments = []
    for index, fragment in enumerate(ordered):
        if not _fragmentary(fragment, max_chars):
            continue
        candidates = []
        for offset in range(1, neighbour_window + 1):
            for neighbour_index in (index - offset, index + offset):
                if neighbour_index < 0 or neighbour_index >= len(ordered):
                    continue
                target = ordered[neighbour_index]
                if not _target_eligible(target, min_target_chars):
                    continue
                score = _geometry_score(
                    fragment,
                    target,
                    min_axis_overlap,
                    max_vertical_gap_px,
                    max_horizontal_gap_px,
                )
                if score is not None:
                    candidates.append((score, offset, neighbour_index, target))
        if not candidates:
            continue
        score, distance, _, target = min(candidates, key=lambda row: (row[0], row[1], row[2]))
        attachments.append({
            "fragment_id": fragment["node_id"],
            "target_id": target["node_id"],
            "fragment_text": _text(fragment),
            "target_text_preview": _text(target)[:180],
            "fragment_is_complete": fragment.get("is_complete"),
            "fragment_possible_continuation": fragment.get("possible_continuation"),
            "reading_order_distance": distance,
            "geometry_score": round(float(score), 6),
            "reason": "short_or_incomplete_fragment_same_page_local_geometry",
        })
    return attachments
