import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_semantic_relation_trial as trial


def entry():
    e = {"task": {"task_id": "T", "candidate_matches": []}, "lookups": {}, "images": [], "image_sha256": []}
    for side in ("A", "B"):
        eid = side + ":E000"
        raw = "The named method did\nnot reduce pressure."
        e["task"][side] = {"node_id": side, "evidence": [{"evidence_id": eid, "kind": "ORIGINAL_TEXT", "text": raw}]}
        e["lookups"][side] = {eid: {"node_id": side, "kind": "ORIGINAL_TEXT", "quote": raw}}
    return trial.make_entry(e)


def value(tag="SHARED_COMPONENT_OR_ENTITY", use="NAVIGATION_ONLY"):
    return {"task_id": "T", "relatedness": "RELATED", "relations": [{"type": tag,
        "A_evidence_id": "A:E000", "B_evidence_id": "B:E000", "A_quote": "named method",
        "B_quote": "named method", "explanation": "Same named method."}],
        "evidence_use": use, "reason": "Explicit component.", "limitation": "Different uses."}


def test_prompt_changes_only_policy_and_no_source_mutation():
    source = entry()
    snapshot = copy.deepcopy(source)
    new = trial.make_entry(source)
    assert source == snapshot
    assert new["task"] == source["task"] and new["lookups"] == source["lookups"]
    assert new["images"] == [] and trial.key(new) == new["inference_key"]
    assert "STAGE 2 — graph decision" not in new["prompt"]
    assert "CONTRADICTION" in new["prompt"]


def test_grounded_positive_and_negation_quote():
    v = value()
    v["relations"][0]["A_quote"] = "did not reduce pressure"
    assert trial.validate(v, entry()) == v


@pytest.mark.parametrize("field,bad", [("A_quote", "invented method"), ("A_quote", "reduced pressure"),
                                     ("A_evidence_id", "B:E000"), ("type", "SAME_TOPIC")])
def test_unsupported_quotes_ownership_and_types_fail(field, bad):
    v = value()
    v["relations"][0][field] = bad
    with pytest.raises(ValueError): trial.validate(v, entry())


@pytest.mark.parametrize("tag,use", [("CONTRADICTION", "SUPPORT_REVIEW"),
    ("CONTRADICTION", "NAVIGATION_ONLY"), ("SHARED_COMPONENT_OR_ENTITY", "SUPPORT_REVIEW"),
    ("CLAIM_CORRESPONDENCE", "CONFLICT_REVIEW")])
def test_evidence_use_safety_matrix(tag, use):
    with pytest.raises(ValueError): trial.validate(value(tag, use), entry())


def test_conflict_is_related_but_never_support():
    v = value("CONTRADICTION", "CONFLICT_REVIEW")
    assert trial.validate(v, entry())["relatedness"] == "RELATED"
    assert trial.projected({"valid": True, "result": v}, "semantic")["result"]["decision"] == "NAVIGATION_LINK"
    assert "decision" not in v  # report projection never rewrites actual schema


@pytest.mark.parametrize("broad", ["NO_LINK", "UNCERTAIN"])
def test_nonlinks_have_no_tags_and_no_propagation(broad):
    v = value()
    v["relatedness"] = broad
    with pytest.raises(ValueError): trial.validate(v, entry())
    v.update(relations=[], evidence_use="NONE")
    assert trial.validate(v, entry()) == v


def test_duplicate_relations_and_extra_fields_rejected():
    v = value()
    v["relations"].append(copy.deepcopy(v["relations"][0]))
    with pytest.raises(ValueError): trial.validate(v, entry())
    v = value()
    v["auto_propagate"] = True
    with pytest.raises(ValueError): trial.validate(v, entry())


def test_report_pending_invalid_and_no_gold_type_accuracy(tmp_path):
    e = entry()
    trial.jsonl(tmp_path / "semantic/inputs.jsonl", [e])
    trial.jsonl(tmp_path / "reference.jsonl", [{"task_id": "T", "dataset": "real", "suite_case_id": "test<script>",
        "source_suite": "old_development", "cutoff_evaluable": True, "allowed_levels": [2],
        "decision_evaluable": True, "allowed_decisions": ["EVIDENCE_LINK"]}])
    trial.jsonl(tmp_path / "baseline/predictions.jsonl", [{"task_id": "T", "valid": True,
        "result": {"decision": "NO_LINK"}}])
    s = trial.report(tmp_path)
    assert not s["complete"] and s["new_tags_have_no_gold"]
    assert s["datasets"]["real"]["semantic"]["scored_missing"] == 1
    assert s["datasets"]["real"]["semantic"]["strict_scored_total"] == 0
    assert "test<script>" not in (tmp_path / "index.html").read_text()
    trial.jsonl(tmp_path / "semantic/predictions.jsonl", [{"task_id": "T", "inference_key": e["inference_key"],
        "valid": False, "result": None}])
    s = trial.report(tmp_path)
    assert s["complete"] and s["datasets"]["real"]["semantic"]["scored_invalid"] == 1
    trial.jsonl(tmp_path / "semantic/predictions.jsonl", [{"task_id": "T", "inference_key": e["inference_key"],
        "valid": True, "result": value()}])
    s = trial.report(tmp_path)
    assert s["datasets"]["real"]["semantic"]["tp"] == 1
    assert s["flips"][0]["new_wrong"] is False
    assert s["tag_counts"] == {"SHARED_COMPONENT_OR_ENTITY": 1}
