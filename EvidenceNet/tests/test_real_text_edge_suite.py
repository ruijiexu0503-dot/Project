import copy
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_real_text_edge_suite as suite
import report_real_text_edge_suite as reporting
from run_node_context_edges import jsonl


def make_source(tid):
    nodes = {}
    entry = {"task": {"task_id": tid}, "lookups": {}, "images": ["old-a.png", "old-b.png"],
             "routing": {"A": "prose", "B": "prose", "group": "prose"}}
    for side in ("A", "B"):
        raw = "The NERIS model does\nnot remove the input signal."
        nid = tid + side
        nodes[nid] = {"id": nid, "document": "doc_" + nid,
                      "members": [{"id": "member", "kind": "atom", "type": "text", "text": raw}]}
        eid = side + ":E000"
        entry["task"][side] = {"node_id": nid, "node_source_image_number": 1 if side == "A" else 2,
                              "evidence": [{"evidence_id": eid, "kind": "ORIGINAL_TEXT", "text": raw, "image_number": None}]}
        entry["lookups"][side] = {eid: {"node_id": nid, "member_id": "member", "kind": "ORIGINAL_TEXT",
            "char_start": 0, "char_end": len(raw), "quote": raw,
            "member_sha256": hashlib.sha256(raw.encode()).hexdigest()}}
    return entry, nodes


def fixture_data():
    originals, nodes = [], {}
    for tid in ("old_positive", "old_negative", "fresh_positive", "fresh_uncertain", "unlabelled", "empty"):
        entry, members = make_source(tid)
        originals.append(entry)
        nodes.update(members)
    originals[-1]["task"]["A"]["evidence"] = []
    originals[-1]["lookups"]["A"] = {}
    old = [{"task_id": tid, "suite_case_id": label, "allowed_levels": levels, "cutoff_evaluable": True}
           for tid, label, levels in [("old_positive", "U03", [2]), ("old_negative", "N01", [0]), ("empty", "N13", [0])]]
    fresh = [{"task_id": "fresh_positive", "suite_case_id": "F001", "allowed_levels": [2, 3],
              "cutoff_evaluable": True, "allowed_decisions": ["EVIDENCE_LINK"], "decision_evaluable": True, "annotation_label": "E"},
             {"task_id": "fresh_uncertain", "suite_case_id": "F009", "allowed_levels": [0, 1, 2, 3],
              "cutoff_evaluable": False, "allowed_decisions": ["EVIDENCE_LINK", "NAVIGATION_LINK", "NO_LINK", "UNCERTAIN"],
              "decision_evaluable": False, "annotation_label": "U"}]
    sources = [("old_development", originals[:2] + originals[4:], old),
               ("fresh_reviewed", originals[2:4], fresh)]
    return sources, nodes


def materialize(out):
    sources, nodes = fixture_data()
    selected, refs, planned, excluded, images = suite.build(sources, nodes)
    jsonl(out / "nodes.jsonl", selected)
    jsonl(out / "reference.jsonl", refs)
    for arm, entries in planned.items():
        jsonl(out / arm / "inputs.jsonl", entries)
    return refs, planned, excluded, images


def test_only_annotated_nonempty_real_prose_pairs_are_selected(tmp_path):
    refs, planned, excluded, images = materialize(tmp_path)
    assert len(refs) == 4
    assert excluded == {"old_development_unlabelled": 1, "old_development_empty_original_text_N13": 1}
    assert images == {"2": 4}
    audit = suite.check_inputs(tmp_path)
    assert audit["broad_scored"] == 3 and audit["strict_decision_scored"] == 1
    assert audit["boundary_unscored"] == 1 and audit["images"] == 0


def test_no_source_mutation_or_gold_leak():
    sources, nodes = fixture_data()
    snapshot = copy.deepcopy((sources, nodes))
    _, _, planned, _, _ = suite.build(sources, nodes)
    assert (sources, nodes) == snapshot
    changed = copy.deepcopy(sources)
    for _, _, refs in changed:
        for ref in refs:
            ref["note"] = "a hidden changed label rationale"
            ref["allowed_levels"] = [0]
    _, _, replanned, _, _ = suite.build(changed, nodes)
    assert replanned == planned


def test_old_u_prefix_is_not_uncertain_and_not_strict_evidence_gold(tmp_path):
    refs, *_ = materialize(tmp_path)
    ref = next(r for r in refs if r["suite_case_id"] == "OLD_U03")
    assert ref["annotation_label"] == "RELATED" and ref["cutoff_evaluable"]
    assert set(ref["allowed_decisions"]) == {"EVIDENCE_LINK", "NAVIGATION_LINK"}
    assert not ref["decision_evaluable"]
    uncertain = next(r for r in refs if r["suite_case_id"] == "FRESH_F009")
    assert uncertain["annotation_label"] == "U" and not uncertain["cutoff_evaluable"]


def test_remove_screenshot_pointers_without_altering_text_and_swap_ownership():
    original, _ = make_source("T")
    snapshot = copy.deepcopy(original)
    stripped = suite.strip_images(original)
    swapped = suite.swap(stripped)
    assert original == snapshot
    assert stripped["images"] == []
    assert "node_source_image_number" not in stripped["task"]["A"]
    assert swapped["task"]["task_id"] == stripped["task"]["task_id"]
    assert swapped["task"]["B"]["node_id"] == stripped["task"]["A"]["node_id"]
    assert swapped["lookups"]["B"]["B:E000"] == stripped["lookups"]["A"]["A:E000"]
    assert suite.swap(swapped) == stripped


def test_nontext_anchor_rejected():
    original, _ = make_source("T")
    original["lookups"]["A"]["A:E000"]["kind"] = "ORIGINAL_CROP"
    with pytest.raises(ValueError, match="original text"):
        suite.strip_images(original)


def test_readable_keeps_negation_raw_anchors_and_scope_isolated(tmp_path):
    _, planned, *_ = materialize(tmp_path)
    c, s, r = [planned[a][0] for a in ("control", "text_scope", "text_readable")]
    assert s["prompt"] == c["prompt"] + suite.routed.SCOPE
    assert c["lookups"] == s["lookups"]
    assert "does not" in r["task"]["A"]["evidence"][0]["text"]
    assert "does\nnot" in r["lookups"]["A"]["A:E000"]["quote"]


def test_duplicate_pair_across_sources_rejected():
    sources, nodes = fixture_data()
    with pytest.raises(ValueError, match="overlaps"):
        suite.build([sources[0], sources[0]], nodes)


def test_report_full_denominators_and_old_no_strict_gold(tmp_path):
    refs, *_ = materialize(tmp_path)
    jsonl(tmp_path / "control/predictions.jsonl", [
        {"task_id": "old_positive", "valid": True, "result": {"decision": "NAVIGATION_LINK"}},
        {"task_id": "old_negative", "valid": False},
        {"task_id": "fresh_uncertain", "valid": True, "result": {"decision": "EVIDENCE_LINK"}},
    ])
    scores = reporting.report(tmp_path)
    stat = scores["groups"]["all"]["control"]
    assert stat["scored_total"] == 3 and stat["broad_correct"] == 1
    assert stat["scored_invalid"] == 1 and stat["scored_missing"] == 1
    assert stat["broad_accuracy_all_scored"] == 1 / 3
    assert stat["strict_scored_total"] == 1 and stat["strict_missing"] == 1
    assert scores["groups"]["old_development"]["control"]["strict_scored_total"] == 0
    assert stat["annotation_uncertain_total"] == 1


def test_report_uncertain_output_not_treated_as_correct_negative():
    ref = {"task_id": "T", "suite_case_id": "X", "source_suite": "old", "allowed_levels": [0], "cutoff_evaluable": True}
    stat = reporting._score([ref], {"T": {"valid": True, "result": {"decision": "UNCERTAIN"}}})
    assert stat["tn"] == 0 and stat["scored_abstention"] == 1 and stat["broad_accuracy_all_scored"] == 0


def test_report_escapes_output_and_swapped_e_n_are_broad_consistent(tmp_path):
    materialize(tmp_path)
    for arm, decision in (("control", "EVIDENCE_LINK"), ("swapped", "NAVIGATION_LINK")):
        jsonl(tmp_path / arm / "predictions.jsonl", [{"task_id": "old_positive", "valid": True,
              "result": {"decision": decision, "reason": "<script>alert(1)</script>"}}])
    stat = reporting.report(tmp_path)["swap_consistency"]["all"]
    assert stat["broad_agreement_both_binary"] == 1 and stat["exact_agreement_both_valid"] == 0
    html = (tmp_path / "index.html").read_text()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_run_restores_shared_arms_and_prepare_refuses_overwrite(tmp_path, monkeypatch):
    materialize(tmp_path)
    old = suite.routed.ARMS
    def fail(*args):
        assert suite.routed.ARMS == suite.ARMS
        raise RuntimeError("fixture")
    monkeypatch.setattr(suite.routed, "run", fail)
    with pytest.raises(RuntimeError, match="fixture"):
        suite.run(tmp_path, tmp_path, tmp_path, 1)
    assert suite.routed.ARMS == old
    with pytest.raises(ValueError, match="Fresh output"):
        suite.prepare(tmp_path, tmp_path)
