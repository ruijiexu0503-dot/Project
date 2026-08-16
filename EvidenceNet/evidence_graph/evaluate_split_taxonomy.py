from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


SEMANTIC_RELATIONS = (
    "SUPPORTS",
    "EXPLAINS_OR_ELABORATES",
    "MODIFIES",
    "CONTRASTS_WITH",
)
REJECT = "REJECT_UNCERTAIN"
INVALID = "INVALID"


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def safe_div(numerator: int | float, denominator: int | float) -> float:
    return numerator / denominator if denominator else 0.0


def rounded(value: float) -> float:
    return round(value, 4)


def prediction_for_task(predictions: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for prediction in predictions:
        task_id = prediction.get("task_id")
        if not task_id or task_id in result:
            raise ValueError(f"Missing or duplicate task_id: {task_id!r}")
        result[task_id] = prediction
    return result


def semantic_label(prediction: dict) -> str:
    semantic = prediction.get("semantic") or {}
    relation = semantic.get("relation")
    if relation in SEMANTIC_RELATIONS or relation == REJECT:
        return relation
    return INVALID


def reference_value(prediction: dict) -> bool | None:
    value = (prediction.get("references") or {}).get("exists")
    return value if isinstance(value, bool) else None


def score_predictions(tasks: list[dict], predictions: list[dict], truth_rows: list[dict]) -> tuple[dict, list[dict]]:
    truth = {pair(row["node_a"], row["node_b"]): row for row in truth_rows}
    predicted = prediction_for_task(predictions)
    diagnostics = []

    for task in tasks:
        key = pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])
        gold = truth[key]
        prediction = predicted.get(task["task_id"], {})
        predicted_semantic = semantic_label(prediction)
        semantic_gold = gold["semantic"]
        semantic_resolved = semantic_gold["status"] == "RESOLVED"
        semantic_type_correct = (
            predicted_semantic == semantic_gold["relation"] if semantic_resolved else None
        )
        semantic_prediction = prediction.get("semantic") or {}
        if semantic_resolved and semantic_gold["directed"]:
            semantic_direction_correct = (
                semantic_prediction.get("source_node_id") == semantic_gold["source"]
                and semantic_prediction.get("target_node_id") == semantic_gold["target"]
            )
        elif semantic_resolved:
            semantic_direction_correct = None
        else:
            semantic_direction_correct = None
        semantic_exact = (
            semantic_type_correct
            and (semantic_direction_correct is not False)
            if semantic_resolved else None
        )

        reference_gold = gold["references"]
        predicted_reference = reference_value(prediction)
        reference_existence_correct = predicted_reference is reference_gold["exists"]
        reference_prediction = prediction.get("references") or {}
        if reference_gold["exists"]:
            reference_direction_correct = (
                predicted_reference is True
                and reference_prediction.get("source_node_id") == reference_gold["source"]
                and reference_prediction.get("target_node_id") == reference_gold["target"]
            )
            reference_exact = reference_existence_correct and reference_direction_correct
        else:
            reference_direction_correct = None
            reference_exact = reference_existence_correct

        diagnostics.append({
            "task_id": task["task_id"],
            "pair_id": task["pair_id"],
            "semantic_resolved": semantic_resolved,
            "original_relation_label": gold["original_relation_label"],
            "gold_semantic_relation": semantic_gold["relation"],
            "gold_semantic_source": semantic_gold["source"],
            "gold_semantic_target": semantic_gold["target"],
            "gold_semantic_directed": semantic_gold["directed"],
            "predicted_semantic_relation": predicted_semantic,
            "predicted_semantic_source": semantic_prediction.get("source_node_id"),
            "predicted_semantic_target": semantic_prediction.get("target_node_id"),
            "semantic_type_correct": semantic_type_correct,
            "semantic_direction_correct": semantic_direction_correct,
            "semantic_exact": semantic_exact,
            "gold_reference_exists": reference_gold["exists"],
            "gold_reference_source": reference_gold["source"],
            "gold_reference_target": reference_gold["target"],
            "reference_cue": reference_gold["cue"],
            "predicted_reference_exists": predicted_reference,
            "predicted_reference_source": reference_prediction.get("source_node_id"),
            "predicted_reference_target": reference_prediction.get("target_node_id"),
            "reference_existence_correct": reference_existence_correct,
            "reference_direction_correct": reference_direction_correct,
            "reference_exact": reference_exact,
        })

    semantic_rows = [row for row in diagnostics if row["semantic_resolved"]]
    directed_semantic = [row for row in semantic_rows if row["gold_semantic_directed"]]
    gold_semantic = [row["gold_semantic_relation"] for row in semantic_rows]
    predicted_semantic = [row["predicted_semantic_relation"] for row in semantic_rows]

    per_class = {}
    for relation in SEMANTIC_RELATIONS:
        tp = sum(g == relation and p == relation for g, p in zip(gold_semantic, predicted_semantic))
        fp = sum(g != relation and p == relation for g, p in zip(gold_semantic, predicted_semantic))
        fn = sum(g == relation and p != relation for g, p in zip(gold_semantic, predicted_semantic))
        precision = safe_div(tp, tp + fp)
        recall = safe_div(tp, tp + fn)
        f1 = safe_div(2 * precision * recall, precision + recall)
        per_class[relation] = {
            "support": sum(g == relation for g in gold_semantic),
            "predicted": sum(p == relation for p in predicted_semantic),
            "precision": rounded(precision),
            "recall": rounded(recall),
            "f1": rounded(f1),
        }
    predicted_labels = list(SEMANTIC_RELATIONS) + [REJECT, INVALID]
    confusion = {
        gold: {
            pred: sum(g == gold and p == pred for g, p in zip(gold_semantic, predicted_semantic))
            for pred in predicted_labels
        }
        for gold in SEMANTIC_RELATIONS
    }

    gold_positive = sum(row["gold_reference_exists"] for row in diagnostics)
    predicted_positive = sum(row["predicted_reference_exists"] is True for row in diagnostics)
    true_positive = sum(
        row["gold_reference_exists"] and row["predicted_reference_exists"] is True
        for row in diagnostics
    )
    ref_precision = safe_div(true_positive, predicted_positive)
    ref_recall = safe_div(true_positive, gold_positive)
    ref_f1 = safe_div(2 * ref_precision * ref_recall, ref_precision + ref_recall)

    jointly_resolved = semantic_rows
    joint = Counter()
    for row in jointly_resolved:
        semantic_ok = bool(row["semantic_exact"])
        reference_ok = bool(row["reference_exact"])
        if semantic_ok and reference_ok:
            joint["both_correct"] += 1
        elif semantic_ok:
            joint["semantic_only"] += 1
        elif reference_ok:
            joint["reference_only"] += 1
        else:
            joint["both_wrong"] += 1

    macro_precision = sum(row["precision"] for row in per_class.values()) / len(SEMANTIC_RELATIONS)
    macro_recall = sum(row["recall"] for row in per_class.values()) / len(SEMANTIC_RELATIONS)
    macro_f1 = sum(row["f1"] for row in per_class.values()) / len(SEMANTIC_RELATIONS)
    report = {
        "oracle_pairs": len(tasks),
        "semantic": {
            "evaluated_pairs": len(semantic_rows),
            "unresolved_ground_truth_pairs": len(tasks) - len(semantic_rows),
            "type_accuracy": rounded(safe_div(sum(row["semantic_type_correct"] for row in semantic_rows), len(semantic_rows))),
            "direction_accuracy": rounded(safe_div(sum(row["semantic_direction_correct"] for row in directed_semantic), len(directed_semantic))),
            "directed_evaluated_pairs": len(directed_semantic),
            "exact_type_and_direction_accuracy": rounded(safe_div(sum(row["semantic_exact"] for row in semantic_rows), len(semantic_rows))),
            "macro_precision": rounded(macro_precision),
            "macro_recall": rounded(macro_recall),
            "macro_f1": rounded(macro_f1),
            "per_class": per_class,
            "confusion_matrix": confusion,
            "reject_uncertain_count": sum(row["predicted_semantic_relation"] == REJECT for row in diagnostics),
            "invalid_count": sum(row["predicted_semantic_relation"] == INVALID for row in diagnostics),
        },
        "reference": {
            "evaluated_pairs": len(diagnostics),
            "gold_positive": gold_positive,
            "predicted_positive": predicted_positive,
            "true_positive": true_positive,
            "precision": rounded(ref_precision),
            "recall": rounded(ref_recall),
            "f1": rounded(ref_f1),
            "existence_accuracy": rounded(safe_div(sum(row["reference_existence_correct"] for row in diagnostics), len(diagnostics))),
            "direction_accuracy": rounded(safe_div(sum(row["reference_direction_correct"] for row in diagnostics if row["gold_reference_exists"]), gold_positive)),
            "direction_denominator_gold_positive": gold_positive,
        },
        "joint": {
            "evaluated_pairs": len(jointly_resolved),
            **{label: joint[label] for label in ("both_correct", "semantic_only", "reference_only", "both_wrong")},
        },
    }
    return report, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate independent semantic and REFERENCES predictions")
    parser.add_argument(
        "--tasks",
        default="evaluation/ground_truth/gw150914_detection/split_taxonomy_oracle_pairs.jsonl",
    )
    parser.add_argument("--predictions", required=True)
    parser.add_argument(
        "--ground-truth",
        default="evaluation/ground_truth/gw150914_detection/split_taxonomy_relation_ground_truth.jsonl",
    )
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    tasks = read_jsonl(Path(args.tasks))
    predictions = read_jsonl(Path(args.predictions))
    truth = read_jsonl(Path(args.ground_truth))
    report, diagnostics = score_predictions(tasks, predictions, truth)
    output = Path(args.output_dir) if args.output_dir else Path(args.predictions).parent
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "split_taxonomy_evaluation.json", report)
    write_jsonl(output / "split_taxonomy_diagnostics.jsonl", diagnostics)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
