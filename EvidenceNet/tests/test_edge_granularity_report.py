"""CPU-only scoring and display checks for the frozen granularity experiment."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import report_edge_granularity as reporting


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def reference(tid, dataset="real", expected=True, source="old_development", strict=True):
    return {"task_id": tid, "suite_case_id": tid.upper(), "dataset": dataset,
            "source_suite": source, "cutoff_evaluable": expected is not None,
            "allowed_levels": [0, 1, 2, 3] if expected is None else [2, 3] if expected else [0, 1],
            "allowed_decisions": ["EVIDENCE_LINK", "NAVIGATION_LINK"] if expected else ["NO_LINK"],
            "decision_evaluable": strict if expected is not None else False}


def prediction(tid, decision, valid=True, **fields):
    return {"task_id": tid, "valid": valid, "result": {"decision": decision, **fields}}


def materialize(out):
    refs = [reference("r_pos", strict=False), reference("r_neg", expected=False, strict=False),
            reference("r_fpos", source="fresh_reviewed"),
            reference("r_u", expected=None, source="fresh_reviewed"),
            reference("s_pos", dataset="synthetic", source="synthetic_authored"),
            reference("s_neg", dataset="synthetic", expected=False, source="synthetic_authored"),
            reference("s_u", dataset="synthetic", expected=None, source="synthetic_authored")]
    nodes, pairs = [], []
    for ref in refs:
        tid = ref["task_id"]
        pair = {"dataset": ref["dataset"], "task": {"task_id": tid}}
        for side in ("A", "B"):
            nid = tid + "_" + side
            raw = "<script>not executable</script> The model did\nnot remove the signal."
            nodes.append({"id": nid, "document": "same" if tid == "r_neg" else "doc_" + nid,
                          "text": raw, "members": [{"id": "m", "text": raw}]})
            pair["task"][side] = {"node_id": nid}
        pairs.append(pair)
    (out / "protocol.json").write_text(json.dumps({"selection": {"budgets": {"real": 200, "synthetic": 100}}}), encoding="utf-8")
    write_jsonl(out / "references.jsonl", refs)
    write_jsonl(out / "nodes.jsonl", nodes)
    write_jsonl(out / "pairs.jsonl", pairs)
    return refs, nodes, pairs


def add_matching(out, dataset, arm, refs, pairs):
    selected_refs = [ref for ref in refs if ref["dataset"] == dataset]
    pair_by_id = {pair["task"]["task_id"]: pair for pair in pairs}
    views, rankings, matches, entries = [], [], [], []
    for rank, ref in enumerate(selected_refs, 1):
        tid = ref["task_id"]
        task = copy.deepcopy(pair_by_id[tid]["task"])
        candidate, span_match = {}, {"score": 0.87654}
        entry = {"task": task, "lookups": {"A": {}, "B": {}}, "images": []}
        for side in ("A", "B"):
            nid = task[side]["node_id"]
            vid = arm + "_" + nid
            eid = side + ":E000"
            quote = "did\nnot"
            views.append({"view_id": vid, "node_id": nid, "member_id": "m", "char_start": 4,
                          "char_end": 11, "quote": quote, "retrieval_text": "did not"})
            span_match[side + "_view_id"] = vid
            candidate[side + "_focus"] = "did not"
            candidate[side + "_evidence_id"] = eid
            entry["lookups"][side][eid] = {"quote": "Context: the model did\nnot remove the signal.",
                                                "node_id": nid, "member_id": "m"}
            task[side]["evidence"] = [{"evidence_id": eid, "text": "Actual normalized context for " + side}]
        task["candidate_matches"] = [candidate]
        row = {"source": task["A"]["node_id"], "target": task["B"]["node_id"],
               "score": 0.9 - rank / 100, "rank": rank, "selected": rank <= 2}
        rankings.append(row)
        matches.append({**row, "task_id": tid, "matches": [span_match]})
        entries.append(entry)
    # This additional ranked pair has no reference label. It is not a negative.
    rankings.append({"source": "unlabelled_a", "target": "unlabelled_b", "rank": 5,
                     "selected": True, "score": 0.8})
    write_jsonl(out / dataset / arm / "views.jsonl", views)
    write_jsonl(out / "matching" / dataset / arm / "pairs.jsonl", matches)
    write_jsonl(out / "matching" / dataset / arm / "rankings.jsonl", rankings)
    return entries


def test_pending_report_has_full_denominators_and_no_observed_failures(tmp_path):
    materialize(tmp_path)
    summary = reporting.report(tmp_path)
    assert summary["total_pairs"] == 7
    for arm in reporting.ARMS:
        real = summary["datasets"]["real"]["arms"][arm]
        synthetic = summary["datasets"]["synthetic"]["arms"][arm]
        assert real["verifier"]["total"] == 4
        assert real["verifier"]["scored_total"] == 3
        assert real["verifier"]["missing_total"] == 4
        assert real["verifier"]["scored_missing"] == 3
        assert real["verifier"]["strict_scored_total"] == 1
        assert real["verifier"]["strict_missing"] == 1
        assert not real["verifier"]["complete"]
        assert synthetic["verifier"]["scored_total"] == 2
        assert not real["retrieval"]["available"]
        assert real["retrieval"]["positive_total"] == 2
        assert real["retrieval"]["positive_missing"] == 2
        assert real["retrieval"]["positive_coverage_all_labelled_positives"] == 0
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert page.count('class="case"') == 7
    assert 'data-failure="true"' not in page
    assert page.count('data-pending="true"') == 7
    assert "所有 7 对已选样本在三组均强制送入 verifier" in page
    assert "模型不接收相似度分数" in page
    assert json.loads((tmp_path / "report.json").read_text())["total_pairs"] == 7


def test_invalid_missing_abstention_and_u_are_not_silently_removed():
    refs = [reference("positive"), reference("negative", expected=False), reference("missing"),
            reference("abstain", expected=False), reference("u", expected=None)]
    predictions = {"positive": prediction("positive", "NAVIGATION_LINK"),
                   "negative": prediction("negative", "NO_LINK", valid=False),
                   "abstain": prediction("abstain", "UNCERTAIN"),
                   "u": prediction("u", "NO_LINK")}
    score = reporting._score(refs, predictions)
    assert score["total"] == 5 and score["excluded_total"] == 1
    assert score["scored_total"] == score["strict_scored_total"] == 4
    assert score["broad_correct"] == score["strict_correct"] == 1
    assert score["broad_accuracy_all_scored"] == 0.25
    assert (score["scored_missing"], score["scored_invalid"], score["scored_abstention"]) == (1, 1, 1)
    assert (score["strict_missing"], score["strict_invalid"], score["strict_abstention"]) == (1, 1, 1)
    assert (score["tp"], score["tn"], score["fp"], score["fn"]) == (1, 0, 0, 0)
    assert score["processed_total"] == 4 and score["valid_total"] == 3


def test_broad_and_strict_decision_scores_are_separate():
    ref = reference("x")
    ref["allowed_decisions"] = ["EVIDENCE_LINK"]
    score = reporting._score([ref], {"x": prediction("x", "NAVIGATION_LINK")})
    assert score["broad_correct"] == 1
    assert score["strict_correct"] == 0
    ref["decision_evaluable"] = False
    score = reporting._score([ref], {"x": prediction("x", "NAVIGATION_LINK")})
    assert score["strict_scored_total"] == 0
    assert score["strict_accuracy_all_scored"] is None


def test_real_source_suites_and_document_scope_remain_separate(tmp_path):
    materialize(tmp_path)
    preds = [prediction("r_pos", "EVIDENCE_LINK"), prediction("r_neg", "NO_LINK"),
             prediction("r_fpos", "NO_LINK"), prediction("r_u", "EVIDENCE_LINK"),
             prediction("s_pos", "NO_LINK"), prediction("s_neg", "NO_LINK")]
    write_jsonl(tmp_path / "verifier" / "control" / "predictions.jsonl", preds)
    summary = reporting.report(tmp_path)
    real = summary["datasets"]["real"]
    assert real["arms"]["window96"]["verifier"]["broad_correct"] == 2
    old = real["by_source_suite"]["old_development"]["arms"]["window96"]["verifier"]
    fresh = real["by_source_suite"]["fresh_reviewed"]["arms"]["window96"]["verifier"]
    assert old["broad_correct"] == old["scored_total"] == 2
    assert old["strict_scored_total"] == 0
    assert fresh["broad_correct"] == 0 and fresh["scored_total"] == 1
    assert fresh["excluded_total"] == 1
    assert real["by_document_scope"]["same_document"]["arms"]["window96"]["verifier"]["total"] == 1
    assert real["by_document_scope"]["cross_document"]["arms"]["window96"]["verifier"]["total"] == 3
    synthetic = summary["datasets"]["synthetic"]["arms"]["window96"]["verifier"]
    assert synthetic["broad_correct"] == 1 and synthetic["scored_total"] == 2


def test_restricted_pool_retrieval_does_not_label_unknown_pairs_negative(tmp_path):
    refs, _, pairs = materialize(tmp_path)
    add_matching(tmp_path, "real", "physical_line", refs, pairs)
    summary = reporting.report(tmp_path)
    row = summary["datasets"]["real"]["arms"]["physical_line"]["retrieval"]
    assert row["fixed_candidate_budget"] == 200
    assert row["ranking_pool_pair_count"] == 5
    assert row["ranking_selected_pair_count"] == 3
    assert row["unlabelled_pool_pair_count"] == row["unlabelled_selected_pair_count"] == 1
    assert row["positive_total"] == 2 and row["positive_selected"] == 1
    assert row["positive_coverage_all_labelled_positives"] == 0.5
    assert row["negative_total"] == row["negative_selected"] == 1
    assert row["excluded_total"] == 1
    assert row["complete"] and row["available"]
    assert row["positive_not_selected"] == [{"task_id": "r_fpos", "suite_case_id": "R_FPOS", "rank": 3, "state": "outside_budget"}]
    # Group reports still describe the entire dataset ranking pool consistently.
    old = summary["datasets"]["real"]["by_source_suite"]["old_development"]["arms"]["physical_line"]["retrieval"]
    assert old["unlabelled_pool_pair_count"] == 1


def test_html_shows_raw_match_clean_focus_actual_context_and_escaped_predictions(tmp_path):
    refs, _, pairs = materialize(tmp_path)
    entries = add_matching(tmp_path, "real", "physical_line", refs, pairs)
    write_jsonl(tmp_path / "verifier" / "physical_line" / "inputs.jsonl", entries)
    write_jsonl(tmp_path / "verifier" / "physical_line" / "predictions.jsonl", [
        prediction("r_pos", "NO_LINK", reason='<img src=x onerror="alert(1)">',
                   limitation="<unsafe limitation>", matched_claim="does not remove")])
    reporting.report(tmp_path)
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '<script>not executable</script>' not in page
    assert '&lt;script&gt;not executable&lt;/script&gt;' in page
    assert '<img src=x onerror=' not in page
    assert '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;' in page
    assert '&lt;unsafe limitation&gt;' in page
    assert '<pre>did\nnot</pre>' in page
    assert '清理后匹配文本</summary><pre>did not</pre>' in page
    assert 'm [4:11]' in page
    assert 'cosine 0.87654（未提供给模型）' in page
    assert 'Context: the model did\nnot remove the signal.' in page
    assert '实际送入模型的上下文文本</summary><pre>Actual normalized context for A</pre>' in page
    assert 'data-failure="true"' in page
    assert 'data-retrieval-miss="true"' in page
    assert '对应主张' in page and '理由' in page and '限制' in page


def test_input_and_prediction_progress_are_distinct(tmp_path):
    refs, _, pairs = materialize(tmp_path)
    entries = add_matching(tmp_path, "synthetic", "sentence", refs, pairs)
    write_jsonl(tmp_path / "verifier" / "sentence" / "inputs.jsonl", entries)
    summary = reporting.report(tmp_path)
    row = summary["datasets"]["synthetic"]["arms"]["sentence"]
    assert row["verifier_input_count"] == 3
    assert row["verifier"]["processed_total"] == 0
    assert row["view_count"] == 6 and row["view_node_count"] == 6
    assert row["retrieval"]["matching_available_total"] == 3


def test_duplicate_or_unknown_prediction_ids_fail_closed(tmp_path):
    materialize(tmp_path)
    location = tmp_path / "verifier" / "control" / "predictions.jsonl"
    write_jsonl(location, [prediction("not_frozen", "NO_LINK")])
    with pytest.raises(ValueError, match="Unexpected verifier task ID"):
        reporting.report(tmp_path)
    write_jsonl(location, [prediction("r_pos", "NO_LINK"), prediction("r_pos", "NO_LINK")])
    with pytest.raises(ValueError, match="duplicate task_id"):
        reporting.report(tmp_path)


def test_mixed_cutoff_reference_is_not_guessed():
    ref = reference("x")
    ref["allowed_levels"] = [1, 2]
    with pytest.raises(ValueError, match="crosses broad cutoff"):
        reporting._score([ref], {})


def test_matching_missing_records_keep_positive_denominator(tmp_path):
    refs, _, pairs = materialize(tmp_path)
    add_matching(tmp_path, "real", "window96", refs, pairs)
    path = tmp_path / "matching" / "real" / "window96" / "pairs.jsonl"
    rows = reporting._rows(path)
    write_jsonl(path, [row for row in rows if row["task_id"] != "r_pos"])
    summary = reporting.report(tmp_path)
    row = summary["datasets"]["real"]["arms"]["window96"]["retrieval"]
    assert row["positive_total"] == 2 and row["positive_missing"] == 1
    assert row["positive_coverage_all_labelled_positives"] == 0
    assert row["matching_missing_total"] == 1 and not row["complete"]
