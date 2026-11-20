"""Gold-aware diagnostic: can static candidate edges reach missed Pilot gold pages?

This is explicitly an *opportunity audit*, not a graph retrieval run.  Query and
gold are read only after the Stage-1 candidate graph is fixed; neither is used
to construct, score, filter, or cluster edges.
"""
from __future__ import annotations

import argparse
import collections

from common import load_config, read_jsonl, repo_path, run_dir, write_json, write_jsonl


BASELINE = "EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011"


def page(row):
    return str(row["document_id"]), str(row["page_number"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed-page-k", type=int, choices=(3, 5, 10), default=10)
    args = parser.parse_args()
    config, out = load_config(args.config), run_dir(load_config(args.config))
    base = repo_path(BASELINE)
    queries = {str(row["question_id"]): row for row in read_jsonl(base / "pilot/queries.jsonl")}
    gold = collections.defaultdict(set)
    for row in read_jsonl(base / "pilot/gold_evidence.jsonl"):
        gold[str(row["question_id"])].add(page(row))
    scores = collections.defaultdict(dict)
    for row in read_jsonl(base / "retrieval/hybrid_visual_scores.jsonl"):
        qid, pid = str(row["question_id"]), page(row)
        scores[qid][pid] = max(float(row["score"]), scores[qid].get(pid, float("-inf")))
    nodes_by_page = collections.defaultdict(set)
    for row in read_jsonl(base / "retrieval/node_pages.jsonl"):
        for source_page in row["source_pages"]:
            nodes_by_page[page(source_page)].add(row["node_id"])
    seed_nodes = set()
    top_pages = {}
    for qid in queries:
        ranked = sorted(scores[qid], key=lambda pid: (-scores[qid][pid], pid))
        top_pages[qid] = ranked[:args.seed_page_k]
        seed_nodes.update(node for pid in top_pages[qid] for node in nodes_by_page[pid])
    node_page = {node: pid for pid, nodes in nodes_by_page.items() for node in nodes}
    targets = collections.defaultdict(set)
    candidates = repo_path(config["candidate_union_path"])
    pairs_scanned = 0
    for row in read_jsonl(candidates):
        left, right = row["source_id"], row["target_id"]
        pairs_scanned += 1
        if left in seed_nodes and right in node_page: targets[left].add(node_page[right])
        if right in seed_nodes and left in node_page: targets[right].add(node_page[left])
    per_query = []
    for qid, query in sorted(queries.items()):
        seeds = top_pages[qid]
        seed_set = set(seeds)
        seeds_nodes = set().union(*(nodes_by_page[p] for p in seeds))
        reachable = set().union(*(targets[node] for node in seeds_nodes))
        missed = gold[qid] - seed_set
        reached_missed = missed & reachable
        per_query.append({"question_id": qid, "question_type": query["question_type"], "seed_page_k": args.seed_page_k, "seed_pages": [list(p) for p in seeds], "seed_nodes": len(seeds_nodes), "candidate_target_pages": len(reachable), "gold_pages": [list(p) for p in sorted(gold[qid])], "gold_missed_by_seed": [list(p) for p in sorted(missed)], "candidate_reachable_missed_gold": [list(p) for p in sorted(reached_missed)], "opportunity": bool(reached_missed)})
    write_jsonl(out / f"query_candidate_opportunity_top{args.seed_page_k}.jsonl", per_query)
    by_type = collections.defaultdict(list)
    for row in per_query: by_type[row["question_type"]].append(row)
    def summary(rows):
        missing = sum(bool(r["gold_missed_by_seed"]) for r in rows)
        opportunities = sum(r["opportunity"] for r in rows)
        return {"queries": len(rows), "queries_with_missed_gold": missing, "queries_with_candidate_opportunity": opportunities, "opportunity_given_missed_gold": opportunities / missing if missing else None, "mean_candidate_target_pages": sum(r["candidate_target_pages"] for r in rows) / len(rows)}
    result = {"kind": "gold-aware offline opportunity audit; not graph retrieval", "seed_retriever": "frozen hybrid_visual no-edge baseline", "seed_page_k": args.seed_page_k, "candidate_graph": "static Pilot five-route Top-100 OR union", "candidate_pairs_scanned": pairs_scanned, "candidate_query_independent": True, "query_used_only_for": "post-hoc audit", "gold_used_only_for": "post-hoc audit", "overall": summary(per_query), "by_question_type": {kind: summary(rows) for kind, rows in sorted(by_type.items())}}
    destination = out / f"query_candidate_opportunity_top{args.seed_page_k}_metrics.json"
    write_json(destination, result)
    print(destination)


if __name__ == "__main__":
    main()
