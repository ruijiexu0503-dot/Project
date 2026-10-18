from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import postprocess_named_identity_gate as post
import run_named_identity_gate_verifier as gate


def make_entry():
    def anchor(eid, quote, kind="ORIGINAL_TEXT"):
        return {"node_id": eid[0], "member_id": eid, "kind": kind, "quote": quote}
    return {"task": {"task_id": "T1"}, "lookups": {
        "A": {"A:E000": anchor("A:E000", "FUSU-Net architecture"),
              "A:E001": anchor("A:E001", "Sentinel image", "QWEN_VISUAL_DESCRIPTION_AND_ORIGINAL_CROP")},
        "B": {"B:E000": anchor("B:E000", "EuroSAT dataset samples")},
    }}


def base_value(decision="NO_LINK", basis=None):
    return {"task_id": "T1", "discovery_level": 2, "decision": decision, "basis": basis,
            "shared_identity": None, "identity_conflicts": [],
            "A_evidence_ids": ["A:E000"], "B_evidence_ids": ["B:E000"],
            "matched_claim": "", "reason": "Different subjects.", "limitation": ""}


def test_drops_ungrounded_conflict_only_for_rejected_edge():
    candidate = base_value()
    candidate["identity_conflicts"] = [{"kind": "DATASET", "A_name": "Unknown dataset",
        "A_evidence_id": "A:E000", "B_name": "EuroSAT", "B_evidence_id": "B:E000"}]
    repaired, changes = post.repair_optional_metadata(candidate, make_entry())
    assert repaired["decision"] == "NO_LINK"
    assert repaired["identity_conflicts"] == []
    assert changes == ["dropped_ungrounded_conflict_metadata"]
    assert gate.validate(repaired, make_entry())["decision"] == "NO_LINK"


def test_does_not_hide_conflict_on_accepted_edge():
    candidate = base_value("EVIDENCE_LINK", "DIRECT_COMPLEMENT")
    candidate["identity_conflicts"] = [{"kind": "DATASET", "A_name": "Unknown dataset",
        "A_evidence_id": "A:E000", "B_name": "EuroSAT", "B_evidence_id": "B:E000"}]
    repaired, changes = post.repair_optional_metadata(candidate, make_entry())
    assert repaired["identity_conflicts"] == candidate["identity_conflicts"]
    assert changes == []


def test_drops_optional_visual_identity_for_direct_complement():
    candidate = base_value("EVIDENCE_LINK", "DIRECT_COMPLEMENT")
    candidate["shared_identity"] = {"kind": "METHOD", "canonical_name": "Sentinel",
        "A_surface": "Sentinel", "A_evidence_id": "A:E001",
        "B_surface": "EuroSAT", "B_evidence_id": "B:E000"}
    repaired, changes = post.repair_optional_metadata(candidate, make_entry())
    assert repaired["shared_identity"] is None
    assert changes == ["dropped_invalid_optional_shared_identity"]
    assert gate.validate(repaired, make_entry())["decision"] == "EVIDENCE_LINK"
