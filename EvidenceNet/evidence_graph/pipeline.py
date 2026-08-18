from __future__ import annotations

from .aligned_fragment_consolidation import (
    apply_aligned_fragment_attachments,
    collect_fragment_review_rows,
    propose_aligned_fragment_attachments,
)
from .block_classifier import classify_block_role
from .evidence_builder import build_provisional_evidence_nodes
from .exporter import export_graph
from .io_utils import write_json, write_jsonl
from .loader import load_aligned_document
from .metadata_extractor import extract_document_metadata
from .reading_order import order_blocks
from .schemas import document_node
from .section_builder import build_sections
from .statistics import calculate_statistics
from .structural_graph import build_structural_edges
from .validator import validate_graph


def _micro_fragment_enabled(doc_id, config):
    cfg = config.get("micro_fragment_consolidation", {})
    if not cfg.get("enabled", False):
        return False
    prefixes = cfg.get("document_prefixes", [])
    return not prefixes or any(doc_id.startswith(prefix) for prefix in prefixes)


def build_nodes(doc_id, config):
    pages = load_aligned_document(config["input"]["aligned_root"], doc_id)
    raw_blocks, reading_issues = order_blocks(
        pages, config["validation"]["deepseek_order_conflict_threshold"]
    )

    blocks = raw_blocks
    fragment_proposals = []
    fragment_review_rows = []
    fragment_provenance = []
    fragment_stats = {}
    fragment_cfg = config.get("micro_fragment_consolidation", {})
    fragment_enabled = _micro_fragment_enabled(doc_id, config)
    if fragment_enabled:
        fragment_review_rows = collect_fragment_review_rows(raw_blocks, fragment_cfg)
        fragment_proposals, fragment_stats = propose_aligned_fragment_attachments(raw_blocks, fragment_cfg)
        if fragment_cfg.get("apply", False):
            blocks, fragment_provenance = apply_aligned_fragment_attachments(raw_blocks, fragment_proposals)

    classified = [(b, classify_block_role(b)) for b in blocks]
    metadata = extract_document_metadata(doc_id, classified, [p["_source_file"] for p in pages])
    sections, assignments = build_sections(doc_id, classified)
    evidence = build_provisional_evidence_nodes(doc_id, classified, assignments)
    documents = [document_node(doc_id, metadata)]
    edges = build_structural_edges(
        doc_id,
        sections,
        evidence,
        config["structure"]["create_previous_edges"],
        config["structure"]["detect_continuations"],
    )
    validation = validate_graph(
        doc_id, pages, classified, documents, sections, evidence, edges, reading_issues
    )
    stats = calculate_statistics(pages, classified, evidence, edges)
    if fragment_enabled:
        stats["micro_fragment_consolidation"] = {
            **fragment_stats,
            "review_rows": len(fragment_review_rows),
            "apply": bool(fragment_cfg.get("apply", False)),
            "input_blocks": len(raw_blocks),
            "output_blocks": len(blocks),
            "absorbed_fragments": len(fragment_provenance),
        }
    output = export_graph(
        config["output"]["graph_root"],
        doc_id,
        metadata,
        documents,
        sections,
        evidence,
        edges,
        validation,
        stats,
    )

    if fragment_enabled:
        write_jsonl(output / "aligned_fragment_review.jsonl", fragment_review_rows)
        write_jsonl(output / "aligned_fragment_proposals.jsonl", fragment_proposals)
        write_jsonl(output / "aligned_fragment_provenance.jsonl", fragment_provenance)
        write_json(output / "aligned_fragment_statistics.json", {
            **fragment_stats,
            "review_rows": len(fragment_review_rows),
            "apply": bool(fragment_cfg.get("apply", False)),
            "input_blocks": len(raw_blocks),
            "output_blocks": len(blocks),
            "absorbed_fragments": len(fragment_provenance),
        })

    return {
        "output": str(output),
        "metadata": metadata,
        "sections": sections,
        "evidence": evidence,
        "structural_edges": edges,
        "validation": validation,
        "statistics": stats,
        "aligned_fragment_review": fragment_review_rows,
        "aligned_fragment_proposals": fragment_proposals,
        "aligned_fragment_provenance": fragment_provenance,
    }
