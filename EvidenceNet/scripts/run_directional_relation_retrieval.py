#!/usr/bin/env python3
"""Qwen-free adjacency retrieval and matched source reranking for R0--R5."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from typing import Any

import numpy as np

import encode_directional_relation_views as encoding
import prepare_directional_relation_views as prep

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = prep.DEFAULT_OUT
TASKS = ROOT / "EvidenceNet/output/query_adaptive_evidence_v2_20261030/tasks.jsonl"
NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
HF_CASES = ROOT / "EvidenceNet/output/hf_evidence_comparison_v1_20261031/paired_cases.jsonl"
ARMS = ("R0_dense",) + encoding.ARMS


def enumerate_routes(seeds: list[str], views: list[dict[str, Any]], scores: np.ndarray) -> list[dict[str, Any]]:
    seed_rank = {node_id: rank for rank, node_id in enumerate(seeds, 1)}
    routes = []
    for index, view in enumerate(views):
        if view["source_node_id"] in seed_rank:
            routes.append({"view_id": view["view_id"], "edge_id": view["edge_id"],
                "source_node_id": view["source_node_id"], "target_node_id": view["target_node_id"],
                "source_page": view["source_page"], "target_page": view["target_page"],
                "seed_rank": seed_rank[view["source_node_id"]], "score": float(scores[index]),
                "status": view["status"]})
    return sorted(routes, key=lambda r: (-r["score"], r["seed_rank"], r["edge_id"], r["target_node_id"]))


def select_targets(routes: list[dict[str, Any]], seeds: list[str], budget: int) -> tuple[list[str], list[dict[str, Any]]]:
    selected, seen, decisions = [], set(seeds), []
    for route in routes:
        if route["target_node_id"] in seen:
            decision = "seed_or_duplicate_target"
        elif len(selected) >= budget:
            decision = "budget_full"
        elif route["status"] != "proposal":
            decision = "unavailable_source"
        else:
            decision = "selected"; selected.append(route["target_node_id"]); seen.add(route["target_node_id"])
        decisions.append({**route, "decision": decision})
    return selected, decisions


def _node_text(node: dict[str, Any]) -> str:
    return "\n\n".join(str(m.get("text", "")) for m in node.get("members", []) if m.get("text")).strip()


def retrieve(out: Path, max_new_targets: int) -> dict[str, Any]:
    encoding.check(out)
    em = json.loads((out / "embedding_manifest.json").read_text())
    views = prep.rows(out / "edges_with_views.jsonl")
    tasks = prep.rows(TASKS); nodes_list = prep.rows(NODES); nodes = {n["id"]: n for n in nodes_list}
    query_vectors = np.load(out / em["outputs"]["query"]["file"], allow_pickle=False)
    arm_vectors = {arm: np.load(out / em["outputs"][arm]["file"], allow_pickle=False) for arm in encoding.ARMS}
    scores_out, visits, exposures, reranker = [], [], [], {}
    for qi, task in enumerate(tasks):
        qid, seeds, ranking = task["question_id"], task["seed_nodes"], task["node_ranking"]
        if seeds != ranking[:10]: raise ValueError("seed list is not frozen node Top10")
        dense_extra = [node for node in ranking if node not in set(seeds)][:max_new_targets]
        chosen_by_arm = {"R0_dense": dense_extra}
        paths_by_arm = {"R0_dense": [{"target_node_id": node, "decision": "selected_dense_control",
                                       "dense_rank": ranking.index(node) + 1} for node in dense_extra]}
        for arm in encoding.ARMS:
            route_scores = arm_vectors[arm] @ query_vectors[qi]
            routes = enumerate_routes(seeds, views, route_scores)
            selected, decisions = select_targets(routes, seeds, max_new_targets)
            fallback = [node for node in ranking if node not in set(seeds + selected)][:max_new_targets - len(selected)]
            chosen_by_arm[arm] = selected + fallback
            paths_by_arm[arm] = decisions + [{"target_node_id": node, "decision": "selected_dense_fallback",
                                               "dense_rank": ranking.index(node) + 1} for node in fallback]
            scores_out.extend({"question_id": qid, "arm": arm, **route} for route in routes)
        for arm in ARMS:
            exposed = seeds + chosen_by_arm[arm]
            if len(exposed) != 10 + max_new_targets or len(set(exposed)) != len(exposed):
                raise ValueError("target exposure budget mismatch")
            exposures.append({"question_id": qid, "arm": arm, "seed_nodes": seeds,
                "new_target_nodes": chosen_by_arm[arm], "all_exposed_nodes": exposed,
                "graph_targets": sum(p.get("decision") == "selected" for p in paths_by_arm[arm]),
                "online_llm_calls": 0, "max_new_targets": max_new_targets})
            visits.extend({"question_id": qid, "arm": arm, **path} for path in paths_by_arm[arm])
            for node_id in exposed:
                key = (qid, node_id)
                if key not in reranker:
                    text = _node_text(nodes[node_id])
                    if not text: raise ValueError("exposed node has no original text: " + node_id)
                    rid = prep.digest([qid, node_id])
                    reranker[key] = {"id": rid, "query": task["question"], "text": text,
                                     "question_id": qid, "node_id": node_id,
                                     "page": [nodes[node_id]["document"], str(nodes[node_id]["page"])],
                                     "original_text_sha256": prep.digest(text)}
    prep.jsonl(out / "route_scores.jsonl", scores_out)
    prep.jsonl(out / "routes_visited.jsonl", visits)
    prep.jsonl(out / "candidate_exposures.jsonl", exposures)
    provenance = list(reranker.values())
    prep.jsonl(out / "reranker_inputs.jsonl", ({k: row[k] for k in ("id", "query", "text")} for row in provenance))
    prep.jsonl(out / "reranker_provenance.jsonl", provenance)
    summary = {"queries": len(tasks), "arms": list(ARMS), "max_new_targets": max_new_targets,
               "route_scores": len(scores_out), "reranker_tasks": len(provenance), "online_llm_calls": 0,
               "reading_layer_loaded": False, "gold_read": False}
    prep.write(out / "retrieval_summary.json", summary)
    prep.write(out / "status.json", {"stage": "reranker_ready", "complete": False,
                                      "reranker_processed": 0, "reranker_total": len(provenance)})
    return summary


def report(out: Path) -> dict[str, Any]:
    from run_cached_query_reranker import load_inputs, load_scores
    from evaluate_vldocir import evaluate
    from evaluate_vldocir_ap import average_precision
    inputs = load_inputs(out / "reranker_inputs.jsonl")
    scores = load_scores(out / "reranker_scores.jsonl", inputs, require_complete=True)
    score = {row["id"]: row["score"] for row in scores}
    provenance = prep.rows(out / "reranker_provenance.jsonl")
    meta = {row["id"]: row for row in provenance}
    tasks = prep.rows(TASKS); nodes = {n["id"]: n for n in prep.rows(NODES)}
    exposure = {(r["question_id"], r["arm"]): r for r in prep.rows(out / "candidate_exposures.jsonl")}
    rankings, final_rows, per_query = {arm: {} for arm in ARMS}, [], []
    for task in tasks:
        qid = task["question_id"]
        all_pages = []
        for node_id in task["node_ranking"]:
            page = (nodes[node_id]["document"], str(nodes[node_id]["page"]))
            if page not in all_pages: all_pages.append(page)
        for arm in ARMS:
            seen_nodes = exposure[(qid, arm)]["all_exposed_nodes"]
            ranked_nodes = sorted(seen_nodes, key=lambda node: (-score[prep.digest([qid, node])], node))
            head = []
            for node in ranked_nodes:
                page = (nodes[node]["document"], str(nodes[node]["page"]))
                if page not in head: head.append(page)
            complete = head + [page for page in all_pages if page not in set(head)]
            rankings[arm][qid] = complete
            per_query.append({"question_id": qid, "arm": arm, "exposed_nodes": seen_nodes,
                              "reranked_exposed_nodes": ranked_nodes, "top10_pages": [list(p) for p in complete[:10]],
                              "graph_targets": exposure[(qid, arm)]["graph_targets"]})
            final_rows.extend({"question_id": qid, "arm": arm, "rank": rank, "page": list(page)}
                              for rank, page in enumerate(complete, 1))
    cases = prep.rows(HF_CASES)
    gold = {row["question_id"]: {tuple(page) for page in row["gold_pages"]} for row in cases}
    gold_rows = [{"question_id": qid, "document_id": page[0], "page_number": int(page[1])}
                 for qid, pages in gold.items() for page in pages]
    queries = [{"question_id": task["question_id"], "question": task["question"],
                "question_type": next(row.get("question_type") for row in prep.rows(
                    ROOT / "EvidenceNet/output/hf_evidence_comparison_v1_20261031/tasks.jsonl")
                    if row["question_id"] == task["question_id"])} for task in tasks]
    corpus = {(str(node["document"]), str(node["page"])) for node in nodes.values()}
    def metric(arm):
        ranking = rankings[arm]
        run_rows = [{"question_id": qid, "document_id": page[0], "page_number": int(page[1]), "score": -rank}
                    for qid, pages in ranking.items() for rank, page in enumerate(pages)]
        result = evaluate(queries, gold_rows, run_rows, corpus=corpus)
        for qid, pages in ranking.items():
            for k in (5, 10): result["per_query"][qid][f"AP@{k}"] = average_precision(pages, gold[qid], k)
        for section in ("micro",):
            for k in (5, 10):
                section_rows = [row[f"AP@{k}"] for row in result["per_query"].values()]
                result[section][f"AP@{k}"] = sum(section_rows) / len(section_rows)
        return result
    metrics = {arm: metric(arm) for arm in ARMS}
    prep.jsonl(out / "final_rankings.jsonl", final_rows)
    prep.jsonl(out / "per_query_results.jsonl", per_query)
    aggregate = {"complete": True, "metrics": {arm: metrics[arm]["micro"] for arm in ARMS},
                 "route_labels_available": False, "answer_reader_run": False,
                 "online_llm_calls": 0, "reading_layer_loaded": False,
                 "interpretation": "Page ranking after a shared original-source BGE reranker; no answer correctness claim."}
    prep.write(out / "aggregate.json", aggregate)
    prep.write(out / "status.json", {"stage": "complete", "complete": True,
                                      "reranker_processed": len(scores), "reranker_total": len(inputs)})
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("retrieve", "report"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-new-targets", type=int, choices=(5, 10), default=5)
    args = parser.parse_args()
    result = retrieve(args.out, args.max_new_targets) if args.stage == "retrieve" else report(args.out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
