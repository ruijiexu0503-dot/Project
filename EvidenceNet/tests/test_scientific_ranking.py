from evidence_graph.evaluate_scientific_ranking import is_mandatory
from evidence_graph.rank_scientific_relations import build_ranking_tasks, parse_ranking, ranking_prompt


def node(node_id, order, role="method"):
    return {
        "node_id": node_id,
        "document_order": order,
        "section_path": ["Results"],
        "evidence_type": "text",
        "discourse_role": role,
        "base_summary": f"Summary {node_id}",
        "original_markdown": f"Text {node_id}",
    }


def decision(a, b, classification="RELATED", reasons=None, distance=1):
    return {
        "classification": classification,
        "confidence_any_relation": .9,
        "candidate": {
            "node_a": a,
            "node_b": b,
            "candidate_reasons": reasons or ["structural_neighbor"],
            "reading_order_distance": distance,
            "embedding_similarity": None,
        },
    }


def test_ranking_tasks_use_related_pairs_from_both_endpoints():
    nodes = [node("E1", 1), node("E2", 2), node("E3", 3)]
    tasks = build_ranking_tasks(nodes, [
        decision("E1", "E2"),
        decision("E1", "E3", classification="POSSIBLE"),
    ])
    assert [task["source"] for task in tasks] == ["E1", "E2"]
    assert [row["target"] for row in tasks[0]["candidates"]] == ["E2"]
    assert [row["target"] for row in tasks[1]["candidates"]] == ["E1"]
    assert "is_gold" not in ranking_prompt(tasks[0])


def test_incomplete_model_ranking_is_completed_deterministically():
    nodes = [node("E1", 1), node("E2", 2), node("E3", 3)]
    task = build_ranking_tasks(nodes, [decision("E1", "E2"), decision("E1", "E3")])[0]
    ranked, complete = parse_ranking({"source": "E1", "ranked_target_ids": ["E3", "E3"]}, task)
    assert ranked == ["E3", "E2"]
    assert complete is False


def test_explicit_language_marker_requires_local_grounding_to_be_mandatory():
    nodes = [node("E1", 1), node("E2", 2)]
    by_id = {row["node_id"]: row for row in nodes}
    nearby = decision("E1", "E2", reasons=["qualifies_language_signal"], distance=1)["candidate"]
    distant = decision("E1", "E2", reasons=["qualifies_language_signal"], distance=8)["candidate"]
    assert is_mandatory(nearby, by_id) == (True, ["grounded_explicit_qualification"])
    assert is_mandatory(distant, by_id) == (False, [])


def test_strong_anchored_evidence_claim_is_mandatory():
    nodes = [node("E1", 1, role="evidence"), node("E2", 2, role="conclusion")]
    by_id = {row["node_id"]: row for row in nodes}
    candidate = decision(
        "E1", "E2", reasons=["evidence_claim_signal", "shared_entities"]
    )["candidate"]
    assert is_mandatory(candidate, by_id) == (True, ["high_confidence_evidence_claim"])
