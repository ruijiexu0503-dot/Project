from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .io_utils import read_json, read_jsonl, write_json


MODELS = ("Qwen3.5-35B-A3B", "Qwen3.6-35B-A3B")


def pct(value: float) -> str:
    return f"{100 * value:.1f}%"


def exact_binomial_two_sided(a_only: int, b_only: int) -> float:
    total = a_only + b_only
    if total == 0:
        return 1.0
    lower = min(a_only, b_only)
    return min(1.0, 2 * sum(math.comb(total, k) for k in range(lower + 1)) / (2 ** total))


def matched(old_rows: list[dict], new_rows: list[dict]) -> dict:
    old = {row["task_id"]: bool(row["exact_type_and_direction"]) for row in old_rows if row["resolved"]}
    new = {row["task_id"]: bool(row["semantic_exact"]) for row in new_rows if row["semantic_resolved"]}
    both = sum(old[key] and new[key] for key in new)
    old_only = sum(old[key] and not new[key] for key in new)
    new_only = sum(not old[key] and new[key] for key in new)
    neither = sum(not old[key] and not new[key] for key in new)
    return {
        "pairs": len(new),
        "both_correct": both,
        "old_only_correct": old_only,
        "split_only_correct": new_only,
        "both_wrong": neither,
        "mcnemar_exact_p": round(exact_binomial_two_sided(old_only, new_only), 6),
    }


def model_pair_comparison(rows_a: list[dict], rows_b: list[dict], field: str, semantic_only: bool) -> dict:
    a = {row["task_id"]: row for row in rows_a}
    b = {row["task_id"]: row for row in rows_b}
    task_ids = [key for key, row in a.items() if not semantic_only or row["semantic_resolved"]]
    both = sum(bool(a[key][field]) and bool(b[key][field]) for key in task_ids)
    a_only = sum(bool(a[key][field]) and not bool(b[key][field]) for key in task_ids)
    b_only = sum(not bool(a[key][field]) and bool(b[key][field]) for key in task_ids)
    neither = len(task_ids) - both - a_only - b_only
    return {
        "pairs": len(task_ids), "both_correct": both,
        "qwen35_only_correct": a_only, "qwen36_only_correct": b_only,
        "both_wrong": neither,
        "mcnemar_exact_p": round(exact_binomial_two_sided(a_only, b_only), 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare split-taxonomy oracle-pair experiments")
    parser.add_argument("--output-root", default="output")
    args = parser.parse_args()
    root = Path(args.output_root)
    evaluations, diagnostics, previous, comparisons = {}, {}, {}, {}
    for model in MODELS:
        current = root / "split_taxonomy_relation_typing" / model / "gw150914_detection"
        old = root / "four_class_relation_typing" / model / "gw150914_detection"
        evaluations[model] = read_json(current / "split_taxonomy_evaluation.json")
        diagnostics[model] = read_jsonl(current / "split_taxonomy_diagnostics.jsonl")
        previous[model] = read_json(old / "evaluation.json")
        comparisons[model] = matched(
            read_jsonl(old / "diagnostics.jsonl"), diagnostics[model]
        )

    enriched = {}
    for model in MODELS:
        evaluation = evaluations[model]
        rows = diagnostics[model]
        enriched[model] = {
            **evaluation,
            "reference_exact_accuracy": round(
                sum(row["reference_exact"] for row in rows) / len(rows), 4
            ),
            "previous_mutually_exclusive_four_class": {
                "type_accuracy": previous[model]["relation_type_accuracy"],
                "direction_accuracy": previous[model]["direction_accuracy"],
                "exact_type_and_direction_accuracy": previous[model]["exact_type_and_direction_accuracy"],
                "macro_f1": previous[model]["macro_f1"],
            },
            "matched_exact_comparison": comparisons[model],
        }

    report = {
        "benchmark": "gw150914-split-edge-taxonomy-v1",
        "oracle_pairs": 28,
        "semantic_evaluated_pairs": 27,
        "reference_evaluated_pairs": 28,
        "models": enriched,
        "model_pair_comparison": {
            "semantic_exact": model_pair_comparison(
                diagnostics[MODELS[0]], diagnostics[MODELS[1]], "semantic_exact", True
            ),
            "reference_exact": model_pair_comparison(
                diagnostics[MODELS[0]], diagnostics[MODELS[1]], "reference_exact", False
            ),
        },
        "majority_semantic_type_baseline": {
            "label": "EXPLAINS_OR_ELABORATES",
            "correct": 21,
            "evaluated": 27,
            "type_accuracy": round(21 / 27, 4),
            "macro_f1": 0.2188,
        },
        "qwen35_397b_status": "not run: checkpoint/remote credentials unavailable",
    }
    target = root / "split_taxonomy_relation_typing"
    write_json(target / "comparison.json", report)

    lines = [
        "# Split-taxonomy oracle-pair comparison", "",
        "All results use the same 28 label-blind oracle pairs. Semantic scoring excludes one manually unresolved",
        "`DEPENDS_ON` case (27 evaluated); reference scoring uses all 28 pairs with six positive references.", "",
        "## Semantic relation", "",
        "| Model | Type accuracy | Direction accuracy | Exact type+direction | Macro P / R / F1 | Rejects |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for model in MODELS:
        value = evaluations[model]["semantic"]
        lines.append(
            f"| {model} | {round(value['type_accuracy']*27)}/27 ({pct(value['type_accuracy'])}) | "
            f"{round(value['direction_accuracy']*26)}/26 ({pct(value['direction_accuracy'])}) | "
            f"{round(value['exact_type_and_direction_accuracy']*27)}/27 "
            f"({pct(value['exact_type_and_direction_accuracy'])}) | "
            f"{value['macro_precision']:.4f} / {value['macro_recall']:.4f} / {value['macro_f1']:.4f} | "
            f"{value['reject_uncertain_count']} |"
        )
    lines.append("| Always EXPLAINS_OR_ELABORATES | 21/27 (77.8%) | — | — | — / — / 0.2188 | 0 |")

    lines += [
        "", "## Explicit reference", "",
        "| Model | Precision | Recall | F1 | Existence accuracy | Direction accuracy | Exact reference |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model in MODELS:
        value = evaluations[model]["reference"]
        exact = enriched[model]["reference_exact_accuracy"]
        lines.append(
            f"| {model} | {value['true_positive']}/{value['predicted_positive']} ({pct(value['precision'])}) | "
            f"{value['true_positive']}/{value['gold_positive']} ({pct(value['recall'])}) | {pct(value['f1'])} | "
            f"{round(value['existence_accuracy']*28)}/28 ({pct(value['existence_accuracy'])}) | "
            f"{round(value['direction_accuracy']*6)}/6 ({pct(value['direction_accuracy'])}) | "
            f"{round(exact*28)}/28 ({pct(exact)}) |"
        )

    lines += ["", "## Joint exact outcomes", "",
              "| Model | Both correct | Semantic only | Reference only | Both wrong |",
              "|---|---:|---:|---:|---:|"]
    for model in MODELS:
        value = evaluations[model]["joint"]
        lines.append(
            f"| {model} | {value['both_correct']}/27 | {value['semantic_only']}/27 | "
            f"{value['reference_only']}/27 | {value['both_wrong']}/27 |"
        )

    lines += [
        "", "## Change from the previous mutually exclusive four-class taxonomy", "",
        "| Model | Old direction | Split direction | Old exact | Split semantic exact | Change | McNemar p |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model in MODELS:
        old = previous[model]
        new = evaluations[model]["semantic"]
        comparison = comparisons[model]
        delta = new["exact_type_and_direction_accuracy"] - old["exact_type_and_direction_accuracy"]
        lines.append(
            f"| {model} | {pct(old['direction_accuracy'])} | {pct(new['direction_accuracy'])} | "
            f"{pct(old['exact_type_and_direction_accuracy'])} | "
            f"{pct(new['exact_type_and_direction_accuracy'])} | {100*delta:+.1f} pp | "
            f"{comparison['mcnemar_exact_p']:.4f} |"
        )

    lines += ["", "## Per-class semantic F1", "",
              "| Class | Support | Qwen3.5 F1 | Qwen3.6 F1 |",
              "|---|---:|---:|---:|"]
    for relation in ("SUPPORTS", "EXPLAINS_OR_ELABORATES", "MODIFIES", "CONTRASTS_WITH"):
        a = evaluations[MODELS[0]]["semantic"]["per_class"][relation]
        b = evaluations[MODELS[1]]["semantic"]["per_class"][relation]
        lines.append(f"| {relation} | {a['support']} | {a['f1']:.4f} | {b['f1']:.4f} |")

    lines += [
        "", "## Conclusions", "",
        "1. Separating discourse reference from semantic function materially improves role direction and exact semantic classification. "
        "Qwen3.5 improves by +33.3 percentage points exact (McNemar p=0.0352); Qwen3.6 improves by +22.2 points, "
        "although that paired change is not significant on 27 examples (p=0.2101).",
        "2. Semantic type accuracy alone remains below the 77.8% majority-type baseline because both models confuse some "
        "EXPLAINS_OR_ELABORATES and SUPPORTS cases. Their macro F1 is nevertheless above the majority baseline.",
        "3. Neither model predicts the single MODIFIES or the single CONTRASTS_WITH example correctly. The benchmark is too "
        "small and imbalanced to estimate those classes reliably.",
        "4. Reference detection remains weak. Frequent false positives copy a real cue that points to a third node rather than "
        "the other endpoint; frequent false negatives miss equation back-reference and plural anaphora. Both models obtain only "
        "2/6 correct reference directions and 20/28 exact reference decisions.",
        "5. Qwen3.5 is slightly better on semantic exact and joint both-correct; Qwen3.6 is better on reference existence F1. "
        "Pairwise differences between the two models are not significant (semantic and reference McNemar p=1.0).",
        "", "Qwen3.5-397B-A17B was not run because no local checkpoint or remote inference credentials are available.",
    ]
    (target / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(target / "comparison.md")


if __name__ == "__main__":
    main()
