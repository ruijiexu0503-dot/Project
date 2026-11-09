#!/usr/bin/env python3
"""Compare frozen Dense Top-13 with the already completed D1 candidates.

This script never loads an encoder and never changes the D1 output. Gold and
requirement files are opened only after all three node sets are constructed.
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "migration/vldocir_trace_inputs_20261023"
SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
D1 = ROOT / "EvidenceNet/output/missing_requirement_retrieval_d1_v1_20261106"
ORACLE = ROOT / "EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/query_coverage_matrix.jsonl"
REQ = ROOT / "EvidenceNet/output/answer_requirement_sufficiency_audit_v2_20261106/query_requirement_diagnostics.jsonl"
OUT = ROOT / "EvidenceNet/output/budget_matched_dense_control_v1_20261106"


def rows(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8") if line.strip()]


def requirement_state(requirements, node_ids, text_by_node):
    text = " ".join(text_by_node.get(node, "") for node in node_ids).lower()
    result = []
    for item in requirements:
        groups = item["requirement"].get("groups", [])
        matched = [group for group in groups if any(term.lower() in text for term in group)]
        state = ("missing" if not matched else
                 "supported" if len(matched) == len(groups) else "partial")
        result.append({"requirement_id": item["requirement"]["id"],
                       "label": item["requirement"]["label"], "state": state})
    return result


def main():
    queries = rows(TRACE / "queries.jsonl")
    units = rows(TRACE / "units.jsonl")
    windows = rows(TRACE / "windows.jsonl")
    views = rows(SOURCE / "views.jsonl")
    nodes = {r["id"]: (r["document"], int(r["page"])) for r in rows(SOURCE / "nodes.jsonl")}
    eligible = {r["node_id"] for r in views}
    text_by_node = {}
    for view in views:
        text_by_node[view["node_id"]] = max(
            text_by_node.get(view["node_id"], ""), view.get("quote", ""), key=len
        )
    d1_rows = {r["question_id"]: r for r in rows(D1 / "query_results.jsonl")}
    score_cache = np.load(SOURCE / "search/query_window_scores.npy", mmap_mode="r")
    unit_by_line = {i + 1: row for i, row in enumerate(units)}
    original_rankings = {}
    for qi, query in enumerate(queries):
        scores = {}
        for wi, window in enumerate(windows):
            node_id = unit_by_line[window["unit_input_line"]]["unit_id"]
            if node_id in eligible:
                scores[node_id] = max(scores.get(node_id, -np.inf), float(score_cache[qi, wi]))
        original_rankings[query["question_id"]] = [
            node for node, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        ]

    oracle = {r["question_id"]: r for r in rows(ORACLE)}
    requirements = {r["question_id"]: r for r in rows(REQ)}
    diagnostics = []
    for query in queries:
        qid = query["question_id"]
        ranking = original_rankings[qid]
        d0 = ranking[:10]
        dense13 = ranking[:13]
        d1_added = [r["node_id"] for r in d1_rows[qid]["d1_added"]]
        d1 = d0 + d1_added
        if len(set(d1)) != 13:
            raise ValueError(f"D1 is not exactly 13 unique nodes: {qid}")
        source_ranks = {node: i + 1 for i, node in enumerate(ranking)}
        gold = oracle[qid]

        def metric(ids):
            pages = {nodes[node] for node in ids if node in nodes}
            page_complete = bool(gold["gold_pages"]) and all(tuple(p) in pages for p in gold["gold_pages"])
            strong_by_item = [
                {c["node_id"] for c in item.get("eligible_strong_candidates", [])}
                for item in gold["gold_item_diagnostics"]
            ]
            bbox = bool(strong_by_item) and all(set(ids) & strong for strong in strong_by_item)
            req = requirement_state(requirements[qid]["requirements"], ids, text_by_node)
            return page_complete, bbox, req

        arms = {}
        for name, ids in (("d0_top10", d0), ("dense_top13", dense13), ("d1", d1)):
            page, bbox, req = metric(ids)
            arms[name] = {
                "node_ids": ids,
                "gold_page_complete": page,
                "bbox_supported": bbox,
                "requirement_states": req,
                "requirement_fully_supported": all(x["state"] == "supported" for x in req),
            }
        diagnostics.append({
            "question_id": qid,
            "question": query["question"],
            "arms": arms,
            "d1_added_nodes": [
                {"node_id": node, "original_dense_rank": source_ranks.get(node)}
                for node in d1_added
            ],
            "d1_only_vs_dense13": sorted(set(d1) - set(dense13)),
            "dense13_only_vs_d1": sorted(set(dense13) - set(d1)),
            "d1_gold_evaluation_reference_ignored": True,
            "requirement_review_basis": "AI-assisted token-group diagnostic, not human Gold",
        })

    def count(arm, field):
        return sum(d["arms"][arm][field] for d in diagnostics)

    summary = {
        "queries": len(diagnostics),
        "budget": {"d0_top10": 10, "dense_top13": 13, "d1": 13},
        "gold_page_complete": {a: count(a, "gold_page_complete") for a in ("d0_top10", "dense_top13", "d1")},
        "bbox_supported": {a: count(a, "bbox_supported") for a in ("d0_top10", "dense_top13", "d1")},
        "ai_assisted_requirement_fully_supported": {
            a: count(a, "requirement_fully_supported") for a in ("d0_top10", "dense_top13", "d1")
        },
        "d1_embedding_cost_seconds": 200.58948638709262,
        "dense_control_embedding_cost_seconds": 0,
        "d1_added_node_count": 72,
        "d1_added_original_rank": {
            "min": min(x["original_dense_rank"] for d in diagnostics for x in d["d1_added_nodes"]),
            "max": max(x["original_dense_rank"] for d in diagnostics for x in d["d1_added_nodes"]),
            "mean": sum(x["original_dense_rank"] for d in diagnostics for x in d["d1_added_nodes"]) / 72,
        },
        "d1_gold_or_requirement_inputs_used_for_ranking": False,
        "gold_and_requirement_opened_after_node_sets": True,
        "prior_d1_gold_evaluation_reference_used": False,
        "unknown_edges_counted": False,
    }
    summary["d1_unique_gain_vs_dense13"] = {
        field: sum(
            d["arms"]["d1"][field] and not d["arms"]["dense_top13"][field]
            for d in diagnostics
        )
        for field in ("gold_page_complete", "bbox_supported", "requirement_fully_supported")
    }
    summary["dense13_unique_gain_vs_d1"] = {
        field: sum(
            d["arms"]["dense_top13"][field] and not d["arms"]["d1"][field]
            for d in diagnostics
        )
        for field in ("gold_page_complete", "bbox_supported", "requirement_fully_supported")
    }
    summary["d1_added_rank_buckets"] = {
        "11-13": sum(11 <= x["original_dense_rank"] <= 13 for d in diagnostics for x in d["d1_added_nodes"]),
        "14-20": sum(14 <= x["original_dense_rank"] <= 20 for d in diagnostics for x in d["d1_added_nodes"]),
        "21+": sum(x["original_dense_rank"] >= 21 for d in diagnostics for x in d["d1_added_nodes"]),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "budget_matched_diagnostics.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in diagnostics)
    )
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    (OUT / "BUDGET_MATCHED_REPORT.md").write_text(
        "# Budget-Matched Dense Control\n\n"
        "三组 Arm 均按 13 个 Node 评估：D0+ 是原始 Dense Top-13，D1 是冻结 D0 Top-10 加既有 D1 的 3 个新增 Node。"
        "本轮未重新生成 Embedding，未修改 D1 输出。\n\n"
        "## Results\n\n"
        f"- Gold Page 完整覆盖：D0 {summary['gold_page_complete']['d0_top10']}/24；"
        f"D0+ {summary['gold_page_complete']['dense_top13']}/24；"
        f"D1 {summary['gold_page_complete']['d1']}/24。\n"
        f"- bbox-supported：D0 {summary['bbox_supported']['d0_top10']}/24；"
        f"D0+ {summary['bbox_supported']['dense_top13']}/24；"
        f"D1 {summary['bbox_supported']['d1']}/24。\n"
        f"- AI-assisted 完整 Requirement：D0 {summary['ai_assisted_requirement_fully_supported']['d0_top10']}/24；"
        f"D0+ {summary['ai_assisted_requirement_fully_supported']['dense_top13']}/24；"
        f"D1 {summary['ai_assisted_requirement_fully_supported']['d1']}/24。\n\n"
        f"- D1 相比 Dense Top-13 的独有收益：Gold Page {summary['d1_unique_gain_vs_dense13']['gold_page_complete']}；"
        f"bbox {summary['d1_unique_gain_vs_dense13']['bbox_supported']}；"
        f"Requirement {summary['d1_unique_gain_vs_dense13']['requirement_fully_supported']}。\n"
        f"- D1 新增 Node 的原始 Dense rank：11–13 共 {summary['d1_added_rank_buckets']['11-13']}；"
        f"14–20 共 {summary['d1_added_rank_buckets']['14-20']}；"
        f"21+ 共 {summary['d1_added_rank_buckets']['21+']}。\n\n"
        "D1 的 72 个新增 Node 原始 Dense rank、逐 Query 差异和三组状态见 "
        "`budget_matched_diagnostics.jsonl`。\n\n"
        "## Leakage audit\n\n"
        "- D1 Subquery 已在先前运行完成；本轮只复用其输出，不重新生成。\n"
        "- 本轮排序集合只来自冻结 Dense cache 与既有 D1 Node IDs。\n"
        "- Gold、Gold Node、Requirement label 和答案信息均在构造排序集合后才读取。\n"
        "- 既有 D1 `gold_evaluation_reference` 字段被明确忽略。\n"
        "- unknown Edge 未计入任何 Arm。\n\n"
        "## Interpretation\n\n"
        "- D1 相比 Dense Top-13 的独有收益需要同时满足 D1=True 且 Dense Top-13=False；逐 Query 结果中可直接核对。\n"
        "- Federer 的 Page Recovery 若只改变 Gold Page 指标而不改变 Requirement 状态，说明恢复的是页面/重复证据，不是答案条件增益。\n"
        "- CNN 的 bbox 增益 Dense Top-13 也获得；LighTDiff/MIRNetv2 两组均未获得新的完整 Requirement，因此 D1 没有这些案例的独有收益。\n"
    )


if __name__ == "__main__":
    main()
