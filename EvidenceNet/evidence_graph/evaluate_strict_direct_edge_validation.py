from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _safe(a: int, b: int) -> float:
    return a / b if b else 0.0


def _scores(rows: list[dict], all_gold_positives: int) -> dict:
    kept = [row for row in rows if row["strict_keep"]]
    tp = sum(row["gold_positive"] for row in kept)
    fp = sum(not row["gold_positive"] for row in kept)
    baseline_tp = sum(row["gold_positive"] for row in rows)
    baseline_fp = sum(not row["gold_positive"] for row in rows)
    precision = _safe(tp, tp + fp)
    recall_full = _safe(tp, all_gold_positives)
    return {
        "predicted_edges": len(kept), "true_positive": tp, "false_positive": fp,
        "true_positive_rejected": baseline_tp - tp,
        "false_positive_rejected": baseline_fp - fp,
        "precision": round(precision, 4),
        "recall_within_a_edges": round(_safe(tp, baseline_tp), 4),
        "end_to_end_recall_all_gold": round(recall_full, 4),
        "end_to_end_f1": round(_safe(2 * precision * recall_full, precision + recall_full), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate strict direct-edge validation over A edges")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--predictions", nargs="+", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    tasks = read_jsonl(args.tasks)
    predictions = {}
    for path in args.predictions:
        for row in read_jsonl(path):
            predictions[row["task_id"]] = row
    truth_rows = read_jsonl(args.ground_truth)
    truth = {_pair(row["node_a"], row["node_b"]): row for row in truth_rows}
    all_gold_positives = sum(row["gold_label"] == "RELATION" for row in truth_rows)
    diagnostics = []
    for task in tasks:
        a, b = task["evidence_a"], task["evidence_b"]
        prediction = predictions.get(task["task_id"], {})
        gold = truth[_pair(a["node_id"], b["node_id"])]
        valid = bool(prediction.get("valid"))
        diagnostics.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"],
            "gold_positive": gold["gold_label"] == "RELATION",
            "gold_relation": gold.get("gold_relation"),
            "distance": abs(a["document_order"] - b["document_order"]),
            "valid": valid, "strict_keep": valid and prediction.get("verdict") == "KEEP_EDGE",
            "verdict": prediction.get("verdict") if valid else "INVALID",
            "directness": prediction.get("directness") if valid else "INVALID",
            "confidence": prediction.get("confidence"),
            "anchor_a": prediction.get("anchor_a"), "anchor_b": prediction.get("anchor_b"),
            "shared_atomic_subject": prediction.get("shared_atomic_subject"),
            "contribution_a_to_b": prediction.get("contribution_a_to_b"),
            "contribution_b_to_a": prediction.get("contribution_b_to_a"),
            "rejection_reason": prediction.get("rejection_reason"),
        })

    baseline_tp = sum(row["gold_positive"] for row in diagnostics)
    baseline_fp = len(diagnostics) - baseline_tp
    baseline_precision = _safe(baseline_tp, len(diagnostics))
    baseline_recall = _safe(baseline_tp, all_gold_positives)
    by_distance: dict[str, list[dict]] = defaultdict(list)
    for row in diagnostics:
        label = "1-3" if row["distance"] <= 3 else "4-6" if row["distance"] <= 6 else "7+"
        by_distance[label].append(row)
    directness_by_gold = {
        label: {
            "gold_positive": sum(row["gold_positive"] for row in diagnostics if row["directness"] == label),
            "gold_negative": sum(not row["gold_positive"] for row in diagnostics if row["directness"] == label),
        }
        for label in sorted({row["directness"] for row in diagnostics})
    }
    strict = _scores(diagnostics, all_gold_positives)
    report = {
        "pair_set": len(diagnostics), "all_ground_truth_positive_pairs": all_gold_positives,
        "valid_outputs": sum(row["valid"] for row in diagnostics),
        "invalid_outputs": sum(not row["valid"] for row in diagnostics),
        "a_baseline": {
            "predicted_edges": len(diagnostics), "true_positive": baseline_tp, "false_positive": baseline_fp,
            "precision": round(baseline_precision, 4),
            "end_to_end_recall_all_gold": round(baseline_recall, 4),
            "end_to_end_f1": round(_safe(
                2 * baseline_precision * baseline_recall, baseline_precision + baseline_recall
            ), 4),
        },
        "strict_precision_graph": strict,
        "goal": {
            "false_positive_rejected_at_least": 8, "true_positive_rejected_at_most": 3,
            "false_positive_goal_met": strict["false_positive_rejected"] >= 8,
            "true_positive_goal_met": strict["true_positive_rejected"] <= 3,
            "both_goals_met": (
                strict["false_positive_rejected"] >= 8 and strict["true_positive_rejected"] <= 3
            ),
        },
        "directness_counts": dict(Counter(row["directness"] for row in diagnostics)),
        "directness_by_gold": directness_by_gold,
        "by_distance": {label: _scores(rows, all_gold_positives) for label, rows in sorted(by_distance.items())},
        "policy": "Only valid KEEP_EDGE outputs enter the precision graph; A remains unchanged as the recall graph.",
        "production_graph_modified": False,
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "evaluation.json", report)
    write_jsonl(output / "diagnostics.jsonl", diagnostics)
    lines = [
        "# Strict direct-edge validation", "",
        "The validator audits the same A-version edges without assigning type or direction. No production graph was modified.", "",
        "| Graph | Edges | TP | FP | Precision | End-to-end recall | F1 |", "|---|---:|---:|---:|---:|---:|---:|",
        f"| A recall baseline | {len(diagnostics)} | {baseline_tp} | {baseline_fp} | {baseline_precision:.1%} | {baseline_recall:.1%} | {report['a_baseline']['end_to_end_f1']:.1%} |",
        f"| Strict precision graph | {strict['predicted_edges']} | {strict['true_positive']} | {strict['false_positive']} | {strict['precision']:.1%} | {strict['end_to_end_recall_all_gold']:.1%} | {strict['end_to_end_f1']:.1%} |",
        "", f"False positives removed: {strict['false_positive_rejected']}/{baseline_fp}.",
        f"True positives lost: {strict['true_positive_rejected']}/{baseline_tp}.",
        f"Target met: {report['goal']['both_goals_met']}.", "", "## Directness decisions", "",
        "| Decision | GT positive | GT negative |", "|---|---:|---:|",
    ]
    for label, counts in directness_by_gold.items():
        lines.append(f"| {label} | {counts['gold_positive']} | {counts['gold_negative']} |")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
