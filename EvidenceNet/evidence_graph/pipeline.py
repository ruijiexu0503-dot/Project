from __future__ import annotations

from .block_classifier import classify_block_role
from .evidence_builder import build_provisional_evidence_nodes
from .exporter import export_graph
from .loader import load_aligned_document
from .metadata_extractor import extract_document_metadata
from .reading_order import order_blocks
from .schemas import document_node
from .section_builder import build_sections
from .statistics import calculate_statistics
from .structural_graph import build_structural_edges
from .validator import validate_graph


def build_nodes(doc_id, config):
    pages = load_aligned_document(config["input"]["aligned_root"], doc_id)
    blocks, reading_issues = order_blocks(pages, config["validation"]["deepseek_order_conflict_threshold"])
    classified = [(b, classify_block_role(b)) for b in blocks]
    metadata = extract_document_metadata(doc_id, classified, [p["_source_file"] for p in pages])
    sections, assignments = build_sections(doc_id, classified)
    evidence = build_provisional_evidence_nodes(doc_id, classified, assignments)
    documents = [document_node(doc_id, metadata)]
    edges = build_structural_edges(doc_id, sections, evidence,
        config["structure"]["create_previous_edges"], config["structure"]["detect_continuations"])
    validation = validate_graph(doc_id, pages, classified, documents, sections, evidence, edges, reading_issues)
    stats = calculate_statistics(pages, classified, evidence, edges)
    output = export_graph(config["output"]["graph_root"], doc_id, metadata, documents, sections, evidence, edges, validation, stats)
    return {"output": str(output), "metadata": metadata, "sections": sections, "evidence": evidence,
            "structural_edges": edges, "validation": validation, "statistics": stats}

