"""Bounded verifier v2 must reject unresolved/contradictory identity assertions."""
from pathlib import Path
import sys
import copy

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_kg_link_prediction_bounded_verifier as verifier


def sample():
    anchors = {
        "A": {"quote": "Proposal 2 ratification of auditors. Abstentions have no effect.",
              "kind": "ORIGINAL_TEXT", "document": "doc_a"},
        "B": {"quote": "Ratification of KPMG LLP. Abstentions count as votes against.",
              "kind": "ORIGINAL_TEXT", "document": "doc_b"},
    }
    entry = {"task": {"task_id": "pair"},
             "lookups": {"A": {"A:E000": anchors["A"]},
                         "B": {"B:E000": anchors["B"]}}}
    result = {
        "task_id": "pair", "discovery_level": 2,
        "decision": "EVIDENCE_LINK", "basis": "CLAIM_CORRESPONDENCE",
        "shared_identity": None, "identity_conflicts": [],
        "A_evidence_ids": ["A:E000"], "B_evidence_ids": ["B:E000"],
        "matched_claim": "claimed auditor overlap", "reason": "claimed support",
        "limitation": "cross document", "direction": "UNDIRECTED",
        "target_B_adds": "extra details", "complementarity": "PARTIAL_OVERLAP",
        "entity_condition_constraints": "entity unknown",
        "identity_status": "UNRESOLVED", "claim_consistency": "UNCERTAIN",
        "condition_alignment": "UNRESOLVED",
        "consistency_evidence": {
            "A_evidence_id": "A:E000", "B_evidence_id": "B:E000",
            "explanation": "Corporate identities not established",
        },
    }
    return entry, result


def test_unresolved_identity_blocks_model_accepted_link():
    entry, value = sample()
    with pytest.raises(ValueError, match="unresolved or contradictory"):
        verifier.validate(value, entry)


def test_contradiction_blocks_model_accepted_link():
    entry, value = sample()
    value.update(identity_status="DISTINCT_COMPARISON",
                 condition_alignment="ALIGNED", claim_consistency="CONTRADICTORY")
    with pytest.raises(ValueError, match="unresolved or contradictory"):
        verifier.validate(value, entry)


def test_cross_document_same_identity_requires_independent_confirmation():
    entry, value = sample()
    value.update(identity_status="SAME_VERIFIED",
                 condition_alignment="ALIGNED", claim_consistency="CONSISTENT")
    with pytest.raises(ValueError, match="cross-document same identity"):
        verifier.validate(value, entry)


def test_explicit_distinct_comparison_is_allowed_as_model_only_when_consistent():
    entry, value = sample()
    value.update(identity_status="DISTINCT_COMPARISON",
                 condition_alignment="DISTINCT_STATED", claim_consistency="CONSISTENT")
    result = verifier.validate(value, entry)
    assert result["decision"] == "EVIDENCE_LINK"
    assert result["identity_status"] == "DISTINCT_COMPARISON"


def test_unowned_consistency_anchor_fails():
    entry, value = sample()
    value["consistency_evidence"]["B_evidence_id"] = "B:UNKNOWN"
    with pytest.raises(ValueError, match="consistency evidence ownership"):
        verifier.validate(value, entry)


def test_missing_new_fields_fails_validation():
    entry, value = sample()
    del value["identity_status"]
    with pytest.raises(ValueError, match="identity_status"):
        verifier.validate(value, entry)


def test_no_link_with_unresolved_claims_is_valid_and_not_promoted():
    entry, value = sample()
    value.update(decision="NO_LINK", basis=None,
                 complementarity="NONE", target_B_adds="")
    output = verifier.validate(value, entry)
    assert output["decision"] == "NO_LINK"
    assert output["claim_consistency"] == "UNCERTAIN"
