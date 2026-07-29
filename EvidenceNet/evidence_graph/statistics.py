from collections import Counter


def calculate_statistics(pages, classified, evidence, edges):
    roles = Counter(role for _, role in classified)
    edge_types = Counter(e["edge_type"] for e in edges)
    return {"aligned_source_blocks": sum(len(p.get("aligned_blocks", [])) for p in pages),
            "blocks_by_role": dict(sorted(roles.items())),
            "metadata_blocks": sum(roles[r] for r in ("document_title", "author_metadata", "publication_metadata", "identifier_metadata")),
            "section_headings": roles["section_heading"], "evidence_nodes": len(evidence),
            "incomplete_provisional_evidence_nodes": sum(not n["is_complete"] for n in evidence),
            "structural_edges_by_type": dict(sorted(edge_types.items())), "semantic_candidates": 0,
            "accepted_semantic_edges": 0, "rejected_candidates": 0, "unsupported_relation_suggestions": 0}

