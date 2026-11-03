"""Real frozen-ranking candidate admission audit, exercised with synthetic inputs."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_kg_retrieval_admission as audit


def context():
    return {"question_id": "q", "seed_nodes": ["a"],
            "node_ranking": ["a", "b", "c", "d", "e", "f", "g"]}


def accepted(target="g", direction="A_TO_B"):
    return {"edge_id": "e1", "source_id": "a", "target_id": target,
            "direction": direction, "edge_type": "EVIDENCE_LINK",
            "review_level": "model_accepted_not_human_gold"}


def test_outside_top_budget_is_admitted_without_creating_extra_slot():
    traces, qs = audit.audit([context()], [accepted()], budget=5, core=2, graph_slots=1)
    assert len(traces) == 1
    assert traces[0]["admission"] == "admitted"
    assert traces[0]["target_initial_rank"] == 7
    assert traces[0]["final_candidate_rank"] == 3
    assert qs[0]["control_candidate_ids"] == ["a", "b", "c", "d", "e"]
    assert qs[0]["kg_candidate_ids"] == ["a", "b", "g", "c", "d"]
    assert qs[0]["replaced_dense_tail_ids"] == ["e"]
    assert len(qs[0]["kg_candidate_ids"]) == 5


def test_already_present_target_never_claims_novel_admission():
    routes, summary = audit.audit([context()], [accepted("c")], budget=5, core=2)
    assert routes[0]["admission"] == "already_in_control"
    assert summary[0]["novel_targets_admitted"] == 0
    assert summary[0]["kg_candidate_ids"] == summary[0]["control_candidate_ids"]


def test_directional_edges_cannot_be_traversed_backwards():
    routes, summary = audit.audit([context()], [accepted(direction="B_TO_A")],
                                  budget=5, core=2)
    assert routes == []
    assert summary[0]["kg_candidate_ids"] == ["a", "b", "c", "d", "e"]


def test_reverse_navigation_allowed_for_bidirectional_edges():
    ctx = {"question_id": "q", "seed_nodes": ["g"],
           "node_ranking": ["g", "b", "c", "d", "e", "f", "a"]}
    routes, summary = audit.audit([ctx], [accepted(direction="BIDIRECTIONAL")],
                                  budget=5, core=2, graph_slots=1)
    assert routes[0]["direction"] == "inverse"
    assert routes[0]["target_id"] == "a"
    assert summary[0]["kg_candidate_ids"][:3] == ["g", "b", "a"]


def test_zero_graph_slots_never_changes_baseline():
    _, qs = audit.audit([context()], [accepted()], budget=5, core=2,
                        graph_slots=0)
    assert qs[0]["kg_candidate_ids"] == qs[0]["control_candidate_ids"]


def test_invalid_frozen_ranking_is_rejected():
    ctx = context()
    ctx["node_ranking"].append("a")
    with pytest.raises(ValueError, match="duplicate node"):
        audit.audit([ctx], [accepted()], budget=5, core=2)


def test_missing_edge_endpoint_does_not_invent_candidate():
    _, qs = audit.audit([context()], [accepted(target="missing")],
                        budget=5, core=2)
    assert qs[0]["kg_candidate_ids"] == qs[0]["control_candidate_ids"]


def test_write_does_not_overwrite_existing_artifacts(tmp_path):
    output = tmp_path / "result.jsonl"
    audit.dump_new(output, [{"a": 1}])
    assert json.loads(output.read_text().strip()) == {"a": 1}
    with pytest.raises(FileExistsError):
        audit.dump_new(output, [{"a": 2}])
