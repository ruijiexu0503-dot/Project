from evidence_graph.evaluate_strict_relation_typing import score_predictions
from evidence_graph.prepare_strict_relation_typing import build_tasks
from evidence_graph.run_strict_relation_typing import parse


def node(node_id, order):
    return {"node_id": node_id, "document_order": order, "section_path": ["Methods"],
            "evidence_type": "text", "discourse_role": "method", "original_markdown": f"Text {node_id}"}


def gold(a="D_EV_000001", b="D_EV_000002", source="D_EV_000002", target="D_EV_000001",
         relation="ELABORATES", directed=True):
    return {"node_a": a, "node_b": b, "gold_source": source, "gold_target": target,
            "gold_relation": relation, "directed": directed}


def test_blind_task_excludes_gold_fields_and_is_deterministic():
    nodes = [node("D_EV_000001", 1), node("D_EV_000002", 2)]
    first = build_tasks([gold()], nodes)
    second = build_tasks([gold()], nodes)
    assert first == second
    assert set(first[0]) == {"task_id", "pair_id", "evidence_a", "evidence_b"}
    assert "gold_relation" not in str(first)


def test_strict_prediction_parser_requires_relation_and_both_endpoints():
    task = build_tasks([gold()], [node("D_EV_000001", 1), node("D_EV_000002", 2)])[0]
    parsed, valid = parse({"relation_type": "elaborates", "source_node_id": "D_EV_000002",
                           "target_node_id": "D_EV_000001", "confidence": .8}, task)
    assert valid is True
    assert parsed["relation_type"] == "ELABORATES"
    _, invalid = parse({"relation_type": "NONE", "source_node_id": "D_EV_000002",
                        "target_node_id": "D_EV_000001", "confidence": .8}, task)
    assert invalid is False


def test_oracle_prediction_scores_one_for_directed_and_symmetric_rows():
    nodes = [node(f"D_EV_{index:06d}", index) for index in range(1, 5)]
    truth = [gold(), gold("D_EV_000003", "D_EV_000004", "D_EV_000003", "D_EV_000004",
                          "CONTRASTS_WITH", False)]
    tasks = build_tasks(truth, nodes)
    predictions = [{"task_id": task["task_id"], "valid": True,
                    "relation_type": row["gold_relation"], "source_node_id": row["gold_source"],
                    "target_node_id": row["gold_target"], "confidence": 1.0}
                   for task, row in zip(tasks, truth)]
    report, diagnostics = score_predictions(tasks, predictions, truth)
    assert report["type_accuracy"] == 1.0
    assert report["direction_accuracy_directed_pairs"] == 1.0
    assert report["exact_type_and_direction_accuracy"] == 1.0
    assert all(row["exact_type_and_direction"] for row in diagnostics)
