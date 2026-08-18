from __future__ import annotations

from .aligned_fragment_consolidation import (
    collect_fragment_review_rows,
    propose_aligned_fragment_attachments,
)
from .block_classifier import classify_block_role
from .evidence_builder import build_provisional_evidence_nodes
from .exporter import export_graph
from .io_utils import write_json, write_jsonl
from .loader import load_aligned_document
from .magazine_page_roles import classify_magazine_pages
from .magazine_role_router import route_magazine_roles
from .metadata_extractor import extract_document_metadata
from .reading_order import order_blocks
from .repeated_template_detector import detect_repeated_templates
from .schemas import document_node
from .section_builder import build_sections
from .statistics import calculate_statistics
from .structural_graph import build_structural_edges
from .validator import validate_graph


def _enabled_for_doc(doc_id, config, key):
    cfg = config.get(key, {})
    if not cfg.get("enabled", False):
        return False
    prefixes = cfg.get("document_prefixes", [])
    return not prefixes or any(doc_id.startswith(prefix) for prefix in prefixes)


def build_nodes(doc_id, config):
    pages = load_aligned_document(config["input"]["aligned_root"], doc_id)
    raw_blocks, reading_issues = order_blocks(
        pages, config["validation"]["deepseek_order_conflict_threshold"]
    )

    # Phase 0: coarse structural classification from fused DeepSeek+layout metadata.
    base_classified = [(block, classify_block_role(block)) for block in raw_blocks]

    # Magazine canonicalization is deliberately staged and audit-first:
    # repeated document chrome -> conservative page role -> block routing.
    role_routing_enabled = _enabled_for_doc(doc_id, config, "magazine_role_routing")
    template_enabled = _enabled_for_doc(doc_id, config, "repeated_template_detection")
    template_keys = set()
    template_review = []
    template_stats = {}
    page_role_report = {}
    page_role_counts = {}
    role_routing_review = []
    role_routing_counts = {}

    if role_routing_enabled:
        if template_enabled:
            template_keys, template_review, template_stats = detect_repeated_templates(
                raw_blocks, config.get("repeated_template_detection", {})
            )
        page_role_report, page_role_counts = classify_magazine_pages(raw_blocks, template_keys)
        classified, role_routing_review, role_routing_counts = route_magazine_roles(
            raw_blocks,
            base_classified,
            page_roles=page_role_report,
            template_keys=template_keys,
        )
    else:
        classified = base_classified

    # Fragment diagnostics only inspect content that survives document/page/block routing.
    # Automatic fragment absorption remains blocked until this routing layer is reviewed.
    fragment_enabled = _enabled_for_doc(doc_id, config, "micro_fragment_consolidation")
    fragment_cfg = config.get("micro_fragment_consolidation", {})
    fragment_review_rows = []
    fragment_proposals = []
    fragment_stats = {}
    if fragment_enabled:
        evidence_blocks = [block for block, role in classified if role == "evidence_content"]
        fragment_review_rows = collect_fragment_review_rows(evidence_blocks, fragment_cfg)
        fragment_proposals, fragment_stats = propose_aligned_fragment_attachments(
            evidence_blocks, fragment_cfg
        )
        fragment_stats["routed_evidence_input_blocks"] = len(evidence_blocks)
        fragment_stats["apply"] = False
        if fragment_cfg.get("apply", False):
            fragment_stats["apply_blocked_reason"] = (
                "document-aware routing must be validated before automatic fragment absorption"
            )

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

    if role_routing_enabled:
        stats["magazine_document_canonicalization"] = {
            "repeated_templates": template_stats,
            "page_roles": page_role_counts,
            "changed_blocks": len(role_routing_review),
            "roles_after_routing": role_routing_counts,
        }
    if fragment_enabled:
        stats["micro_fragment_consolidation"] = {
            **fragment_stats,
            "review_rows": len(fragment_review_rows),
            "proposal_rows": len(fragment_proposals),
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

    if role_routing_enabled:
        write_jsonl(output / "repeated_template_review.jsonl", template_review)
        write_json(output / "repeated_template_statistics.json", template_stats)
        write_json(output / "magazine_page_roles.json", {
            "role_counts": page_role_counts,
            "pages": page_role_report,
        })
        write_jsonl(output / "magazine_role_routing_review.jsonl", role_routing_review)
        write_json(output / "magazine_role_routing_statistics.json", {
            "changed_blocks": len(role_routing_review),
            "roles_after_routing": role_routing_counts,
            "page_roles": page_role_counts,
            "template_blocks": template_stats.get("template_blocks", 0),
        })
    if fragment_enabled:
        write_jsonl(output / "aligned_fragment_review.jsonl", fragment_review_rows)
        write_jsonl(output / "aligned_fragment_proposals.jsonl", fragment_proposals)
        write_json(output / "aligned_fragment_statistics.json", {
            **fragment_stats,
            "review_rows": len(fragment_review_rows),
            "proposal_rows": len(fragment_proposals),
        })

    return {
        "output": str(output),
        "metadata": metadata,
        "sections": sections,
        "evidence": evidence,
        "structural_edges": edges,
        "validation": validation,
        "statistics": stats,
        "repeated_template_review": template_review,
        "magazine_page_roles": page_role_report,
        "magazine_role_routing_review": role_routing_review,
        "aligned_fragment_review": fragment_review_rows,
        "aligned_fragment_proposals": fragment_proposals,
    }
