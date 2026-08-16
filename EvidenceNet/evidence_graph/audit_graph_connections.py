from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .io_utils import read_json, read_jsonl, write_json, write_jsonl
from .non_llm_magazine_experiment import DOCS, _labels, _reference
from .relation_ontology import RELATIONS


# Strict, text-grounded review of every accepted semantic edge in the three
# current pilots. "Relabel" means the endpoints are related, but the stored
# ontology label and/or direction is not supported by its definition.
MANUAL_REVIEW = {
    # 2022
    (DOCS[0], 1, 6): ("reject", "Issue welcome text is not background evidence for a publication strapline."),
    (DOCS[0], 2, 18): ("supported", "The introductory paragraph supplies the HL-LHC context summarized by the teaser."),
    (DOCS[0], 2, 21): ("supported", "The detailed HL-LHC/FCC discussion expands the short topic label."),
    (DOCS[0], 3, 6): ("reject", "Article previews do not provide background for the generic publication strapline."),
    (DOCS[0], 3, 20): ("supported", "The introduction contextualizes the laser-plasma commercialisation teaser."),
    (DOCS[0], 6, 23): ("reject", "A publication strapline does not provide substantive background for 'Physics impact'."),
    (DOCS[0], 8, 18): ("reject", "These are duplicate headline/teaser statements, not an elaboration relation."),
    (DOCS[0], 11, 12): ("reject", "Ad heading-to-copy membership is structural, not ontology-level background."),
    (DOCS[0], 11, 13): ("reject", "Ad heading-to-copy membership is structural, not ontology-level background."),
    (DOCS[0], 11, 15): ("reject", "A product-family heading is not background evidence for a product label."),
    (DOCS[0], 11, 16): ("reject", "A product-family heading is not background evidence for a product label."),
    (DOCS[0], 14, 15): ("supported", "The firmware description expands the Open-FPGA product label."),
    # 2025
    (DOCS[1], 377, 381): ("relabel", "The flight-qualification statement is context for later adoption, not a detail expanding it."),
    (DOCS[1], 382, 384): ("supported", "The space-economy statement provides context for the spin-off example."),
    (DOCS[1], 382, 385): ("supported", "The space-economy statement provides context for the Advacam example."),
    (DOCS[1], 382, 386): ("supported", "The space-economy statement provides context for the SigmaLabs example."),
    (DOCS[1], 382, 387): ("supported", "The space-economy statement provides context for the CHIMERA example."),
    (DOCS[1], 383, 386): ("relabel", "SigmaLabs is an example elaborating the broader support claim; the stored direction is reversed."),
    (DOCS[1], 389, 392): ("reject", "Two independent advertising bullets do not support one another."),
    (DOCS[1], 389, 393): ("reject", "Two independent advertising bullets do not support one another."),
    (DOCS[1], 390, 391): ("reject", "Two product features do not constitute evidence and claim."),
    (DOCS[1], 390, 392): ("reject", "Two product features do not constitute evidence and claim."),
    (DOCS[1], 390, 393): ("reject", "Two product features do not constitute evidence and claim."),
    (DOCS[1], 390, 398): ("reject", "A power specification does not support a contact email address."),
    (DOCS[1], 394, 398): ("reject", "Company-to-contact membership is an attribute link outside this ontology."),
    (DOCS[1], 394, 399): ("reject", "Company-to-website membership is an attribute link outside this ontology."),
    (DOCS[1], 397, 398): ("reject", "A call to contact and an email address are structural ad fields, not SUPPORTS."),
    (DOCS[1], 398, 399): ("reject", "An email address does not support a website address."),
    (DOCS[1], 400, 401): ("supported", "The technical statement expands the article's broader gluon-saturation introduction."),
    # 2026
    (DOCS[2], 2, 5): ("reject", "A generic welcome does not elaborate the detailed neutrino-tagging preview."),
    (DOCS[2], 9, 23): ("reject", "The generic publication strapline is not substantive background for the pulsar teaser."),
    (DOCS[2], 9, 25): ("reject", "The generic publication strapline is not substantive background for the interview teaser."),
    (DOCS[2], 12, 13): ("supported", "The conference title supplies the event context needed to interpret its dates."),
    (DOCS[2], 12, 17): ("supported", "The conference title supplies the event context for the registration notice."),
}


def _span_grounded(span: str, text: str) -> bool:
    if span == "__FULL_FORMULA__":
        return True
    return bool(span) and span.casefold() in text.casefold()


def _audit_document(output_root: Path, separation_root: Path, doc: str) -> tuple[dict, list[dict]]:
    root = output_root / "evidence_graph" / doc
    document_nodes = read_jsonl(root / "document_nodes.jsonl")
    sections = read_jsonl(root / "section_nodes.jsonl")
    evidence = sorted(read_jsonl(root / "evidence_nodes.jsonl"), key=lambda row: row["document_order"])
    visuals = read_jsonl(root / "visual_nodes.jsonl")
    structural = read_jsonl(root / "structural_edges.jsonl")
    semantic = read_jsonl(root / "semantic_edges.jsonl")
    exported = read_json(root / "graph.json")
    assignments = read_jsonl(separation_root / doc / "assignments.jsonl")

    evidence_by_id = {row["node_id"]: row for row in evidence}
    order_by_id = {node_id: row["document_order"] for node_id, row in evidence_by_id.items()}
    segment_by_id = {row["node_id"]: row["content_item_id"] for row in assignments}
    _, reference_tuples = _reference(doc, evidence)
    commercial_labels = _labels(reference_tuples, len(evidence))
    commercial_by_id = {
        row["node_id"]: bool(commercial_labels[row["document_order"] - 1]) for row in evidence
    }

    canonical_nodes = document_nodes + sections + evidence + visuals
    canonical_counts = Counter(row["node_id"] for row in canonical_nodes)
    canonical_ids = set(canonical_counts)
    exported_ids = {row["node_id"] for row in exported["nodes"]}
    structural_keys = Counter(
        (row["source"], row["target"], row["edge_type"]) for row in structural)
    structural_key_set = set(structural_keys)
    semantic_keys = Counter((row["source"], row["target"], row["edge_type"]) for row in semantic)

    missing_inverse = []
    nonconsecutive_next = []
    for row in structural:
        if row["edge_type"] == "NEXT":
            if (row["target"], row["source"], "PREVIOUS") not in structural_key_set:
                missing_inverse.append(row)
            if row["source"] in order_by_id and row["target"] in order_by_id:
                if order_by_id[row["target"]] != order_by_id[row["source"]] + 1:
                    nonconsecutive_next.append(row)

    reviews = []
    for row in semantic:
        source_order = order_by_id.get(row["source"])
        target_order = order_by_id.get(row["target"])
        status, reason = MANUAL_REVIEW.get(
            (doc, source_order, target_order),
            ("unreviewed", "No manual decision was registered for this edge."),
        )
        source = evidence_by_id.get(row["source"], {})
        target = evidence_by_id.get(row["target"], {})
        reviews.append({
            "doc_id": doc,
            "source": row["source"],
            "target": row["target"],
            "source_document_order": source_order,
            "target_document_order": target_order,
            "edge_type": row["edge_type"],
            "confidence": row.get("confidence"),
            "status": status,
            "reason": reason,
            "source_text": (source.get("plain_text") or "")[:300],
            "target_text": (target.get("plain_text") or "")[:300],
            "source_span_grounded": _span_grounded(
                row.get("source_supporting_span", ""), source.get("original_markdown", "")),
            "target_span_grounded": _span_grounded(
                row.get("target_supporting_span", ""), target.get("original_markdown", "")),
            "crosses_current_content_item": segment_by_id.get(row["source"]) != segment_by_id.get(row["target"]),
            "touches_commercial_content": commercial_by_id.get(row["source"], False)
                or commercial_by_id.get(row["target"], False),
            "crosses_commercial_noncommercial_boundary": commercial_by_id.get(row["source"], False)
                != commercial_by_id.get(row["target"], False),
        })

    visual_counts = Counter(row["node_id"] for row in visuals)
    duplicate_visual_ids = {
        node_id: count for node_id, count in visual_counts.items() if count > 1
    }
    status_counts = Counter(row["status"] for row in reviews)
    report = {
        "doc_id": doc,
        "ready_for_unqualified_publication": False,
        "counts": {
            "document_nodes": len(document_nodes),
            "section_nodes": len(sections),
            "evidence_nodes": len(evidence),
            "visual_node_rows": len(visuals),
            "unique_visual_node_ids": len(visual_counts),
            "structural_edges": len(structural),
            "semantic_edges": len(semantic),
        },
        "structural_integrity": {
            "dangling_edges_against_canonical_files": sum(
                row["source"] not in canonical_ids or row["target"] not in canonical_ids
                for row in structural + semantic),
            "duplicate_structural_edges": sum(count - 1 for count in structural_keys.values()),
            "self_loop_structural_edges": sum(row["source"] == row["target"] for row in structural),
            "next_edges_without_previous_inverse": len(missing_inverse),
            "nonconsecutive_evidence_next_edges": len(nonconsecutive_next),
        },
        "visual_integrity": {
            "duplicate_visual_ids": duplicate_visual_ids,
            "duplicate_visual_rows": sum(count - 1 for count in visual_counts.values()),
            "visual_nodes_without_caption": sum(not row.get("caption_evidence_id") for row in visuals),
            "graph_json_missing_visual_node_ids": len(set(visual_counts) - exported_ids),
            "graph_json_dangling_edges": sum(
                row["source"] not in exported_ids or row["target"] not in exported_ids
                for row in exported["edges"]),
        },
        "semantic_integrity": {
            "unknown_relation_types": sum(row["edge_type"] not in RELATIONS for row in semantic),
            "duplicate_semantic_edges": sum(count - 1 for count in semantic_keys.values()),
            "self_loop_semantic_edges": sum(row["source"] == row["target"] for row in semantic),
            "ungrounded_support_spans": sum(
                not row["source_span_grounded"] or not row["target_span_grounded"] for row in reviews),
            "cross_current_content_item_edges": sum(row["crosses_current_content_item"] for row in reviews),
            "commercial_semantic_edges": sum(row["touches_commercial_content"] for row in reviews),
            "commercial_to_noncommercial_edges": sum(
                row["crosses_commercial_noncommercial_boundary"] for row in reviews),
            "manual_review": dict(sorted(status_counts.items())),
        },
    }
    return report, reviews


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit all current EvidenceNet graph connections")
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--separation-root", default="output/non_llm_commercial_experiment")
    parser.add_argument("--audit-dir", default="output/publication_graph_audit")
    args = parser.parse_args()
    output_root = Path(args.output_root)
    audit_dir = Path(args.audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)

    documents = []
    all_reviews = []
    for doc in DOCS:
        report, reviews = _audit_document(
            output_root, Path(args.separation_root), doc)
        documents.append(report)
        all_reviews.extend(reviews)

    totals = {
        "documents": len(documents),
        "evidence_nodes": sum(row["counts"]["evidence_nodes"] for row in documents),
        "visual_node_rows": sum(row["counts"]["visual_node_rows"] for row in documents),
        "structural_edges": sum(row["counts"]["structural_edges"] for row in documents),
        "semantic_edges": sum(row["counts"]["semantic_edges"] for row in documents),
        "graph_json_dangling_edges": sum(
            row["visual_integrity"]["graph_json_dangling_edges"] for row in documents),
        "duplicate_visual_rows": sum(
            row["visual_integrity"]["duplicate_visual_rows"] for row in documents),
        "visual_nodes_without_caption": sum(
            row["visual_integrity"]["visual_nodes_without_caption"] for row in documents),
        "semantic_supported": sum(row["status"] == "supported" for row in all_reviews),
        "semantic_relabel": sum(row["status"] == "relabel" for row in all_reviews),
        "semantic_rejected": sum(row["status"] == "reject" for row in all_reviews),
        "commercial_semantic_edges": sum(row["touches_commercial_content"] for row in all_reviews),
    }
    result = {
        "method": "deterministic_integrity_checks_plus_strict_manual_semantic_review",
        "ready_for_unqualified_publication": False,
        "documents": documents,
        "totals": totals,
        "conclusion": (
            "The canonical structural reading-order graph is internally consistent, but the combined "
            "graph export and visual layer are not. Semantic edges require filtering/revision before publication."
        ),
    }
    write_json(audit_dir / "connection_audit.json", result)
    write_jsonl(audit_dir / "semantic_edge_review.jsonl", all_reviews)
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
