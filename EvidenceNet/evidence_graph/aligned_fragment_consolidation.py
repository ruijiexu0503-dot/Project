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
TEXT_LIKE_LABELS = {"text", "list", "paragraph", "body", "body_text"}


def _bbox(block: dict[str, Any]) -> list[float] | None:
    bbox = block.get("bbox") or block.get("deepseek_bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        return [float(v) for v in bbox[:4]]
    except (TypeError, ValueError):
        return None


def _clean_text(block: dict[str, Any] | None) -> str:
    if block is None:
        return ""
    return block_text(block).strip()


def _flags(block: dict[str, Any] | None) -> set[str]:
    if block is None:
        return set()
    return {str(value).lower() for value in (block.get("flags") or [])}


def _excluded(block: dict[str, Any] | None) -> bool:
    if block is None:
        return True
    block_type = str(block.get("block_type") or "").lower()
    label = str(block.get("matched_region_label") or "").lower()
    role = str(block.get("matched_region_role") or "").lower()
    return block_type in EXCLUDED_TYPES or label in EXCLUDED_LABELS or role in {"header", "footer", "footnote"}


def _text_like(block: dict[str, Any] | None) -> bool:
    if block is None or _excluded(block):
        return False
    block_type = str(block.get("block_type") or "").lower()
    label = str(block.get("matched_region_label") or "").lower()
    role = str(block.get("matched_region_role") or "").lower()
    return block_type in {"text", "paragraph", "list"} or label in TEXT_LIKE_LABELS or role == "text"


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


def _target_eligible(block: dict[str, Any] | None, min_target_chars: int) -> bool:
    if block is None:
        return False
    text = _clean_text(block)
    return bool(text) and len(text) >= min_target_chars and not _excluded(block) and not _title_like(text)


def _is_unmatched_fragment(block: dict[str, Any]) -> bool:
    return (
        block.get("matched_region_id") is None
        and _bbox(block) is None
        and ("no_layout_match" in _flags(block) or str(block.get("bbox_source") or "").lower() in {"", "missing", "none"})
    )


def _same_grounded_region(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if left is None or right is None:
        return False
    left_id = left.get("matched_region_id")
    right_id = right.get("matched_region_id")
    return bool(left_id) and left_id == right_id and _text_like(left) and _text_like(right)


def _starts_like_continuation(text: str) -> bool:
    text = text.lstrip()
    return bool(text) and (text[0].islower() or text[0] in ",.;:)]}–—-")


def _unfinished(text: str) -> bool:
    complete, possible, _ = completeness(text)
    return bool(possible or not complete)


def _textual_bridge(previous: dict[str, Any] | None, fragment: dict[str, Any], following: dict[str, Any] | None) -> tuple[bool, list[str]]:
    evidence: list[str] = []
    fragment_text = _clean_text(fragment)
    previous_text = _clean_text(previous)
    next_text = _clean_text(following)

    if previous and _unfinished(previous_text) and _starts_like_continuation(fragment_text):
        evidence.append("previous_unfinished_fragment_continuation")
    if following and _unfinished(fragment_text) and _starts_like_continuation(next_text):
        evidence.append("fragment_unfinished_next_continuation")
    if previous and following and _unfinished(previous_text) and _unfinished(fragment_text):
        evidence.append("previous_and_fragment_both_incomplete")
    return bool(evidence), evidence


def _choose_target(
    previous: dict[str, Any] | None,
    fragment: dict[str, Any],
    following: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    fragment_text = _clean_text(fragment)
    previous_text = _clean_text(previous)
    next_text = _clean_text(following)

    if previous and _unfinished(previous_text) and _starts_like_continuation(fragment_text):
        return previous, "attach_after_previous"
    if following and _unfinished(fragment_text) and _starts_like_continuation(next_text):
        return following, "attach_before_next"
    if previous:
        return previous, "attach_after_previous_by_reading_order"
    if following:
        return following, "attach_before_next_by_reading_order"
    return None, "no_target"


def collect_fragment_review_rows(
    blocks: list[dict[str, Any]], config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Expose short/incomplete hybrid blocks with their alignment state and local context."""
    cfg = config or {}
    max_chars = int(cfg.get("max_chars", 120))
    rows: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        is_fragment, reason = _fragmentary(block, max_chars)
        if not is_fragment:
            continue
        previous = blocks[index - 1] if index > 0 and blocks[index - 1].get("_page") == block.get("_page") else None
        following = (
            blocks[index + 1]
            if index + 1 < len(blocks) and blocks[index + 1].get("_page") == block.get("_page")
            else None
        )
        bridge, bridge_evidence = _textual_bridge(previous, block, following)
        rows.append({
            "block_id": block.get("block_id"),
            "page": block.get("_page"),
            "text": _clean_text(block),
            "reason": reason,
            "block_type": block.get("block_type"),
            "flags": sorted(_flags(block)),
            "bbox": _bbox(block),
            "bbox_source": block.get("bbox_source"),
            "matched_region_id": block.get("matched_region_id"),
            "matched_region_label": block.get("matched_region_label"),
            "matched_region_role": block.get("matched_region_role"),
            "match_score": block.get("match_score"),
            "unmatched_fragment": _is_unmatched_fragment(block),
            "same_surrounding_layout_region": _same_grounded_region(previous, following),
            "textual_bridge": bridge,
            "textual_bridge_evidence": bridge_evidence,
            "previous": _context_row(previous, tail=True),
            "next": _context_row(following, tail=False),
        })
    return rows


def _context_row(block: dict[str, Any] | None, tail: bool) -> dict[str, Any] | None:
    if block is None:
        return None
    text = _clean_text(block)
    preview = text[-220:] if tail else text[:220]
    return {
        "block_id": block.get("block_id"),
        "text_preview": preview,
        "block_type": block.get("block_type"),
        "matched_region_id": block.get("matched_region_id"),
        "matched_region_label": block.get("matched_region_label"),
        "matched_region_role": block.get("matched_region_role"),
        "match_score": block.get("match_score"),
        "bbox": _bbox(block),
        "bbox_source": block.get("bbox_source"),
        "flags": sorted(_flags(block)),
    }


def propose_hybrid_fragment_attachments(
    blocks: list[dict[str, Any]], config: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Propose fragment absorption using hybrid-alignment state before optional geometry.

    HIGH confidence is intentionally narrow: an unmatched short fragment must be sandwiched between
    two text-like blocks grounded to the same layout region and must show textual continuation.
    MEDIUM candidates are recorded for review but are not safe for automatic application.
    """
    cfg = config or {}
    max_chars = int(cfg.get("max_chars", 120))
    stats = {
        "ordered_blocks": len(blocks),
        "fragment_candidates": 0,
        "unmatched_fragment_candidates": 0,
        "same_region_sandwiches": 0,
        "textual_bridges": 0,
        "high_confidence": 0,
        "medium_confidence": 0,
    }
    proposals: list[dict[str, Any]] = []

    for index, fragment in enumerate(blocks):
        is_fragment, fragment_reason = _fragmentary(fragment, max_chars)
        if not is_fragment:
            continue
        stats["fragment_candidates"] += 1
        previous = blocks[index - 1] if index > 0 and blocks[index - 1].get("_page") == fragment.get("_page") else None
        following = (
            blocks[index + 1]
            if index + 1 < len(blocks) and blocks[index + 1].get("_page") == fragment.get("_page")
            else None
        )
        unmatched = _is_unmatched_fragment(fragment)
        same_region = _same_grounded_region(previous, following)
        bridge, bridge_evidence = _textual_bridge(previous, fragment, following)
        if unmatched:
            stats["unmatched_fragment_candidates"] += 1
        if same_region:
            stats["same_region_sandwiches"] += 1
        if bridge:
            stats["textual_bridges"] += 1

        confidence = None
        reasons: list[str] = []
        if unmatched and same_region and bridge:
            confidence = "HIGH"
            reasons = ["unmatched_fragment", "same_surrounding_layout_region", *bridge_evidence]
            stats["high_confidence"] += 1
        elif unmatched and bridge and previous is not None and following is not None and _text_like(previous) and _text_like(following):
            confidence = "MEDIUM"
            reasons = ["unmatched_fragment", "text_like_surrounding_blocks", *bridge_evidence]
            stats["medium_confidence"] += 1
        else:
            continue

        target, merge_direction = _choose_target(previous, fragment, following)
        if target is None:
            continue
        proposals.append({
            "fragment_block_id": fragment.get("block_id"),
            "target_block_id": target.get("block_id"),
            "page": fragment.get("_page"),
            "confidence": confidence,
            "reasons": reasons,
            "fragment_reason": fragment_reason,
            "merge_direction": merge_direction,
            "fragment_text": _clean_text(fragment),
            "target_text_preview": _clean_text(target)[:220],
            "fragment_alignment": {
                "matched_region_id": fragment.get("matched_region_id"),
                "matched_region_label": fragment.get("matched_region_label"),
                "bbox_source": fragment.get("bbox_source"),
                "flags": sorted(_flags(fragment)),
            },
            "previous": _context_row(previous, tail=True),
            "next": _context_row(following, tail=False),
        })
    return proposals, stats


def apply_aligned_fragment_attachments(
    blocks: list[dict[str, Any]], proposals: list[dict[str, Any]], allowed_confidence: set[str] | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Absorb reviewed hybrid fragments while preserving source provenance."""
    allowed_confidence = allowed_confidence or {"HIGH"}
    by_id = {str(block.get("block_id")): block for block in blocks if block.get("block_id") is not None}
    attached_ids: set[str] = set()
    provenance: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for proposal in proposals:
        if str(proposal.get("confidence") or "").upper() not in allowed_confidence:
            continue
        fragment_id = str(proposal.get("fragment_block_id"))
        target_id = str(proposal.get("target_block_id"))
        if fragment_id == target_id or fragment_id not in by_id or target_id not in by_id:
            continue
        grouped.setdefault(target_id, []).append(proposal)

    output = [copy.deepcopy(block) for block in blocks]
    output_by_id = {str(block.get("block_id")): block for block in output if block.get("block_id") is not None}
    order_by_id = {str(block.get("block_id")): index for index, block in enumerate(blocks)}

    for target_id, rows in grouped.items():
        target = output_by_id[target_id]
        source_target = by_id[target_id]
        rows.sort(key=lambda row: order_by_id.get(str(row["fragment_block_id"]), 10**9))
        target_order = order_by_id[target_id]
        before = [row for row in rows if order_by_id.get(str(row["fragment_block_id"]), 10**9) < target_order]
        after = [row for row in rows if order_by_id.get(str(row["fragment_block_id"]), -1) > target_order]
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
        target["_fragment_consolidation"] = {
            "absorbed_block_ids": absorbed,
            "method": "hybrid_alignment_fragment_absorption_v2",
            "allowed_confidence": sorted(allowed_confidence),
        }
        provenance.extend({
            "source_block_id": source_id,
            "target_block_id": target_id,
            "reason": "hybrid_alignment_micro_fragment_absorbed",
            "confidence": next(
                (row["confidence"] for row in rows if str(row["fragment_block_id"]) == source_id),
                None,
            ),
        } for source_id in absorbed)

    consolidated = [block for block in output if str(block.get("block_id")) not in attached_ids]
    return consolidated, provenance


# Backward-compatible alias used by older imports/tests.
propose_aligned_fragment_attachments = propose_hybrid_fragment_attachments
