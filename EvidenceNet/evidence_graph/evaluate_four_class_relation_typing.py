from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .four_class_relation_typing import ABSTAIN, RELATIONS
from .io_utils import read_jsonl, write_json, write_jsonl


INVALID = "INVALID"


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def class_metrics(gold: list[str], predicted: list[str]) -> tuple[dict, float, float, float]:
    result = {}
    for relation in RELATIONS:
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
    macro_precision = sum(row["precision"] for row in result.values()) / len(RELATIONS)
    macro_recall = sum(row["recall"] for row in result.values()) / len(RELATIONS)
    macro_f1 = sum(row["f1"] for row in result.values()) / len(RELATIONS)
    return result, round(macro_precision, 4), round(macro_recall, 4), round(macro_f1, 4)


def prediction_label(prediction: dict) -> str:
    return prediction.get("relation_type", INVALID) if prediction.get("valid") else INVALID


def score_predictions(tasks: list[dict], predictions: list[dict], truth_rows: list[dict]) -> tuple[dict, list[dict]]:
    truth = {pair(row["node_a"], row["node_b"]): row for row in truth_rows}
    by_task = {row["task_id"]: row for row in predictions}
    diagnostics, gold_types, predicted_types = [], [], []
    all_predicted = []
    for task in tasks:
        gold = truth[pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])]
        prediction = by_task.get(task["task_id"], {})
        predicted_type = prediction_label(prediction)
        all_predicted.append(predicted_type)
        resolved = gold["four_class_status"] == "resolved"
        relation_correct = predicted_type == gold["four_class_relation"] if resolved else None
        if resolved and gold["four_class_directed"]:
            direction_correct = (prediction.get("source_node_id") == gold["four_class_source"]
                                 and prediction.get("target_node_id") == gold["four_class_target"])
        else:
            direction_correct = None
        exact = (relation_correct and direction_correct is not False) if resolved else None
        diagnostics.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"], "resolved": resolved,
            "input_a": task["evidence_a"]["node_id"], "input_b": task["evidence_b"]["node_id"],
            "original_relation_label": gold["original_relation_label"],
            "gold_relation": gold["four_class_relation"],
            "gold_source": gold["four_class_source"], "gold_target": gold["four_class_target"],
            "gold_directed": gold["four_class_directed"],
            "predicted_relation": predicted_type,
            "predicted_source": prediction.get("source_node_id"),
            "predicted_target": prediction.get("target_node_id"),
            "confidence": prediction.get("confidence"), "valid": prediction.get("valid", False),
            "relation_correct": relation_correct, "direction_correct": direction_correct,
            "exact_type_and_direction": exact,
            "mapping_basis": gold["four_class_mapping_basis"],
            "reference_cue": gold.get("four_class_reference_cue"),
        })
        if resolved:
            gold_types.append(gold["four_class_relation"])
            predicted_types.append(predicted_type)
    evaluated = [row for row in diagnostics if row["resolved"]]
    directed = [row for row in evaluated if row["gold_directed"]]
    per_class, macro_precision, macro_recall, macro_f1 = class_metrics(gold_types, predicted_types)
    predicted_labels = list(RELATIONS) + [ABSTAIN, INVALID]
    matrix = {gold: {predicted: sum(g == gold and p == predicted
                                    for g, p in zip(gold_types, predicted_types))
                     for predicted in predicted_labels} for gold in RELATIONS}
    all_counts = Counter(all_predicted)
    evaluated_counts = Counter(predicted_types)
    predicted_a_as_source = sum(
        row["predicted_source"] == row["input_a"] for row in diagnostics
        if row["predicted_source"] is not None
    )
    predictions_with_direction = sum(row["predicted_source"] is not None for row in diagnostics)
    report = {
        "oracle_pairs": len(tasks), "evaluated_pairs": len(evaluated),
        "unresolved_ground_truth_pairs": len(tasks) - len(evaluated),
        "valid_predictions": sum(row["valid"] for row in diagnostics),
        "reject_uncertain_count": all_counts[ABSTAIN],
        "reject_uncertain_evaluated_count": evaluated_counts[ABSTAIN],
        "input_a_as_source_count": predicted_a_as_source,
        "predictions_with_direction": predictions_with_direction,
        "input_a_as_source_rate": round(predicted_a_as_source / predictions_with_direction, 4)
        if predictions_with_direction else 0.0,
        "relation_type_accuracy": round(sum(row["relation_correct"] for row in evaluated) / len(evaluated), 4),
        "direction_accuracy": round(sum(bool(row["direction_correct"]) for row in directed) / len(directed), 4),
        "directed_evaluated_pairs": len(directed),
        "exact_type_and_direction_accuracy": round(
            sum(row["exact_type_and_direction"] for row in evaluated) / len(evaluated), 4),
        "macro_precision": macro_precision, "macro_recall": macro_recall, "macro_f1": macro_f1,
        "per_class": per_class, "confusion_matrix": matrix,
        "prediction_proportions_all_oracle_pairs": {
            label: round(all_counts[label] / len(tasks), 4) for label in predicted_labels
        },
        "prediction_proportions_evaluated_pairs": {
            label: round(evaluated_counts[label] / len(evaluated), 4) for label in predicted_labels
        },
    }
    return report, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate known-related four-class predictions")
    parser.add_argument("--tasks", default="output/strict_relation_typing/shared/blind_tasks.jsonl")
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--ground-truth", default=(
        "evaluation/ground_truth/gw150914_detection/four_class_relation_ground_truth.jsonl"))
    args = parser.parse_args()
    tasks, predictions, truth = read_jsonl(args.tasks), read_jsonl(args.predictions), read_jsonl(args.ground_truth)
    report, diagnostics = score_predictions(tasks, predictions, truth)
    baseline = [{"task_id": task["task_id"], "relation_type": "CONTRIBUTES_TO",
                 "source_node_id": task["evidence_a"]["node_id"],
                 "target_node_id": task["evidence_b"]["node_id"], "confidence": 1.0, "valid": True}
                for task in tasks]
    baseline_report, _ = score_predictions(tasks, baseline, truth)
    report["always_contributes_to_baseline"] = baseline_report
    target = Path(args.predictions).parent
    write_json(target / "evaluation.json", report)
    write_jsonl(target / "diagnostics.jsonl", diagnostics)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
