from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _safe(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _metrics(selected: set[tuple[str, str]], candidate_pairs: set[tuple[str, str]],
             gold_positive: set[tuple[str, str]], all_gold_count: int) -> dict:
    available_gold = gold_positive & candidate_pairs
    tp, fp = len(selected & available_gold), len(selected - available_gold)
    fn, tn = len(available_gold - selected), len(candidate_pairs - available_gold - selected)
    precision, recall = _safe(tp, tp + fp), _safe(tp, tp + fn)
    return {
        "predicted_edges": len(selected), "true_positive": tp, "false_positive": fp,
        "true_negative": tn, "false_negative": fn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(_safe(2 * precision * recall, precision + recall), 4),
        "specificity": round(_safe(tn, tn + fp), 4),
        "end_to_end_recall_all_gold": round(_safe(tp, all_gold_count), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate comparative edge selection")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--predictions", required=True, nargs="+")
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    tasks = read_jsonl(Path(args.tasks))
    predictions = []
    for path in args.predictions:
        predictions.extend(read_jsonl(Path(path)))
    by_source = {row["source_id"]: row for row in predictions if row.get("valid")}

    candidate_pairs = {
        _pair(task["source"]["node_id"], candidate["node_id"])
        for task in tasks for candidate in task["candidates"]
    }
    truth_rows = read_jsonl(Path(args.ground_truth))
    gold_positive = {
        _pair(row["node_a"], row["node_b"])
        for row in truth_rows if row["gold_label"] == "RELATION"
    }

    votes: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for source, prediction in by_source.items():
        for rank, selection in enumerate(prediction.get("selected") or [], start=1):
            pair = _pair(source, selection["target_id"])
            if pair in candidate_pairs:
                votes[pair].append({"source": source, "rank": rank, **selection})

    unilateral_top1 = {pair for pair, rows in votes.items() if any(row["rank"] == 1 for row in rows)}
    unilateral_top2 = {
        pair for pair, rows in votes.items() if any(row["rank"] <= 2 for row in rows)
    }
    mutual_top2 = {
        pair for pair, rows in votes.items()
        if len({row["source"] for row in rows if row["rank"] <= 2}) == 2
    }
    mutual_top3 = {pair for pair, rows in votes.items() if len({row["source"] for row in rows}) == 2}
    strategies = {
        "unilateral_top1": unilateral_top1,
        "unilateral_top2": unilateral_top2,
        "unilateral_top3": set(votes),
        "mutual_top2": mutual_top2,
        "mutual_top3": mutual_top3,
        "mutual_with_top1": {
            pair for pair in mutual_top3
            if any(row["rank"] == 1 for row in votes[pair])
        },
        "top1_or_mutual_top3": unilateral_top1 | mutual_top3,
        "top2_or_mutual_top3": unilateral_top2 | mutual_top3,
    }
    report = {
        "center_nodes": len(tasks), "valid_center_predictions": len(by_source),
        "invalid_center_predictions": len(tasks) - len(by_source),
        "candidate_pairs": len(candidate_pairs),
        "gold_positive_candidates": len(gold_positive & candidate_pairs),
        "gold_total": len(gold_positive),
        "candidate_recall": round(_safe(len(gold_positive & candidate_pairs), len(gold_positive)), 4),
        "directed_selections": sum(len(row.get("selected") or []) for row in by_source.values()),
        "centers_selecting_none": sum(not row.get("selected") for row in by_source.values()),
        "strategies": {
            name: _metrics(selected, candidate_pairs, gold_positive, len(gold_positive))
            for name, selected in strategies.items()
        },
        "production_graph_modified": False,
    }
    diagnostics = []
    for pair in sorted(candidate_pairs):
        diagnostics.append({
            "pair_id": "||".join(pair), "node_a": pair[0], "node_b": pair[1],
            "gold_positive": pair in gold_positive,
            "selection_votes": votes.get(pair, []),
            **{f"selected_{name}": pair in selected for name, selected in strategies.items()},
        })
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "evaluation.json", report)
    write_jsonl(output / "diagnostics.jsonl", diagnostics)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
