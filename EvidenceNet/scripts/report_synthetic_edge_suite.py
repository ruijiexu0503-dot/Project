#!/usr/bin/env python3
"""Report an independently frozen synthetic edge suite without running inference.

Missing, invalid, and abstaining predictions remain in scored denominators.
The four confusion counts cover valid binary decisions only; separate counters
account for the other outcomes. Synthetic labels are provisional author labels,
not claims about performance on a natural corpus or an embedding retriever.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
from typing import Any


ARMS = ("control", "text_scope", "text_readable", "swapped")
LINKS = {"EVIDENCE_LINK", "NAVIGATION_LINK"}
DECISIONS = LINKS | {"NO_LINK", "UNCERTAIN"}
ARM_LABELS = {
    "control": "Control",
    "text_scope": "Text scope",
    "text_readable": "Text readable",
    "swapped": "Control · A/B swapped",
}


def _rows(path: Path, *, optional: bool = False) -> list[dict[str, Any]]:
    if optional and not path.exists():
        return []
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Expected object at {path}:{line_number}")
        result.append(value)
    return result


def _index(items: list[dict[str, Any]], field: str, description: str) -> dict[str, dict]:
    result = {}
    for item in items:
        value = item.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Missing string {field} in {description}")
        if value in result:
            raise ValueError(f"Duplicate {field} {value!r} in {description}")
        result[value] = item
    return result


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _prediction_state(prediction: dict | None) -> tuple[str, str | None]:
    if prediction is None:
        return "missing", None
    result = prediction.get("result")
    if prediction.get("valid") is not True or not isinstance(result, dict):
        return "invalid", None
    decision = result.get("decision")
    if decision not in DECISIONS:
        return "invalid", None
    if decision == "UNCERTAIN":
        return "abstention", decision
    return "binary", decision


def _score(specs: list[dict], references: dict[str, dict], predictions: dict[str, dict]) -> dict:
    counts = Counter({name: 0 for name in (
        "total", "scored_total", "excluded_total", "positive_total", "negative_total",
        "processed_total", "valid_total", "missing_total", "invalid_total", "abstention_total",
        "scored_missing", "scored_invalid", "scored_abstention", "tp", "tn", "fp", "fn",
        "positive_missing", "positive_invalid", "positive_abstention",
        "negative_missing", "negative_invalid", "negative_abstention",
        "allowed_decision_correct",
    )})
    decisions: Counter[str] = Counter()
    failures = []
    for spec in specs:
        ref = references[spec["id"]]
        prediction = predictions.get(ref["task_id"])
        state, decision = _prediction_state(prediction)
        counts["total"] += 1
        counts["processed_total"] += prediction is not None
        counts["valid_total"] += state in {"binary", "abstention"}
        if state != "binary":
            counts[state + "_total"] += 1
        if decision:
            decisions[decision] += 1
        if not ref["cutoff_evaluable"]:
            counts["excluded_total"] += 1
            continue
        positive = spec["expected"] == "RELATED"
        category = "positive" if positive else "negative"
        counts["scored_total"] += 1
        counts[category + "_total"] += 1
        if state != "binary":
            counts["scored_" + state] += 1
            counts[category + "_" + state] += 1
        else:
            linked = decision in LINKS
            key = ("tp" if linked else "fn") if positive else ("fp" if linked else "tn")
            counts[key] += 1
        allowed = state in {"binary", "abstention"} and decision in ref["allowed_decisions"]
        counts["allowed_decision_correct"] += allowed
        broad_correct = state == "binary" and (decision in LINKS) == positive
        if not broad_correct or not allowed:
            failures.append({
                "suite_case_id": spec["id"], "task_id": ref["task_id"], "state": state,
                "decision": decision, "expected": spec["expected"],
                "broad_correct": broad_correct, "allowed_decision_correct": allowed,
            })
    result: dict[str, Any] = dict(counts)
    result.update({
        "complete": counts["processed_total"] == counts["total"],
        "decisions": dict(sorted(decisions.items())),
        "broad_correct": counts["tp"] + counts["tn"],
        "broad_accuracy_all_scored": _ratio(counts["tp"] + counts["tn"], counts["scored_total"]),
        "positive_recall_all_positives": _ratio(counts["tp"], counts["positive_total"]),
        "negative_rejection_all_negatives": _ratio(counts["tn"], counts["negative_total"]),
        "false_link_rate_all_negatives": _ratio(counts["fp"], counts["negative_total"]),
        "allowed_decision_agreement": _ratio(counts["allowed_decision_correct"], counts["scored_total"]),
        "failures": failures,
    })
    return result


def _symmetry(specs: list[dict], references: dict[str, dict], arms: dict[str, dict]) -> dict:
    valid_paired = binary_paired = exact_agreed = broad_agreed = 0
    differences = []
    excluded = Counter({"missing": 0, "invalid": 0, "abstention_for_broad": 0})
    for spec in specs:
        task_id = references[spec["id"]]["task_id"]
        left_state, left = _prediction_state(arms["control"].get(task_id))
        right_state, right = _prediction_state(arms["swapped"].get(task_id))
        states = {left_state, right_state}
        if "missing" in states:
            excluded["missing"] += 1
            continue
        if "invalid" in states:
            excluded["invalid"] += 1
            continue
        valid_paired += 1
        exact_agreed += left == right
        if "abstention" in states:
            excluded["abstention_for_broad"] += 1
            broad_equal = None
        else:
            binary_paired += 1
            broad_equal = (left in LINKS) == (right in LINKS)
            broad_agreed += broad_equal
        if left != right:
            differences.append({
                "suite_case_id": spec["id"], "control": left, "swapped": right,
                "broad_agreement": broad_equal,
            })
    return {
        "total_pairs": len(specs),
        "valid_paired": valid_paired,
        "binary_paired": binary_paired,
        "exact_decision_agreed": exact_agreed,
        "exact_decision_agreement": _ratio(exact_agreed, valid_paired),
        "broad_agreed": broad_agreed,
        "broad_agreement": _ratio(broad_agreed, binary_paired),
        "excluded": dict(excluded),
        "differences": differences,
        "includes_unscored_U": True,
    }


def _e(value: Any) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    return html.escape(str(value), quote=True)


def _fraction(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}" if denominator else "—"


def _prediction_html(spec: dict, ref: dict, arm: str, prediction: dict | None) -> tuple[str, bool, bool]:
    state, decision = _prediction_state(prediction)
    scored = ref["cutoff_evaluable"]
    positive = spec["expected"] == "RELATED"
    broad_correct = state == "binary" and (decision in LINKS) == positive
    allowed = state in {"binary", "abstention"} and decision in ref["allowed_decisions"]
    failed = bool(scored and state != "missing" and (not broad_correct or not allowed))
    css = "fail" if failed else "pending" if state == "missing" else "neutral" if not scored else "pass"
    if state == "missing":
        body = '<p class="muted">待运行／预测尚未同步</p>'
    else:
        result = prediction.get("result")
        result = result if isinstance(result, dict) else {}
        shown_decision = decision or result.get("decision") or "INVALID"
        body = f'<p class="decision">{_e(shown_decision)}</p>'
        if state == "invalid":
            body += '<p class="muted">无效输出，不计为正确</p>'
        elif not scored:
            body += '<p class="muted">边界标签：展示但不计分</p>'
        elif not broad_correct:
            body += '<p class="error">具体关联判断未通过</p>'
        elif not allowed:
            body += '<p class="error">关联判断通过，但不在允许决策集合中</p>'
        else:
            body += '<p class="success">符合参考标签</p>'
        for field, label in (("reason", "理由"), ("basis", "依据类型"), ("matched_claim", "对应论断"), ("limitation", "限制")):
            if result.get(field):
                body += f'<p><strong>{label}：</strong><span class="raw">{_e(result[field])}</span></p>'
        if state == "invalid":
            errors = [item.get("error") for item in prediction.get("attempts", [])
                      if isinstance(item, dict) and item.get("error")]
            if prediction.get("error"):
                errors.append(prediction["error"])
            if errors:
                body += f'<p><strong>错误：</strong><span class="raw">{_e(errors)}</span></p>'
    order_note = '<small>A/B 输入顺序已交换；下方原文按原始标注顺序展示。</small>' if arm == "swapped" else ""
    content = f'<section class="prediction {css}"><h4>{_e(ARM_LABELS[arm])}</h4>{order_note}{body}</section>'
    return content, failed, state == "missing"


def _render_html(specs: list[dict], references: dict[str, dict], arms: dict[str, dict], scores: dict) -> str:
    summary_rows = []
    for arm in ARMS:
        row = scores["arms"][arm]["all"]
        state = "完成" if row["complete"] else "待运行" if not row["processed_total"] else "部分完成"
        summary_rows.append(
            f'<tr><th>{_e(ARM_LABELS[arm])}</th><td>{state} · {row["processed_total"]}/{row["total"]}</td>'
            f'<td>{_fraction(row["broad_correct"], row["scored_total"])}</td>'
            f'<td>{_fraction(row["tp"], row["positive_total"])}</td>'
            f'<td>{_fraction(row["fp"], row["negative_total"])}</td>'
            f'<td>{_fraction(row["allowed_decision_correct"], row["scored_total"])}</td>'
            f'<td>{row["scored_missing"]} / {row["scored_invalid"]} / {row["scored_abstention"]}</td></tr>'
        )
    symmetry = scores["symmetry"]["all"]
    cards = []
    for spec in specs:
        ref = references[spec["id"]]
        sections, failed, pending = [], False, False
        for arm in ARMS:
            section, arm_failed, arm_pending = _prediction_html(spec, ref, arm, arms[arm].get(ref["task_id"]))
            sections.append(section)
            failed |= arm_failed
            pending |= arm_pending
        notes = f'<p><strong>补充：</strong>{_e(spec["notes"])}</p>' if spec.get("notes") else ""
        conflict = '<p class="warning">否定／极性冲突：相关不表示论断一致，也不表示相互支持。</p>' if spec.get("polarity_conflict") else ""
        suffix = " · 不计分" if not ref["cutoff_evaluable"] else ""
        cards.append(
            f'<article class="case{ " has-failure" if failed else ""}" id="case-{_e(spec["id"])}" '
            f'data-family="{_e(spec["family"])}" data-failure="{str(failed).lower()}" data-pending="{str(pending).lower()}">'
            f'<h2>{_e(spec["id"])} <span class="tag">{_e(spec["family"])}</span>'
            f'<span class="tag">{_e(spec["expected"])}{suffix}</span></h2>'
            f'<p class="muted">对照组：{_e(spec["group"])} · task_id：{_e(ref["task_id"])}</p>'
            f'<div class="nodes"><section><h3>原文 A</h3><p class="raw">{_e(spec["a"])}</p></section>'
            f'<section><h3>原文 B</h3><p class="raw">{_e(spec["b"])}</p></section></div>'
            f'<p><strong>标注理由：</strong>{_e(spec["reason"])}</p>'
            f'<p class="muted">允许的决策：{_e(ref["allowed_decisions"])}</p>{notes}{conflict}'
            f'<div class="predictions">{"".join(sections)}</div></article>'
        )
    family_options = "".join(f'<option value="{_e(family)}">{_e(family)}</option>' for family in sorted(scores["families"]))
    family_rows = []
    for family in sorted(scores["families"]):
        cells = []
        for arm in ARMS:
            row = scores["arms"][arm]["by_family"][family]
            cells.append(f'<td>{_fraction(row["broad_correct"], row["scored_total"])}</td>')
        sym = scores["symmetry"]["by_family"][family]
        family_rows.append(f'<tr><th>{_e(family)}</th>{"".join(cells)}'
                           f'<td>{_fraction(sym["broad_agreed"], sym["binary_paired"])}</td></tr>')
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>合成纯文本 Edge 对照测试</title>
<style>
:root{color-scheme:light;--ink:#172b3a;--line:#d7e0e7;--muted:#526774}
*{box-sizing:border-box}body{margin:0;background:#f4f7f9;color:var(--ink);font:15px/1.6 system-ui,sans-serif}
main{max-width:1550px;margin:auto;padding:26px}h1{font-size:28px}h2{font-size:21px}h3,h4{margin:0 0 10px}
p{margin:9px 0}a{color:#155f9a}.intro,.case{background:white;border:1px solid var(--line);border-radius:10px;padding:22px;margin:20px 0}
.notice{background:#fff8e8;border-left:4px solid #b27613;padding:12px}.muted,small{color:var(--muted)}
.raw{white-space:pre-wrap;overflow-wrap:anywhere}.nodes{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.nodes>section{background:#f1f5f8;border-radius:6px;padding:16px}.predictions{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:18px}
.prediction{border:1px solid var(--line);border-top:4px solid #94a5b1;border-radius:5px;padding:13px;min-width:0}
.prediction.pass{border-top-color:#277449}.prediction.fail{border-color:#bc4251;background:#fff5f5}.prediction.pending{border-top-color:#bd8f2a}
.has-failure{border-left:5px solid #bc4251}.error{color:#a22534}.success{color:#22633d}.warning{color:#865500}.decision{font-weight:700;overflow-wrap:anywhere}
.tag{display:inline-block;background:#e8eef3;padding:2px 7px;margin-left:7px;border-radius:4px;font-size:12px;vertical-align:middle}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:9px;text-align:left;white-space:nowrap}
.filters{position:sticky;top:0;z-index:2;display:flex;gap:14px;align-items:center;flex-wrap:wrap;background:#e8eff5;padding:13px;border-radius:7px;box-shadow:0 2px 4px #0001}
select{font:inherit;max-width:100%;padding:5px}details{margin-top:16px}[hidden]{display:none!important}
@media(max-width:1050px){.predictions{grid-template-columns:1fr 1fr}}@media(max-width:650px){main{padding:12px}.nodes,.predictions{grid-template-columns:1fr}.case,.intro{padding:14px}}
</style></head><body><main>
<h1>合成纯文本 Edge 对照测试</h1>
<section class="intro">
<p class="notice">这些节点是刻意构造的虚构样本，标签是辅助作者的初步判断。结果用于发现边界问题，不代表真实论文分布上的准确率；这不是 embedding 或候选召回测试。</p>
""" + (
        f'<p>共 {scores["dataset"]["total"]} 对；计分 {scores["dataset"]["scored_total"]} 对；'
        f'边界／未计分 {scores["dataset"]["excluded_total"]} 对。生成时间：{_e(scores["generated_at_utc"])}。</p>'
        '<p>RELATED 表示具体关联，E/N 按允许集合评估，不表示证据可自动传播。'
        'Missing、invalid 和 UNCERTAIN 均保留在主指标分母中，不计为正确。尚未完成时表内比值不是最终成绩。</p>'
        '<div class="scroll"><table><thead><tr><th>方案</th><th>进度</th><th>关联判断正确</th><th>正例找回</th>'
        '<th>负例错连</th><th>允许决策一致</th><th>计分项 缺失 / 无效 / 弃权</th></tr></thead>'
        f'<tbody>{"".join(summary_rows)}</tbody></table></div>'
        f'<p><strong>交换 A/B 一致性：</strong>具体关联 {_fraction(symmetry["broad_agreed"], symmetry["binary_paired"])}；'
        f'完整决策 {_fraction(symmetry["exact_decision_agreed"], symmetry["valid_paired"])}。'
        '只在双方有效、可比较的输出上计算；具体关联一致性另排除 UNCERTAIN，完整决策一致性保留 UNCERTAIN。该诊断包含 U 样本。</p>'
        '<details><summary>按失败模式查看统计</summary><div class="scroll"><table><thead><tr><th>Family</th>'
        + "".join(f'<th>{_e(ARM_LABELS[arm])}</th>' for arm in ARMS)
        + f'<th>交换关联一致</th></tr></thead><tbody>{"".join(family_rows)}</tbody></table></div></details>'
        '<p><a href="scores.json">下载完整统计 scores.json</a></p></section>'
        '<nav class="filters"><label>显示 <select id="status-filter"><option value="all">全部</option>'
        '<option value="failures">已有输出的失败例</option><option value="pending">含待运行项</option></select></label>'
        f'<label>Family <select id="family-filter"><option value="all">全部</option>{family_options}</select></label>'
        '<span id="visible-count" aria-live="polite"></span></nav>'
        + "".join(cards)
    ) + """
</main><script>
(() => {
  const status = document.getElementById('status-filter');
  const family = document.getElementById('family-filter');
  const cards = [...document.querySelectorAll('.case')];
  function filter() {
    let count = 0;
    for (const card of cards) {
      const statusOK = status.value === 'all' ||
        (status.value === 'failures' && card.dataset.failure === 'true') ||
        (status.value === 'pending' && card.dataset.pending === 'true');
      const familyOK = family.value === 'all' || card.dataset.family === family.value;
      card.hidden = !(statusOK && familyOK);
      if (!card.hidden) count += 1;
    }
    document.getElementById('visible-count').textContent = `显示 ${count} / ${cards.length} 对`;
  }
  status.addEventListener('change', filter);
  family.addEventListener('change', filter);
  filter();
})();
</script></body></html>
"""


def report(out: Path) -> dict:
    """Write ``scores.json`` and an escaped, standalone ``index.html`` in out."""
    out = Path(out)
    specs_path = out / "specs.json"
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    if not isinstance(specs, list) or not all(isinstance(item, dict) for item in specs):
        raise ValueError("specs.json must contain a list of objects")
    by_case = _index(specs, "id", "specs.json")
    references = _index(_rows(out / "reference.jsonl"), "suite_case_id", "reference.jsonl")
    if set(by_case) != set(references):
        raise ValueError("specs.json and reference.jsonl case IDs differ")
    task_ids = _index(list(references.values()), "task_id", "reference.jsonl")
    for spec in specs:
        for field in ("family", "group", "a", "b", "reason"):
            if not isinstance(spec.get(field), str) or not spec[field].strip():
                raise ValueError(f"Missing string {field} in {spec['id']}")
        if spec.get("expected") not in {"RELATED", "NO_LINK", "U"}:
            raise ValueError(f"Unknown expected label in {spec['id']}")
        ref = references[spec["id"]]
        if type(ref.get("cutoff_evaluable")) is not bool:
            raise ValueError(f"cutoff_evaluable must be bool in {spec['id']}")
        allowed = ref.get("allowed_decisions")
        if not isinstance(allowed, list) or not all(item in DECISIONS for item in allowed):
            raise ValueError(f"Invalid allowed_decisions in {spec['id']}")
        if spec["expected"] == "U" and ref["cutoff_evaluable"]:
            raise ValueError(f"U label cannot be scored in {spec['id']}")
        if ref["cutoff_evaluable"]:
            broad_allowed = LINKS if spec["expected"] == "RELATED" else {"NO_LINK"}
            if not allowed or not set(allowed) <= broad_allowed:
                raise ValueError(f"Expected label conflicts with allowed_decisions in {spec['id']}")

    families = sorted({spec["family"] for spec in specs})
    grouped = {family: [spec for spec in specs if spec["family"] == family] for family in families}
    arms: dict[str, dict] = {}
    source_hashes = {}
    warnings = []
    for path in (specs_path, out / "reference.jsonl"):
        source_hashes[str(path.relative_to(out))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for arm in ARMS:
        path = out / arm / "predictions.jsonl"
        arms[arm] = _index(_rows(path, optional=True), "task_id", str(path))
        unknown = set(arms[arm]) - set(task_ids)
        if unknown:
            raise ValueError(f"Unknown task IDs in {path}: {sorted(unknown)}")
        input_path = out / arm / "inputs.jsonl"
        if input_path.exists():
            inputs = _rows(input_path)
            input_tasks = []
            for entry in inputs:
                task = entry.get("task")
                if not isinstance(task, dict):
                    raise ValueError(f"Missing task in {input_path}")
                input_tasks.append(task)
            indexed_inputs = _index(input_tasks, "task_id", str(input_path))
            if set(indexed_inputs) != set(task_ids):
                raise ValueError(f"Input/reference task IDs differ in {input_path}")
        else:
            warnings.append(f"Input file missing: {arm}/inputs.jsonl; scoring uses frozen references.")
        for source in (path, input_path):
            if source.exists():
                source_hashes[str(source.relative_to(out))] = hashlib.sha256(source.read_bytes()).hexdigest()

    scored_specs = [spec for spec in specs if references[spec["id"]]["cutoff_evaluable"]]
    scores = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "synthetic": True,
            "annotation_provenance": "assistant_authored_provisional_labels_not_independent_expert",
            "total": len(specs), "scored_total": len(scored_specs),
            "excluded_total": len(specs) - len(scored_specs),
            "label_counts": dict(Counter(spec["expected"] for spec in specs)),
        },
        "evaluation_policy": {
            "primary": "specific-related (EVIDENCE_LINK or NAVIGATION_LINK) versus NO_LINK",
            "denominators": "all scored references, including missing, invalid, and UNCERTAIN outputs",
            "confusion_counts": "TP/TN/FP/FN use valid binary decisions only; other states counted separately",
            "U": "displayed but excluded from reference-label scores",
            "scope": "synthetic fixed-pair verifier stress test, not natural-distribution accuracy or embedding/retrieval evaluation",
            "related_is_not_support": True,
        },
        "families": families,
        "arms": {
            arm: {"all": _score(specs, references, predictions),
                  "by_family": {family: _score(subset, references, predictions) for family, subset in grouped.items()}}
            for arm, predictions in arms.items()
        },
        "symmetry": {
            "all": _symmetry(specs, references, arms),
            "by_family": {family: _symmetry(subset, references, arms) for family, subset in grouped.items()},
        },
        "input_and_prediction_sha256": source_hashes,
        "warnings": warnings,
    }
    scores["complete"] = all(scores["arms"][arm]["all"]["complete"] for arm in ARMS)
    rendered = _render_html(specs, references, arms, scores)
    (out / "scores.json").write_text(json.dumps(scores, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "index.html").write_text(rendered, encoding="utf-8")
    return scores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scores = report(args.output)
    print(json.dumps({
        "output": str(args.output), "complete": scores["complete"], "dataset": scores["dataset"],
        "arms": {arm: scores["arms"][arm]["all"] for arm in ARMS},
        "symmetry": scores["symmetry"]["all"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
