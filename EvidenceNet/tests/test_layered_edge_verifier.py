from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_layered_edge_verifier import validate


def entry():
    return {"task": {"task_id": "x"}, "lookups": {"A": {"a": {}}, "B": {"b": {}}}}


def value(**updates):
    base = {"task_id": "x", "decision": "EVIDENCE_LINK", "basis": "SAME_SPECIFIC_SUBJECT",
            "relation": "SAME_SUBJECT", "direction": "SYMMETRIC", "explicit_reference": "NONE",
            "A_evidence_ids": ["a"], "B_evidence_ids": ["b"], "matched_claim": "same object",
            "reason": "same named object", "limitation": "does not prove other claims"}
    return {**base, **updates}


def test_same_subject_is_not_forced_to_supports():
    assert validate(value(), entry())["relation"] == "SAME_SUBJECT"


def test_navigation_is_separate_and_untyped():
    result = validate(value(decision="NAVIGATION_LINK", basis="SHARED_NAMED_COMPONENT",
                            relation=None, direction="SYMMETRIC"), entry())
    assert result["decision"] == "NAVIGATION_LINK"


def test_supports_requires_direction():
    try:
        validate(value(relation="SUPPORTS", direction="SYMMETRIC"), entry())
    except ValueError as exc:
        assert "directed" in str(exc)
    else:
        raise AssertionError("symmetric SUPPORTS must be rejected")
