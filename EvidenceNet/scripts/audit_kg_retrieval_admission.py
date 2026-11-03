#!/usr/bin/env python3
"""CPU-only frozen-ranking KG admission audit; no inference or gold labels.

Reads the original frozen node rankings and MODEL-accepted bounded verifier
edges. Quantifies how many edges are reachable and which targets could enter
a FIXED node candidate budget after deterministic replacement of its tail.
This is an eligibility/candidate-admission diagnostic, NOT reranking,
retrieval-quality evaluation, or promotion of model-reviewed edges to gold.

Never reruns OCR, embedding, model verification or Slurm internally.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NAVIGATION = ROOT / "EvidenceNet/output/top10_node_navigation_20261029/navigation.jsonl"
DEFAULT_EDGES = (ROOT / "EvidenceNet/output/"
                 "kg_link_prediction_bounded_verification_ultra_smoke_v1_20261102/"
                 "accepted_new_edges_model_only.jsonl")
DEFAULT_OUTPUT = ROOT / "EvidenceNet/output/kg_retrieval_admission_20261103"


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def dump_new(path, records):
    """Exclusive creation: never silently replace frozen experiment artifacts."""
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def stable_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def permitted_routes(edge):
    """Preserve verifier direction: an A_TO_B relation cannot be inverted."""
    direction = edge.get("direction")
    if direction not in {"A_TO_B", "B_TO_A", "BIDIRECTIONAL", "UNDIRECTED"}:
        raise ValueError("unrecognized edge direction")
    if direction in {"A_TO_B", "BIDIRECTIONAL", "UNDIRECTED"}:
        yield edge["source_id"], edge["target_id"], "stored"
    if direction in {"B_TO_A", "BIDIRECTIONAL", "UNDIRECTED"}:
        yield edge["target_id"], edge["source_id"], "inverse"


def audit(navigation, edges, *, budget=20, core=10, graph_slots=3):
    """Counterfactual frozen top-B admission, without scores or query gold.

    Preserve core entries and the total node budget. Eligible KG targets
    displace only the dense tail; never infer whether reranker would select
    them. One target is admitted at most once per query.
    """
    if not 0 < core <= budget or not 0 <= graph_slots <= budget - core:
        raise ValueError("invalid core/budget/graph_slots")
    eids = [e.get("edge_id") for e in edges]
    if not all(isinstance(i, str) and i for i in eids) or len(set(eids)) != len(eids):
        raise ValueError("duplicate or missing edge ID")
    traces, summaries = [], []
    qids = set()
    for ctx in navigation:
        qid = ctx["question_id"]
        if qid in qids:
            raise ValueError("duplicate question ID")
        qids.add(qid)
        ranking = ctx["node_ranking"]
        if len(ranking) != len(set(ranking)):
            raise ValueError("duplicate node in frozen ranking")
        if not ranking:
            raise ValueError("empty frozen node ranking")
        seeds = ctx["seed_nodes"]
        if len(seeds) != len(set(seeds)) or any(s not in ranking for s in seeds):
            raise ValueError("invalid frozen seeds")
        baseline = ranking[:budget]
        ranks = {node: i + 1 for i, node in enumerate(ranking)}
        eligible = []
        missing_endpoints = 0
        for edge in edges:
            if edge.get("edge_type") not in {"EVIDENCE_LINK", "NAVIGATION_LINK"}:
                raise ValueError("expected model-reviewed accepted edge")
            for source, target, orientation in permitted_routes(edge):
                if source not in ranks or target not in ranks:
                    missing_endpoints += 1
                    continue
                if source not in seeds:
                    continue
                eligible.append({
                    "question_id": qid, "edge_id": edge["edge_id"],
                    "edge_type": edge["edge_type"],
                    "seed_id": source, "seed_initial_rank": ranks[source],
                    "target_id": target, "target_initial_rank": ranks[target],
                    "direction": orientation,
                    "target_in_baseline_top_budget": target in baseline,
                    "target_in_seed_set": target in seeds,
                    "review_level": edge.get("review_level"),
                    "query_scope_checked": False,
                    "reranker_executed": False,
                })
        eligible.sort(key=lambda row: (
            row["seed_initial_rank"], row["target_initial_rank"],
            row["edge_id"], row["direction"]))
        # Reserve up to graph_slots of the last budget-core positions.
        promoted, seen_targets = [], set(baseline)
        for row in eligible:
            if row["target_id"] in seen_targets or len(promoted) >= graph_slots:
                continue
            promoted.append(row["target_id"])
            seen_targets.add(row["target_id"])
        kept_dense = [n for n in baseline if n not in promoted]
        # Never displace core or reintroduce a promoted target.
        selected = ranking[:core] + promoted
        selected += [n for n in ranking[core:] if n not in selected][:max(0, budget - len(selected))]
        if (len(selected) != min(budget, len(ranking))
                or len(set(selected)) != len(selected)
                or selected[:core] != ranking[:core]):
            raise ValueError("fixed-budget/core invariant failed")
        promoted_set = set(promoted)
        for row in eligible:
            row["admission"] = (
                "already_in_control" if row["target_in_baseline_top_budget"]
                else "admitted" if row["target_id"] in promoted_set
                else "budget_or_duplicate_rejected"
            )
            row["final_candidate_rank"] = (
                selected.index(row["target_id"]) + 1
                if row["target_id"] in selected else None
            )
        traces.extend(eligible)
        summaries.append({
            "question_id": qid, "frozen_seed_count": len(seeds),
            "reachable_routes": len(eligible),
            "novel_targets_admitted": len(promoted),
            "control_candidate_ids": baseline,
            "kg_candidate_ids": selected,
            "replaced_dense_tail_ids": [n for n in baseline if n not in selected],
            "candidate_budget_held": len(selected) == min(budget, len(ranking)),
            "reranker_executed": False,
        })
    return traces, summaries


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--navigation", type=Path, default=DEFAULT_NAVIGATION)
    p.add_argument("--edges", type=Path, default=DEFAULT_EDGES)
    p.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--budget", type=int, default=20)
    p.add_argument("--core", type=int, default=10)
    p.add_argument("--graph-slots", type=int, default=3)
    args = p.parse_args()
    for name, path in (("navigation", args.navigation), ("edges", args.edges)):
        if not path.is_file():
            p.error(f"missing {name} file: {path}")
    if args.out.exists():
        p.error("output directory already exists; choose a new --out to preserve history")
    navigation, edges = read_jsonl(args.navigation), read_jsonl(args.edges)
    traces, summaries = audit(navigation, edges, budget=args.budget,
                              core=args.core, graph_slots=args.graph_slots)
    totals = Counter(row["admission"] for row in traces)
    result = {
        "status": "FROZEN_CANDIDATE_ADMISSION_AUDIT_COMPLETE",
        "queries": len(summaries), "model_accepted_edges": len(edges),
        "reachable_routes": len(traces),
        "admission_counts": dict(totals),
        "queries_with_reachable_routes": sum(bool(row["reachable_routes"]) for row in summaries),
        "queries_with_novel_admissions": sum(bool(row["novel_targets_admitted"]) for row in summaries),
        "total_novel_admitted_targets": sum(row["novel_targets_admitted"] for row in summaries),
        "budget": args.budget, "core": args.core, "graph_slots": args.graph_slots,
        "navigation_sha256": stable_digest(args.navigation),
        "edges_sha256": stable_digest(args.edges),
        "scope_evaluated": False, "reranker_executed": False,
        "gold_consulted": False, "retrieval_metrics_available": False,
        "caution": "Model-reviewed accepted edges, not human gold. Admission != relevance or rank gain.",
    }
    args.out.mkdir(parents=True)
    dump_new(args.out / "routes.jsonl", traces)
    dump_new(args.out / "per_query.jsonl", summaries)
    (args.out / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
