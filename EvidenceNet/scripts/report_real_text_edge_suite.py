#!/usr/bin/env python3
"""Report a genuine text-only rerun of previously inspected real-paper pairs.

This is a fixed-pair verifier diagnostic, not a new held-out evaluation or an
embedding/retrieval experiment. Existing labels are preserved and remain
provisional. Missing, invalid and abstaining outputs stay in scored denominators.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ARMS = ("control", "text_scope", "text_readable", "swapped")
LINKS = {"EVIDENCE_LINK", "NAVIGATION_LINK"}
DECISIONS = LINKS | {"NO_LINK", "UNCERTAIN"}
ARM_LABELS = {"control": "Control", "text_scope": "Text scope",
              "text_readable": "Text readable", "swapped": "Control · A/B swapped"}


def _rows(path: Path, optional: bool = False) -> List[dict]:
    if optional and not path.exists():
        return []
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("Expected object at %s:%s" % (path, line_number))
        result.append(value)
    return result


def _index(items: List[dict], field: str, description: str) -> Dict[str, dict]:
    result = {}
    for item in items:
        key = item.get(field)
        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Missing or duplicate %s in %s: %r" % (field, description, key))
        result[key] = item
    return result


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return numerator / denominator if denominator else None


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


def _expected(ref: dict) -> Optional[bool]:
    if not ref.get("cutoff_evaluable", False):
        return None
    levels = set(ref.get("allowed_levels", []))
    if levels and levels <= {2, 3}:
        return True
    if levels and levels <= {0, 1}:
        return False
    raise ValueError("Scored broad reference straddles cutoff: " + ref["task_id"])


def _score(refs: List[dict], predictions: Dict[str, dict]) -> dict:
    names = ("total", "scored_total", "positive_total", "negative_total",
             "excluded_total", "unlabelled_total", "annotation_uncertain_total",
             "processed_total", "valid_total", "missing_total", "invalid_total",
             "abstention_total", "scored_missing", "scored_invalid", "scored_abstention",
             "tp", "tn", "fp", "fn", "strict_scored_total", "strict_correct",
             "strict_missing", "strict_invalid", "strict_abstention")
    counts = Counter({name: 0 for name in names})
    decisions = Counter()
    failures, strict_confusion = [], Counter()
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
            if ref.get("annotation_label") == "UNLABELLED":
                counts["unlabelled_total"] += 1
            else:
                counts["annotation_uncertain_total"] += 1
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
                raise ValueError("Missing strict decision reference: " + ref["task_id"])
            counts["strict_scored_total"] += 1
            strict_correct = state in {"binary", "abstention"} and decision in allowed
            counts["strict_correct"] += strict_correct
            if state != "binary":
                counts["strict_" + state] += 1
            strict_confusion[(" | ".join(sorted(allowed)), decision or state.upper())] += 1
        if broad_correct is False or strict_correct is False:
            failures.append({"suite_case_id": ref["suite_case_id"], "task_id": ref["task_id"],
                             "source_suite": ref["source_suite"], "state": state,
                             "decision": decision, "broad_correct": broad_correct,
                             "strict_correct": strict_correct})
    return {**dict(counts), "broad_correct": counts["tp"] + counts["tn"],
            "broad_accuracy_all_scored": _ratio(counts["tp"] + counts["tn"], counts["scored_total"]),
            "positive_recall_all_expected": _ratio(counts["tp"], counts["positive_total"]),
            "negative_false_link_rate": _ratio(counts["fp"], counts["negative_total"]),
            "strict_accuracy_all_scored": _ratio(counts["strict_correct"], counts["strict_scored_total"]),
            "decision_counts": dict(decisions), "failures": failures,
            "strict_confusion": [{"expected": exp, "actual": actual, "count": count}
                                 for (exp, actual), count in sorted(strict_confusion.items())]}


def _swap_consistency(refs: List[dict], control: Dict[str, dict], swapped: Dict[str, dict]) -> dict:
    counts = Counter({name: 0 for name in ("total", "both_valid_total", "both_binary_total",
                                          "exact_decision_agree", "broad_link_agree")})
    differences = []
    for ref in refs:
        state_a, decision_a = _state(control.get(ref["task_id"]))
        state_b, decision_b = _state(swapped.get(ref["task_id"]))
        counts["total"] += 1
        if state_a in {"binary", "abstention"} and state_b in {"binary", "abstention"}:
            counts["both_valid_total"] += 1
            counts["exact_decision_agree"] += decision_a == decision_b
            if decision_a != decision_b:
                differences.append({"suite_case_id": ref["suite_case_id"],
                                    "control": decision_a, "swapped": decision_b})
        if state_a == state_b == "binary":
            counts["both_binary_total"] += 1
            counts["broad_link_agree"] += (decision_a in LINKS) == (decision_b in LINKS)
    return {**dict(counts), "exact_agreement_both_valid": _ratio(counts["exact_decision_agree"], counts["both_valid_total"]),
            "broad_agreement_both_binary": _ratio(counts["broad_link_agree"], counts["both_binary_total"]),
            "not_both_valid": counts["total"] - counts["both_valid_total"], "differences": differences,
            "interpretation": "Consistency only, not accuracy; includes unlabelled/uncertain cases. Missing/invalid pairs excluded only from consistency ratios and explicitly counted."}


def _original_text(entry: dict, side: str, nodes: Dict[str, dict]) -> str:
    endpoint = entry["task"][side]
    node = nodes.get(endpoint["node_id"], {})
    anchors = entry.get("lookups", {}).get(side, {})
    member_ids = []
    for anchor in anchors.values():
        member_id = anchor.get("member_id")
        if member_id not in member_ids:
            member_ids.append(member_id)
    parts = []
    for member_id in member_ids:
        member = next((m for m in node.get("members", []) if m.get("id") == member_id), None)
        if member and isinstance(member.get("text"), str):
            parts.append(member["text"])
        else:
            ordered = sorted((a for a in anchors.values() if a.get("member_id") == member_id),
                             key=lambda a: (a.get("char_start", 0), a.get("char_end", 0)))
            parts.extend(a.get("quote", "") for a in ordered)
    if not parts:
        parts = [e.get("text", "") for e in endpoint.get("evidence", [])]
    return "\n\n".join(parts)


def _escape(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _fraction(numerator: int, denominator: int) -> str:
    return "%s / %s" % (numerator, denominator) if denominator else "—"


def _render(out: Path, scores: dict, refs: List[dict], inputs: Dict[str, Dict[str, dict]],
            predictions: Dict[str, Dict[str, dict]], nodes: Dict[str, dict]) -> None:
    summary = []
    for source, groups in scores["groups"].items():
        for arm in ARMS:
            stats = groups[arm]
            summary.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                _escape(source), _escape(ARM_LABELS[arm]),
                _fraction(stats["broad_correct"], stats["scored_total"]),
                _fraction(stats["fp"], stats["negative_total"]),
                _fraction(stats["strict_correct"], stats["strict_scored_total"]),
                "%s / %s / %s" % (stats["scored_missing"], stats["scored_invalid"], stats["scored_abstention"]),
                "%s / %s" % (stats["unlabelled_total"], stats["annotation_uncertain_total"])))
    cards = []
    for ref in refs:
        tid = ref["task_id"]
        expected = _expected(ref)
        entry = inputs["control"][tid]
        model_rows, failed = [], False
        for arm in ARMS:
            prediction = predictions[arm].get(tid)
            state, decision = _state(prediction)
            result = prediction.get("result", {}) if prediction else {}
            if not isinstance(result, dict):
                result = {}
            broad_correct = None if expected is None else state == "binary" and (decision in LINKS) == expected
            strict_correct = None if not ref.get("decision_evaluable") else (
                state in {"binary", "abstention"} and decision in ref.get("allowed_decisions", []))
            # Pending tasks are not labelled empirical failures in the filter.
            failed = failed or (state != "missing" and (broad_correct is False or strict_correct is False))
            status = "未运行" if state == "missing" else "无效输出" if state == "invalid" else decision
            verdict = "不计分" if expected is None else "待运行" if state == "missing" else "正确" if broad_correct else "错误／弃权"
            model_rows.append("<section class='prediction'><h4>%s · %s</h4><p>Broad: %s%s</p><dl>%s</dl></section>" % (
                _escape(ARM_LABELS[arm]), _escape(status), _escape(verdict),
                " · strict: " + _escape("待运行" if state == "missing" else "正确" if strict_correct else "错误／弃权")
                    if strict_correct is not None else "",
                "".join("<dt>%s</dt><dd>%s</dd>" % (_escape(name), _escape(result.get(name, "")))
                        for name in ("basis", "matched_claim", "reason", "limitation"))))
        broad_label = "未标注／不计分" if ref.get("annotation_label") == "UNLABELLED" else "U／不计分" if expected is None else "RELATED" if expected else "NO_LINK"
        cards.append("<article class='case' data-failed='%s'><h2>%s · %s</h2><p>%s · 原标注 %s · %s</p><p>%s</p>"
                     "<div class='endpoints'>%s</div><div class='predictions'>%s</div></article>" % (
                         "1" if failed else "0", _escape(ref["suite_case_id"]), _escape(broad_label),
                         _escape(ref["source_suite"]), _escape(ref.get("annotation_label", "")), _escape(tid),
                         _escape(ref.get("rationale", ref.get("note", ""))),
                         "".join("<section><h3>%s · %s</h3><pre>%s</pre></section>" % (
                             side, _escape(entry["task"][side]["node_id"]), _escape(_original_text(entry, side, nodes)))
                                 for side in ("A", "B")), "".join(model_rows)))
    swap = scores["swap_consistency"]["all"]
    document = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>真实样本 · 纯文本复测</title>
<style>body{font:16px/1.55 system-ui,sans-serif;margin:0 auto;padding:24px;max-width:1500px;background:#f7f8fa;color:#17212e}h1,h2,h3,h4{line-height:1.3}table{border-collapse:collapse;width:100%%;font-size:14px}td,th{padding:8px;border:1px solid #d8dfe8;text-align:left}.case{background:white;border:1px solid #d8dfe8;border-radius:10px;padding:18px;margin:22px 0}.endpoints,.predictions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 ui-monospace,monospace;background:#f3f6fa;padding:12px}dt{font-weight:600}dd{margin-left:0;white-space:pre-wrap;overflow-wrap:anywhere}.prediction{border-top:1px solid #d8dfe8}label{display:block;margin-top:20px}body.only-failed .case[data-failed="0"]{display:none}@media(max-width:800px){.endpoints,.predictions{grid-template-columns:1fr}table{display:block;overflow:auto}}</style>
<h1>真实样本 · 纯文本复测</h1><p>已有真实论文样本的固定 node pair 复测；全部推理不带图片。不是新的 held-out 测试，不评估 embedding／召回。旧开发集与新标注集分开报告，标签不随本次预测调整。</p>
<p>主指标合并 EVIDENCE_LINK 与 NAVIGATION_LINK 为 RELATED，NO_LINK 为负类；RELATED 不等于支持或蕴含。U 与未标注样本均不计准确率，且分别计数。Missing、invalid、UNCERTAIN 保留在所有已标注样本分母内。Strict 仅采用 decision_evaluable 的参考标签；旧集不强制 E/N。</p>
<p>生成时间（UTC）：%s</p><table><thead><tr><th>来源</th><th>方案</th><th>Broad 正确/计分</th><th>错连/负例</th><th>Strict 正确/计分</th><th>计分样本 Missing/Invalid/弃权</th><th>未标注/U</th></tr></thead><tbody>%s</tbody></table>
<p>A/B 交换：有效输出中严格决策一致 %s；双方均为二元决策时 broad 一致 %s。尚未双方有效：%s。交换一致性不是准确率。</p>
<label><input type="checkbox" onchange="document.body.classList.toggle('only-failed',this.checked)"> 只显示已有预测失败／无效／弃权的样本（不把未运行视为实测失败）</label>%s</html>""" % (
        _escape(scores["generated_at_utc"]), "".join(summary),
        _fraction(swap["exact_decision_agree"], swap["both_valid_total"]),
        _fraction(swap["broad_link_agree"], swap["both_binary_total"]), swap["not_both_valid"], "".join(cards))
    (out / "index.html").write_text(document, encoding="utf-8")


def report(out: Path) -> dict:
    out = Path(out)
    refs = _rows(out / "reference.jsonl")
    references = _index(refs, "task_id", "references")
    _index(refs, "suite_case_id", "references")
    nodes = _index(_rows(out / "nodes.jsonl"), "id", "nodes")
    inputs, predictions = {}, {}
    for arm in ARMS:
        entries = _rows(out / arm / "inputs.jsonl")
        inputs[arm] = _index([{**entry, "task_id": entry["task"]["task_id"]} for entry in entries], "task_id", arm + " inputs")
        if set(inputs[arm]) != set(references):
            raise ValueError("Input/reference task mismatch in " + arm)
        if any(e.get("images") or e.get("image_sha256") for e in entries):
            raise ValueError("Expected genuinely image-free inputs in " + arm)
        predictions[arm] = _index(_rows(out / arm / "predictions.jsonl", optional=True), "task_id", arm + " predictions")
        if not set(predictions[arm]) <= set(references):
            raise ValueError("Unexpected prediction task in " + arm)
    groups = {"all": refs}
    groups.update({source: [ref for ref in refs if ref["source_suite"] == source]
                   for source in sorted({ref["source_suite"] for ref in refs})})
    scores = {"experiment": "previous_real_pairs_text_only_rerun",
              "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": __doc__.strip(), "arms": list(ARMS), "images": 0,
              "groups": {name: {arm: _score(group, predictions[arm]) for arm in ARMS}
                         for name, group in groups.items()},
              "swap_consistency": {name: _swap_consistency(group, predictions["control"], predictions["swapped"])
                                   for name, group in groups.items()}}
    (out / "scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _render(out, scores, refs, inputs, predictions, nodes)
    return scores


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = report(args.output)
    print(json.dumps(result["groups"], ensure_ascii=False, indent=2))
