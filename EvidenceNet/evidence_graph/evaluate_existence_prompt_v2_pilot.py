from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _safe(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _metrics(rows: list[dict], positive_key: str) -> dict:
    tp = sum(row["gold_positive"] and row[positive_key] for row in rows)
    fp = sum(not row["gold_positive"] and row[positive_key] for row in rows)
    fn = sum(row["gold_positive"] and not row[positive_key] for row in rows)
    tn = sum(not row["gold_positive"] and not row[positive_key] for row in rows)
    precision, recall = _safe(tp, tp + fp), _safe(tp, tp + fn)
    return {
        "true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn,
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(_safe(2 * precision * recall, precision + recall), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the diagnostic existence prompt-v2 pilot")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--predictions", nargs="+", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--v1-diagnostics", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    tasks = read_jsonl(args.tasks)
    predictions = {}
    for path in args.predictions:
        for row in read_jsonl(path):
            predictions[row["task_id"]] = row
    truth = {_pair(row["node_a"], row["node_b"]): row for row in read_jsonl(args.ground_truth)}
    v1 = {row["task_id"]: row for row in read_jsonl(args.v1_diagnostics)}

    diagnostics = []
    for task in tasks:
        prediction = predictions.get(task["task_id"], {})
        gold = truth[_pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])]
        valid = bool(prediction.get("valid"))
        status = prediction.get("status") if valid else "INVALID"
        old_positive = bool(v1[task["task_id"]]["production_positive"])
        gold_positive = gold["gold_label"] == "RELATION"
        diagnostics.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"],
            "gold_positive": gold_positive, "gold_relation": gold.get("gold_relation"),
            "v1_positive": old_positive,
            "v1_group": (
                "v1_true_positive" if gold_positive and old_positive else
                "v1_false_negative" if gold_positive else
                "v1_false_positive" if old_positive else "v1_true_negative"
            ),
            "v2_status": status,
            "v2_strict_positive": status == "RELATED",
            "v2_high_recall_positive": status in {"RELATED", "POSSIBLE_RELATION"},
            "signals": prediction.get("signals") or [],
            "relationship_probability": prediction.get("relationship_probability"),
            "best_relation_hypothesis": prediction.get("best_relation_hypothesis"),
            "unrelated_reason": prediction.get("unrelated_reason"),
            "distance": abs(task["evidence_a"]["document_order"] - task["evidence_b"]["document_order"]),
        })

    relation_rows: dict[str, list[dict]] = defaultdict(list)
    for row in diagnostics:
        if row["gold_positive"]:
            relation_rows[row["gold_relation"]].append(row)
    per_relation = {}
    for relation, rows in sorted(relation_rows.items()):
        per_relation[relation] = {
            "total": len(rows),
            "v1_recall": round(_safe(sum(row["v1_positive"] for row in rows), len(rows)), 4),
            "v2_strict_recall": round(_safe(sum(row["v2_strict_positive"] for row in rows), len(rows)), 4),
            "v2_high_recall_gate_recall": round(
                _safe(sum(row["v2_high_recall_positive"] for row in rows), len(rows)), 4
            ),
        }

    groups = Counter(row["v1_group"] for row in diagnostics)
    v1_fn = [row for row in diagnostics if row["v1_group"] == "v1_false_negative"]
    v1_fp = [row for row in diagnostics if row["v1_group"] == "v1_false_positive"]
    report = {
        "pilot_pairs": len(diagnostics), "valid_outputs": sum(row["v2_status"] != "INVALID" for row in diagnostics),
        "selection_groups": dict(groups),
        "status_counts": dict(Counter(row["v2_status"] for row in diagnostics)),
        "v1_on_same_pilot": _metrics(diagnostics, "v1_positive"),
        "v2_related_only": _metrics(diagnostics, "v2_strict_positive"),
        "v2_related_or_possible_gate": _metrics(diagnostics, "v2_high_recall_positive"),
        "v1_false_negative_recovery": {
            "total": len(v1_fn),
            "as_related": sum(row["v2_status"] == "RELATED" for row in v1_fn),
            "as_possible": sum(row["v2_status"] == "POSSIBLE_RELATION" for row in v1_fn),
            "still_unrelated": sum(row["v2_status"] == "UNRELATED" for row in v1_fn),
        },
        "v1_false_positive_behavior": {
            "total": len(v1_fp),
            "still_related": sum(row["v2_status"] == "RELATED" for row in v1_fp),
            "moved_to_possible": sum(row["v2_status"] == "POSSIBLE_RELATION" for row in v1_fp),
            "rejected": sum(row["v2_status"] == "UNRELATED" for row in v1_fp),
        },
        "per_gold_relation": per_relation,
        "precision_scope_note": (
            "Pilot precision is diagnostic, not a production estimate: negatives comprise all 8 prior false positives "
            "plus 12 sampled prior true negatives."
        ),
        "production_graph_modified": False,
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "evaluation.json", report)
    write_jsonl(output / "diagnostics.jsonl", diagnostics)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
