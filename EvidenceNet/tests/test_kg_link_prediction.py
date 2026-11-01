import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import prepare_kg_link_prediction as kg


def test_document_split_is_stable_and_atomic():
    assert kg._split_for_document("doc-a") == kg._split_for_document("doc-a")
    assert kg._split_for_document("doc-a") in {"train", "valid", "test"}


def test_candidate_evaluation_does_not_count_unknown_as_negative():
    rows = [
        {"proposer": "m", "review_label": "accepted"},
        {"proposer": "m", "review_label": "rejected"},
        {"proposer": "m", "review_label": "unknown"},
        {"proposer": "m", "review_label": None},
    ]
    report = kg.evaluate_candidates(rows)["by_proposer"]["m"]
    assert report["decided_precision"] == 0.5
    assert report["counts"] == {"accepted": 1, "rejected": 1, "unknown": 1, "unreviewed": 1}


def test_semantic_record_preserves_score_boundary_and_gold_status():
    nodes = {"a": {"document": "d1"}, "b": {"document": "d2"}}
    edge = {"source": "a", "target": "b", "task_id": "t", "status": "MODEL_PROPOSED_NOT_HUMAN_VERIFIED",
            "model_result": {"matched_claim": "A relates to B", "anchors": {"A": [1], "B": [2]}}}
    row = kg._semantic_record(edge, nodes)
    assert row["raw_score"] is None
    assert row["supervision_eligible"] is False
    assert row["evidence_propagation_allowed"] is False
    assert row["candidate_scope"] == "cross_document"


def test_reading_audit_refuses_partial_coverage(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    assignments = root / "article_assignments.jsonl"
    edges = root / "reading_edges.jsonl"
    assignments.write_text(json.dumps({"node_id": "a"}) + "\n")
    edges.write_text("")
    manifest = {"ready_for_downstream": True, "reading_ready": True,
                "files": {"article_assignments.jsonl": kg._sha(assignments), "reading_edges.jsonl": kg._sha(edges)}}
    (root / "article_graph_manifest.json").write_text(json.dumps(manifest))
    audit = kg._reading_audit([root], {"a", "b"})
    assert audit["complete_for_evidence_corpus"] is False
    assert audit["import_decision"] == "coverage_limited_do_not_mark_global_ready"
    assert audit["evidence_node_coverage"] == 0.5


def test_review_scaffold_is_blind_but_contains_reviewable_source_text():
    nodes = {
        "a": {"document": "d1", "page": 1, "node_type": "TEXT", "members": [{"text": "source fact"}]},
        "b": {"document": "d2", "page": 2, "node_type": "TABLE", "members": [{"text": "target fact"}]},
    }
    edge = {"source": "a", "target": "b", "task_id": "t", "model_result": {"matched_claim": "same object"}}
    public, key = kg._review_scaffold({"related": [edge]}, nodes, 1)
    assert public[0]["source"]["text"] == "source fact"
    assert public[0]["target"]["text"] == "target fact"
    assert "proposer_bucket" not in public[0]
    assert key[0]["proposer_bucket"] == "related"
