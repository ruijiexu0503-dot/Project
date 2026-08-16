from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _safe(a: int, b: int) -> float:
    return a / b if b else 0.0


def _metrics(selected: set[tuple[str, str]], candidates: set[tuple[str, str]],
             positive: set[tuple[str, str]]) -> dict:
    available = positive & candidates
    tp, fp = len(selected & available), len(selected - available)
    fn, tn = len(available - selected), len(candidates - available - selected)
    precision, recall = _safe(tp, tp + fp), _safe(tp, tp + fn)
    return {
        "predicted_edges": len(selected), "true_positive": tp, "false_positive": fp,
        "true_negative": tn, "false_negative": fn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(_safe(2 * precision * recall, precision + recall), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate sequential long-range ranking")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--rankings", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    tasks = read_jsonl(Path(args.tasks))
    rankings = {row["current_node_id"]: row for row in read_jsonl(Path(args.rankings)) if row.get("valid")}
    positive = {
        _pair(row["node_a"], row["node_b"])
        for row in read_jsonl(Path(args.ground_truth)) if row["gold_label"] == "RELATION"
    }
    candidates, rank_by_pair = set(), {}
    for task in tasks:
        current = task["current_node"]["node_id"]
        for candidate in task["earlier_candidates"]:
            candidates.add(_pair(current, candidate["node_id"]))
        ranking = rankings.get(current)
        if not ranking:
            continue
        for rank, target in enumerate(ranking["ranked_candidate_ids"], start=1):
            rank_by_pair[_pair(current, target)] = {
                "current": current, "rank": rank, "cutoff": ranking["edge_cutoff"],
            }

    strategies = {
        "model_cutoff": {pair for pair, row in rank_by_pair.items() if row["rank"] <= row["cutoff"]},
        "top1_per_current": {pair for pair, row in rank_by_pair.items() if row["rank"] <= 1},
        "top2_per_current": {pair for pair, row in rank_by_pair.items() if row["rank"] <= 2},
        "top3_per_current": {pair for pair, row in rank_by_pair.items() if row["rank"] <= 3},
    }
    report = {
        "center_tasks": len(tasks), "valid_rankings": len(rankings),
        "long_range_candidate_pairs": len(candidates),
        "gold_positive_long_range_candidates": len(positive & candidates),
        "strategies": {name: _metrics(selected, candidates, positive) for name, selected in strategies.items()},
        "production_graph_modified": False,
        "ground_truth_note": "Metrics are relative to the provisional closed-world curated_reference_v1.",
    }
    diagnostics = [{
        "pair_id": "||".join(pair), "gold_positive": pair in positive,
        **rank_by_pair.get(pair, {}),
        **{f"selected_{name}": pair in selected for name, selected in strategies.items()},
    } for pair in sorted(candidates)]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "evaluation.json", report)
    write_jsonl(output / "diagnostics.jsonl", diagnostics)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
