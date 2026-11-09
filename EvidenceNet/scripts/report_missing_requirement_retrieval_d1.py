#!/usr/bin/env python3
"""Evaluate the completed D1 replay without changing retrieval decisions."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "EvidenceNet/output/missing_requirement_retrieval_d1_v1_20261106"
ORACLE = ROOT / "EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/query_coverage_matrix.jsonl"
REQ = ROOT / "EvidenceNet/output/answer_requirement_sufficiency_audit_v2_20261106/query_requirement_diagnostics.jsonl"
VIEWS = ROOT / "migration/vldocir-edge-20261022/results/views.jsonl"
NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"


def rows(path):
    return [json.loads(line) for line in Path(path).open() if line.strip()]


def requirement_state(requirements, node_ids, text_by_node):
    text = " ".join(text_by_node.get(node, "") for node in node_ids).lower()
    states = []
    for item in requirements:
        groups = item["requirement"].get("groups", [])
        matched = [group for group in groups if any(term.lower() in text for term in group)]
        if not groups or not matched:
            state = "missing"
        elif len(matched) == len(groups):
            state = "supported"
        else:
            state = "partial"
        states.append({"requirement_id": item["requirement"]["id"],
                       "label": item["requirement"]["label"], "state": state})
    return states


def main():
    result_rows = rows(OUT / "query_results.jsonl")
    oracle = {r["question_id"]: r for r in rows(ORACLE)}
    requirements = {r["question_id"]: r for r in rows(REQ)}
    views = rows(VIEWS)
    nodes = {r["id"]: (r["document"], int(r["page"])) for r in rows(NODES)}
    text_by_node = {}
    for view in views:
        text_by_node.setdefault(view["node_id"], "")
        text_by_node[view["node_id"]] = max(
            text_by_node[view["node_id"]], view.get("quote", ""), key=len
        )
    diagnostics = []
    for result in result_rows:
        qid = result["question_id"]
        oracle_row = oracle[qid]
        d0 = [x["node_id"] for x in result["d0_top10"]]
        d1 = result["d1_top13_node_ids"]
        def metric(ids):
            pages = {nodes[node] for node in ids if node in nodes}
            page_hit = int(all(tuple(page) in pages for page in oracle_row["gold_pages"]))
            strong_by_item = [
                {candidate["node_id"] for candidate in item.get("eligible_strong_candidates", [])}
                for item in oracle_row["gold_item_diagnostics"]
            ]
            bbox_hit = bool(strong_by_item) and all(set(ids) & strong for strong in strong_by_item)
            req = requirement_state(
                requirements[qid]["requirements"], ids, text_by_node
            )
            return page_hit, bbox_hit, req
        d0_page, d0_bbox, d0_req = metric(d0)
        d1_page, d1_bbox, d1_req = metric(d1)
        diagnostics.append({
            "question_id": qid, "question": result["question"],
            "d0_gold_page_hits": d0_page, "d1_gold_page_hits": d1_page,
            "d0_bbox_supported": d0_bbox, "d1_bbox_supported": d1_bbox,
            "d0_requirement_states": d0_req, "d1_requirement_states": d1_req,
            "new_nodes": result["d1_added"],
            "requirement_review_basis": "AI-assisted token-group audit, not human Gold; prior labels were not used as truth",
        })
    def totals(key):
        return sum(1 for row in diagnostics if row[key])
    summary = {
        "queries": len(diagnostics),
        "d0_gold_page_complete": totals("d0_gold_page_hits"),
        "d1_gold_page_complete": totals("d1_gold_page_hits"),
        "d0_bbox_supported_queries": totals("d0_bbox_supported"),
        "d1_bbox_supported_queries": totals("d1_bbox_supported"),
        "requirement_coverage": "AI-assisted diagnostic only; not Ground Truth",
        "d0_requirement_supported_queries": sum(
            all(x["state"] == "supported" for x in r["d0_requirement_states"])
            for r in diagnostics
        ),
        "d1_requirement_supported_queries": sum(
            all(x["state"] == "supported" for x in r["d1_requirement_states"])
            for r in diagnostics
        ),
        "g1_graph_opportunity": "Recorded inspection-only; unknown Edge was not allowed or counted",
        "added_candidates": sum(len(r["new_nodes"]) for r in diagnostics),
        "no_gold_page_gain_queries": sum(
            r["d0_gold_page_hits"] == r["d1_gold_page_hits"] for r in diagnostics
        ),
        "subquery_candidates_beyond_top20": sum(
            any(x["subquery_dense_rank"] > 20 for x in r["new_nodes"])
            for r in diagnostics
        ),
    }
    (OUT / "d0_vs_d1_diagnostics.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in diagnostics)
    )
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    report = [
        "# Missing-Requirement Retrieval Baseline (D1)",
        "",
        "本报告是独立的 D0/D1 replay；24 个 Query 全部保留。",
        "",
        "## Protocol",
        "- D0：冻结 `query_window_scores.npy` 的原始 Top-10。",
        "- D1：Query + D0 Node 文本生成 deterministic subquery；同一 6,520 Node universe；最多新增 3 个 Node。",
        "- 不使用 Gold、Gold Node ID 或评估标签构造 Subquery。",
        "- Gold page/bbox 只在排序完成后离线评估。",
        "- Requirement Coverage 是 AI-assisted token-group diagnostic，不是人工 Gold，也不把上一轮分类当作真值。",
        "",
        "## Summary",
        f"- Gold page hit queries: D0 {summary['d0_gold_page_complete']}/24 -> D1 {summary['d1_gold_page_complete']}/24",
        f"- bbox-supported queries: D0 {summary['d0_bbox_supported_queries']}/24 -> D1 {summary['d1_bbox_supported_queries']}/24",
        f"- AI-assisted fully-supported requirement queries: D0 {summary['d0_requirement_supported_queries']}/24 -> D1 {summary['d1_requirement_supported_queries']}/24",
        "- D1 每个 Query 生成 3 个新增候选；具体候选、原始 rank 和页见 `query_results.jsonl`。",
        "- G1 仅记录 inspection-only opportunity；unknown Edge 未升级为 allowed，未计入正式导航收益。",
        "",
        "## Concrete outcomes",
        f"- 新增候选总数：{summary['added_candidates']}；其中至少有一个 Subquery rank > 20 的 Query：{summary['subquery_candidates_beyond_top20']}/24。",
        f"- 无 Gold page completeness 增益：{summary['no_gold_page_gain_queries']}/24；D1 不是对所有 Query 都有收益。",
        "- 典型正向案例：CNN Query 获得 bbox-supported evidence；LighTDiff/MIRNetv2 Query 的 AI-assisted MIRNetv2 requirement 从 partial 变为 supported；Federer Query 的 page gain 不等于新的答案充分性证明。",
        "- 典型失败案例：opening ceremony、Steffi Graf、Revolve phone 和 Federer 等 Query 的新增候选没有形成 bbox-supported 增益；这说明 subquery 可能扩展到相关但不具备目标空间证据的 Node。",
        "",
        "## Per-query diagnostics",
        "完整逐 Query、逐 Requirement 结果见 `d0_vs_d1_diagnostics.jsonl`。",
    ]
    (OUT / "D1_REPORT.md").write_text("\n".join(report) + "\n")


if __name__ == "__main__":
    main()
