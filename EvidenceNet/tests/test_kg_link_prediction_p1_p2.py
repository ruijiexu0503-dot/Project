from pathlib import Path
import sys

import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_kg_link_prediction_p1_p2 as kg


def entity(node_id: str) -> dict:
    return {"entity_id": node_id, "document": "doc", "document_split": "train"}


def test_aggregate_node_vectors_uses_only_existing_views():
    views = [{"node_id": "a"}, {"node_id": "a"}, {"node_id": "b"}]
    vectors = np.asarray([[1, 0], [0, 1], [0, 1]], dtype=np.float32)
    result, counts = kg.aggregate_node_vectors(["a", "b"], views, vectors)
    assert counts == {"a": 2, "b": 1}
    assert np.allclose(result[0], np.asarray([2 ** -0.5, 2 ** -0.5]))
    assert np.allclose(np.linalg.norm(result, axis=1), 1)


def test_graph_adjacency_is_typed_and_no_absence_is_created():
    edges = [{"source_id": "a", "target_id": "b", "relation_id": "RELATED_OPEN",
              "graph_layer": "semantic_noisy_observation", "edge_id": "e1"},
             {"source_id": "a", "target_id": "c", "relation_id": "NEXT",
              "graph_layer": "reading_validated_v5", "edge_id": "e2"}]
    adjacency = kg.build_adjacency(edges, {"a", "b", "c", "d"})
    assert {row["neighbor_id"] for row in adjacency["a"]} == {"b", "c"}
    assert [row["neighbor_id"] for row in adjacency["b"]] == ["a"]
    assert "d" not in adjacency


def test_generate_rankings_preserves_isolated_p1_fallback_and_filters_observed():
    entities = [entity(node_id) for node_id in ("a", "b", "c", "d")]
    vectors = np.asarray([[1, 0], [.9, .1], [0, 1], [.2, .8]], dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1)[:, None]
    edge = {"source_id": "a", "target_id": "b", "relation_id": "RELATED_OPEN",
            "graph_layer": "semantic_noisy_observation", "edge_id": "e1"}
    p1, p2, decisions, _ = kg.generate_rankings(
        entities, vectors, {node_id: 1 for node_id in ("a", "b", "c", "d")},
        [edge], set(), top_k=2, batch_size=2)
    assert not any(row["source_id"] == "a" and row["target_id"] == "b" for row in p1 + p2)
    isolated = {row["source_id"] for row in decisions if not row["graph_context_used"]}
    for source_id in isolated:
        p1_targets = [row["target_id"] for row in p1 if row["source_id"] == source_id]
        p2_targets = [row["target_id"] for row in p2 if row["source_id"] == source_id]
        assert p1_targets == p2_targets


def test_budget_selection_deduplicates_canonical_pairs():
    rankings = [
        {"source_id": "a", "target_id": "b", "raw_score": .9},
        {"source_id": "b", "target_id": "a", "raw_score": .8},
        {"source_id": "a", "target_id": "c", "raw_score": .7},
    ]
    chosen = kg.select_budget(rankings, 2)
    assert [(row["source_id"], row["target_id"]) for row in chosen] == [("a", "b"), ("a", "c")]
