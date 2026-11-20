"""Post-hoc failure audit for fixed B/C rankings against frozen no-edge scores."""
from __future__ import annotations
import argparse, collections, json
from pathlib import Path
from common import load_config, read_jsonl, repo_path, run_dir, write_json, write_jsonl

BASE = "EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011"
def page(r): return str(r["document_id"]), str(r["page_number"])

def main():
    p = argparse.ArgumentParser(); p.add_argument("--config", required=True); p.add_argument("--input-subdir", default="query_conditioned_retrieval"); args = p.parse_args()
    out = run_dir(load_config(args.config)); result = out / args.input_subdir; base = repo_path(BASE)
    queries = {str(r["question_id"]): r for r in read_jsonl(base / "pilot/queries.jsonl")}
    gold = collections.defaultdict(set)
    for r in read_jsonl(base / "pilot/gold_evidence.jsonl"): gold[str(r["question_id"])].add(page(r))
    frozen = collections.defaultdict(dict)
    for r in read_jsonl(base / "retrieval/hybrid_visual_scores.jsonl"): frozen[str(r["question_id"])][page(r)] = float(r["score"])
    base_rank = {qid: sorted(scores, key=lambda x: (-scores[x], x)) for qid, scores in frozen.items()}
    all_summary = {}
    for arm in ("target_only", "pair_aware"):
        ranking = collections.defaultdict(list); score = {}
        for r in read_jsonl(result / f"{arm}_page_rankings.jsonl"):
            qid, pid = str(r["question_id"]), page(r); ranking[qid].append(pid); score[qid, pid] = r
        traces = collections.defaultdict(set)
        for r in read_jsonl(result / f"{arm}_edge_trace.jsonl"): traces[str(r["question_id"])].add(tuple(r["target_page"]))
        rows = []
        for qid in sorted(queries):
            base5, graph5 = set(base_rank[qid][:5]), set(ranking[qid][:5])
            dropped, added = (base5 - graph5) & gold[qid], (graph5 - base5) & gold[qid]
            reachable = gold[qid] & traces[qid]
            rows.append({"question_id": qid, "question_type": queries[qid]["question_type"], "baseline_top5_gold": [list(x) for x in sorted(base5 & gold[qid])], "graph_top5_gold": [list(x) for x in sorted(graph5 & gold[qid])], "dropped_gold_pages": [list(x) for x in sorted(dropped)], "new_gold_pages": [list(x) for x in sorted(added)], "candidate_reachable_gold_pages": [list(x) for x in sorted(reachable)], "candidate_gold_not_promoted": [list(x) for x in sorted(reachable - graph5)], "top5_pages_changed": len(base5 ^ graph5) // 2, "failure_mode": "DROPPED_GOLD" if dropped else ("REACHABLE_GOLD_NOT_PROMOTED" if reachable - graph5 else ("NO_GRAPH_GOLD_OPPORTUNITY" if not reachable else "NO_TOP5_CHANGE"))})
        write_jsonl(result / f"{arm}_fusion_audit.jsonl", rows)
        count = collections.Counter(r["failure_mode"] for r in rows)
        all_summary[arm] = {"queries": len(rows), "failure_modes": dict(count), "queries_dropping_baseline_top5_gold": sum(bool(r["dropped_gold_pages"]) for r in rows), "queries_with_reachable_gold_not_promoted": sum(bool(r["candidate_gold_not_promoted"]) for r in rows), "mean_top5_pages_changed": sum(r["top5_pages_changed"] for r in rows) / len(rows), "gold_used_only_for": "post-hoc audit"}
    write_json(result / "ranking_fusion_audit_metrics.json", all_summary)
    lines = ["# Ranking / Fusion Failure Audit", "", "此报告在固定 B/C 排名完成后才读取 Gold；不改变 Candidate Graph、Seed、scorer 或融合权重。", "", "| Arm | Drop baseline Top-5 Gold | Reachable Gold 未进入 Top-5 | 平均 Top-5 页替换数 |", "|---|---:|---:|---:|"]
    for arm, x in all_summary.items(): lines.append(f"| {arm} | {x['queries_dropping_baseline_top5_gold']} | {x['queries_with_reachable_gold_not_promoted']} | {x['mean_top5_pages_changed']:.2f} |")
    lines += ["", "失败分类：`DROPPED_GOLD` 是融合引入的明确损失；`REACHABLE_GOLD_NOT_PROMOTED` 表示候选图可达但固定分数未使其进入 Top-5；`NO_GRAPH_GOLD_OPPORTUNITY` 表示当前一跳实际评分边未触及 Gold。几何/聚类指标不作为成功判据。", ""]
    (result / "RANKING_FUSION_AUDIT.md").write_text("\n".join(lines), encoding="utf-8")
    print(result / "RANKING_FUSION_AUDIT.md")

if __name__ == "__main__": main()
