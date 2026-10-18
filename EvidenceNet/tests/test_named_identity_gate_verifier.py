from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_named_identity_gate_verifier as gate


def entry():
    def anchor(side, eid, quote, kind="ORIGINAL_TEXT"):
        return {"node_id": side, "member_id": eid, "kind": kind, "quote": quote}
    return {
        "task": {"task_id": "T1"},
        "lookups": {
            "A": {"A:E000": anchor("A", "a", "Figure 5: FUSU-Net architecture"),
                  "A:E001": anchor("A", "v", "satellite-style image", "QWEN_VISUAL_DESCRIPTION_AND_ORIGINAL_CROP")},
            "B": {"B:E000": anchor("B", "b", "Figure 1: EuroSAT dataset samples")},
        },
    }


def value():
    return {"task_id": "T1", "discovery_level": 2, "decision": "EVIDENCE_LINK",
            "basis": "SAME_SPECIFIC_SUBJECT",
            "shared_identity": {"kind": "DATASET", "canonical_name": "EuroSAT",
                                "A_surface": "EuroSAT", "A_evidence_id": "A:E000",
                                "B_surface": "EuroSAT", "B_evidence_id": "B:E000"},
            "identity_conflicts": [], "A_evidence_ids": ["A:E000"],
            "B_evidence_ids": ["B:E000"], "matched_claim": "same dataset",
            "reason": "same", "limitation": ""}


def test_rejects_identity_absent_from_original_side():
    with pytest.raises(ValueError, match="surface absent"):
        gate.validate(value(), entry())


def test_rejects_visual_description_as_identity_anchor():
    candidate = value()
    candidate["shared_identity"]["A_surface"] = "satellite"
    candidate["shared_identity"]["A_evidence_id"] = "A:E001"
    with pytest.raises(ValueError, match="original text"):
        gate.validate(candidate, entry())


def test_accepts_checked_shared_identity():
    candidate = value()
    checked_entry = entry()
    checked_entry["lookups"]["A"]["A:E000"]["quote"] = "Graph WaveNet is fixed once trained"
    checked_entry["lookups"]["B"]["B:E000"]["quote"] = "Graph WaveNet is fixed after training"
    candidate["shared_identity"] = {"kind": "MODEL", "canonical_name": "Graph WaveNet",
        "A_surface": "Graph WaveNet", "A_evidence_id": "A:E000",
        "B_surface": "Graph WaveNet", "B_evidence_id": "B:E000"}
    result = gate.validate(candidate, checked_entry)
    assert result["decision"] == "EVIDENCE_LINK"


def test_caps_anchor_count():
    candidate = value()
    candidate["A_evidence_ids"] = ["A:E000"] * 4
    with pytest.raises(ValueError, match="at most 3"):
        gate.validate(candidate, entry())
