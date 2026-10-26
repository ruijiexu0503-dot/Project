#!/usr/bin/env python3
"""Report the frozen span-granularity experiment, including partially run jobs.

Retrieval is measured within the restricted endpoint pool, not the whole corpus.
Only explicit reference labels are scored; other ranked pairs are not negatives.
Verifier scores include every frozen labelled pair, even if retrieval missed it.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


ARMS = ("window96", "physical_line", "sentence")
VERIFIER_ARMS = {"window96": "control", "physical_line": "physical_line", "sentence": "sentence"}
LABELS = {"window96": "96 词滑窗", "physical_line": "物理逐行", "sentence": "完整句"}
LINKS = {"EVIDENCE_LINK", "NAVIGATION_LINK"}
DECISIONS = LINKS | {"NO_LINK", "UNCERTAIN"}


def _rows(path: Path, optional: bool = False) -> List[dict]:
    if optional and not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError("Expected object at %s:%s" % (path, number))
        rows.append(row)
    return rows


def _index(rows: List[dict], field: str, description: str) -> Dict[str, dict]:
    result = {}
    for row in rows:
        key = row.get(field)
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Missing or duplicate %s in %s: %r" % (field, description, key))
        result[key] = row
    return result


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return numerator / denominator if denominator else None


def _expected(ref: dict) -> Optional[bool]:
    if not ref.get("cutoff_evaluable", False):
        return None
    levels = set(ref.get("allowed_levels", []))
    if levels and levels <= {2, 3}:
        return True
    if levels and levels <= {0, 1}:
        return False
    raise ValueError("Scored reference crosses broad cutoff: " + ref["task_id"])


def _state(prediction: Optional[dict]) -> Tuple[str, Optional[str]]:
    if prediction is None:
        return "missing", None
    result = prediction.get("result")
    if prediction.get("valid") is not True or not isinstance(result, dict):
        return "invalid", None
    decision = result.get("decision")
    if decision not in DECISIONS:
        return "invalid", None
    return ("abstention" if decision == "UNCERTAIN" else "binary"), decision


def _score(refs: List[dict], predictions: Dict[str, dict]) -> dict:
    names = ("total", "processed_total", "valid_total", "missing_total", "invalid_total",
             "abstention_total", "scored_total", "excluded_total", "positive_total", "negative_total",
             "scored_missing", "scored_invalid", "scored_abstention", "tp", "tn", "fp", "fn",
             "strict_scored_total", "strict_correct", "strict_missing", "strict_invalid", "strict_abstention")
    counts = Counter({name: 0 for name in names})
    decisions, failures = Counter(), []
    for ref in refs:
        prediction = predictions.get(ref["task_id"])
        state, decision = _state(prediction)
        expected = _expected(ref)
        counts["total"] += 1
        counts["processed_total"] += prediction is not None
        counts["valid_total"] += state in {"binary", "abstention"}
        if state != "binary":
            counts[state + "_total"] += 1
        if decision:
            decisions[decision] += 1
        broad_correct, strict_correct = None, None
        if expected is None:
            counts["excluded_total"] += 1
        else:
            counts["scored_total"] += 1
            counts["positive_total" if expected else "negative_total"] += 1
            broad_correct = state == "binary" and (decision in LINKS) == expected
            if state != "binary":
                counts["scored_" + state] += 1
            else:
                linked = decision in LINKS
                counts[("tp" if linked else "fn") if expected else ("fp" if linked else "tn")] += 1
        if ref.get("decision_evaluable", False):
            allowed = ref.get("allowed_decisions", [])
            if not allowed:
                raise ValueError("Missing strict reference: " + ref["task_id"])
            counts["strict_scored_total"] += 1
            strict_correct = state in {"binary", "abstention"} and decision in allowed
            counts["strict_correct"] += strict_correct
            if state != "binary":
                counts["strict_" + state] += 1
        if broad_correct is False or strict_correct is False:
            failures.append({"task_id": ref["task_id"], "suite_case_id": ref.get("suite_case_id"),
                             "state": state, "decision": decision, "broad_correct": broad_correct,
                             "strict_correct": strict_correct})
    return {**dict(counts), "complete": counts["processed_total"] == counts["total"],
            "broad_correct": counts["tp"] + counts["tn"],
            "broad_accuracy_all_scored": _ratio(counts["tp"] + counts["tn"], counts["scored_total"]),
            "positive_recall_all_expected": _ratio(counts["tp"], counts["positive_total"]),
            "negative_false_link_rate": _ratio(counts["fp"], counts["negative_total"]),
            "strict_accuracy_all_scored": _ratio(counts["strict_correct"], counts["strict_scored_total"]),
            "decision_counts": dict(decisions), "failures": failures}


def _endpoint(pair: dict, side: str) -> Optional[str]:
    task = pair.get("task", pair)
    endpoint = task.get(side, {})
    if isinstance(endpoint, str):
        return endpoint
    return endpoint.get("node_id") or pair.get("source" if side == "A" else "target")


def _pair_key(source: Optional[str], target: Optional[str]) -> Optional[Tuple[str, str]]:
    if not source or not target:
        return None
    return tuple(sorted((source, target)))


def _document_scope(ref: dict, pair: dict, nodes: Dict[str, dict]) -> str:
    if ref.get("document_scope"):
        return ref["document_scope"]
    left, right = (nodes.get(_endpoint(pair, side), {}) for side in ("A", "B"))
    left_doc, right_doc = left.get("document"), right.get("document")
    if not left_doc or not right_doc:
        return "unknown_document"
    return "same_document" if left_doc == right_doc else "cross_document"


def _retrieval(refs: List[dict], matches: Dict[str, dict], rankings: List[dict],
               pairs: Dict[str, dict], budget: int, available: bool,
               pool_refs: Optional[List[dict]] = None) -> dict:
    counts = Counter({name: 0 for name in ("labelled_total", "matching_available_total", "matching_missing_total",
                     "positive_total", "positive_selected", "positive_missing", "negative_total",
                     "negative_selected", "negative_missing", "excluded_total", "excluded_selected")})
    failures = []
    for ref in refs:
        counts["labelled_total"] += 1
        match = matches.get(ref["task_id"])
        counts["matching_available_total" if match is not None else "matching_missing_total"] += 1
        expected = _expected(ref)
        category = "excluded" if expected is None else "positive" if expected else "negative"
        counts[category + "_total"] += 1
        selected = match is not None and match.get("selected") is True
        counts[category + "_selected"] += selected
        if expected is not None and match is None:
            counts[category + "_missing"] += 1
        if expected is True and not selected:
            failures.append({"task_id": ref["task_id"], "suite_case_id": ref.get("suite_case_id"),
                             "rank": match.get("rank") if match else None,
                             "state": "missing" if match is None else "outside_budget"})
    # Pair identity, not labels, identifies annotated entries in the ranking pool.
    known = {_pair_key(_endpoint(pairs[ref["task_id"]], "A"), _endpoint(pairs[ref["task_id"]], "B"))
             for ref in (pool_refs if pool_refs is not None else refs) if ref["task_id"] in pairs}
    known.discard(None)
    unlabelled = [row for row in rankings if _pair_key(row.get("source"), row.get("target")) not in known]
    return {**dict(counts), "available": available,
            "complete": available and counts["matching_missing_total"] == 0,
            "fixed_candidate_budget": budget, "ranking_pool_pair_count": len(rankings),
            "ranking_selected_pair_count": sum(row.get("selected") is True for row in rankings),
            "unlabelled_pool_pair_count": len(unlabelled),
            "unlabelled_selected_pair_count": sum(row.get("selected") is True for row in unlabelled),
            "positive_coverage_all_labelled_positives": _ratio(counts["positive_selected"], counts["positive_total"]),
            "negative_candidate_inclusion_all_labelled_negatives": _ratio(counts["negative_selected"], counts["negative_total"]),
            "positive_not_selected": failures,
            "interpretation": "Restricted endpoint-pool coverage only; not full-corpus recall. Unlabelled ranked pairs are not negatives. Missing matching records remain in denominators."}


def _e(value: object) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return html.escape(str(value), quote=True)


def _fraction(numerator: int, denominator: int) -> str:
    return "%s/%s" % (numerator, denominator) if denominator else "—"


def _original(node: dict) -> str:
    if isinstance(node.get("text"), str):
        return node["text"]
    return "\n\n".join(member.get("text", "") for member in node.get("members", []) if isinstance(member.get("text"), str))


def _match_html(match: Optional[dict], entry: Optional[dict], views: Dict[str, dict]) -> str:
    if match is None:
        return '<p class="muted">片段匹配尚未运行／同步。</p>'
    selected = "预算内" if match.get("selected") is True else "预算外（仍强制送入 verifier）"
    sections = ['<p>候选排名：%s · %s</p>' % (_e(match.get("rank", "—")), selected)]
    selected_matches = match.get("matches", [])
    task = (entry or {}).get("task", {})
    candidates = task.get("candidate_matches", (entry or {}).get("candidate_matches", []))
    # The actual LLM evidence context is displayed separately from ranked raw spans.
    for index, span_pair in enumerate(selected_matches):
        score = span_pair.get("score")
        score_text = "%.5f" % score if isinstance(score, (int, float)) else _e(score if score is not None else "—")
        candidate = candidates[index] if index < len(candidates) else {}
        sides = []
        for side in ("A", "B"):
            view_id = span_pair.get(side + "_view_id")
            view = views.get(view_id, {})
            raw = view.get("quote", "")
            rendered = candidate.get(side + "_focus", view.get("retrieval_text", ""))
            evidence_id = candidate.get(side + "_evidence_id")
            anchor = (entry or {}).get("lookups", {}).get(side, {}).get(evidence_id, {})
            context = anchor.get("quote")
            shown_evidence = next((e for e in task.get(side, {}).get("evidence", [])
                                   if e.get("evidence_id") == evidence_id), {})
            position = "%s [%s:%s]" % (view.get("member_id", "—"), view.get("char_start", "—"), view.get("char_end", "—"))
            block = '<section><h5>%s 命中片段</h5><small>%s · %s</small><pre>%s</pre>' % (side, _e(view_id), _e(position), _e(raw))
            if rendered and rendered != raw:
                block += '<details><summary>清理后匹配文本</summary><pre>%s</pre></details>' % _e(rendered)
            if context is not None:
                block += '<h5>上下文原始锚点 · %s</h5><pre>%s</pre>' % (_e(evidence_id), _e(context))
                if "text" in shown_evidence:
                    block += '<details><summary>实际送入模型的上下文文本</summary><pre>%s</pre></details>' % _e(shown_evidence["text"])
            else:
                block += '<p class="muted">Verifier 输入尚未生成／对应上下文尚未同步。</p>'
            sides.append(block + '</section>')
        sections.append('<details open><summary>片段对 %s · cosine %s（未提供给模型）</summary><div class="nodes">%s</div></details>' % (index + 1, score_text, "".join(sides)))
    if not selected_matches:
        sections.append('<p class="muted">没有片段匹配记录。</p>')
    return "".join(sections)


def _prediction_html(ref: dict, prediction: Optional[dict]) -> Tuple[str, bool, bool]:
    state, decision = _state(prediction)
    expected = _expected(ref)
    broad_ok = None if expected is None else state == "binary" and (decision in LINKS) == expected
    strict_ok = None if not ref.get("decision_evaluable", False) else state in {"binary", "abstention"} and decision in ref.get("allowed_decisions", [])
    failed = state != "missing" and (broad_ok is False or strict_ok is False)
    css = "fail" if failed else "pending" if state == "missing" else "neutral" if expected is None else "pass"
    if state == "missing":
        return '<div class="prediction pending">模型预测尚未运行／同步。</div>', False, True
    result = prediction.get("result")
    result = result if isinstance(result, dict) else {}
    parts = ['<div class="prediction %s"><strong>%s</strong> · %s' % (css, _e(decision or result.get("decision", "INVALID")), _e(state))]
    if expected is None:
        parts.append('<p>参考关联标签不计分。</p>')
    elif broad_ok:
        parts.append('<p>具体关联判断通过。%s</p>' % ("允许决策不通过。" if strict_ok is False else ""))
    else:
        parts.append('<p>具体关联判断未通过；无效／弃权输出不视为正确。</p>')
    for field, label in (("reason", "理由"), ("basis", "依据类型"), ("matched_claim", "对应主张"), ("limitation", "限制")):
        if result.get(field):
            parts.append('<p><strong>%s：</strong><span class="raw">%s</span></p>' % (label, _e(result[field])))
    if state == "invalid":
        errors = [attempt.get("error") for attempt in prediction.get("attempts", []) if isinstance(attempt, dict) and attempt.get("error")]
        if prediction.get("error"):
            errors.append(prediction["error"])
        if errors:
            parts.append('<pre>%s</pre>' % _e(errors))
    return "".join(parts) + '</div>', failed, False


def _render(refs: List[dict], nodes: Dict[str, dict], pairs: Dict[str, dict],
            predictions: dict, entries: dict, matching: dict, views: dict, summary: dict) -> str:
    rows, source_rows, cards = [], [], []
    for dataset, dataset_summary in summary["datasets"].items():
        for arm in ARMS:
            value = dataset_summary["arms"][arm]
            verifier, retrieval = value["verifier"], value["retrieval"]
            rows.append('<tr><th>%s · %s</th><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s / %s / %s</td></tr>' % (
                _e(dataset), LABELS[arm], _fraction(verifier["processed_total"], verifier["total"]),
                _fraction(retrieval["positive_selected"], retrieval["positive_total"]),
                _fraction(retrieval["negative_selected"], retrieval["negative_total"]),
                _fraction(verifier["broad_correct"], verifier["scored_total"]),
                _fraction(verifier["fp"], verifier["negative_total"]),
                _fraction(verifier["strict_correct"], verifier["strict_scored_total"]),
                verifier["scored_missing"], verifier["scored_invalid"], verifier["scored_abstention"]))
        for source, grouped in dataset_summary.get("by_source_suite", {}).items():
            for arm in ARMS:
                row = grouped["arms"][arm]["verifier"]
                source_rows.append('<tr><th>%s · %s</th><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                    _e(source), LABELS[arm], _fraction(row["processed_total"], row["total"]),
                    _fraction(row["broad_correct"], row["scored_total"]), _fraction(row["fp"], row["negative_total"])))
    for ref in refs:
        dataset, task_id = ref["dataset"], ref["task_id"]
        pair = pairs.get(task_id, {})
        expected = _expected(ref)
        expected_text = "不计分 / U" if expected is None else "RELATED" if expected else "NO_LINK"
        sides, sections, failed, pending, retrieval_miss = [], [], False, False, False
        for side in ("A", "B"):
            node_id = _endpoint(pair, side)
            node = nodes.get(node_id, {})
            sides.append('<section><h3>原 node %s</h3><small>%s · %s</small><pre>%s</pre></section>' % (
                side, _e(node_id), _e(node.get("document", "—")), _e(_original(node))))
        for arm in ARMS:
            match = matching[dataset][arm].get(task_id)
            prediction, arm_failed, arm_pending = _prediction_html(ref, predictions[arm].get(task_id))
            failed |= arm_failed
            pending |= arm_pending
            retrieval_miss |= expected is True and match is not None and not match.get("selected", False)
            section = '<section class="arm"><h3>%s</h3>%s%s</section>' % (LABELS[arm],
                _match_html(match, entries[arm].get(task_id), views[dataset][arm]), prediction)
            sections.append(section)
        cards.append('<article class="case" id="%s" data-dataset="%s" data-failure="%s" data-pending="%s" data-retrieval-miss="%s">'
                     '<h2>%s · %s <span class="tag">%s</span></h2><p class="muted">%s · %s · task_id: %s</p>'
                     '<p>允许决策：%s；严格决策计分：%s</p><details><summary>查看完整原 node（保留原换行）</summary>'
                     '<div class="nodes">%s</div></details><div class="arms">%s</div></article>' % (
                         _e(dataset + "-" + str(ref.get("suite_case_id", task_id))), _e(dataset),
                         str(failed).lower(), str(pending).lower(), str(retrieval_miss).lower(),
                         _e(dataset), _e(ref.get("suite_case_id", task_id)), expected_text,
                         _e(ref.get("source_suite", "—")), _e(_document_scope(ref, pair, nodes)), _e(task_id),
                         _e(ref.get("allowed_decisions", [])), "是" if ref.get("decision_evaluable", False) else "否",
                         "".join(sides), "".join(sections)))
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>纯文字匹配粒度对照</title><style>
body{font:15px/1.55 system-ui,sans-serif;margin:0;background:#f4f6f8;color:#192331}main{max-width:1700px;margin:auto;padding:24px}
h1,h2,h3,h4,h5{line-height:1.25}h5{margin:12px 0 6px}.notice,.case{background:white;border:1px solid #d8dfe7;border-radius:10px;padding:20px;margin:18px 0}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d8dfe7;padding:8px;text-align:left}.table{overflow-x:auto}
.nodes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.arms{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.arm{min-width:0;border:1px solid #d8dfe7;padding:12px;border-radius:8px}
pre,.raw{white-space:pre-wrap;overflow-wrap:anywhere}pre{font:13px/1.5 ui-monospace,monospace;background:#f5f7fa;border-radius:5px;padding:9px;max-height:380px;overflow:auto}
.arm .nodes{display:block}.prediction{padding:10px;border-left:4px solid #9aa8b8;margin-top:15px}.fail{border-color:#b92035;background:#fff0f2}.pass{border-color:#1e8756;background:#eefaf3}.pending{background:#f4f4f4}.neutral{background:#eef3fb}
.muted,small{color:#5b687a;overflow-wrap:anywhere}.tag{font-size:14px;padding:4px 7px;background:#e8eef7;border-radius:5px}summary{cursor:pointer}.controls{position:sticky;top:0;background:#eef2f7;padding:12px;z-index:2;border-bottom:1px solid #bcc8d8}select,input{font:inherit;padding:6px;margin:4px}article[hidden]{display:none}@media(max-width:1000px){.arms{grid-template-columns:1fr}.arm .nodes{display:grid}}@media(max-width:600px){.nodes,.arm .nodes{display:block}main{padding:10px}}
</style></head><body><main><h1>纯文字：96 词滑窗 / 物理逐行 / 完整句</h1>
<p class="muted">生成时间：''' + _e(summary["generated_at_utc"]) + ''' · <a href="report.json">结构化分数</a></p>
<section class="notice"><p>两批样本分开统计；真实样本按既有来源组另报。参考标签为已有暂定标注，不修改原始数据。</p>
<p><strong>召回范围：</strong>仅限本次样本端点组成的受限 node 池（同文档 pair 也参与排名），不是全文库 recall；固定候选预算为真实池 ''' + _e(summary["budgets"].get("real", 200)) + '''、合成池 ''' + _e(summary["budgets"].get("synthetic", 100)) + '''。未标注的 node pair 绝不按负例计算。</p>
<p><strong>关系核验：</strong>所有 ''' + str(len(refs)) + ''' 对已选样本在三组均强制送入 verifier，不因预算外而跳过；模型不接收相似度分数。E/N 合并为 RELATED，U 不计关联分；严格决策仅按 decision_evaluable 的允许集合计分。缺失、无效、弃权保留在完整分母中；缺失不是已观测失败。</p>
<p>匹配片段展示原始换行及位置；上下文同时提供原始锚点和实际送入模型的清理文本。逐行命中本身不代表关系成立。</p></section>
<div class="table"><table><thead><tr><th>数据 / 方案</th><th>预测进度</th><th>受限池正例覆盖</th><th>负例入候选</th><th>关联正确</th><th>错连 / 负例</th><th>严格决策正确</th><th>计分缺失 / 无效 / 弃权</th></tr></thead><tbody>''' + "".join(rows) + '''</tbody></table></div>
<details><summary>真实样本原来源分组</summary><table><thead><tr><th>来源 / 方案</th><th>进度</th><th>关联正确</th><th>错连 / 负例</th></tr></thead><tbody>''' + "".join(source_rows) + '''</tbody></table></details>
<div class="controls"><label>数据 <select id="dataset"><option value="all">全部</option><option value="real">真实样本</option><option value="synthetic">合成样本</option></select></label>
<label>状态 <select id="status"><option value="all">全部</option><option value="failure">有已观测核验失败</option><option value="retrieval-miss">有正例预算外</option><option value="pending">有待预测</option></select></label>
<input id="query" placeholder="搜索编号、原文或理由"><span id="visible"></span></div>''' + "".join(cards) + '''
<script>const controls=['dataset','status','query'].map(id=>document.getElementById(id));function filter(){let count=0;const [dataset,status,query]=controls.map(el=>el.value.toLowerCase());document.querySelectorAll('article.case').forEach(card=>{const ok=(dataset==='all'||card.dataset.dataset===dataset)&&(status==='all'||card.getAttribute('data-'+status)==='true')&&(!query||card.textContent.toLowerCase().includes(query));card.hidden=!ok;count+=ok?1:0});document.getElementById('visible').textContent=count+' 对'}controls.forEach(el=>el.addEventListener('input',filter));filter();</script></main></body></html>'''


def report(out: Path) -> dict:
    out = Path(out)
    protocol = json.loads((out / "protocol.json").read_text(encoding="utf-8"))
    refs = _rows(out / "references.jsonl")
    references = _index(refs, "task_id", "references")
    nodes = _index(_rows(out / "nodes.jsonl"), "id", "nodes")
    pair_rows = _rows(out / "pairs.jsonl")
    pairs = _index([{**row, "task_id": row.get("task_id") or row.get("task", {}).get("task_id")} for row in pair_rows], "task_id", "pairs")
    if set(pairs) != set(references):
        raise ValueError("Frozen pairs and references have different task IDs")
    budgets = {"real": 200, "synthetic": 100, **protocol.get("selection", {}).get("budgets", {})}
    predictions, entries, matching, views = {}, {}, {}, {}
    for arm in ARMS:
        folder = out / "verifier" / VERIFIER_ARMS[arm]
        predictions[arm] = _index(_rows(folder / "predictions.jsonl", optional=True), "task_id", arm + " predictions")
        entry_rows = _rows(folder / "inputs.jsonl", optional=True)
        entries[arm] = _index([{**row, "task_id": row.get("task_id") or row.get("task", {}).get("task_id")} for row in entry_rows], "task_id", arm + " inputs")
        if set(predictions[arm]) - set(references) or set(entries[arm]) - set(references):
            raise ValueError("Unexpected verifier task ID in " + arm)
    summary = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "budgets": budgets,
               "total_pairs": len(refs), "protocol": protocol, "datasets": {},
               "notes": ["All frozen pairs are forced verifier inputs, independently of retrieval selection.",
                         "E/N count as RELATED. Missing/invalid/abstaining predictions remain in scored denominators.",
                         "Restricted-pool retrieval only; unlabelled ranked pairs are never assumed negative."]}
    for dataset in sorted({ref["dataset"] for ref in refs}):
        dataset_refs = [ref for ref in refs if ref["dataset"] == dataset]
        matching[dataset], views[dataset] = {}, {}
        dataset_summary = {"total_pairs": len(dataset_refs), "arms": {}, "by_source_suite": {}, "by_document_scope": {}}
        for arm in ARMS:
            folder = out / "matching" / dataset / arm
            matches = _index(_rows(folder / "pairs.jsonl", optional=True), "task_id", dataset + " " + arm + " matching")
            if set(matches) - {ref["task_id"] for ref in dataset_refs}:
                raise ValueError("Unexpected matching task ID in " + dataset + "/" + arm)
            rankings = _rows(folder / "rankings.jsonl", optional=True)
            matching[dataset][arm] = matches
            view_rows = _rows(out / dataset / arm / "views.jsonl", optional=True)
            views[dataset][arm] = _index(view_rows, "view_id", dataset + " " + arm + " views")
            available = (folder / "pairs.jsonl").exists() and (folder / "rankings.jsonl").exists()
            def group(group_refs: List[dict]) -> dict:
                return {"verifier": _score(group_refs, predictions[arm]),
                        "retrieval": _retrieval(group_refs, matches, rankings, pairs, budgets[dataset], available, dataset_refs)}
            dataset_summary["arms"][arm] = {**group(dataset_refs), "view_count": len(view_rows),
                "view_node_count": len({row.get("node_id") for row in view_rows}),
                "verifier_input_count": sum(ref["task_id"] in entries[arm] for ref in dataset_refs)}
            if dataset == "real":
                for source in sorted({ref.get("source_suite", "unknown") for ref in dataset_refs}):
                    dataset_summary["by_source_suite"].setdefault(source, {"arms": {}})["arms"][arm] = group(
                        [ref for ref in dataset_refs if ref.get("source_suite", "unknown") == source])
            for scope in sorted({_document_scope(ref, pairs[ref["task_id"]], nodes) for ref in dataset_refs}):
                dataset_summary["by_document_scope"].setdefault(scope, {"arms": {}})["arms"][arm] = group(
                    [ref for ref in dataset_refs if _document_scope(ref, pairs[ref["task_id"]], nodes) == scope])
        summary["datasets"][dataset] = dataset_summary
    page = _render(refs, nodes, pairs, predictions, entries, matching, views, summary)
    for filename, content in (("report.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n"), ("index.html", page)):
        temporary = out / (filename + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(out / filename)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = report(args.output)
    print(json.dumps({"total_pairs": summary["total_pairs"], "report": str(args.output / "index.html"),
                      "progress": {dataset: {arm: row["verifier"]["processed_total"] for arm, row in value["arms"].items()}
                                   for dataset, value in summary["datasets"].items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
