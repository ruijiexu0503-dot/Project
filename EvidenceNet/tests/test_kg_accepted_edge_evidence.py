"""No-inference, fail-closed accepted KG edge evidence audit tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_kg_accepted_edge_evidence as audit


def anchored_edge(a_quote, b_quote, a_doc="doc_a", b_doc="doc_b"):
    return {
        "edge_id": "MODEL_EDGE_test", "source_id": "a", "target_id": "b",
        "edge_type": "EVIDENCE_LINK", "review_level": "model_accepted_not_human_gold",
        "complementarity": "COMPLEMENTARY", "target_B_adds": "Additional context",
        "identity_conflicts": [],
        "anchors": {
            "A": [{"document": a_doc, "quote": a_quote, "member_id": "A:1"}],
            "B": [{"document": b_doc, "quote": b_quote, "member_id": "B:1"}],
        },
    }


def test_known_auditor_abstention_mismatch_is_flagged_but_not_gold():
    e = anchored_edge(
        "Proposal 2: Ratification of Independent Public Accounting Firm. "
        "Abstentions and broker non-votes will have no effect.",
        "Ratification of KPMG LLP. Abstentions have the same effect as a vote AGAINST the proposal.",
    )
    result = audit.audit_edge(e)
    assert "POTENTIAL_ABSTENTION_EFFECT_CONTRADICTION" in result["audit_flags"]
    assert "CROSS_DOCUMENT_IDENTITY_UNRESOLVED" in result["audit_flags"]
    assert result["audit_status"] == "CONTRADICTION_REVIEW_REQUIRED"
    assert not result["allowed_for_navigation"]
    assert not result["independently_human_verified"]
    assert result["original_anchors"] == e["anchors"]


def test_same_document_without_flags_still_requires_independent_review():
    e = anchored_edge("Novel method A", "Supporting details for method A", "doc", "doc")
    result = audit.audit_edge(e)
    assert result["audit_status"] == "PENDING_INDEPENDENT_REVIEW"
    assert not result["allowed_for_navigation"]


def test_cross_document_shared_event_title_is_not_identity_proof():
    e = anchored_edge("Proposal 2: Auditor ratification", "Proposal 2: Auditor ratification")
    result = audit.audit_edge(e)
    assert result["audit_status"] == "IDENTITY_UNRESOLVED"
    assert not result["allowed_for_navigation"]


def test_no_anchor_is_not_silently_accepted():
    e = anchored_edge("", "some original text", "doc", "doc")
    result = audit.audit_edge(e)
    assert "MISSING_ORIGINAL_ENDPOINT_ANCHOR" in result["audit_flags"]
    assert result["audit_status"] == "INSUFFICIENT_EVIDENCE"


def test_no_false_contradiction_when_only_one_side_discusses_abstentions():
    e = anchored_edge("Votes withheld have no effect", "Abstentions have the same effect as a vote AGAINST")
    result = audit.audit_edge(e)
    assert "POTENTIAL_ABSTENTION_EFFECT_CONTRADICTION" not in result["audit_flags"]


def test_no_duplicate_edges():
    import pytest
    e = anchored_edge("A", "B")
    with pytest.raises(ValueError, match="duplicate"):
        audit.audit([e, e])
