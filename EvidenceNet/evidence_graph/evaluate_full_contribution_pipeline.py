from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _safe(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _coarse_gold(relation: str | None) -> str | None:
    if relation in {"SUPPORTS", "EXPLAINS_OR_ELABORATES"}:
        return "CONTRIBUTES_TO"
    if relation in {"MODIFIES", "CONTRASTS_WITH"}:
        return relation
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate existence followed by contribution-profile typing")
    parser.add_argument("--all-tasks", required=True)
    parser.add_argument("--existence-predictions", nargs="+", required=True)
    parser.add_argument("--typing-predictions", required=True)
    parser.add_argument("--existence-ground-truth", required=True)
    parser.add_argument("--typing-ground-truth", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    tasks = read_jsonl(args.all_tasks)
    resolved_existence: dict[str, dict] = {}
    for path in args.existence_predictions:
        for row in read_jsonl(path):
            previous = resolved_existence.get(row["task_id"])
            if previous is None or (not previous.get("valid") and row.get("valid")):
                resolved_existence[row["task_id"]] = row
    typing = {row["task_id"]: row for row in read_jsonl(args.typing_predictions)}
    existence_truth = {
        _pair(row["node_a"], row["node_b"]): row
        for row in read_jsonl(args.existence_ground_truth)
    }
    typing_truth = {
        _pair(row["node_a"], row["node_b"]): row
        for row in read_jsonl(args.typing_ground_truth)
    }

    diagnostics = []
    for task in tasks:
        pair = _pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])
        gold = existence_truth[pair]
        existence = resolved_existence.get(task["task_id"], {})
        accepted = bool(existence.get("valid") and existence.get("status") == "RELATED_STRONG")
        typed = typing.get(task["task_id"])
        semantic = (typing_truth.get(pair) or {}).get("semantic") or {}
        gold_primary = _coarse_gold(semantic.get("relation")) if semantic.get("status") == "RESOLVED" else None
        type_correct = None
        direction_correct = None
        if accepted and typed and typed.get("valid") and gold_primary:
            type_correct = typed.get("primary_relation") == gold_primary
            if semantic.get("directed"):
                direction_correct = (
                    typed.get("direction_status") == "DIRECTED"
                    and typed.get("source_node_id") == semantic.get("source")
                    and typed.get("target_node_id") == semantic.get("target")
                )
            else:
                direction_correct = typed.get("direction_status") == "SYMMETRIC"
        diagnostics.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"],
            "gold_positive": gold.get("gold_label") == "RELATION",
            "existence_positive": accepted,
            "gold_primary_relation": gold_primary,
            "predicted_primary_relation": typed.get("primary_relation") if typed else None,
            "predicted_contribution_modes": typed.get("contribution_modes") if typed else None,
            "type_correct": type_correct, "direction_correct": direction_correct,
        })

    tp = sum(row["gold_positive"] and row["existence_positive"] for row in diagnostics)
    fp = sum(not row["gold_positive"] and row["existence_positive"] for row in diagnostics)
    fn = sum(row["gold_positive"] and not row["existence_positive"] for row in diagnostics)
    tn = sum(not row["gold_positive"] and not row["existence_positive"] for row in diagnostics)
    typed_resolved = [row for row in diagnostics if row["type_correct"] is not None]
    total_gold_positive = sum(row.get("gold_label") == "RELATION" for row in existence_truth.values())
    candidate_gold_positive = tp + fn
    report = {
        "candidate_pairs": len(diagnostics),
        "candidate_generation": {
            "gold_positive_retrieved": candidate_gold_positive,
            "gold_positive_total": total_gold_positive,
            "recall": round(_safe(candidate_gold_positive, total_gold_positive), 4),
        },
        "existence": {
            "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
            "precision": round(_safe(tp, tp + fp), 4),
            "recall": round(_safe(tp, tp + fn), 4),
            "f1": round(_safe(2 * tp, 2 * tp + fp + fn), 4),
            "end_to_end_recall_against_all_gold": round(_safe(tp, total_gold_positive), 4),
        },
        "typing_on_accepted_resolved_gt": {
            "pairs": len(typed_resolved),
            "primary_type_correct": sum(row["type_correct"] for row in typed_resolved),
            "primary_type_accuracy": round(_safe(sum(row["type_correct"] for row in typed_resolved), len(typed_resolved)), 4),
            "direction_correct": sum(row["direction_correct"] for row in typed_resolved),
            "direction_accuracy": round(_safe(sum(row["direction_correct"] for row in typed_resolved), len(typed_resolved)), 4),
            "exact_correct": sum(row["type_correct"] and row["direction_correct"] for row in typed_resolved),
            "exact_accuracy": round(_safe(sum(row["type_correct"] and row["direction_correct"] for row in typed_resolved), len(typed_resolved)), 4),
        },
        "mode_accuracy_available": False,
        "mode_accuracy_note": "Existing GT is mutually exclusive and cannot score non-exclusive contribution modes.",
        "production_graph_modified": False,
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "evaluation.json", report)
    write_jsonl(output / "diagnostics.jsonl", diagnostics)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
