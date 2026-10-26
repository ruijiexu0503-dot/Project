#!/usr/bin/env python3
"""Source-backed review of the completed/partial HoReKa v1 results."""
from collections import Counter
from html import escape
import json
from pathlib import Path

import run_routed_edge_context as exp
from run_node_context_edges import ROOT, rows, jsonl, write

OUT = ROOT / "EvidenceNet/output/edge_context_failure_audit_20261020"
RESULTS = ROOT / "migration/horeka-edge-context-20261018/results"
NOTES = {
    "P07": "bounded 转而比较 HTVGNN 与 STTN，忽略两端关于 DCRNN/STGCN 固定图局限的局部对应。应按具体被比较的组件/claim限定关系。",
    "P08": "不同主模型不应自动否定原文明确描述的局部空间依赖机制；先比较局部claim，再记录方法差异。",
    "P10": "两端都谈 position encoding，但因 DETR 与交通 Transformer 不同而拒绝。共享机制与整个模型同一性需要分开。",
    "P11": "两端均出现 multi-head attention；若没有同一局部claim，可以是具名组件导航，不必认定整个模型相同。",
    "P12": "同一 L1 数学操作在不同任务的角色被上下文差异压过；公式上下文需解释符号，并保留局部数学对应。",
    "P13": "旧无效输出含名称/属性混写，例如把日期附加到数据集名，导致逐字原文校验失败。保留硬校验，拆开实体名与属性。",
    "N06": "228 与 883 个传感器不能当成可互换评测总体。RELATED参考正例不等于可以提升为同一数据集实例的强证据边；应保留子集/总体差异。",
    "U03": "原文都有 Adam 等具名训练组件；主模型/超参不同可以保留在 limitation，共享组件只作为导航。",
    "N22": "三组已处理输出均拒绝连接，但元数据曾把 FUSU-Net 模型写为 DATASET。决策通过校验不代表所有解释语义正确。",
    "N17": "图像提示的词与 OCR 原文并不一致；不能把未在原文出现的修正词当作经过验证的身份锚。",
}


def main():
    nodes = {n["id"]: n for n in rows(exp.prior.CORPUS / "corpus_nodes.jsonl")}
    formulas = {b["formula"]["node_id"] for b in rows(exp.prior.FORMULAS)}
    entries = rows(exp.prior.SOURCE / "inputs.jsonl")
    references = rows(exp.prior.SOURCE / "evaluation/reference.jsonl")
    by_id = {e["task"]["task_id"]: e for e in entries}
    for entry in entries:
        kinds = [exp.modality(nodes[entry["task"][s]["node_id"]], formulas) for s in ("A", "B")]
        entry["routing"] = {"group": "visual_table" if "visual_table" in kinds else "formula" if "formula" in kinds else "prose"}
    predictions, summary = {}, {}
    for arm in ("anchor", "bounded", "neighbors"):
        values = rows(RESULTS / f"edge_context_ablation_{arm}_v1_20261018/predictions.jsonl")
        predictions[arm] = {p["task_id"]: p for p in values}
        errors = Counter(a.get("error", "") for p in values if not p["valid"] for a in p["attempts"] if not a["valid"])
        summary[arm] = {"processed": len(values), "total": len(entries), "invalid": sum(not p["valid"] for p in values),
                        "error_counts": dict(errors), "evaluation": exp.evaluate(entries, values, references)}
    records = []
    for ref in references:
        tid = ref["task_id"]
        entry = by_id[tid]
        record = {"case_id": ref["suite_case_id"], "group": entry["routing"]["group"], "reference": ref,
                  "diagnosis": NOTES.get(ref["suite_case_id"], ""), "endpoints": {}, "predictions": {}}
        for side in ("A", "B"):
            node = nodes[entry["task"][side]["node_id"]]
            record["endpoints"][side] = {"node_id": node["id"], "document": node["document"],
                "text": "\n\n".join(m.get("text", "") for m in node["members"] if m["kind"] == "atom")}
        for arm in predictions:
            p = predictions[arm].get(tid)
            record["predictions"][arm] = {"decision": "MISSING" if p is None else "INVALID" if not p["valid"] else p["result"]["decision"],
                 "reason": p["result"]["reason"] if p and p["valid"] else "",
                 "errors": [a.get("error") for a in p["attempts"] if not a["valid"]] if p else []}
        records.append(record)
    jsonl(OUT / "cases.jsonl", records)
    write(OUT / "summary.json", summary)
    table = []
    for arm, values in summary.items():
        scores = values["evaluation"]["all"]
        table.append(f"|{arm}|{values['processed']}/103|{scores.get('useful_tp', 0)}/{scores['positive_total']}|{scores.get('useful_fp', 0)}|{values['invalid']}|")
    intro = ("这是已完成/部分完成的旧 v1 实验审计。参考为开发集 RELATED 临时标注；不等于独立专家确认的强证据边。"
             "31 正例、25 负例、2 个争议例，其余固定pair无参考标签。无效/未完成输出保留在全分母中。"
             "旧context拒绝条件有逻辑错误，因此新试验重建共同基线。")
    markdown = intro + "\n\n|方案|处理|有效关联正例/全正例|已接受FP|全部无效输出|\n|---|---:|---:|---:|---:|\n" + "\n".join(table)
    markdown += "\n\n" + "\n\n".join(f"{k}：{v}" for k, v in NOTES.items())
    markdown += "\n\n召回阶段：此前 P01/P02/P08/P11 已进入初始池，但在article route/degree cap/pair quota阶段丢失。修复方向是候选分配与局部claim检索，并非给最终verifier增加上下文。\n"
    (OUT / "audit.md").write_text(markdown)
    cards = []
    for record in records:
        decisions = " · ".join(f"{a}: {p['decision']}" for a, p in record["predictions"].items())
        endpoints = "".join(f"<section><h4>{side} · {escape(e['node_id'])}</h4><pre>{escape(e['text'])}</pre></section>" for side, e in record["endpoints"].items())
        reasons = "".join(f"<p><b>{arm}</b>: {escape(p['reason'])} {escape('; '.join(p['errors']))}</p>" for arm, p in record["predictions"].items())
        cards.append(f"<article data-group='{record['group']}' id='{record['case_id']}'><h3>{record['case_id']} · {record['group']}</h3><p>{escape(decisions)}</p><p>{escape(record['diagnosis'])}</p><details><summary>查看两端原文和模型理由</summary><div class='pair'>{endpoints}</div>{reasons}</details></article>")
    html = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>上下文实验失败审计</title>
<style>body{font:16px/1.6 system-ui;background:#f6f5f1;color:#242829;margin:0}main{max-width:1150px;margin:auto;padding:28px}article{background:white;border:1px solid #ddd;border-radius:10px;padding:18px;margin:16px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}section{min-width:0}pre{white-space:pre-wrap;max-height:430px;overflow:auto;font-size:13px;background:#f1f3f2;padding:12px}select{padding:8px}h1{font-size:26px}summary{cursor:pointer}@media(max-width:750px){.pair{grid-template-columns:1fr}}</style><main><h1>上下文与纯文本失败审计</h1>"""
    html += f"<p>{escape(intro)}</p><p>完整结果：<a href='audit.md'>审计说明</a> · <a href='summary.json'>分层指标</a> · <a href='cases.jsonl'>逐例原始数据</a></p>"
    html += "<p>筛选：<select id='filter'><option value='all'>全部</option><option value='prose'>纯文本</option><option value='formula'>公式</option><option value='visual_table'>图表</option></select></p>" + "".join(cards)
    html += "<script>document.getElementById('filter').onchange=function(){document.querySelectorAll('article').forEach(e=>{e.hidden=this.value!=='all'&&e.dataset.group!==this.value})}</script></main></html>"
    (OUT / "index.html").write_text(html)
    print(json.dumps({"output": str(OUT), "cases": len(records)}))


if __name__ == "__main__":
    main()
