from __future__ import annotations

import argparse
import json
from pathlib import Path

from .candidate_generator import add_high_recall_distance_candidates
from .io_utils import read_jsonl, write_json, write_jsonl


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare deterministic high-recall paper candidates")
    parser.add_argument("--doc-id", default="gw150914_detection")
    parser.add_argument("--source-root", default="output/scientific_body_semantics/shared_candidates")
    parser.add_argument("--output-root", default="output/scientific_body_high_recall/shared_candidates")
    parser.add_argument("--distance-window", type=int, default=15)
    parser.add_argument("--ground-truth", default="evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl")
    args = parser.parse_args()

    source = Path(args.source_root) / args.doc_id
    target = Path(args.output_root) / args.doc_id
    target.mkdir(parents=True, exist_ok=True)
    nodes = read_jsonl(source / "evidence_nodes.jsonl")
    candidates = read_jsonl(source / "candidates.jsonl")
    assignments = {node["node_id"]: f"{args.doc_id}_SCIENTIFIC_BODY" for node in nodes}
    expanded = add_high_recall_distance_candidates(
        nodes, candidates, args.distance_window, assignments)
    write_jsonl(target / "evidence_nodes.jsonl", nodes)
    write_jsonl(target / "candidates.jsonl", expanded)

    report = {
        "doc_id": args.doc_id,
        "method": "normal_candidates_union_deterministic_distance_window",
        "distance_window": args.distance_window,
        "nodes": len(nodes),
        "baseline_candidates": len(candidates),
        "expanded_candidates": len(expanded),
    }
    truth_path = Path(args.ground_truth)
    if truth_path.exists():
        truth = read_jsonl(truth_path)
        gold = {pair(row["node_a"], row["node_b"]) for row in truth
                if row["gold_label"] == "RELATION"}
        baseline_pairs = {pair(row["node_a"], row["node_b"]) for row in candidates}
        expanded_pairs = {pair(row["node_a"], row["node_b"]) for row in expanded}
        report.update({
            "gold_relations": len(gold),
            "baseline_gold_retrieved": len(gold & baseline_pairs),
            "baseline_candidate_recall": round(len(gold & baseline_pairs) / max(1, len(gold)), 4),
            "expanded_gold_retrieved": len(gold & expanded_pairs),
            "expanded_candidate_recall": round(len(gold & expanded_pairs) / max(1, len(gold)), 4),
        })
    write_json(target / "summary.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
