from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl
from .prepare_strict_relation_typing import RELATIONS


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def class_metrics(gold: list[str], predicted: list[str]) -> tuple[dict, float]:
    result = {}
    for relation in RELATIONS:
        tp = sum(g == relation and p == relation for g, p in zip(gold, predicted))
        fp = sum(g != relation and p == relation for g, p in zip(gold, predicted))
        fn = sum(g == relation and p != relation for g, p in zip(gold, predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result[relation] = {"support": sum(g == relation for g in gold), "predicted": sum(p == relation for p in predicted),
                            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}
    return result, round(sum(row["f1"] for row in result.values()) / len(RELATIONS), 4)


def score_predictions(tasks: list[dict], predictions: list[dict], truth_rows: list[dict]) -> tuple[dict, list[dict]]:
    truth = {pair(row["node_a"], row["node_b"]): row for row in truth_rows}
    by_task = {row["task_id"]: row for row in predictions}
    diagnostics, gold_types, predicted_types = [], [], []
    for task in tasks:
        gold = truth[pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])]
        prediction = by_task.get(task["task_id"], {})
        predicted_type = prediction.get("relation_type") if prediction.get("valid") else "INVALID"
        relation_correct = predicted_type == gold["gold_relation"]
        if gold["directed"]:
            direction_correct = (prediction.get("source_node_id") == gold["gold_source"]
                                 and prediction.get("target_node_id") == gold["gold_target"])
        else:
            direction_correct = None
        exact = relation_correct and (direction_correct is not False)
        diagnostics.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"],
            "input_a": task["evidence_a"]["node_id"], "input_b": task["evidence_b"]["node_id"],
            "gold_relation": gold["gold_relation"], "gold_source": gold["gold_source"],
            "gold_target": gold["gold_target"], "gold_directed": gold["directed"],
            "predicted_relation": predicted_type,
            "predicted_source": prediction.get("source_node_id"),
            "predicted_target": prediction.get("target_node_id"),
            "confidence": prediction.get("confidence"), "valid": prediction.get("valid", False),
            "relation_correct": relation_correct, "direction_correct": direction_correct,
            "exact_type_and_direction": exact,
        })
        gold_types.append(gold["gold_relation"])
        predicted_types.append(predicted_type)
    per_relation, macro_f1 = class_metrics(gold_types, predicted_types)
    directed = [row for row in diagnostics if row["direction_correct"] is not None]
    labels = list(RELATIONS) + (["INVALID"] if "INVALID" in predicted_types else [])
    matrix = {gold: {predicted: sum(g == gold and p == predicted for g, p in zip(gold_types, predicted_types))
                     for predicted in labels} for gold in RELATIONS}
    report = {
        "pairs": len(tasks), "valid_predictions": sum(row["valid"] for row in diagnostics),
        "type_accuracy": round(sum(row["relation_correct"] for row in diagnostics) / len(tasks), 4),
        "direction_accuracy_directed_pairs": round(sum(row["direction_correct"] for row in directed) / len(directed), 4),
        "directed_pairs": len(directed),
        "exact_type_and_direction_accuracy": round(sum(row["exact_type_and_direction"] for row in diagnostics) / len(tasks), 4),
        "macro_f1": macro_f1, "per_relation": per_relation,
        "elaborates_prediction_rate": round(sum(p == "ELABORATES" for p in predicted_types) / len(tasks), 4),
        "confusion_matrix": matrix,
    }
    return report, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate strict known-related type+direction predictions")
    parser.add_argument("--tasks", default="output/strict_relation_typing/shared/blind_tasks.jsonl")
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--ground-truth",
                        default="evaluation/ground_truth/gw150914_detection/strict_relation_ground_truth.jsonl")
    args = parser.parse_args()
    tasks, predictions, truth = read_jsonl(args.tasks), read_jsonl(args.predictions), read_jsonl(args.ground_truth)
    report, diagnostics = score_predictions(tasks, predictions, truth)
    # Trivial baseline: always predict ELABORATES and orient input A -> input B.
    baseline = [{"task_id": task["task_id"], "relation_type": "ELABORATES",
                 "source_node_id": task["evidence_a"]["node_id"],
                 "target_node_id": task["evidence_b"]["node_id"], "confidence": 1.0, "valid": True}
                for task in tasks]
    baseline_report, _ = score_predictions(tasks, baseline, truth)
    report["always_elaborates_baseline"] = baseline_report
    target = Path(args.predictions).parent
    write_json(target / "evaluation.json", report)
    write_jsonl(target / "diagnostics.jsonl", diagnostics)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
