"""Build a truthful same-corpus benchmark table from completed Pilot runs.

Unrun models/graph arms remain explicitly NOT_EVALUATED.  Published full-corpus
paper figures are deliberately not copied into this 24-query Pilot table.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_config, repo_path, run_dir, sha256_file, write_json


METRICS = ("Recall", "nDCG", "RecallAll", "nDCGAll")
KS = (3, 5, 10)


def read_metrics(path: Path):
    if not path.is_file(): return None
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot(name, family, path, version, notes):
    metrics = read_metrics(path)
    if not metrics:
        return {"name": name, "family": family, "status": "NOT_EVALUATED", "notes": notes}
    macro = metrics.get("macro_six_types")
    return {"name": name, "family": family, "status": "EVALUATED_SAME_PILOT", "metrics_path": str(path), "metrics_sha256": sha256_file(path), "model_version": version, "corpus": {"queries": metrics.get("queries"), "pages": metrics.get("corpus_pages", 518)}, "macro_six_types": macro, "per_query": metrics.get("per_query"), "by_question_type": metrics.get("by_question_type"), "notes": notes}


def val(row, key):
    return "—" if row.get("status") != "EVALUATED_SAME_PILOT" else f"{100 * row['macro_six_types'][key]:.2f}%"


def markdown(rows):
    lines = ["# VL-DocIR 24-query Pilot Benchmark Comparison", "", "同一冻结语料：24 Query、518 页、相同 page ID / 去重 / Gold，以及 @3/@5/@10。仅 `EVALUATED_SAME_PILOT` 行可横向比较；Published Reference 与本表严格分开。", "", "| Method | Status | Recall@3 | nDCG@3 | RecallAll@3 | nDCGAll@3 | Recall@5 | nDCG@5 | RecallAll@5 | nDCGAll@5 | Recall@10 | nDCG@10 | RecallAll@10 | nDCGAll@10 |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        cells = [row["name"], row["status"]]
        cells += [val(row, f"{metric}@{k}") for k in KS for metric in METRICS]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## Published Reference", "", "未在本表填写论文完整 VL-DocIR 数字：其语料规模、页库与本 Pilot 不同，不能直接比较。若后续引用论文结果，单独注明论文版本、完整语料规模与评测设置。", "", "## 成本与覆盖", "", "- ColNomic-7B 缓存：24×518 页全评分，历史 H100 Job 82567；当前 manifest 未保存可比 wall-time，因此成本列为 `not_available`，不作效率结论。", "- hybrid_visual：冻结本地 baseline；本表不从旧日志推断其运行时。", "- ColQwen3、OCR-BM25、ColNomic Ctx、ColNomic Ensemble：本工作区未发现可验证的同 Pilot 完整分数，均保持 `NOT_EVALUATED`。", "- B/C/D 已完成；E 尚未运行。所有 Graph arm 必须使用同一 page evaluator，并记录实际 score count、CPU/GPU 时长、显存和候选/目标暴露数。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); args = parser.parse_args()
    out = run_dir(load_config(args.config))
    root = repo_path(".")
    rows = [
        snapshot("A. hybrid_visual No-edge", "internal_no_edge", root / "EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011/retrieval/hybrid_visual_metrics.json", "vldocir_no_edge_v1_20261011", "Frozen no-edge baseline."),
        snapshot("ColNomic-7B original pages", "official_model", root / "EvidenceNet/output/vldocir_colnomic_7b_20261016/metrics.json", "nomic-ai/colnomic-embed-multimodal-7b@09dbc950", "Cached local same-Pilot reproduction; no Ctx/rerank/ensemble."),
        {"name": "ColQwen3", "family": "official_model", "status": "NOT_EVALUATED", "notes": "No verified same-Pilot full score cache found."},
        {"name": "OCR-BM25", "family": "official_model", "status": "NOT_EVALUATED", "notes": "No verified official same-Pilot page-ranking output found."},
        {"name": "ColNomic (Ctx)", "family": "official_model", "status": "NOT_EVALUATED", "notes": "No verified same-Pilot full score cache found."},
        {"name": "ColNomic (Ensemble)", "family": "official_model", "status": "NOT_EVALUATED", "notes": "No verified same-Pilot full score cache found."},
        snapshot("B. DynamicEdgeGraph Target-only", "graph_ablation", out / "query_conditioned_retrieval/target_only_metrics.json", "qwen3-0.6b + full Pilot Top-100 union", "One-hop, 10 frozen hybrid_visual seed pages; target-only graph connectivity baseline."),
        snapshot("C. DynamicEdgeGraph Original Directed Edge", "graph_ablation", out / "query_conditioned_retrieval/pair_aware_metrics.json", "qwen3-0.6b + E0 MidDiff components", "One-hop, same seeds/candidates; query-conditioned source-target difference and midpoint scoring."),
        snapshot("D. DynamicEdgeGraph Cluster / Prototype Context", "graph_ablation", out / "query_conditioned_retrieval_cluster_context/pair_aware_metrics.json", "qwen3-0.6b + E0 MidDiff + K32 hard prototype", "One-hop, same seeds/candidates/fusion as C; nearest hard prototype context, fixed weight 0.10."),
        {"name": "E. DynamicEdgeGraph Dynamic Edge Updating", "family": "graph_ablation", "status": "NOT_EVALUATED", "notes": "Requires full Candidate Union update coverage; sampled updates may not be mixed with original edges."},
    ]
    payload = {"dataset": "VL-DocIR frozen Pilot", "queries": 24, "pages": 518, "evaluation": {"ks": list(KS), "metrics": list(METRICS), "aggregation": "page max score, deterministic page-ID tie-break, macro over six question types", "same_corpus_required_for_comparison": True}, "rows": rows, "published_reference": {"status": "SEPARATE_NOT_COMPARABLE", "reason": "Full-paper VL-DocIR results use a different corpus scale and are not inserted into Pilot results."}}
    write_json(out / "benchmark_comparison.json", payload)
    (out / "BENCHMARK_COMPARISON.md").write_text(markdown(rows), encoding="utf-8")
    print(out / "BENCHMARK_COMPARISON.md")


if __name__ == "__main__": main()
