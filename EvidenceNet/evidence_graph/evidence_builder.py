from __future__ import annotations

import re
from typing import Any

from .block_classifier import block_text
from .continuation_detector import completeness
from .schemas import EvidenceNode, SourceMember


def plain_text(markdown: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", markdown, flags=re.M)
    text = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    # Underscores commonly belong to LaTeX subscripts; never strip them here.
    text = re.sub(r"(?<!\\)[*~`]", "", text)
    return text.strip()


def _float_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _list_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        return [float(v) for v in value[:4]]
    except (TypeError, ValueError):
        return None


def _raw_bbox(block: dict[str, Any]) -> tuple[list[float] | None, str | None]:
    raw = block.get("raw") or {}
    bbox = _list_bbox(raw.get("raw_bbox"))
    scale = raw.get("bbox_scale")
    return bbox, str(scale) if scale is not None else None


def _region_candidates(block: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = block.get("matched_region_candidates") or []
    output: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        row = dict(candidate)
        if row.get("bbox") is not None:
            row["bbox"] = _list_bbox(row.get("bbox"))
        output.append(row)
    return output


def _source_member(block: dict[str, Any], original_len: int, role: str = "core") -> SourceMember:
    raw_bbox, raw_bbox_scale = _raw_bbox(block)
    return SourceMember(
        page=str(block.get("_page") or block.get("page") or ""),
        block_id=str(block.get("block_id") or ""),
        start_char=0,
        end_char=original_len,
        bbox=_list_bbox(block.get("bbox")),
        deepseek_bbox=_list_bbox(block.get("deepseek_bbox")),
        matched_region_id=block.get("matched_region_id"),
        matched_region_label=block.get("matched_region_label"),
        match_score=_float_or_none(block.get("match_score")),
        role=role,
        raw_bbox=raw_bbox,
        raw_bbox_scale=raw_bbox_scale,
        page_width=_float_or_none(block.get("_page_width")),
        page_height=_float_or_none(block.get("_page_height")),
        bbox_source=block.get("bbox_source"),
        bbox_granularity=block.get("bbox_granularity"),
        matched_region_candidates=_region_candidates(block),
    )


def build_provisional_evidence_nodes(doc_id: str, classified, assignments):
    nodes = []
    for block, role in classified:
        if role != "evidence_content":
            continue
        original = block_text(block)
        clean = plain_text(original)
        complete, possible, reason = completeness(clean)
        section_id, path = assignments[id(block)]
        members = [_source_member(block, len(original), "core")]
        for absorbed in block.get("_absorbed_source_blocks") or []:
            members.append(_source_member(absorbed, len(block_text(absorbed)), "absorbed_fragment"))
        metadata = {
            "block_type": block.get("block_type"),
            "order_source": block.get("order_source"),
            "bbox_source": block.get("bbox_source"),
            "bbox_granularity": block.get("bbox_granularity"),
            "source_flags": block.get("flags") or [],
        }
        if block.get("_fragment_consolidation"):
            metadata["fragment_consolidation"] = block["_fragment_consolidation"]
        node = EvidenceNode(
            node_id=f"{doc_id}_EV_{len(nodes)+1:06d}",
            doc_id=doc_id,
            section_id=section_id,
            section_path=path,
            source_members=members,
            original_markdown=original,
            plain_text=clean,
            evidence_type=str(block.get("block_type") or "text"),
            modalities=["text"],
            document_order=len(nodes)+1,
            page_ids=sorted({member.page for member in members if member.page}),
            is_complete=complete,
            possible_continuation=possible,
            continuation_reason=reason,
            metadata=metadata,
        )
        nodes.append(node.to_dict())
    return nodes
