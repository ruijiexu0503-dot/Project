from __future__ import annotations

import argparse
import json
from pathlib import Path

from .coarse_relation_typing import COARSE_RELATIONS, FINE_TO_COARSE, coarse_relation
from .io_utils import read_jsonl, write_json, write_jsonl


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def class_metrics(gold: list[str], predicted: list[str]) -> tuple[dict, float]:
    result = {}
    for relation in COARSE_RELATIONS:
        tp = sum(g == relation and p == relation for g, p in zip(gold, predicted))
        fp = sum(g != relation and p == relation for g, p in zip(gold, predicted))
        fn = sum(g == relation and p != relation for g, p in zip(gold, predicted))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result[relation] = {
            "support": sum(g == relation for g in gold),
            "predicted": sum(p == relation for p in predicted),
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        }
    return result, round(sum(row["f1"] for row in result.values()) / len(COARSE_RELATIONS), 4)


def normalize_predictions(predictions: list[dict], predictions_are_fine: bool) -> list[dict]:
    if not predictions_are_fine:
        return predictions
    normalized = []
    for row in predictions:
        copy = dict(row)
        relation = copy.get("relation_type")
        if relation in FINE_TO_COARSE:
            copy["relation_type"] = FINE_TO_COARSE[relation]
        else:
            copy["valid"] = False
        normalized.append(copy)
    return normalized


def score_predictions(tasks: list[dict], predictions: list[dict], truth_rows: list[dict]) -> tuple[dict, list[dict]]:
    truth = {pair(row["node_a"], row["node_b"]): row for row in truth_rows}
    by_task = {row["task_id"]: row for row in predictions}
    diagnostics, gold_types, predicted_types = [], [], []
    for task in tasks:
        fine_gold = truth[pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])]
        gold_type = coarse_relation(fine_gold["gold_relation"])
        prediction = by_task.get(task["task_id"], {})
        predicted_type = prediction.get("relation_type") if prediction.get("valid") else "INVALID"
        relation_correct = predicted_type == gold_type
        if fine_gold["directed"]:
            direction_correct = (prediction.get("source_node_id") == fine_gold["gold_source"]
                                 and prediction.get("target_node_id") == fine_gold["gold_target"])
        else:
            direction_correct = None
        exact = relation_correct and direction_correct is not False
        diagnostics.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"],
            "gold_fine_relation": fine_gold["gold_relation"], "gold_coarse_relation": gold_type,
            "gold_source": fine_gold["gold_source"], "gold_target": fine_gold["gold_target"],
            "gold_directed": fine_gold["directed"], "predicted_relation": predicted_type,
            "predicted_source": prediction.get("source_node_id"),
            "predicted_target": prediction.get("target_node_id"),
            "confidence": prediction.get("confidence"), "valid": prediction.get("valid", False),
            "relation_correct": relation_correct, "direction_correct": direction_correct,
            "exact_type_and_direction": exact,
        })
        gold_types.append(gold_type)
        predicted_types.append(predicted_type)
    per_relation, macro_f1 = class_metrics(gold_types, predicted_types)
    directed = [row for row in diagnostics if row["direction_correct"] is not None]
    labels = list(COARSE_RELATIONS) + (["INVALID"] if "INVALID" in predicted_types else [])
    matrix = {gold: {predicted: sum(g == gold and p == predicted for g, p in zip(gold_types, predicted_types))
                     for predicted in labels} for gold in COARSE_RELATIONS}
    contrast_gold = [g == "CONTRASTS_WITH" for g in gold_types]
    contrast_pred = [p == "CONTRASTS_WITH" for p in predicted_types]
    contrast_tp = sum(g and p for g, p in zip(contrast_gold, contrast_pred))
    contrast_fp = sum(not g and p for g, p in zip(contrast_gold, contrast_pred))
    contrast_fn = sum(g and not p for g, p in zip(contrast_gold, contrast_pred))
    contrast_precision = contrast_tp / (contrast_tp + contrast_fp) if contrast_tp + contrast_fp else 0.0
    contrast_recall = contrast_tp / (contrast_tp + contrast_fn) if contrast_tp + contrast_fn else 0.0
    report = {
        "pairs": len(tasks), "valid_predictions": sum(row["valid"] for row in diagnostics),
        "type_accuracy": round(sum(row["relation_correct"] for row in diagnostics) / len(tasks), 4),
        "direction_accuracy_directed_pairs": round(sum(row["direction_correct"] for row in directed) / len(directed), 4),
        "directed_pairs": len(directed),
        "exact_type_and_direction_accuracy": round(sum(row["exact_type_and_direction"] for row in diagnostics) / len(tasks), 4),
        "macro_f1": macro_f1, "per_relation": per_relation, "confusion_matrix": matrix,
        "contrast_detection": {"tp": contrast_tp, "fp": contrast_fp, "fn": contrast_fn,
                               "precision": round(contrast_precision, 4), "recall": round(contrast_recall, 4)},
    }
    return report, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate hierarchical coarse known-related predictions")
    parser.add_argument("--tasks", default="output/strict_relation_typing/shared/blind_tasks.jsonl")
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--ground-truth", default=(
        "evaluation/ground_truth/gw150914_detection/strict_relation_ground_truth.jsonl"))
    parser.add_argument("--predictions-are-fine", action="store_true")
    parser.add_argument("--output", default=None)
    parser.add_argument("--prefix", default="coarse")
    args = parser.parse_args()
    tasks = read_jsonl(args.tasks)
    predictions = normalize_predictions(read_jsonl(args.predictions), args.predictions_are_fine)
    truth = read_jsonl(args.ground_truth)
    report, diagnostics = score_predictions(tasks, predictions, truth)
    baseline = [{"task_id": task["task_id"], "relation_type": "EXPANDS",
                 "source_node_id": task["evidence_a"]["node_id"],
                 "target_node_id": task["evidence_b"]["node_id"], "confidence": 1.0, "valid": True}
                for task in tasks]
    baseline_report, _ = score_predictions(tasks, baseline, truth)
    report["always_expands_baseline"] = baseline_report
    report["predictions_are_fine_then_collapsed"] = args.predictions_are_fine
    target = Path(args.output) if args.output else Path(args.predictions).parent
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / f"{args.prefix}_evaluation.json", report)
    write_jsonl(target / f"{args.prefix}_diagnostics.jsonl", diagnostics)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
