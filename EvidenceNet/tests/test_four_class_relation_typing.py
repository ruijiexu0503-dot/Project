from evidence_graph.evaluate_four_class_relation_typing import score_predictions
from evidence_graph.prepare_strict_relation_typing import build_tasks
from evidence_graph.run_four_class_relation_typing import parse


def node(node_id, order):
    return {"node_id": node_id, "document_order": order, "section_path": ["Methods"],
            "evidence_type": "text", "discourse_role": "method", "original_markdown": f"Text {node_id}"}


def truth(status="resolved", relation="REFERENCES"):
    return {"node_a": "D_EV_000001", "node_b": "D_EV_000002",
            "original_relation_label": "ELABORATES", "four_class_status": status,
            "four_class_relation": relation if status == "resolved" else None,
            "four_class_source": "D_EV_000002" if status == "resolved" else None,
            "four_class_target": "D_EV_000001" if status == "resolved" else None,
            "four_class_directed": True if status == "resolved" else None,
            "four_class_mapping_basis": "test", "four_class_reference_cue": "see Figure"}


def task_and_truth(row=None):
    row = row or truth()
    nodes = [node("D_EV_000001", 1), node("D_EV_000002", 2)]
    strict = [{"node_a": row["node_a"], "node_b": row["node_b"],
               "gold_source": "D_EV_000002", "gold_target": "D_EV_000001",
               "gold_relation": "ELABORATES", "directed": True}]
    return build_tasks(strict, nodes)[0], row


def test_parser_accepts_relation_and_abstention():
    task, _ = task_and_truth()
    parsed, valid = parse({"relation_type": "references", "source_node_id": "D_EV_000002",
                           "target_node_id": "D_EV_000001", "confidence": .8}, task)
    assert valid and parsed["relation_type"] == "REFERENCES"
    rejected, valid = parse({"relation_type": "REJECT_UNCERTAIN", "source_node_id": "D_EV_000002",
                             "target_node_id": "D_EV_000001", "confidence": .2}, task)
    assert valid and rejected["source_node_id"] is None and rejected["target_node_id"] is None


def test_oracle_scores_one_and_unresolved_is_excluded():
    task, row = task_and_truth()
    prediction = [{"task_id": task["task_id"], "valid": True, "relation_type": "REFERENCES",
                   "source_node_id": "D_EV_000002", "target_node_id": "D_EV_000001", "confidence": 1.0}]
    report, diagnostics = score_predictions([task], prediction, [row])
    assert report["relation_type_accuracy"] == 1.0
    assert report["direction_accuracy"] == 1.0
    assert report["exact_type_and_direction_accuracy"] == 1.0
    assert diagnostics[0]["exact_type_and_direction"] is True


def test_reject_is_counted_as_wrong_not_invalid():
    task, row = task_and_truth()
    prediction = [{"task_id": task["task_id"], "valid": True, "relation_type": "REJECT_UNCERTAIN",
                   "source_node_id": None, "target_node_id": None, "confidence": .1}]
    report, _ = score_predictions([task], prediction, [row])
    assert report["valid_predictions"] == 1
    assert report["reject_uncertain_count"] == 1
    assert report["relation_type_accuracy"] == 0.0
    assert report["exact_type_and_direction_accuracy"] == 0.0
