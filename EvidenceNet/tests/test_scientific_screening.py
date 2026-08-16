from evidence_graph.screen_scientific_relations import build_payload, parse_decisions


def candidate(a="d_EV_000001", b="d_EV_000002"):
    return {"node_a": a, "node_b": b, "candidate_reasons": ["structural_neighbor"],
            "reading_order_distance": 1}


def node(node_id, order):
    return {"node_id": node_id, "document_order": order, "section_path": ["Methods"],
            "evidence_type": "text", "discourse_role": "method", "base_summary": "Summary",
            "original_markdown": "Scientific evidence text."}


def test_screen_payload_deduplicates_nodes():
    rows = [candidate(), candidate("d_EV_000001", "d_EV_000003")]
    by_id = {f"d_EV_{i:06d}": node(f"d_EV_{i:06d}", i) for i in range(1, 4)}
    payload = build_payload(rows, by_id)
    assert len(payload["nodes"]) == 3
    assert len(payload["pairs"]) == 2


def test_missing_screen_decision_falls_back_to_possible():
    rows = [candidate(), candidate("d_EV_000002", "d_EV_000003")]
    parsed = {"decisions": [{"pair_id": "d_EV_000001||d_EV_000002",
                              "classification": "RELATED", "confidence_any_relation": .9}]}
    output = parse_decisions(parsed, rows, "model", "timestamp")
    assert output[0]["classification"] == "RELATED"
    assert output[1]["classification"] == "POSSIBLE"
    assert output[1]["fallback_possible"] is True
