"""CPU-only tests for a conservative, provenance-aware KG query scope scorer."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import score_kg_query_scope as scorer


def query(**kwargs):
    return {"question_id": "q1", "decision_object": "Director election",
            "entity": "Acme", "embedding_space": "frozen-v1",
            "vector": [1.0, 0.0], **kwargs}


def edge(**kwargs):
    base = {"edge_id": "e1", "source_id": "a", "target_id": "b",
            "edge_type": "EVIDENCE_LINK", "complementarity": "COMPLEMENTARY",
            "target_B_adds": "Director nominee voting requirements",
            "decision_object": "director election", "entity": "acme",
            "embedding_space": "frozen-v1", "contribution_vector": [0.9, 0.1],
            "review_level": "model_accepted_not_human_gold"}
    base.update(kwargs)
    return base


def test_positive_match_requires_specific_object_and_compatible_vector():
    result = scorer.score_pair(query(), edge())
    assert result["decision"] == "match"
    assert result["scope_score"] > 0.99
    assert result["review_level"] == "model_accepted_not_human_gold"


def test_different_decision_object_fails_even_with_identical_vectors():
    result = scorer.score_pair(query(), edge(decision_object="auditor ratification",
                                             contribution_vector=[1.0, 0.0]))
    assert result["decision"] == "mismatch"
    assert result["reason"] == "decision_object_conflict"


def test_condition_mismatch_is_separate_from_semantic_similarity():
    result = scorer.score_pair({**query(), "conditions": {"year": "2025"}},
                               edge(conditions={"year": "2024"}))
    assert result["decision"] == "mismatch"
    assert result["reason"] == "condition_conflict:year"


@pytest.mark.parametrize("override,reason", [
    ({"embedding_space": "other-model"}, "embedding_space_mismatch"),
    ({"contribution_vector": None}, "missing_compatible_vectors"),
    ({"decision_object": None}, "missing_decision_object"),
    ({"complementarity": "REDUNDANT"}, "no_grounded_complementary_contribution"),
    ({"edge_type": "NAVIGATION_LINK"}, "not_evidence_link"),
])
def test_nonpositive_cases_abstain(override, reason):
    result = scorer.score_pair(query(), edge(**override))
    assert result["decision"] == "abstain"
    assert result["reason"] == reason


def test_low_similarity_abstains_not_mismatches():
    result = scorer.score_pair(query(), edge(contribution_vector=[0.0, 1.0]))
    assert result["decision"] == "abstain"
    assert result["scope_score"] == 0.0


def test_missing_query_identity_abstains_even_with_high_similarity():
    q = query()
    del q["decision_object"]
    assert scorer.score_pair(q, edge())["decision"] == "abstain"


def test_strict_vectors_reject_invalid_numbers_and_dimensions():
    with pytest.raises(ValueError, match="length"):
        scorer.cosine([1.0], [1.0, 0.0])
    with pytest.raises(ValueError, match="finite"):
        scorer.cosine([float("nan")], [1.0])
    with pytest.raises(ValueError, match="zero norm"):
        scorer.cosine([0.0, 0.0], [1.0, 0.0])


def test_duplicate_ids_rejected_and_score_output_is_loader_compatible(tmp_path):
    q, e = query(), edge()
    with pytest.raises(ValueError, match="duplicate"):
        scorer.evaluate([q, q], [e])
    scored = scorer.evaluate([q], [e])
    assert {key: scored[0][key] for key in ("question_id", "edge_id", "decision", "reason")}
    path = tmp_path / "scope.jsonl"
    scorer.write_jsonl(path, scored)
    assert json.loads(path.read_text().strip())["decision"] == "match"
    with pytest.raises(FileExistsError):
        scorer.write_jsonl(path, scored)



def test_missing_named_entity_on_edge_does_not_pass():
    result = scorer.score_pair(query(), edge(entity=None))
    assert result["decision"] == "abstain"
    assert result["reason"] == "missing_entity_identity"


def test_missing_required_query_condition_does_not_pass():
    q = {**query(), "conditions": {"year": "2025"}}
    result = scorer.score_pair(q, edge(conditions={}))
    assert result["decision"] == "abstain"
    assert result["reason"] == "missing_required_condition"
