import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import audit_directional_relation_opportunity as audit


def _route(score, target, view, seed_rank=1, status="proposal"):
    return {"score": score, "target_node_id": target, "view_id": view, "edge_id": view,
            "seed_rank": seed_rank, "status": status, "source_node_id": "s"}


def test_replay_deduplicates_targets_and_obeys_saved_tie_break():
    routes = [_route(0.8, "a", "z", 2), _route(0.8, "b", "a", 1), _route(0.7, "b", "b", 2)]
    targets, views = audit.replay_targets(routes, {"s"}, 2)
    assert targets == ["b", "a"]
    assert views == ["a", "z"]


def test_replay_excludes_seed_and_unavailable_routes():
    routes = [_route(0.9, "s", "seed"), _route(0.8, "x", "bad", status="insufficient_anchor"),
              _route(0.7, "y", "ok")]
    targets, _ = audit.replay_targets(routes, {"s"}, 5)
    assert targets == ["y"]


def test_competition_requires_cutoff_to_exclude_a_target():
    task = {"question_id": "q", "question": "Q?", "seed_nodes": ["s"],
            "node_ranking": ["s", "a", "b", "c", "d", "e", "f"]}
    arms = {arm: [_route(1 - i / 10, target, f"v{i}") for i, target in enumerate("abcdef")]
            for arm in audit.GRAPH_ARMS}
    exposure = {"R0_dense": {"new_target_nodes": list("abcde"), "all_exposed_nodes": ["s", *"abcde"]}}
    result = {"R0_dense": {"top10_pages": [["d", "1"]]}}
    for arm in audit.GRAPH_ARMS:
        exposure[arm] = {"new_target_nodes": list("abcde"), "all_exposed_nodes": ["s", *"abcde"],
                         "graph_targets": 5}
        result[arm] = {"top10_pages": [["d", "1"]]}
    row, _ = audit.analyze_query(task, arms, exposure, result, set(), 5)
    assert row["unique_adjacent_targets"] == 6
    assert row["budget_binding"] is True
    assert row["actual_route_competition"] is True


def test_nonbinding_candidates_are_not_called_actual_competition():
    task = {"question_id": "q", "question": "Q?", "seed_nodes": ["s"],
            "node_ranking": ["s", "a", "b"]}
    arms = {arm: [_route(0.9, "a", "v1"), _route(0.8, "b", "v2")] for arm in audit.GRAPH_ARMS}
    exposure = {"R0_dense": {"new_target_nodes": ["a", "b"], "all_exposed_nodes": ["s", "a", "b"]}}
    result = {"R0_dense": {"top10_pages": []}}
    for arm in audit.GRAPH_ARMS:
        exposure[arm] = {"new_target_nodes": ["a", "b"], "all_exposed_nodes": ["s", "a", "b"],
                         "graph_targets": 2}
        result[arm] = {"top10_pages": []}
    row, _ = audit.analyze_query(task, arms, exposure, result, set(), 5)
    assert row["top1_ranking_choice_possible"] is True
    assert row["budget_binding"] is False
    assert row["actual_route_competition"] is False
