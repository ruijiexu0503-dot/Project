from __future__ import annotations

from collections import Counter


def validate_graph(doc_id, pages, classified, document_nodes, sections, evidence, edges, reading_issues):
    errors, warnings = [], list(reading_issues)
    all_nodes = document_nodes + sections + evidence
    ids = [n["node_id"] for n in all_nodes]
    for node_id, count in Counter(ids).items():
        if count > 1: errors.append({"type": "duplicate_node_id", "node_id": node_id, "count": count})
    id_set = set(ids)
    unresolved = []
    for block, role in classified:
        if role == "unresolved": unresolved.append({"page": block.get("_page"), "block_id": block.get("block_id"), "text": block.get("text")})
    if unresolved: warnings.append({"type": "unclassified_aligned_blocks", "blocks": unresolved})
    for node in evidence:
        if not node.get("original_markdown"): errors.append({"type": "empty_evidence_text", "node_id": node["node_id"]})
        for member in node.get("source_members", []):
            if not member.get("block_id"): errors.append({"type": "missing_source_block_id", "node_id": node["node_id"]})
            if not member.get("page"): errors.append({"type": "missing_page_provenance", "node_id": node["node_id"]})
            if member.get("bbox") is None: warnings.append({"type": "missing_bbox_provenance", "node_id": node["node_id"], "block_id": member.get("block_id")})
            if member.get("start_char") != 0 or member.get("end_char") != len(node.get("original_markdown", "")):
                errors.append({"type": "invalid_source_character_range", "node_id": node["node_id"]})
        if not node.get("is_complete"): warnings.append({"type": "incomplete_evidence_node", "node_id": node["node_id"], "reason": node.get("continuation_reason")})
    for e in edges:
        if e.get("source") not in id_set or e.get("target") not in id_set: errors.append({"type": "edge_to_nonexistent_node", "edge": e})
        if e.get("edge_layer") != "structural": errors.append({"type": "mixed_edge_layer", "edge": e})
    for page in pages:
        matched = {b.get("matched_region_id") for b in page.get("aligned_blocks", []) if b.get("matched_region_id")}
        unmatched = [r.get("region_id") or r.get("id") for r in page.get("layout_regions", [])
                     if (r.get("label") in {"text", "paragraph_title", "title", "header", "footer", "footnote"}
                         and (r.get("region_id") or r.get("id")) not in matched)]
        if unmatched: warnings.append({"type": "unmatched_layout_text_regions", "page": page.get("page"), "region_ids": unmatched})
    connected = {e["source"] for e in edges if e["edge_type"] in {"NEXT", "PREVIOUS", "CONTINUES_TO"}} | {e["target"] for e in edges if e["edge_type"] in {"NEXT", "PREVIOUS", "CONTINUES_TO"}}
    isolated = [n["node_id"] for n in evidence if n["node_id"] not in connected]
    if isolated: warnings.append({"type": "isolated_evidence_nodes", "node_ids": isolated})
    return {"doc_id": doc_id, "valid": not errors, "errors": errors, "warnings": warnings,
            "summary": {"error_count": len(errors), "warning_count": len(warnings),
                        "unresolved_block_count": len(unresolved), "isolated_evidence_count": len(isolated)}}

