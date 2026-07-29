from __future__ import annotations

from .continuation_detector import continuation_confidence


def edge(source, target, edge_type, confidence=1.0, metadata=None):
    return {"source": source, "target": target, "edge_layer": "structural",
            "edge_type": edge_type, "confidence": confidence, "metadata": metadata or {}}


def build_structural_edges(doc_id, sections, evidence, create_previous=True, detect_continuations=True):
    edges = []
    for node in evidence:
        edges.append(edge(node["node_id"], doc_id, "IN_DOCUMENT"))
        if node.get("section_id"): edges.append(edge(node["node_id"], node["section_id"], "IN_SECTION"))
    for section in sections: edges.append(edge(section["node_id"], doc_id, "IN_DOCUMENT"))
    for left, right in zip(evidence, evidence[1:]):
        edges.append(edge(left["node_id"], right["node_id"], "NEXT"))
        if create_previous: edges.append(edge(right["node_id"], left["node_id"], "PREVIOUS"))
        if detect_continuations:
            detected = continuation_confidence(left, right)
            if detected:
                confidence, reason = detected
                edges.append(edge(left["node_id"], right["node_id"], "CONTINUES_TO", confidence, {"reason": reason}))
    return edges

