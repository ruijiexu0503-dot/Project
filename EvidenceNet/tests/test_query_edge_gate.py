import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import query_edge_gate as gate


def record():
    return {"query": "Did ORBIT reduce pressure?",
            "seed_hit": {"text": "ORBIT results are reported in the pressure experiment."},
            "source": {"anchor": "The ORBIT pressure experiment used NEXA valves.",
                       "context": "This experiment compared two settings.", "role": "BODY"},
            "target": {"anchor": "ORBIT did\nnot reduce pressure with NEXA valves.", "role": "BODY"}}


def decision(role="DIRECT"):
    return {"role": role, "reason": "Same experiment; target states its pressure outcome.",
            "source_quote": "ORBIT pressure experiment used NEXA valves",
            "target_quote": "ORBIT did not reduce pressure with NEXA valves.",
            "answered_aspect": "Pressure outcome for ORBIT" if role in {"DIRECT", "PARTIAL"} else "",
            "bridge_step": "Explicit connection to the named experiment." if role == "BRIDGE" else ""}


def test_allowlist_does_not_leak_gold_scores_question_type_or_old_reason():
    r = record()
    original = gate.make_prompt(r)
    r.update(gold=["GOLD_SECRET"], query_type="QUESTION_TYPE_SECRET", score=999,
             edge_reason="OLD_REASON_SECRET", decision="OLD_DECISION_SECRET")
    r["target"].update(reason="NESTED_REASON_SECRET", score=888, gold="NESTED_GOLD_SECRET")
    r["seed_hit"]["label"] = "HIT_GOLD_SECRET"
    assert gate.make_prompt(r) == original
    assert "SECRET" not in original
    json.dumps(gate.prompt_record(r))


@pytest.mark.parametrize("role", sorted(gate.ROLES))
def test_roles_and_whitespace_preserve_grounded_negation(role):
    r, v = record(), decision(role)
    before = copy.deepcopy((r, v))
    validated = gate.validate(v, r)
    assert validated == v and validated is not v
    assert (r, v) == before
    assert set(validated) == gate.FIELDS
    assert "support" not in validated and "auto_propagate" not in validated


@pytest.mark.parametrize("field,content", [
    ("source_quote", "ORBIT did not reduce pressure"),  # Wrong endpoint.
    ("target_quote", "ORBIT reduced pressure"),  # Invented affirmative claim.
    ("source_quote", "This experiment compared two settings."),  # Context not anchor.
    ("source_quote", "ORBIT results are reported"),  # Seed-hit not edge anchor.
    ("target_quote", ""),
    ("source_quote", " \n "),
])
def test_literal_ownership_and_empty_navigation_quotes(field, content):
    v = decision()
    v[field] = content
    with pytest.raises(ValueError):
        gate.validate(v, record())


def test_optional_negative_quotes_still_grounded():
    v = decision("UNCERTAIN")
    v.update(source_quote="", target_quote="")
    assert gate.validate(v, record()) == v
    v["target_quote"] = "unseen result"
    with pytest.raises(ValueError):
        gate.validate(v, record())


@pytest.mark.parametrize("role,field,value", [
    ("DIRECT", "answered_aspect", ""),
    ("PARTIAL", "bridge_step", "some bridge"),
    ("BRIDGE", "bridge_step", ""),
    ("BRIDGE", "answered_aspect", "some answer"),
    ("BACKGROUND", "answered_aspect", "some answer"),
    ("UNSUPPORTED", "bridge_step", "some bridge"),
])
def test_role_field_consistency(role, field, value):
    v = decision(role)
    v[field] = value
    with pytest.raises(ValueError):
        gate.validate(v, record())


@pytest.mark.parametrize("change", [
    {"auto_propagate": True}, {"semantic_support": True}, {"role": "SUPPORT"},
    {"reason": []}, {"source_quote": 12}, {"reason": ""},
])
def test_no_support_schema_escape_or_invalid_values(change):
    v = decision()
    v.update(change)
    with pytest.raises(ValueError):
        gate.validate(v, record())


def test_quotes_must_appear_in_shown_not_hidden_original():
    r = record()
    r["target"]["anchor"] = "x" * gate.ANCHOR_LIMIT + " HIDDEN_TAIL"
    shown = gate.prompt_record(r)
    assert shown["target"]["anchor_truncated"]
    assert "HIDDEN_TAIL" not in gate.make_prompt(r)
    v = decision()
    v["target_quote"] = "HIDDEN_TAIL"
    with pytest.raises(ValueError):
        gate.validate(v, r)


def test_missing_visual_transcript_can_abstain_but_not_pass():
    r = record()
    r["target"]["anchor"] = ""
    v = decision("UNCERTAIN")
    v["target_quote"] = ""
    assert gate.validate(v, r) == v
    v = decision()
    v["target_quote"] = ""
    with pytest.raises(ValueError):
        gate.validate(v, r)


def test_original_text_required_and_context_bounded():
    r = record()
    r["source"]["context"] = "c" * 10000
    r["source"]["role"] = "GOLD_ANSWER_PAGE"
    shown = gate.prompt_record(r)
    assert len(shown["source"]["context"]) == gate.CONTEXT_LIMIT
    assert shown["source"]["context_truncated"]
    assert shown["source"]["role"] == "UNKNOWN"
    del r["seed_hit"]
    with pytest.raises(ValueError):
        gate.make_prompt(r)


def test_citation_question_not_globally_filtered():
    r = record()
    r.update(query="Who wrote the cited ORBIT study?")
    r["source"]["anchor"] = "The ORBIT study [12] examines pressure."
    r["target"].update(anchor="[12] Doe, J. The ORBIT study. 2024.", role="BIBLIOGRAPHY")
    v = decision()
    v.update(source_quote="ORBIT study [12]", target_quote="Doe, J. The ORBIT study.",
             answered_aspect="Author of the cited ORBIT study")
    assert gate.validate(v, r) == v
