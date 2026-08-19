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


def _fragmentary(block: dict[str, Any]) -> tuple[bool, str | None]:
    """Return whether a body-text block looks like an interrupted continuation.

    Intentionally has no length cutoff: paragraph length is a layout/parsing property, not a
    semantic boundary. Long blocks can still end mid-sentence and short blocks can be valid
    standalone content.
    """
    text = _clean_text(block)
    if not text or _excluded(block) or _title_like(text):
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
    return None, "ambiguous_target"


def _block_key(block: dict[str, Any] | None) -> tuple[str, str] | None:
    if block is None or block.get("block_id") is None:
        return None
    page = str(block.get("_page") if block.get("_page") is not None else block.get("page") or "")
    return page, str(block.get("block_id"))


def _proposal_key(page: Any, block_id: Any) -> tuple[str, str]:
    return str(page if page is not None else ""), str(block_id)


def collect_fragment_review_rows(
    blocks: list[dict[str, Any]], config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Expose incomplete/continuation-like body blocks with alignment state and local context."""
    rows: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        is_fragment, reason = _fragmentary(block)
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
        "page": block.get("_page"),
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
    """Propose conservative fragment absorption candidates.

    HIGH confidence requires an unmatched fragment, a textual continuation signal, and two
    surrounding text-like blocks grounded to the same layout region. MEDIUM is audit-only.
    Targets are chosen only when textual directionality is explicit; reading-order fallback is
    intentionally removed to prevent arbitrary absorption. Candidate discovery is length-agnostic.
    """
    stats = {
        "ordered_blocks": len(blocks),
        "fragment_candidates": 0,
        "unmatched_fragment_candidates": 0,
        "same_region_sandwiches": 0,
        "textual_bridges": 0,
        "high_confidence": 0,
        "medium_confidence": 0,
        "ambiguous_target_rejected": 0,
    }
    proposals: list[dict[str, Any]] = []

    for index, fragment in enumerate(blocks):
        is_fragment, fragment_reason = _fragmentary(fragment)
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
            stats["ambiguous_target_rejected"] += 1
            continue
        target_key = _block_key(target)
        fragment_key = _block_key(fragment)
        if target_key is None or fragment_key is None or target_key == fragment_key:
            continue
        proposals.append({
            "fragment_block_id": fragment.get("block_id"),
            "target_block_id": target.get("block_id"),
            "page": fragment.get("_page"),
            "fragment_key": list(fragment_key),
            "target_key": list(target_key),
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
    """Absorb reviewed hybrid fragments while preserving source provenance.

    Safety rules:
    - blocks are keyed by (page, block_id), never block_id alone;
    - a block cannot be both an absorbed fragment and a merge target in the same pass;
    - duplicate fragment assignments are rejected;
    - only same-page attachments are accepted;
    - original target and absorbed source blocks are copied into provenance metadata.
    """
    allowed_confidence = allowed_confidence or {"HIGH"}
    source_by_key = {key: block for block in blocks if (key := _block_key(block)) is not None}
    order_by_key = {key: index for index, block in enumerate(blocks) if (key := _block_key(block)) is not None}

    eligible: list[dict[str, Any]] = []
    claimed_fragments: set[tuple[str, str]] = set()
    for proposal in proposals:
        if str(proposal.get("confidence") or "").upper() not in allowed_confidence:
            continue
        fragment_key = _proposal_key(proposal.get("page"), proposal.get("fragment_block_id"))
        target_key = _proposal_key(proposal.get("page"), proposal.get("target_block_id"))
        if fragment_key == target_key or fragment_key not in source_by_key or target_key not in source_by_key:
            continue
        if fragment_key[0] != target_key[0]:
            continue
        if fragment_key in claimed_fragments:
            continue
        claimed_fragments.add(fragment_key)
        eligible.append({**proposal, "_fragment_key": fragment_key, "_target_key": target_key})

    absorbed_keys = {row["_fragment_key"] for row in eligible}
    safe_rows = [row for row in eligible if row["_target_key"] not in absorbed_keys]

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in safe_rows:
        grouped.setdefault(row["_target_key"], []).append(row)

    output = [copy.deepcopy(block) for block in blocks]
    output_by_key = {key: block for block in output if (key := _block_key(block)) is not None}
    actually_absorbed: set[tuple[str, str]] = set()
    provenance: list[dict[str, Any]] = []

    for target_key, rows in grouped.items():
        target = output_by_key[target_key]
        source_target = source_by_key[target_key]
        target_order = order_by_key[target_key]
        rows.sort(key=lambda row: order_by_key.get(row["_fragment_key"], 10**9))
        before = [row for row in rows if order_by_key.get(row["_fragment_key"], 10**9) < target_order]
        after = [row for row in rows if order_by_key.get(row["_fragment_key"], -1) > target_order]
        if len(before) + len(after) != len(rows):
            continue

        parts = [_clean_text(source_by_key[row["_fragment_key"]]) for row in before]
        parts.append(_clean_text(source_target))
        parts.extend(_clean_text(source_by_key[row["_fragment_key"]]) for row in after)
        merged_text = " ".join(part for part in parts if part).strip()
        if not merged_text:
            continue

        if target.get("markdown") is not None:
            target["markdown"] = merged_text
        elif target.get("text") is not None:
            target["text"] = merged_text
        else:
            target["text"] = merged_text

        absorbed = [row["_fragment_key"] for row in rows]
        actually_absorbed.update(absorbed)
        target["_fragment_consolidation_original_target"] = copy.deepcopy(source_target)
        target["_absorbed_source_blocks"] = [copy.deepcopy(source_by_key[key]) for key in absorbed]
        target["_fragment_consolidation"] = {
            "absorbed_block_keys": [list(key) for key in absorbed],
            "method": "hybrid_alignment_fragment_absorption_v4_length_agnostic",
            "allowed_confidence": sorted(allowed_confidence),
        }

        for row in rows:
            source_key = row["_fragment_key"]
            provenance.append({
                "source_page": source_key[0],
                "source_block_id": source_key[1],
                "target_page": target_key[0],
                "target_block_id": target_key[1],
                "reason": "hybrid_alignment_micro_fragment_absorbed",
                "confidence": row.get("confidence"),
                "merge_direction": row.get("merge_direction"),
                "source_block": copy.deepcopy(source_by_key[source_key]),
                "target_block_before_merge": copy.deepcopy(source_target),
            })

    consolidated = [block for block in output if _block_key(block) not in actually_absorbed]
    return consolidated, provenance


# Backward-compatible alias used by older imports/tests.
propose_aligned_fragment_attachments = propose_hybrid_fragment_attachments
