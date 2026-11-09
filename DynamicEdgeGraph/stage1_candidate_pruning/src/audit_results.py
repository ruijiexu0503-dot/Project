"""Audit canonical Node accounting, route overlaps, and reviewed-pair recall."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from .common import load_config, read_jsonl, repo_path, run_dir, write_jsonl


def pair(row):
    return tuple(sorted((str(row["source_id"]), str(row["target_id"]))))


def load_reviewed(path):
    labels = {}
    for row in read_jsonl(path):
        a = row.get("A", {}).get("node_id")
        b = row.get("B", {}).get("node_id")
        if not a or not b or a == b:
            continue
        key = tuple(sorted((str(a), str(b))))
        labels[key] = {
            "label": row.get("label", "UNKNOWN"),
            "relation": row.get("relation"),
            "case_id": row.get("case_id", row.get("suite_case_id")),
            "source": str(path),
        }
    return labels


def budget_pairs(rows, budget):
    best_rank = {}
    for row in rows:
        key = pair(row)
        best_rank[key] = min(best_rank.get(key, math.inf), int(row["rank"]))
    return {key for key, rank in sorted(best_rank.items(), key=lambda item: (item[1], item[0]))[:budget]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--reviewed-cases", default="EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/evaluation/cases.jsonl")
    args = parser.parse_args()
    config = load_config(args.config)
    source = repo_path(args.source_run)
    audit_id = str(config["run_id"])
    out = repo_path(str(config["output_root"])) / audit_id
    out.mkdir(parents=True, exist_ok=True)

    route_rows = {}
    route_pairs = {}
    route_nodes = {}
    for path in sorted((source / "route_candidates").glob("*.jsonl")):
        rows = list(read_jsonl(path))
        route = path.stem
        route_rows[route] = rows
        route_pairs[route] = {pair(row) for row in rows}
        route_nodes[route] = {node for p in route_pairs[route] for node in p}

    union_pairs = set().union(*route_pairs.values())
    union_nodes = {node for p in union_pairs for node in p}
    corpus_path = repo_path(config["node_path"])
    view_path = repo_path(config["text_view_path"])
    corpus_rows = list(read_jsonl(corpus_path))
    view_rows = list(read_jsonl(view_path))
    corpus_nodes = {str(r.get("node_id", r.get("id"))) for r in corpus_rows}
    view_nodes = {str(r.get("node_id")) for r in view_rows if r.get("node_id")}
    reviewed = load_reviewed(repo_path(args.reviewed_cases))
    eligible_reviewed = {k: v for k, v in reviewed.items() if k[0] in union_nodes and k[1] in union_nodes}
    positives = {k for k, v in eligible_reviewed.items() if v["label"] == "POSITIVE"}
    negatives = {k for k, v in eligible_reviewed.items() if v["label"] == "NEGATIVE"}
    uncertain = set(eligible_reviewed) - positives - negatives

    node_counts = {
        "corpus_node_records": len(corpus_rows),
        "corpus_unique_node_ids": len(corpus_nodes),
        "view_records": len(view_rows),
        "view_unique_node_ids": len(view_nodes),
        "view_records_per_node": len(view_rows) / max(len(view_nodes), 1),
        "candidate_union_unique_node_ids": len(union_nodes),
        "candidate_union_pairs": len(union_pairs),
        "candidate_union_possible_pairs": len(union_nodes) * (len(union_nodes) - 1) // 2,
        "candidate_union_pruning_rate": 1 - len(union_pairs) / max(len(union_nodes) * (len(union_nodes) - 1) // 2, 1),
        "views_without_candidate_node": len(view_nodes - union_nodes),
        "corpus_nodes_without_view": len(corpus_nodes - view_nodes),
    }

    rows = []
    gate = {}
    for route, candidates in route_rows.items():
        thresholds = config.get("dense_thresholds", [0.0]) if route in config.get("vector_routes", {}) else (
            config.get("bm25_thresholds", [0.0]) if route == "bm25" else [0.0]
        )
        for threshold in thresholds:
            selected = {pair(r) for r in candidates if float(r["raw_score"]) >= float(threshold)}
            observed_recall = len(selected & positives) / len(positives) if positives else None
            rows.append({
                "scheme": route, "threshold": threshold, "eligible_nodes": len(route_nodes[route]),
                "retrieved_rows": len(candidates), "unique_pairs": len(route_pairs[route]),
                "retained_pairs": len(selected),
                "possible_pairs_for_route": len(route_nodes[route]) * (len(route_nodes[route]) - 1) // 2,
                "pruning_rate_route_universe": 1 - len(selected) / max(len(route_nodes[route]) * (len(route_nodes[route]) - 1) // 2, 1),
                "reviewed_positive_denominator": len(positives),
                "reviewed_positive_survivors": len(selected & positives),
                "observed_reviewed_panel_recall": observed_recall,
                "reviewed_negative_survivors": len(selected & negatives),
                "unknown_survivors": len(selected & uncertain),
            })
            if route == "qwen3_0_6b_dense" and float(threshold) == 0.5:
                gate[route] = selected
        for budget in config.get("candidate_budgets", []):
            selected = budget_pairs(candidates, int(budget))
            rows.append({
                "scheme": f"{route}_matched_budget", "threshold": f"top_{budget}",
                "eligible_nodes": len(route_nodes[route]), "retrieved_rows": len(candidates),
                "unique_pairs": len(route_pairs[route]), "retained_pairs": len(selected),
                "possible_pairs_for_route": len(route_nodes[route]) * (len(route_nodes[route]) - 1) // 2,
                "pruning_rate_route_universe": 1 - len(selected) / max(len(route_nodes[route]) * (len(route_nodes[route]) - 1) // 2, 1),
                "reviewed_positive_denominator": len(positives),
                "reviewed_positive_survivors": len(selected & positives),
                "observed_reviewed_panel_recall": len(selected & positives) / len(positives) if positives else None,
                "reviewed_negative_survivors": len(selected & negatives),
                "unknown_survivors": len(selected & uncertain),
            })
    for route in ("bm25", "structural"):
        if route in route_pairs:
            threshold = 5.0 if route == "bm25" else 0.0
            selected = {pair(r) for r in route_rows[route] if float(r["raw_score"]) >= threshold}
            gate[route] = selected
    if gate:
        union = set().union(*gate.values())
        rows.append({
            "scheme": "OR_UNION_qwen3@0.5_bm25@5_structural@0",
            "threshold": json.dumps({"qwen3_0_6b_dense": 0.5, "bm25": 5.0, "structural": 0.0}, sort_keys=True),
            "eligible_nodes": len({n for p in union for n in p}), "retrieved_rows": None,
            "unique_pairs": len(union), "retained_pairs": len(union),
            "possible_pairs_for_route": node_counts["candidate_union_possible_pairs"],
            "pruning_rate_route_universe": 1 - len(union) / max(node_counts["candidate_union_possible_pairs"], 1),
            "reviewed_positive_denominator": len(positives),
            "reviewed_positive_survivors": len(union & positives),
            "observed_reviewed_panel_recall": len(union & positives) / len(positives) if positives else None,
            "reviewed_negative_survivors": len(union & negatives), "unknown_survivors": len(union & uncertain),
        })

    with (out / "canonical_threshold_metrics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    overlap = {}
    for left in sorted(route_pairs):
        overlap[left] = {
            "eligible_nodes": len(route_nodes[left]),
            "unique_pairs": len(route_pairs[left]),
            "unique_to_route_pairs": len(route_pairs[left] - set().union(*(route_pairs[x] for x in route_pairs if x != left))),
            "reviewed_positive_pairs": len(route_pairs[left] & positives),
            "reviewed_positive_recall": len(route_pairs[left] & positives) / len(positives) if positives else None,
            "reviewed_positive_unique_to_route": len((route_pairs[left] - set().union(*(route_pairs[x] for x in route_pairs if x != left))) & positives),
        }
    for left in sorted(route_pairs):
        for right in sorted(route_pairs):
            if left < right:
                overlap[f"{left}∩{right}"] = len(route_pairs[left] & route_pairs[right])
    (out / "canonical_route_overlap.json").write_text(json.dumps(overlap, indent=2, sort_keys=True), encoding="utf-8")

    leave_one_out = {}
    for omitted in sorted(route_pairs):
        kept = set().union(*(route_pairs[x] for x in route_pairs if x != omitted))
        leave_one_out[omitted] = {
            "pairs_without_route": len(kept),
            "pairs_lost": len(union_pairs - kept),
            "reviewed_positive_survivors": len(kept & positives),
            "reviewed_positive_lost": len((union_pairs - kept) & positives),
            "reviewed_panel_recall_without_route": len(kept & positives) / len(positives) if positives else None,
        }
    (out / "leave_one_route_out.json").write_text(json.dumps(leave_one_out, indent=2, sort_keys=True), encoding="utf-8")
    relation_counts = defaultdict(int)
    for value in eligible_reviewed.values():
        relation_counts[f"{value['label']}::{value.get('relation') or 'unspecified'}"] += 1
    (out / "reviewed_panel_stats.json").write_text(json.dumps({
        "total_reviewed_cases": len(reviewed), "eligible_in_union": len(eligible_reviewed),
        "positive": len(positives), "negative": len(negatives), "unknown_or_navigation": len(uncertain),
        "label_relation_counts": dict(sorted(relation_counts.items())),
    }, indent=2, sort_keys=True), encoding="utf-8")
    score_rows = []
    for key in sorted(positives):
        route_scores = {}
        for route, candidates in route_rows.items():
            matches = [r for r in candidates if pair(r) == key]
            if matches:
                best = min(matches, key=lambda r: (int(r["rank"]), -float(r["raw_score"])))
                route_scores[route] = {"raw_score": best["raw_score"], "rank": best["rank"]}
            else:
                route_scores[route] = None
        score_rows.append({"source_id": key[0], "target_id": key[1], "label": "POSITIVE",
                           "route_scores": route_scores})
    write_jsonl(out / "reviewed_positive_route_scores.jsonl", score_rows)
    positive_route_counts = {
        route: len(route_pairs[route] & positives) for route in sorted(route_pairs)
    }
    positive_route_unique = {
        route: len((route_pairs[route] - set().union(*(route_pairs[x] for x in route_pairs if x != route))) & positives)
        for route in sorted(route_pairs)
    }

    report = out / "reports" / "results_audit.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(f"""# Stage 1 results audit: `{audit_id}`

## Scope and counting contract

This audit reads the immutable outputs from `{source}` and writes a new run.
It does not overwrite the original jobs or candidate files.

| Quantity | Count | Meaning |
|---|---:|---|
| Corpus node records | {len(corpus_rows)} | Records in `corpus_nodes.jsonl`; canonical Node IDs |
| Corpus unique Node IDs | {len(corpus_nodes)} | Node-level universe before view eligibility |
| Frozen retrieval views | {len(view_rows)} | Retrieval records, not graph Nodes |
| View-covered unique Node IDs | {len(view_nodes)} | Nodes represented by at least one view |
| Candidate-union Node IDs | {len(union_nodes)} | Nodes actually present in canonical candidate pairs |
| Candidate-union pairs | {len(union_pairs)} | Unique undirected canonical Node pairs |

The previous `1,204` value is the active candidate-union Node count, not the
full corpus denominator. `1,313` is the corpus-record count and `2,223` is the
view-record count. Views are never counted as graph Nodes in this audit.
Each route has its own eligible Node count because unsupported or unreturned
Nodes do not appear in that route's candidate list.

## Reviewed evidence panel

The reusable reviewed file contains {len(reviewed)} pair cases: {len(positives)}
`POSITIVE`, {len(negatives)} `NEGATIVE`, and {len(uncertain)} uncertain/navigation
cases inside the candidate universe. This is a small, purpose-limited reviewed
panel, not an exhaustive graph ground truth and not a random corpus sample.
Unknown cases are excluded from both positive and negative denominators.
Therefore `observed_reviewed_panel_recall` is reported, while corpus-wide Edge
Recall remains unavailable.

The same file also contains matched-budget rows (`top_10000`, `top_25000`,
`top_50000`). These use route rank, not cross-route raw-score comparison, so
BM25/cosine/formula scores are never put on a shared threshold scale.

## Route semantics

`unique_pairs` means all unique canonical pairs emitted by that route at its
retrieval ceiling. `retained_pairs` means those same pairs after the
route-specific score threshold. `unique_to_route_pairs` means pairs absent from
all other route ceilings. Every intersection in `canonical_route_overlap.json`
is calculated over canonical pairs, so it cannot exceed either participating
route's pair count.

## Outputs

- `canonical_threshold_metrics.csv`: route thresholds, pruning, reviewed-panel recall
- `canonical_route_overlap.json`: valid pair intersections and route-only pairs
- `leave_one_route_out.json`: union ablation
- `reviewed_panel.json`: reviewed labels used and their scope
- `reviewed_panel_stats.json`: label and relation composition
- `reviewed_positive_route_scores.jsonl`: per-route score/rank or miss for each reviewed positive
- `input_accounting.json`: frozen universe and denominator accounting

The 120-query RepresentativeSubset remains a separate downstream task. Its
0/120 page mapping is not used as Node--Node evidence here.

## Reviewed positive complementarity

Positive-panel coverage by route is: `{json.dumps(positive_route_counts, sort_keys=True)}`.
Positive pairs found only by one route at the retrieval ceiling are:
`{json.dumps(positive_route_unique, sort_keys=True)}`. These are observed-panel
rescue counts, not corpus-wide novelty. The per-positive score/rank table is
provided separately so low-score positives can be inspected without treating
missing retrieval as a negative label.
""", encoding="utf-8")
    (out / "input_accounting.json").write_text(json.dumps(node_counts, indent=2, sort_keys=True), encoding="utf-8")
    reviewed_json = {"|".join(key): value for key, value in eligible_reviewed.items()}
    (out / "reviewed_panel.json").write_text(json.dumps(reviewed_json, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(out), "positive_panel": len(positives), "union_pairs": len(union_pairs),
                      "union_nodes": len(union_nodes)}))


if __name__ == "__main__":
    main()
