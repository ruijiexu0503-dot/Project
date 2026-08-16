from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def metrics(predicted: set[tuple[str, str]], positives: set[tuple[str, str]], universe: set[tuple[str, str]]) -> dict:
    predicted = predicted & universe
    negatives = universe - positives
    tp, fp = len(predicted & positives), len(predicted & negatives)
    fn, tn = len(positives - predicted), len(negatives - predicted)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "predicted": len(predicted), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 6), "recall": round(recall, 6),
        "f1": round(f1, 6), "accuracy": round((tp + tn) / len(universe), 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate DETR semantic stages on the strict audit GT")
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--verification-tasks", required=True)
    parser.add_argument("--verification-predictions", nargs="+", required=True)
    parser.add_argument("--final-semantic-edges", required=True)
    parser.add_argument("--reference-edges", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    gt = read_jsonl(args.ground_truth)
    universe = {pair(row["node_a"], row["node_b"]) for row in gt}
    semantic_positive = {
        pair(row["node_a"], row["node_b"]) for row in gt if row["semantic_exists"]
    }
    reference_positive = {
        pair(row["node_a"], row["node_b"]) for row in gt if row["reference_exists"]
    }
    verification_task_rows = read_jsonl(args.verification_tasks)
    ranking = {
        pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])
        for task in verification_task_rows
    }
    grounded = set()
    for path in args.verification_predictions:
        for row in read_jsonl(path):
            if row.get("valid") and row.get("status") == "RELATED_STRONG":
                # pair_id is opaque; task lookup is recovered below.
                grounded.add(row["task_id"])
    verification_tasks = {
        task["task_id"]: pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])
        for task in verification_task_rows
    }
    grounded_pairs = {verification_tasks[task_id] for task_id in grounded}
    final_pairs = {
        pair(row["source"], row["target"]) for row in read_jsonl(args.final_semantic_edges)
    }
    reference_pairs = {
        pair(row["source"], row["target"]) for row in read_jsonl(args.reference_edges)
    }
    result = {
        "benchmark_pairs": len(universe),
        "semantic_positives": len(semantic_positive),
        "semantic_negatives": len(universe - semantic_positive),
        "semantic_methods": {
            "ranking_only_previous_behavior": metrics(ranking, semantic_positive, universe),
            "grounded_existence_without_exact_span_gate": metrics(grounded_pairs, semantic_positive, universe),
            "current_final_exact_span_gate": metrics(final_pairs, semantic_positive, universe),
        },
        "reference_detection": metrics(reference_pairs, reference_positive, universe),
        "reference_target_resolution_unresolved": sum(
            row.get("reference_target_resolution") == "SECTION_ANCHOR_UNRESOLVED" for row in gt
        ),
        "semantic_false_negative_decomposition": {
            "missed_before_or_at_ranking": len(semantic_positive - ranking),
            "rejected_by_grounded_existence": len((semantic_positive & ranking) - grounded_pairs),
            "rejected_by_exact_span_gate": len((semantic_positive & grounded_pairs) - final_pairs),
        },
        "semantic_false_positive_decomposition": {
            "ranking_only_false_positives": len(ranking - semantic_positive),
            "remaining_after_grounded_existence": len(grounded_pairs - semantic_positive),
            "remaining_in_final_graph": len(final_pairs - semantic_positive),
        },
        "limitations": [
            "Post-hoc Codex-assisted audit, not blinded to model outputs and not independent human GT.",
            "Benchmark is enriched for ranking-selected pairs and is not exhaustive over all 3,403 body-node pairs.",
            "Recall values are benchmark recall, not guaranteed full-document recall.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_json(output, result)
    lines = [
        "# DETR taxonomy-free strict audit", "",
        f"Pairs: {len(universe)}; semantic positives: {len(semantic_positive)}; semantic negatives: {len(universe-semantic_positive)}.", "",
        "| Method | TP | FP | FN | Precision | Recall | F1 |", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in result["semantic_methods"].items():
        lines.append(
            f"| {name} | {row['tp']} | {row['fp']} | {row['fn']} | "
            f"{100*row['precision']:.1f}% | {100*row['recall']:.1f}% | {100*row['f1']:.1f}% |"
        )
    lines.extend(["", "This is an internal Codex-assisted post-hoc audit benchmark, not independent human or publication-grade GT.", ""])
    output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
