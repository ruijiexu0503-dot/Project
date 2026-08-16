from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


EXPECTED_SIGNAL = {
    "SUPPORTS": "EVIDENCE_OR_QUANTIFICATION",
    "EXPLAINS_OR_ELABORATES": "EXPLANATION_OR_MECHANISM",
    "MODIFIES": "CONDITION_OR_SCOPE",
    "CONTRASTS_WITH": "EXPLICIT_CONTRAST",
}
SEMANTIC_RELATIONS = tuple(EXPECTED_SIGNAL)


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _safe(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _load_many(paths: list[str]) -> dict[str, dict]:
    rows = {}
    for path in paths:
        for row in read_jsonl(path):
            rows[row["task_id"]] = row
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate two taxonomy versions on one frozen pair set")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--profile-predictions", nargs="+", required=True)
    parser.add_argument("--fixed-predictions", nargs="+", required=True)
    parser.add_argument("--existence-ground-truth", required=True)
    parser.add_argument("--typing-ground-truth", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    tasks = read_jsonl(args.tasks)
    profile, fixed = _load_many(args.profile_predictions), _load_many(args.fixed_predictions)
    existence_truth = {
        _pair(row["node_a"], row["node_b"]): row for row in read_jsonl(args.existence_ground_truth)
    }
    typing_truth = {
        _pair(row["node_a"], row["node_b"]): row for row in read_jsonl(args.typing_ground_truth)
    }
    diagnostics = []
    for task in tasks:
        task_id, pair_id = task["task_id"], task["pair_id"]
        pair = _pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])
        gold_positive = existence_truth[pair]["gold_label"] == "RELATION"
        semantic = (typing_truth.get(pair) or {}).get("semantic") or {}
        gold_relation = semantic.get("relation") if semantic.get("status") == "RESOLVED" else None
        profile_row, fixed_row = profile[task_id], fixed.get(task_id, {})
        fixed_valid = bool(fixed_row.get("valid"))
        fixed_reject = not fixed_valid or fixed_row.get("relation") == "REJECT_UNCERTAIN"
        type_correct = None
        direction_correct = None
        secondary_rescue = None
        signal_contains_gold = None
        if gold_relation:
            type_correct = fixed_valid and fixed_row.get("relation") == gold_relation
            secondary_rescue = fixed_valid and gold_relation in {
                fixed_row.get("relation"), fixed_row.get("secondary_relation")
            }
            signal_contains_gold = EXPECTED_SIGNAL[gold_relation] in (profile_row.get("signals") or [])
            if semantic.get("directed"):
                direction_correct = (
                    fixed_valid and fixed_row.get("direction_status") == "DIRECTED"
                    and fixed_row.get("source_node_id") == semantic.get("source")
                    and fixed_row.get("target_node_id") == semantic.get("target")
                )
            else:
                direction_correct = fixed_valid and fixed_row.get("direction_status") == "SYMMETRIC"
        diagnostics.append({
            "task_id": task_id, "pair_id": pair_id, "gold_positive": gold_positive,
            "gold_relation": gold_relation, "profile_signals": profile_row.get("signals") or [],
            "profile_expected_signal_present": signal_contains_gold,
            "fixed_valid": fixed_valid, "fixed_reject": fixed_reject,
            "fixed_relation": fixed_row.get("relation"),
            "fixed_secondary_relation": fixed_row.get("secondary_relation"),
            "fixed_type_correct": type_correct, "fixed_direction_correct": direction_correct,
            "fixed_primary_or_secondary_correct": secondary_rescue,
        })

    resolved = [row for row in diagnostics if row["gold_relation"]]
    false_positive_pairs = [row for row in diagnostics if not row["gold_positive"]]
    gold_positive_pairs = [row for row in diagnostics if row["gold_positive"]]
    by_class: dict[str, list[dict]] = defaultdict(list)
    for row in resolved:
        by_class[row["gold_relation"]].append(row)
    confusion = {
        gold: {
            predicted: sum(
                row["gold_relation"] == gold
                and (row["fixed_relation"] if row["fixed_valid"] else "INVALID") == predicted
                for row in resolved
            )
            for predicted in (*SEMANTIC_RELATIONS, "REJECT_UNCERTAIN", "INVALID")
        }
        for gold in SEMANTIC_RELATIONS
    }
    fixed_per_class = {}
    for relation in SEMANTIC_RELATIONS:
        true_positive = sum(
            row["gold_relation"] == relation and row["fixed_relation"] == relation
            and row["fixed_valid"] for row in resolved
        )
        predicted_positive = sum(
            row["fixed_relation"] == relation and row["fixed_valid"] for row in resolved
        )
        gold_support = sum(row["gold_relation"] == relation for row in resolved)
        precision = _safe(true_positive, predicted_positive)
        recall = _safe(true_positive, gold_support)
        fixed_per_class[relation] = {
            "support": gold_support,
            "predicted": predicted_positive,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(_safe(2 * precision * recall, precision + recall), 4),
        }
    supported_class_metrics = [
        metrics for metrics in fixed_per_class.values() if metrics["support"]
    ]
    report = {
        "shared_pair_set": len(diagnostics),
        "existence_gold_positive": len(gold_positive_pairs),
        "existence_gold_negative": len(false_positive_pairs),
        "version_a_nonexclusive_profile": {
            "signal_counts": dict(Counter(signal for row in diagnostics for signal in row["profile_signals"])),
            "multi_signal_pairs": sum(len(row["profile_signals"]) > 1 for row in diagnostics),
            "resolved_gt_pairs": len(resolved),
            "expected_gold_signal_present": sum(row["profile_expected_signal_present"] for row in resolved),
            "expected_gold_signal_coverage": round(_safe(
                sum(row["profile_expected_signal_present"] for row in resolved), len(resolved)
            ), 4),
            "direction_available": False,
        },
        "version_b_exclusive_fixed": {
            "valid_outputs": sum(row["fixed_valid"] for row in diagnostics),
            "reject_or_invalid": sum(row["fixed_reject"] for row in diagnostics),
            "relation_counts": dict(Counter(row["fixed_relation"] or "INVALID" for row in diagnostics)),
            "secondary_relation_pairs": sum(bool(row["fixed_secondary_relation"]) for row in diagnostics),
            "resolved_gt_pairs": len(resolved),
            "type_correct": sum(row["fixed_type_correct"] for row in resolved),
            "type_accuracy": round(_safe(sum(row["fixed_type_correct"] for row in resolved), len(resolved)), 4),
            "direction_correct": sum(row["fixed_direction_correct"] for row in resolved),
            "direction_accuracy": round(_safe(
                sum(row["fixed_direction_correct"] for row in resolved), len(resolved)
            ), 4),
            "exact_type_and_direction_correct": sum(
                row["fixed_type_correct"] and row["fixed_direction_correct"] for row in resolved
            ),
            "exact_type_and_direction_accuracy": round(_safe(sum(
                row["fixed_type_correct"] and row["fixed_direction_correct"] for row in resolved
            ), len(resolved)), 4),
            "primary_or_secondary_type_correct": sum(row["fixed_primary_or_secondary_correct"] for row in resolved),
            "primary_or_secondary_type_accuracy": round(_safe(
                sum(row["fixed_primary_or_secondary_correct"] for row in resolved), len(resolved)
            ), 4),
            "macro_precision_supported_classes": round(_safe(sum(
                row["precision"] for row in supported_class_metrics
            ), len(supported_class_metrics)), 4),
            "macro_recall_supported_classes": round(_safe(sum(
                row["recall"] for row in supported_class_metrics
            ), len(supported_class_metrics)), 4),
            "macro_f1_supported_classes": round(_safe(sum(
                row["f1"] for row in supported_class_metrics
            ), len(supported_class_metrics)), 4),
            "per_class": fixed_per_class,
            "confusion_matrix": confusion,
            "gold_positive_rejected": sum(row["fixed_reject"] for row in gold_positive_pairs),
            "existence_false_positive_rejected": sum(row["fixed_reject"] for row in false_positive_pairs),
        },
        "per_resolved_gold_class": {
            relation: {
                "support": len(rows),
                "profile_signal_coverage": round(_safe(
                    sum(row["profile_expected_signal_present"] for row in rows), len(rows)
                ), 4),
                "fixed_type_accuracy": round(_safe(sum(row["fixed_type_correct"] for row in rows), len(rows)), 4),
                "fixed_exact_accuracy": round(_safe(sum(
                    row["fixed_type_correct"] and row["fixed_direction_correct"] for row in rows
                ), len(rows)), 4),
            }
            for relation, rows in sorted(by_class.items())
        },
        "interpretation_note": (
            "Version A can preserve overlapping signals but has no semantic-role direction. Version B provides one "
            "directed primary type; secondary type is diagnostic metadata. The pilot pair set is deliberately enriched "
            "with all candidate gold positives and prior hard false positives, so it is not a production prevalence sample."
        ),
        "production_graph_modified": False,
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "comparison.json", report)
    write_jsonl(output / "diagnostics.jsonl", diagnostics)
    a = report["version_a_nonexclusive_profile"]
    b = report["version_b_exclusive_fixed"]
    class_rows = "\n".join(
        f"| {relation} | {metrics['support']} | {metrics['precision']:.1%} | "
        f"{metrics['recall']:.1%} | {metrics['f1']:.1%} |"
        for relation, metrics in b["per_class"].items()
    )
    markdown = f"""# Two-version semantic edge comparison

Both versions use the same {report['shared_pair_set']} pairs accepted by existence prompt v2. No production graph was modified.

| Measure | Version A: non-exclusive profile | Version B: fixed type + direction |
|---|---:|---:|
| Semantic edges retained | {report['shared_pair_set']} | {report['shared_pair_set']} |
| Resolved GT pairs used for typing | {a['resolved_gt_pairs']} | {b['resolved_gt_pairs']} |
| Expected type/signal coverage | {a['expected_gold_signal_coverage']:.1%} | {b['type_accuracy']:.1%} |
| Direction accuracy | n/a | {b['direction_accuracy']:.1%} |
| Exact type + direction | n/a | {b['exact_type_and_direction_accuracy']:.1%} |
| Primary or secondary type accuracy | n/a | {b['primary_or_secondary_type_accuracy']:.1%} |
| Macro F1 (supported classes) | n/a | {b['macro_f1_supported_classes']:.1%} |
| Multi/secondary-label pairs | {a['multi_signal_pairs']} | {b['secondary_relation_pairs']} |
| Rejected or invalid | 0 | {b['reject_or_invalid']} |

## Version B per-class results

| Relation | GT support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
{class_rows}

Version A preserves overlap such as evidence plus explanation, but it does not assert semantic-role direction. Version B is easier to query and visualize as a typed graph, while its primary/secondary difference exposes how much accuracy is lost by forcing mutually exclusive labels.

This is a diagnostic, enriched pair set containing all candidate-retrieved positives and hard negatives from the pilot; its precision is not a production-prevalence estimate.
"""
    (output / "comparison_report.md").write_text(markdown, encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
