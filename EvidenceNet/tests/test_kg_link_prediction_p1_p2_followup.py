from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_kg_link_prediction_p1_p2_followup as followup


def test_canonical_pair_is_unordered_and_rejects_self_pair():
    assert followup.canonical("b", "a") == ("a", "b")
    try:
        followup.canonical("a", "a")
    except ValueError:
        pass
    else:
        raise AssertionError("self-pair must be rejected")


def test_pair_record_preserves_direction_but_keys_canonically():
    def entity(node_id):
        return {"entity_id": node_id, "document": "doc", "page": 1,
                "modality": "TEXT", "document_split": "train", "text": node_id,
                "text_source": "members[].text", "text_sha256": node_id + "sha"}
    entities = {node_id: entity(node_id) for node_id in ("a", "b")}
    row = {"source_id": "b", "target_id": "a", "raw_score": .5,
           "is_new_to_baseline": True, "graph_provenance": {"neighbor_count": 1}}
    record = followup.pair_record(("a", "b"), "p2_only", entities, {}, {("a", "b"): row})
    assert record["canonical_pair"] == ["a", "b"]
    assert record["p2_direction"] == ["b", "a"]
    assert record["review_label"] is None and record["human_gold"] is False


def test_deterministic_selection_is_order_independent():
    assert followup.deterministic([3, 1, 2], "x") == followup.deterministic([2, 3, 1], "x")
