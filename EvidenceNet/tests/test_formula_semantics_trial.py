"""Protocol integrity checks; these do not assert model accuracy."""
import copy
import json

import pytest

import run_formula_semantics_trial as trial


def case(task_id="fixture"):
    return {
        "task_id": task_id,
        "source_kind": "synthetic_hypothetical",
        "endpoints": {
            side: {"node_id": task_id + ":" + side, "evidence": [
                {"evidence_id": side + ":E000", "kind": "FORMULA", "text": "x+x"}]
            } for side in ("A", "B")
        },
        "contexts": {side: [{"evidence_id": side + ":C000", "quote": "x is a real scalar"}]
                     for side in ("A", "B")},
        "formulas": {side: [{"evidence_id": side + ":E000", "latex": "x+x"}]
                     for side in ("A", "B")},
        "images": ["/fixture/formula.png"], "image_sha256": ["a" * 64],
    }


def response(entry, semantic="same_definition", structure="same"):
    return {
        "task_id": entry["task_id"], "structure_match": structure,
        "semantic_relation": semantic, "same_research_claim": False,
        "edge_description": "Both double the same real scalar." if semantic in ("same_definition", "shared_operation") else "",
        "role_alignment": "x is a real scalar on each side.",
        "scope_limit": "This is a local definition, with no empirical finding.",
        "evidence_ids": {"A": ["A:E000", "A:C000"], "B": ["B:E000", "B:C000"]},
        "confidence": 0.7,
    }


def prediction(entry, valid=True, result=None):
    return {"task_id": entry["task_id"], "inference_key": entry["inference_key"],
            "valid": valid, "result": result if valid else None, "attempts": []}


def test_label_changes_do_not_change_prompt_or_inference_identity(monkeypatch):
    monkeypatch.setattr(trial, "structural_hints", lambda formulas: {"status": "unknown"})
    original = case()
    changed = copy.deepcopy(original)
    changed.update(expected={"semantic_relation": "GOLD_MARKER_DO_NOT_SEND"},
                   rationale="RATIONALE_MARKER_DO_NOT_SEND",
                   historical_reference="OLD_GOLD_MARKER_DO_NOT_SEND")
    for arm in trial.ARMS:
        before = trial.make_entry(original, arm)
        after = trial.make_entry(changed, arm)
        assert before["prompt"] == after["prompt"]
        assert before["inference_key"] == after["inference_key"]
        assert "MARKER_DO_NOT_SEND" not in after["prompt"]


def test_arms_preserve_identical_evidence_images_and_original_input(monkeypatch):
    monkeypatch.setattr(trial, "structural_hints", lambda formulas: {"status": "unknown"})
    original = case()
    snapshot = copy.deepcopy(original)
    control = trial.make_entry(original, trial.ARMS[0])
    treatment = trial.make_entry(original, trial.ARMS[1])
    assert original == snapshot
    for key in ("endpoints", "contexts", "formulas", "images", "image_sha256"):
        assert control[key] == treatment[key] == original[key]
    assert treatment["prompt"].startswith(control["prompt"])
    assert treatment["inference_key"] != control["inference_key"]


def test_validator_accepts_grounded_abstention_with_parser_unknown():
    entry = case()
    value = response(entry, semantic="insufficient_information", structure="unknown")
    value["role_alignment"] = "unknown"
    assert trial.validate(value, entry) == value


@pytest.mark.parametrize("ids", [["B:E000"], ["A:missing"], [], "A:E000", [None]])
def test_validator_rejects_wrong_side_missing_or_invalid_citations(ids):
    entry = case()
    value = response(entry)
    value["evidence_ids"]["A"] = ids
    with pytest.raises(ValueError, match="ownership"):
        trial.validate(value, entry)


@pytest.mark.parametrize("field,value", [
    ("task_id", "wrong-task"), ("confidence", float("nan")),
    ("confidence", float("inf")), ("confidence", True),
    ("same_research_claim", "false"), ("edge_description", ""),
    ("role_alignment", " "), ("scope_limit", ""),
])
def test_validator_rejects_invalid_schema_and_unsupported_emptiness(field, value):
    entry = case()
    result = response(entry)
    result[field] = value
    with pytest.raises(ValueError):
        trial.validate(result, entry)


def test_no_relation_cannot_still_export_edge_description():
    entry = case()
    result = response(entry, semantic="different_meaning")
    result["edge_description"] = "Unjustified positive relation"
    with pytest.raises(ValueError, match="edge_description"):
        trial.validate(result, entry)


def test_accuracy_retains_invalid_and_missing_in_full_denominator():
    entries = [case(str(i)) for i in range(5)]
    refs = {e["task_id"]: {
        "cohort": "synthetic", "category": "contrast",
        "expected": {"structure_match": "same", "semantic_relation": "different_meaning",
                     "same_research_claim": False},
    } for e in entries}
    refs["4"]["cohort"] = "real_development"
    predictions = {
        "0": {"valid": True, "result": response(entries[0], semantic="different_meaning")},
        "1": {"valid": False, "result": None},
        # "2" deliberately missing.
        "3": {"valid": True, "result": response(entries[3], semantic="same_definition")},
        "4": {"valid": True, "result": response(entries[4], semantic="different_meaning")},
    }
    scores = trial.score(entries, predictions, refs)
    assert scores["all"] == scores["contrast"]
    assert scores["all"] == {
        "pairs": 4, "invalid_or_missing": 2, "all_axes_correct": 1,
        "structure_match_correct": 2, "semantic_relation_correct": 1,
        "same_research_claim_correct": 2, "unsupported_relation_fp": 1,
        "expected_no_relation": 4,
    }


def test_inference_identity_changes_with_evidence_and_ordered_image_hashes():
    entry = trial.make_entry(case(), "context_control")
    changed_prompt = dict(entry, prompt=entry["prompt"] + " extra context")
    changed_image = dict(entry, image_sha256=["b" * 64])
    assert trial.inference_key(entry) != trial.inference_key(changed_prompt)
    assert trial.inference_key(entry) != trial.inference_key(changed_image)
    two = dict(entry, image_sha256=["a" * 64, "b" * 64])
    reversed_two = dict(entry, image_sha256=list(reversed(two["image_sha256"])))
    assert trial.inference_key(two) != trial.inference_key(reversed_two)


def test_cache_resume_revalidates_response_ownership(tmp_path):
    entry = trial.make_entry(case(), "context_control")
    result = response(entry)
    checkpoint = prediction(entry, result=result)
    path = tmp_path / "cache.jsonl"
    path.write_text(json.dumps(checkpoint) + "\n")
    assert trial.load_cache(tmp_path, {"context_control": [entry]}) == {entry["inference_key"]: checkpoint}
    result["evidence_ids"]["B"] = ["A:E000"]
    path.write_text(json.dumps(checkpoint) + "\n")
    with pytest.raises(ValueError, match="ownership"):
        trial.load_cache(tmp_path, {"context_control": [entry]})


@pytest.mark.parametrize("damage", ["unknown_key", "wrong_task", "duplicate", "invalid_with_result"])
def test_cache_rejects_mismatched_or_ambiguous_checkpoint(tmp_path, damage):
    entry = trial.make_entry(case(), "context_control")
    checkpoint = prediction(entry, result=response(entry))
    records = [checkpoint]
    if damage == "unknown_key":
        checkpoint["inference_key"] = "foreign-run-key"
    elif damage == "wrong_task":
        checkpoint["task_id"] = "foreign-task"
    elif damage == "duplicate":
        records.append(checkpoint)
    else:
        checkpoint["valid"] = False
    (tmp_path / "cache.jsonl").write_text("".join(json.dumps(p) + "\n" for p in records))
    with pytest.raises(ValueError):
        trial.load_cache(tmp_path, {"context_control": [entry]})


def test_partial_publish_withholds_final_accuracy_and_complete_invalid_is_counted(tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "structural_hints", lambda formulas: {"status": "unknown"})
    entry = trial.make_entry(case(), "context_control")
    expected = {"structure_match": "same", "semantic_relation": "same_definition", "same_research_claim": False}
    trial.jsonl(tmp_path / "reference.jsonl", [{"task_id": entry["task_id"], "id": "fixture",
        "cohort": "synthetic", "category": "test", "expected": expected}])
    trial.write(tmp_path / "protocol.json", {"scope": "test-only"})
    treatment = trial.make_entry(case(), "structure_context")
    planned = {"context_control": [entry], "structure_context": [treatment]}
    partial = trial.publish(tmp_path, planned, {})
    assert partial["complete"] is False
    assert not (tmp_path / "metrics.json").exists()
    cache = {e["inference_key"]: prediction(e, valid=False) for e in (entry, treatment)}
    final = trial.publish(tmp_path, planned, cache)
    assert final["complete"] is True
    metrics = trial.read(tmp_path / "metrics.json")["synthetic"]["context_control"]["all"]
    assert metrics["pairs"] == metrics["invalid_or_missing"] == 1
    assert metrics["all_axes_correct"] == 0
    # A recovered/truncated checkpoint must not leave an earlier complete score visible.
    recovered_partial = trial.publish(tmp_path, planned, {})
    assert recovered_partial["complete"] is False
    assert not (tmp_path / "metrics.json").exists()
