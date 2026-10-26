import copy
import hashlib
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_edge_granularity as suite


def data():
    nodes, pairs, refs, allowed = {}, [], [], {}
    for dataset in ("real", "synthetic"):
        allowed[dataset] = set()
        task = {"task_id": dataset + "_T"}
        for side in ("A", "B"):
            nid = dataset + side
            raw = "Preface. The model did\nnot remove information. Another sentence. Last sentence."
            nodes[nid] = {"id": nid, "document": dataset + side,
                          "members": [{"id": "m", "kind": "atom", "type": "text", "text": raw}]}
            allowed[dataset].add((nid, "m"))
            task[side] = {"node_id": nid, "evidence": [{"text": "WHOLE_NODE_MUST_NOT_BE_COPIED"}],
                          "node_source_image_number": 1}
        pairs.append({"dataset": dataset, "task": task})
        refs.append({"task_id": task["task_id"], "suite_case_id": dataset + "case", "dataset": dataset,
                     "source_suite": "old_development" if dataset == "real" else "synthetic_authored",
                     "allowed_levels": [2], "cutoff_evaluable": True, "decision_evaluable": False})
    return nodes, pairs, refs, allowed, {}


def test_ranking_fixed_budget_and_stable_ties_has_no_label_input():
    views = [{"node_id": n, "view_id": n + str(i)} for n, i in [("A", 0), ("A", 1), ("B", 0), ("C", 0)]]
    vectors = {v["view_id"]: np.array([1.0, 0]) for v in views}
    ranked = suite.rank_pairs(list(reversed(views)), vectors, 2)
    assert [(r["source"], r["target"]) for r in ranked] == [("A", "B"), ("A", "C"), ("B", "C")]
    assert [r["selected"] for r in ranked] == [True, True, False]
    assert [r["rank"] for r in ranked] == [1, 2, 3]
    vectors["A0"] = np.array([0, 1.0])
    assert suite.rank_pairs(views, vectors, 2)[0]["score"] == 1.0  # maximum, not average


def test_matching_prompt_uses_only_selected_original_context_and_no_scores():
    nodes, pairs, _, allowed, _ = data()
    views = suite.granular.make_views(nodes, allowed["real"], "physical_line")
    chosen = {s: next(v for v in views if v["node_id"] == "real" + s and v["char_start"] == 0) for s in ("A", "B")}
    matches = [{"A_view_id": chosen["A"]["view_id"], "B_view_id": chosen["B"]["view_id"], "score": 0.987654321}]
    original = copy.deepcopy((pairs, nodes))
    entry = suite.matched_entry(pairs[0], matches, {v["view_id"]: v for v in views}, nodes)
    assert original == (pairs, nodes)
    assert entry["images"] == entry["image_sha256"] == []
    assert "WHOLE_NODE_MUST_NOT_BE_COPIED" not in entry["prompt"]
    assert "node_source_image_number" not in entry["prompt"]
    assert "0.987654321" not in entry["prompt"]
    assert "physical_line" not in entry["prompt"]
    assert "candidate_matches" in entry["prompt"]
    assert "Last sentence." not in entry["prompt"]
    assert "did not" in entry["task"]["A"]["evidence"][0]["text"]
    assert "did\nnot" in entry["lookups"]["A"]["A:E000"]["quote"]
    changed_pair = copy.deepcopy(pairs[0])
    changed_pair["gold"] = "NO_LINK"
    assert suite.matched_entry(changed_pair, matches, {v["view_id"]: v for v in views}, nodes) == entry
    bad = copy.deepcopy(matches)
    bad[0]["A_view_id"] = chosen["B"]["view_id"]
    with pytest.raises(ValueError, match="ownership"):
        suite.matched_entry(pairs[0], bad, {v["view_id"]: v for v in views}, nodes)


@pytest.mark.parametrize("bad", [np.array([[0., 0.]]), np.array([[np.nan, 1.]]), np.array([1., 0.]), np.ones((2, 2))])
def test_invalid_vectors_fail_closed(bad):
    with pytest.raises(ValueError):
        suite.validate_vectors(bad, 1)


def test_prepare_embed_match_frozen_stages_and_reuse_without_gpu(tmp_path, monkeypatch):
    snapshot = data()
    monkeypatch.setattr(suite, "snapshot_data", lambda _: copy.deepcopy(snapshot))
    monkeypatch.setattr(suite, "encoder_identity", lambda _: {"test_only": True})
    # Integration fixtures freeze artifacts; actual-code hashing is checked in the real prepare.
    monkeypatch.setattr(suite, "code_paths", lambda: [])
    model = tmp_path / "model"
    suite.write(model / "config.json", {"test_only": True})
    out = tmp_path / "output"
    suite.prepare(out, tmp_path, model)
    assert not (out / "verifier").exists()
    assert len(suite.rows(out / "references.jsonl")) == 2
    assert suite.read(out / "report.json")["datasets"]["real"]
    with pytest.raises(ValueError, match="Fresh"):
        suite.prepare(out, tmp_path, model)
    monkeypatch.setattr(suite.encoders, "load_tokenizer", lambda *args: lambda text, **kwargs: {"input_ids": [1, 2]})
    calls = []
    def embed(texts, *args):
        calls.append(texts)
        return np.tile(np.array([[1., 0.]]), (len(texts), 1)), {"test_only": True}
    monkeypatch.setattr(suite.encoders, "embed", embed)
    suite.embed(out, tmp_path)
    suite.embed(out, tmp_path)
    assert len(calls) == 1
    suite.match(out, model)
    first = suite.sha(out / "matching_manifest.json")
    suite.match(out, model)
    assert suite.sha(out / "matching_manifest.json") == first
    suite.verify(out, model, tmp_path)
    for arm in suite.VERIFIER_ARMS:
        entries = suite.rows(out / "verifier" / arm / "inputs.jsonl")
        assert [e["task"]["task_id"] for e in entries] == ["real_T", "synthetic_T"]
        assert all(not e["images"] and len(e["task"]["candidate_matches"]) <= 2 for e in entries)
    suite.jsonl(out / "verifier/control/inputs.jsonl", [])
    with pytest.raises(ValueError, match="changed input"):
        suite.verify(out, model)


def test_snapshot_preserves_original_anchors_and_rejects_corruption(tmp_path, monkeypatch):
    nodes, pairs, refs, _, _ = data()
    monkeypatch.setattr(suite, "ROOT", tmp_path)
    sources = {}
    for dataset in ("real", "synthetic"):
        directory = tmp_path / dataset
        sources[dataset] = directory
        pair = next(p for p in pairs if p["dataset"] == dataset)
        entry = {"task": pair["task"], "images": [], "image_sha256": [], "lookups": {}}
        for side in ("A", "B"):
            nid = pair["task"][side]["node_id"]
            raw = nodes[nid]["members"][0]["text"]
            entry["lookups"][side] = {side + ":E000": {"kind": "ORIGINAL_TEXT", "node_id": nid,
                "member_id": "m", "member_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                "char_start": 0, "char_end": len(raw), "quote": raw}}
        suite.jsonl(directory / "nodes.jsonl", [n for n in nodes.values() if n["id"].startswith(dataset)])
        suite.jsonl(directory / "reference.jsonl", [r for r in refs if r["dataset"] == dataset])
        suite.jsonl(directory / "control/inputs.jsonl", [entry])
        suite.write(directory / "manifest.json", {"files": {name: suite.sha(directory / name)
                    for name in ("nodes.jsonl", "reference.jsonl", "control/inputs.jsonl")}})
    actual = suite.snapshot_data(sources)
    assert actual[0] == nodes and len(actual[1]) == 2
    assert all(r["document_scope"] == "cross_document" for r in actual[2])
    suite.jsonl(sources["real"] / "nodes.jsonl", [])
    with pytest.raises(ValueError, match="Source snapshot changed"):
        suite.snapshot_data(sources)
