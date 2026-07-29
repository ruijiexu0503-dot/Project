from __future__ import annotations

import json
from pathlib import Path


def _json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _jsonl(path, values):
    path.write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in values), encoding="utf-8")


def export_graph(root, doc_id, metadata, document_nodes, sections, evidence, structural, validation, statistics):
    out = Path(root) / doc_id
    out.mkdir(parents=True, exist_ok=True)
    _json(out/"document_metadata.json", metadata)
    _jsonl(out/"document_nodes.jsonl", document_nodes); _jsonl(out/"section_nodes.jsonl", sections)
    _jsonl(out/"evidence_nodes.jsonl", evidence); _jsonl(out/"structural_edges.jsonl", structural)
    for name in ("semantic_candidates", "semantic_edges", "rejected_semantic_candidates", "unsupported_relations"):
        _jsonl(out/f"{name}.jsonl", [])
    _json(out/"validation_report.json", validation); _json(out/"statistics.json", statistics)
    _json(out/"graph.json", {"doc_id": doc_id, "nodes": document_nodes+sections+evidence, "edges": structural,
                            "phase": 1, "semantic_layer_status": "not_built_pending_review"})
    return out

