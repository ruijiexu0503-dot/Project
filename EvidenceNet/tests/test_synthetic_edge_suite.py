import copy
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_synthetic_edge_suite as experiment
from run_node_context_edges import jsonl, write


def materialize(out, specs=None):
    specs = experiment.SPECS if specs is None else specs
    nodes, refs, planned = experiment.build(specs)
    write(out / "specs.json", specs)
    jsonl(out / "nodes.jsonl", nodes)
    jsonl(out / "reference.jsonl", refs)
    for arm, entries in planned.items():
        jsonl(out / arm / "inputs.jsonl", entries)
    return nodes, refs, planned


def test_balanced_synthetic_dataset_is_genuinely_text_only(tmp_path):
    materialize(tmp_path)
    audit = experiment.check_inputs(tmp_path)
    assert audit["pairs"] == 32
    assert audit["labels"] == {"NO_LINK": 14, "RELATED": 16, "U": 2}
    assert audit["images"] == 0
    assert 64 <= audit["unique_inferences"] <= 128


def test_authored_sources_do_not_mutate_and_gold_cannot_change_prompts():
    snapshot = copy.deepcopy(experiment.SPECS)
    nodes, refs, planned = experiment.build()
    assert experiment.SPECS == snapshot
    relabelled = copy.deepcopy(snapshot)
    for spec in relabelled:
        spec["expected"] = "U"
        spec["reason"] = "Unique hidden annotation only."
        spec["family"] = "not visible to model"
    new_nodes, new_refs, new_planned = experiment.build(relabelled)
    assert new_nodes == nodes and new_planned == planned
    assert new_refs != refs


def test_swap_changes_side_ownership_but_not_the_pair_identity():
    _, _, planned = experiment.build()
    for normal, swapped in zip(planned["control"], planned["swapped"]):
        assert normal["task"]["task_id"] == swapped["task"]["task_id"]
        assert normal["inference_key"] != swapped["inference_key"]
        for left, right in (("A", "B"), ("B", "A")):
            assert normal["task"][left]["node_id"] == swapped["task"][right]["node_id"]
            assert list(normal["lookups"][left].values()) == list(swapped["lookups"][right].values())
            assert all(eid.startswith(right + ":") for eid in swapped["lookups"][right])


def test_readable_preserves_crlf_and_negation_in_original_anchors():
    _, _, planned = experiment.build()
    wrapped = planned["text_readable"][26]
    raw_anchor = next(iter(wrapped["lookups"]["B"].values()))
    assert "\r\n" in raw_anchor["quote"]
    assert "\r\n" not in wrapped["task"]["B"]["evidence"][0]["text"]
    negative = planned["text_readable"][29]
    assert "did not reduce" in negative["task"]["A"]["evidence"][0]["text"]
    assert "did\nnot reduce" in next(iter(negative["lookups"]["A"].values()))["quote"]


def test_ambiguous_labels_are_unscored_and_related_accepts_e_or_n():
    _, refs, _ = experiment.build()
    for ref in refs:
        if ref["annotation_label"] == "U":
            assert not ref["cutoff_evaluable"] and not ref["decision_evaluable"]
        elif ref["annotation_label"] == "RELATED":
            assert set(ref["allowed_decisions"]) == {"EVIDENCE_LINK", "NAVIGATION_LINK"}
        else:
            assert ref["allowed_decisions"] == ["NO_LINK"]


def test_minimal_pairs_reuse_source_node_and_long_case_really_has_multiple_windows():
    _, _, planned = experiment.build()
    entries = planned["control"]
    assert entries[0]["task"]["A"]["node_id"] == entries[1]["task"]["A"]["node_id"]
    assert entries[24]["task"]["A"]["node_id"] == entries[25]["task"]["A"]["node_id"]
    assert len(entries[24]["task"]["A"]["evidence"]) > 1
    assert len(entries[24]["task"]["B"]["evidence"]) > 1


def test_duplicate_pairs_and_edited_anchor_fail(tmp_path):
    with pytest.raises(ValueError, match="Duplicate"):
        experiment.build([experiment.SPECS[0], experiment.SPECS[0]])
    _, _, planned = materialize(tmp_path)
    entry = planned["control"][0]
    next(iter(entry["lookups"]["A"].values()))["quote"] = "invented"
    entry["inference_key"] = experiment.routed.inference_key(entry)
    jsonl(tmp_path / "control/inputs.jsonl", planned["control"])
    with pytest.raises(AssertionError):
        experiment.check_inputs(tmp_path)


def test_frozen_code_and_inputs_block_mutation(tmp_path):
    materialize(tmp_path)
    write(tmp_path / "manifest.json", {"code": {}, "files": {
        "specs.json": hashlib.sha256((tmp_path / "specs.json").read_bytes()).hexdigest()}})
    experiment.routed.verify(tmp_path)
    write(tmp_path / "specs.json", [])
    with pytest.raises(ValueError, match="changed input"):
        experiment.routed.verify(tmp_path)


def test_refuse_to_overwrite_existing_suite(tmp_path):
    with pytest.raises(ValueError, match="Fresh suite"):
        experiment.prepare(tmp_path, tmp_path / "out", tmp_path)


def test_run_restores_shared_arms_if_executor_fails(tmp_path, monkeypatch):
    materialize(tmp_path)
    original_arms = experiment.routed.ARMS
    def fail(*args):
        assert experiment.routed.ARMS == experiment.ARMS
        raise RuntimeError("test failure")
    monkeypatch.setattr(experiment.routed, "run", fail)
    with pytest.raises(RuntimeError, match="test failure"):
        experiment.run(tmp_path, tmp_path, tmp_path, 1)
    assert experiment.routed.ARMS == original_arms


def prediction(tid, decision, **extra):
    return {"task_id": tid, "valid": True, "result": {"decision": decision, **extra}}


def test_report_missing_invalid_uncertain_and_U_denominators(tmp_path):
    from report_synthetic_edge_suite import report
    _, refs, _ = materialize(tmp_path)
    # S001 negative correct; S002 positive invalid; S003 negative abstention;
    # S004 positive correct navigation; S017 U excluded even if invalid.
    jsonl(tmp_path / "control/predictions.jsonl", [
        prediction(refs[0]["task_id"], "NO_LINK"),
        {"task_id": refs[1]["task_id"], "valid": False},
        prediction(refs[2]["task_id"], "UNCERTAIN"),
        prediction(refs[3]["task_id"], "NAVIGATION_LINK"),
        {"task_id": refs[16]["task_id"], "valid": False},
    ])
    scores = report(tmp_path)
    assert not scores["complete"]
    stat = scores["arms"]["control"]["all"]
    assert stat["scored_total"] == 30 and stat["excluded_total"] == 2
    assert stat["tp"] == 1 and stat["tn"] == 1
    assert stat["scored_invalid"] == 1 and stat["invalid_total"] == 2
    assert stat["scored_missing"] == 26 and stat["scored_abstention"] == 1
    assert stat["broad_accuracy_all_scored"] == 2 / 30
    assert stat["allowed_decision_agreement"] == 2 / 30
    assert scores["symmetry"]["all"]["valid_paired"] == 0
    assert "待运行" in (tmp_path / "index.html").read_text()


def test_report_symmetry_does_not_treat_e_vs_n_as_broad_disagreement(tmp_path):
    from report_synthetic_edge_suite import report
    _, refs, _ = materialize(tmp_path)
    tid = refs[1]["task_id"]
    jsonl(tmp_path / "control/predictions.jsonl", [prediction(tid, "EVIDENCE_LINK", reason="<script>alert(1)</script>")])
    jsonl(tmp_path / "swapped/predictions.jsonl", [prediction(tid, "NAVIGATION_LINK")])
    stat = report(tmp_path)["symmetry"]["all"]
    assert stat["binary_paired"] == 1 and stat["broad_agreement"] == 1
    assert stat["exact_decision_agreement"] == 0
    html = (tmp_path / "index.html").read_text()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_report_rejects_unknown_prediction_and_reference_conflict(tmp_path):
    from report_synthetic_edge_suite import report
    _, refs, _ = materialize(tmp_path)
    jsonl(tmp_path / "control/predictions.jsonl", [prediction("unknown", "NO_LINK")])
    with pytest.raises(ValueError, match="Unknown task"):
        report(tmp_path)
    jsonl(tmp_path / "control/predictions.jsonl", [])
    refs[0]["allowed_decisions"] = ["EVIDENCE_LINK"]
    jsonl(tmp_path / "reference.jsonl", refs)
    with pytest.raises(ValueError, match="conflicts"):
        report(tmp_path)
