from pathlib import Path
import copy
import hashlib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_routed_edge_context as experiment


def test_routing_ignores_prose_screenshot_and_recognizes_display_math():
    node = {"id": "n", "members": [{"kind": "atom", "type": "text", "text": "ordinary prose"}],
            "node_source_image_number": 1}
    assert experiment.modality(node, set()) == "prose"
    assert experiment.modality(node, {"n"}) == "formula"
    node["members"][0]["text"] = "$$ L = ||Y-Z||_1 $$"
    assert experiment.modality(node, set()) == "formula"
    node["members"].append({"kind": "visual", "type": "visual"})
    assert experiment.modality(node, set()) == "visual_table"


def test_context_rejects_other_article_ineligible_member_and_fabricated_quote():
    endpoint = {"id": "e", "document": "doc", "article_id": "article"}
    member = {"id": "m", "kind": "atom", "text": "A literal figure explanation."}
    source = {"id": "s", "document": "doc", "article_id": "article", "members": [member]}
    policies = {"s": {"members": [{"member_id": "m", "kind": "atom", "eligible": True}]}}
    context = {"source_node_id": "s", "member_id": "m", "quote": "literal figure", "route": "explicit_figure_reference"}
    result = experiment.grounded_context([context], endpoint, {"s": source}, policies)
    assert result[0]["char_start"] == 2
    assert member["text"][result[0]["char_start"]:result[0]["char_end"]] == context["quote"]
    source["article_id"] = "other"
    assert not experiment.grounded_context([context], endpoint, {"s": source}, policies)
    source["article_id"] = "article"
    policies["s"]["members"][0]["eligible"] = False
    assert not experiment.grounded_context([context], endpoint, {"s": source}, policies)
    policies["s"]["members"][0]["eligible"] = True
    context["quote"] = "invented dataset"
    assert not experiment.grounded_context([context], endpoint, {"s": source}, policies)


def test_readable_windows_recover_midword_cut_and_preserve_raw_sources():
    raw = "We model spatial dependencies. " * 35
    sha = hashlib.sha256(raw.encode()).hexdigest()
    node = {"id": "n", "members": [{"id": "m", "kind": "atom", "type": "text", "text": raw}]}
    task, lookups = {"task_id": "T"}, {}
    for side in ("A", "B"):
        task[side] = {"node_id": "n", "evidence": [], "node_source_image_number": 1}
        lookups[side] = {f"{side}:E{i:03d}": {"node_id": "n", "member_id": "m", "member_sha256": sha,
                        "kind": "ORIGINAL_TEXT", "quote": raw[lo:hi], "char_start": lo, "char_end": hi}
                        for i, (lo, hi) in enumerate([(0, 800), (680, len(raw))])}
    source = {"task": task, "lookups": lookups}
    snapshot = copy.deepcopy(source)
    rebuilt = experiment.readable_entry(source, {"n": node})
    assert source == snapshot
    for anchor in rebuilt["lookups"]["A"].values():
        assert anchor["quote"] == raw[anchor["char_start"]:anchor["char_end"]]
        assert anchor["quote"].endswith(".")


def test_metrics_keep_invalid_and_missing_in_positive_denominator():
    entries = [{"task": {"task_id": str(i)}, "routing": {"group": "prose"}} for i in range(4)]
    refs = [{"task_id": str(i), "cutoff_evaluable": True, "allowed_levels": [2 if i < 3 else 1]} for i in range(4)]
    preds = [{"task_id": "0", "valid": True, "result": {"decision": "NAVIGATION_LINK", "discovery_level": 2}},
             {"task_id": "1", "valid": False}, {"task_id": "3", "valid": False}]
    report = experiment.evaluate(entries, preds, refs)["all"]
    assert report["positive_total"] == 3
    assert report["positive_invalid"] == 1
    assert report["positive_missing"] == 1
    assert report["negative_invalid"] == 1
    assert report["useful_recall_all_positives"] == 1 / 3
    assert report["evidence_recall_all_positives"] == 0
    assert report.get("useful_tn", 0) == 0


def test_cache_key_changes_for_context_or_evidence_ownership():
    entry = {"prompt": "task and empty context", "image_sha256": ["a"], "lookups": {"A": {}, "B": {}}}
    original = experiment.inference_key(entry)
    assert experiment.inference_key(copy.deepcopy(entry)) == original
    entry["prompt"] += "new context"
    assert experiment.inference_key(entry) != original
