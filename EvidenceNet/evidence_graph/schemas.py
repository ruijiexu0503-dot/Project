from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SourceMember:
    page: str
    block_id: str
    start_char: int
    end_char: int
    bbox: list[float] | None
    deepseek_bbox: list[float] | None
    matched_region_id: str | None
    matched_region_label: str | None
    match_score: float | None
    role: str = "core"
    raw_bbox: list[float] | None = None
    raw_bbox_scale: str | None = None
    pixel_bbox: list[float] | None = None
    bbox_original: list[float] | None = None
    bbox_corrected: list[float] | None = None
    page_width: float | None = None
    page_height: float | None = None
    bbox_source: str | None = None
    bbox_granularity: str | None = None
    matched_region_candidates: list[dict[str, Any]] = field(default_factory=list)
    geometry_members: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvidenceNode:
    node_id: str
    doc_id: str
    section_id: str | None
    section_path: list[str]
    source_members: list[SourceMember]
    original_markdown: str
    plain_text: str
    evidence_type: str
    modalities: list[str]
    document_order: int
    page_ids: list[str]
    is_complete: bool
    possible_continuation: bool
    continuation_reason: str | None
    geometry_members: list[dict[str, Any]] = field(default_factory=list)
    provisional: bool = True
    node_type: str = "evidence"
    base_summary: str | None = None
    keywords: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    discourse_role: str | None = None
    embedding: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def document_node(doc_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {"node_id": doc_id, "node_type": "document", "doc_id": doc_id,
            "title": metadata.get("title")}
