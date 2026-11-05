"""Unit tests for the CPU-only graph-retrieval oracle diagnostic."""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyze_graph_retrieval_oracle_feasibility as oracle


def test_overlap_reports_gold_coverage_without_asserting_gold_identity():
    result = oracle.overlap((0, 0, 100, 20), (0, 0, 100, 40))
    assert result["gold_coverage"] == 1.0
    assert result["node_coverage"] == 0.5
    assert result["iou"] == 0.5


def test_spatial_candidates_separate_eligible_and_excluded_nodes():
    gold = {"bounding_box": {"relative_page_x": 0.0, "relative_page_y": 0.0,
                              "relative_width": 0.5, "relative_height": 0.5}}
    nodes = [
        {"id": "eligible", "page": 1, "node_type": "TEXT", "geometry_image_size": [100, 100],
         "members": [{"boxes": [[0, 0, 50, 50]]}]},
        {"id": "excluded", "page": 1, "node_type": "VISUAL", "geometry_image_size": [100, 100],
         "members": [{"boxes": [[0, 0, 25, 50]]}]},
    ]
    _, strong = oracle.spatial_candidates(gold, nodes, {"eligible"}, 0.5)
    assert [row["node_id"] for row in strong] == ["eligible", "excluded"]
    assert strong[0]["eligible"] is True
    assert strong[1]["eligible"] is False


def test_reachability_and_direction_are_explicit():
    graph = {"a": {"b"}, "b": {"c"}}
    reached, distance = oracle.reachable(graph, ["a"])
    assert reached == {"a", "b", "c"}
    assert distance["c"] == 2
    edge = {"source_id": "a", "target_id": "b", "direction": "A_TO_B"}
    assert list(oracle.semantic_routes(edge)) == [("a", "b")]
    edge["direction"] = "UNDIRECTED"
    assert list(oracle.semantic_routes(edge)) == [("a", "b"), ("b", "a")]
