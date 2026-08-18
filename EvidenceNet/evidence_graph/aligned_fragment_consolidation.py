from __future__ import annotations

import copy
import re
from typing import Any

from .block_classifier import block_text
from .continuation_detector import completeness


EXCLUDED_TYPES = {"caption", "formula", "reference", "table", "figure", "heading", "title"}
EXCLUDED_LABELS = {
    "header", "header_text", "footer", "footnote", "doc_title", "document_title",
    "paragraph_title", "section_heading", "title",
}


def _bbox(block: dict[str, Any]) -> list[float] | None:
    bbox = block.get("bbox") or block.get("deepseek_bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        return [float(v) for v in bbox[:4]]
    except (TypeError, ValueError):
        return None


def _clean_text(block: dict[str, Any]) -> str:
    return block_text(block).strip()


def _excluded(block: dict[str, Any]) -> bool:
    block_type = str(block.get("block_type") or "").lower()
    label = str(block.get("matched_region_label") or "").lower()
    role = str(block.get("matched_region_role") or "").lower()
    return block_type in EXCLUDED_TYPES or label in EXCLUDED_LABELS or role in {"header", "footer", "footnote"}


def _title_like(text: str) -> bool:
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", text)
    if not words or len(words) > 10:
        return False
    alpha = [c for c in text if c.isalpha()]
    if alpha and sum(c.isupper() for c in alpha) / len(alpha) >= 0.8:
        return True
    return False


def _fragmentary(block: dict[str, Any], max_chars: int) -> tuple[bool, str | None]:
    text = _clean_text(block)
    if not text or len(text) > max_chars or _excluded(block) or _title_like(text):
        return False, None
    complete, possible, reason = completeness(text)
    if possible or not complete:
        return True, reason or "continuation_detector"
    if text[0].islower() or text[0] in ",.;:)]}–—-":
        return True, "lowercase_or_continuation_prefix"
    if text.endswith((",", ";", ":", "-", "–", "—")):
        return True, "open_punctuation_suffix"
    if len(text) <= 40 and len(text.split()) <= 8 and not re.search(r"[.!?]$", text):
        return True, "very_short_nonterminal_text"
    return False, None


def _target_eligible(block: dict[str, Any], min_target_chars: int) -> bool:
    text = _clean_text(block)
    return bool(text) and len(text) >= min_target_chars and not _excluded(block) and not _title_like(text)


def _overlap(a1: float, a2: float, b1: float, b2: float) -> float:
    return max(0.0, min(a2, b2) - max(a1, b1))


def _geometry_score(a: list[float], b: list[float], min_axis_overlap: float,
                    max_vertical_gap_px: float, max_horizontal_gap_px: float) -> tuple[float, str] | None:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    aw, ah = max(ax2 - ax1, 1e-6), max(ay2 - ay1, 1e-6)
    bw, bh = max(bx2 - bx1, 1e-6), max(by2 - by1, 1e-6)
    x_overlap = _overlap(ax1, ax2, bx1, bx2) / max(min(aw, bw), 1e-6)
    y_overlap = _overlap(ay1, ay2, by1, by2) / max(min(ah, bh), 1e-6)
    vertical_gap = max(0.0, max(ay1, by1) - min(ay2, by2))
    horizontal_gap = max(0.0, max(ax1, bx1) - min(ax2, bx2))
    candidates: list[tuple[float, str]] = []
    if x_overlap >= min_axis_overlap and vertical_gap <= max_vertical_gap_px:
        candidates.append((vertical_gap / max(max_vertical_gap_px, 1e-6) + (1.0 - x_overlap), "vertical_flow"))
    if y_overlap >= min_axis_overlap and horizontal_gap <= max_horizontal_gap_px:
        candidates.append((horizontal_gap / max(max_horizontal_gap_px, 1e-6) + (1.0 - y_overlap), "horizontal_flow"))
    return min(candidates, key=lambda item: item[0]) if candidates else None


def propose_aligned_fragment_attachments(
    blocks: list[dict[str, Any]], config: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    cfg = config or {}
    max_chars = int(cfg.get("max_chars", 120))
    min_target_chars = int(cfg.get("min_target_chars", 40))
    neighbour_window = int(cfg.get("neighbour_window", 2))
    min_axis_overlap = float(cfg.get("min_axis_overlap", 0.30))
    max_vertical_gap_px = float(cfg.get("max_vertical_gap_px", 120.0))
    max_horizontal_gap_px = float(cfg.get("max_horizontal_gap_px", 100.0))

    stats = {
        "ordered_blocks": len(blocks),
        "fragment_candidates": 0,
        "fragment_candidates_with_bbox": 0,
        "same_page_target_candidates": 0,
        "geometry_accepted": 0,
    }
    proposals: list[dict[str, Any]] = []
    for index, fragment in enumerate(blocks):
        is_fragment, fragment_reason = _fragmentary(fragment, max_chars)
        if not is_fragment:
            continue
        stats["fragment_candidates"] += 1
        fragment_bbox = _bbox(fragment)
        if fragment_bbox is None:
            continue
        stats["fragment_candidates_with_bbox"] += 1
        candidates = []
        for distance in range(1, neighbour_window + 1):
            for neighbour_index in (index - distance, index + distance):
                if not 0 <= neighbour_index < len(blocks):
                    continue
                target = blocks[neighbour_index]
                if fragment.get("_page") != target.get("_page") or not _target_eligible(target, min_target_chars):
                    continue
                target_bbox = _bbox(target)
                if target_bbox is None:
                    continue
                stats["same_page_target_candidates"] += 1
                geometry = _geometry_score(
                    fragment_bbox, target_bbox, min_axis_overlap, max_vertical_gap_px, max_horizontal_gap_px
                )
                if geometry is not None:
                    score, flow = geometry
                    candidates.append((score, distance, neighbour_index, target, flow))
        if not candidates:
            continue
        score, distance, neighbour_index, target, flow = min(candidates, key=lambda row: (row[0], row[1], row[2]))
        stats["geometry_accepted"] += 1
        proposals.append({
            "fragment_block_id": fragment.get("block_id"),
            "target_block_id": target.get("block_id"),
            "page": fragment.get("_page"),
            "fragment_text": _clean_text(fragment),
            "target_text_preview": _clean_text(target)[:180],
            "fragment_reason": fragment_reason,
            "reading_order_distance": distance,
            "relative_position": "before_target" if index < neighbour_index else "after_target",
            "flow": flow,
            "geometry_score": round(float(score), 6),
            "fragment_bbox": fragment_bbox,
            "target_bbox": _bbox(target),
        })
    return proposals, stats


def apply_aligned_fragment_attachments(
    blocks: list[dict[str, Any]], proposals: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Conservatively absorb proposed parsing shards while preserving source-block provenance."""
    by_id = {str(block.get("block_id")): block for block in blocks if block.get("block_id") is not None}
    attached_ids: set[str] = set()
    provenance: list[dict[str, Any]] = []

    # A target may absorb several local fragments; apply in original reading order.
    indexed = {id(block): i for i, block in enumerate(blocks)}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for proposal in proposals:
        fragment_id = str(proposal.get("fragment_block_id"))
        target_id = str(proposal.get("target_block_id"))
        if fragment_id == target_id or fragment_id not in by_id or target_id not in by_id:
            continue
        grouped.setdefault(target_id, []).append(proposal)

    output = [copy.deepcopy(block) for block in blocks]
    output_by_id = {str(block.get("block_id")): block for block in output if block.get("block_id") is not None}
    for target_id, rows in grouped.items():
        target = output_by_id[target_id]
        source_target = by_id[target_id]
        rows.sort(key=lambda row: indexed.get(id(by_id[str(row["fragment_block_id"])]), 10**9))
        before = [row for row in rows if row["relative_position"] == "before_target"]
        after = [row for row in rows if row["relative_position"] == "after_target"]
        parts = [_clean_text(by_id[str(row["fragment_block_id"])]) for row in before]
        parts.append(_clean_text(source_target))
        parts.extend(_clean_text(by_id[str(row["fragment_block_id"])]) for row in after)
        merged_text = " ".join(part for part in parts if part).strip()
        if not merged_text:
            continue
        if target.get("markdown") is not None:
            target["markdown"] = merged_text
        elif target.get("text") is not None:
            target["text"] = merged_text
        else:
            target["text"] = merged_text
        absorbed = [str(row["fragment_block_id"]) for row in rows]
        attached_ids.update(absorbed)
        target["_absorbed_source_blocks"] = [copy.deepcopy(by_id[source_id]) for source_id in absorbed]
        target["_fragment_consolidation"] = {"absorbed_block_ids": absorbed, "method": "aligned_block_local_geometry_v1"}
        provenance.extend({
            "source_block_id": source_id,
            "target_block_id": target_id,
            "reason": "aligned_micro_fragment_absorbed",
        } for source_id in absorbed)

    consolidated = [block for block in output if str(block.get("block_id")) not in attached_ids]
    return consolidated, provenance
