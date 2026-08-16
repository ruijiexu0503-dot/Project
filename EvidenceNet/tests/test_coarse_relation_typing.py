from evidence_graph.coarse_relation_typing import FINE_TO_COARSE
from evidence_graph.evaluate_coarse_relation_typing import normalize_predictions, score_predictions
from evidence_graph.prepare_strict_relation_typing import build_tasks
from evidence_graph.run_coarse_relation_typing import parse


def node(node_id, order):
    return {"node_id": node_id, "document_order": order, "section_path": ["Methods"],
            "evidence_type": "text", "discourse_role": "method", "original_markdown": f"Text {node_id}"}


def gold(relation="EXPLAINS", directed=True):
    return {"node_a": "D_EV_000001", "node_b": "D_EV_000002",
            "gold_source": "D_EV_000002", "gold_target": "D_EV_000001",
            "gold_relation": relation, "directed": directed}


def test_mapping_covers_all_six_fine_relations():
    assert set(FINE_TO_COARSE) == {
        "ELABORATES", "SUPPORTS", "EXPLAINS", "QUALIFIES", "DEPENDS_ON", "CONTRASTS_WITH"
    }
    assert FINE_TO_COARSE["ELABORATES"] == FINE_TO_COARSE["EXPLAINS"] == "EXPANDS"
    assert FINE_TO_COARSE["QUALIFIES"] == FINE_TO_COARSE["DEPENDS_ON"] == "CONDITIONS"


def test_parser_accepts_coarse_and_rejects_old_fine_label():
    task = build_tasks([gold()], [node("D_EV_000001", 1), node("D_EV_000002", 2)])[0]
    result, valid = parse({"relation_type": "expands", "source_node_id": "D_EV_000002",
                           "target_node_id": "D_EV_000001", "confidence": .8}, task)
    assert valid and result["relation_type"] == "EXPANDS"
    _, valid = parse({"relation_type": "EXPLAINS", "source_node_id": "D_EV_000002",
                      "target_node_id": "D_EV_000001", "confidence": .8}, task)
    assert not valid


def test_fine_prediction_can_be_collapsed_and_score_as_oracle():
    truth = [gold()]
    task = build_tasks(truth, [node("D_EV_000001", 1), node("D_EV_000002", 2)])[0]
    fine = [{"task_id": task["task_id"], "valid": True, "relation_type": "EXPLAINS",
             "source_node_id": "D_EV_000002", "target_node_id": "D_EV_000001", "confidence": 1.0}]
    report, diagnostics = score_predictions([task], normalize_predictions(fine, True), truth)
    assert report["type_accuracy"] == 1.0
    assert report["exact_type_and_direction_accuracy"] == 1.0
    assert diagnostics[0]["gold_coarse_relation"] == "EXPANDS"
