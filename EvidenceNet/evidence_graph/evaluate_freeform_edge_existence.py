from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _safe(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate taxonomy-free edge-existence predictions")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--predictions", required=True, nargs="+")
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    tasks = read_jsonl(Path(args.tasks))
    predictions = []
    for path in args.predictions:
        predictions.extend(read_jsonl(Path(path)))
    by_task = {}
    for row in predictions:
        previous = by_task.get(row["task_id"])
        if previous is None or (not previous.get("valid") and row.get("valid")):
            by_task[row["task_id"]] = row
    truth = {
        _pair(row["node_a"], row["node_b"]): row
        for row in read_jsonl(Path(args.ground_truth))
    }
    diagnostics = []
    for task in tasks:
        prediction = by_task.get(task["task_id"], {})
        gold = truth[_pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])]
        gold_positive = gold["gold_label"] == "RELATION"
        status = prediction.get("status") if prediction.get("valid") else "INVALID"
        production_positive = status == "RELATED_STRONG"
        diagnostics.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"],
            "gold_positive": gold_positive, "gold_label": gold["gold_label"],
            "predicted_status": status, "production_positive": production_positive,
            "correct": production_positive == gold_positive,
            "relation_description": prediction.get("relation_description"),
            "supporting_span_a": prediction.get("supporting_span_a"),
            "supporting_span_b": prediction.get("supporting_span_b"),
            "confidence": prediction.get("confidence"),
        })
    tp = sum(row["gold_positive"] and row["production_positive"] for row in diagnostics)
    fp = sum(not row["gold_positive"] and row["production_positive"] for row in diagnostics)
    tn = sum(not row["gold_positive"] and not row["production_positive"] for row in diagnostics)
    fn = sum(row["gold_positive"] and not row["production_positive"] for row in diagnostics)
    precision, recall = _safe(tp, tp + fp), _safe(tp, tp + fn)
    report = {
        "candidate_pairs": len(tasks), "gold_positive_candidates": tp + fn,
        "gold_negative_candidates": tn + fp,
        "true_positive": tp, "false_positive": fp, "true_negative": tn, "false_negative": fn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(_safe(2 * precision * recall, precision + recall), 4),
        "specificity": round(_safe(tn, tn + fp), 4),
        "accuracy": round(_safe(tp + tn, len(tasks)), 4),
        "ambiguous": sum(row["predicted_status"] == "AMBIGUOUS" for row in diagnostics),
        "ambiguous_gold_positive": sum(
            row["predicted_status"] == "AMBIGUOUS" and row["gold_positive"] for row in diagnostics
        ),
        "invalid": sum(row["predicted_status"] == "INVALID" for row in diagnostics),
        "end_to_end_recall_all_36_gold": round(tp / 36, 4),
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "evaluation.json", report)
    write_jsonl(output / "diagnostics.jsonl", diagnostics)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
