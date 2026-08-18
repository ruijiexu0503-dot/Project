from __future__ import annotations

import re

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


def _source_member(block, original_len: int, role: str = "core") -> SourceMember:
    return SourceMember(page=block.get("_page"), block_id=block.get("block_id"),
        start_char=0, end_char=original_len, bbox=block.get("bbox"), deepseek_bbox=block.get("deepseek_bbox"),
        matched_region_id=block.get("matched_region_id"), matched_region_label=block.get("matched_region_label"),
        match_score=block.get("match_score"), role=role)


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
        metadata = {"block_type": block.get("block_type"), "order_source": block.get("order_source"),
                    "bbox_source": block.get("bbox_source"), "bbox_granularity": block.get("bbox_granularity"),
                    "source_flags": block.get("flags") or []}
        if block.get("_fragment_consolidation"):
            metadata["fragment_consolidation"] = block["_fragment_consolidation"]
        node = EvidenceNode(node_id=f"{doc_id}_EV_{len(nodes)+1:06d}", doc_id=doc_id,
            section_id=section_id, section_path=path, source_members=members, original_markdown=original,
            plain_text=clean, evidence_type=str(block.get("block_type") or "text"), modalities=["text"],
            document_order=len(nodes)+1, page_ids=[block.get("_page")], is_complete=complete,
            possible_continuation=possible, continuation_reason=reason, metadata=metadata)
        nodes.append(node.to_dict())
    return nodes
