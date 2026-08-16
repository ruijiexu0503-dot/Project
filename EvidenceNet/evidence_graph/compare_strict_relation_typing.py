from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import write_json
from .prepare_strict_relation_typing import RELATIONS


MODELS = ("Qwen3.5-35B-A3B", "Qwen3.5-397B-A17B", "Qwen3.6-35B-A3B")


def percentage(value) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def score_with_count(value: float, denominator: int) -> str:
    numerator = round(value * denominator)
    return f"{numerator}/{denominator} ({percentage(value)})"


def load_diagnostics(root: Path, model: str) -> dict[str, dict] | None:
    path = root / model / "gw150914_detection" / "diagnostics.jsonl"
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["task_id"]: row for row in rows}


def paired_exact_comparisons(root: Path, models: dict[str, dict | None]) -> list[dict]:
    available = [(model, load_diagnostics(root, model)) for model, value in models.items() if value]
    available = [(model, rows) for model, rows in available if rows]
    comparisons = []
    for index, (model_a, rows_a) in enumerate(available):
        for model_b, rows_b in available[index + 1:]:
            common = sorted(set(rows_a) & set(rows_b))
            both_correct = only_a = only_b = both_wrong = 0
            for task_id in common:
                correct_a = bool(rows_a[task_id]["exact_type_and_direction"])
                correct_b = bool(rows_b[task_id]["exact_type_and_direction"])
                if correct_a and correct_b:
                    both_correct += 1
                elif correct_a:
                    only_a += 1
                elif correct_b:
                    only_b += 1
                else:
                    both_wrong += 1
            comparisons.append({
                "model_a": model_a,
                "model_b": model_b,
                "pairs": len(common),
                "both_correct": both_correct,
                "only_model_a_correct": only_a,
                "only_model_b_correct": only_b,
                "both_wrong": both_wrong,
            })
    return comparisons


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare strict type+direction model evaluations")
    parser.add_argument("--root", default="output/strict_relation_typing")
    args = parser.parse_args()
    root = Path(args.root)
    models = {}
    for model in MODELS:
        path = root / model / "gw150914_detection" / "evaluation.json"
        models[model] = json.loads(path.read_text()) if path.exists() else None
    available = [value for value in models.values() if value]
    baseline = available[0]["always_elaborates_baseline"] if available else None
    paired = paired_exact_comparisons(root, models)
    report = {"benchmark": "gw150914-strict-type-direction-v1", "pairs": 28,
              "relation_choices": list(RELATIONS), "models": models,
              "always_elaborates_baseline": baseline,
              "paired_exact_comparisons": paired}
    write_json(root / "comparison.json", report)
    lines = [
        "# Strict known-related type + direction comparison", "",
        "Every model receives the same 28 label-blind Evidence pairs and is explicitly told that one relation exists.",
        "It must choose one of six types and independently orient the endpoints. `CONTRASTS_WITH` is symmetric.", "",
        "| Model | Status | Type accuracy | Direction accuracy | Exact type+direction | Macro F1 | ELABORATES rate |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for model, value in models.items():
        if not value:
            lines.append(f"| {model} | unavailable/not run | — | — | — | — | — |")
        else:
            lines.append(f"| {model} | complete | {score_with_count(value['type_accuracy'], value['pairs'])} | "
                         f"{score_with_count(value['direction_accuracy_directed_pairs'], value['directed_pairs'])} | "
                         f"{score_with_count(value['exact_type_and_direction_accuracy'], value['pairs'])} | "
                         f"{value['macro_f1']:.4f} | {percentage(value['elaborates_prediction_rate'])} |")
    if baseline:
        lines.append(f"| Always ELABORATES (input A→B) | baseline | {score_with_count(baseline['type_accuracy'], 28)} | "
                     f"{score_with_count(baseline['direction_accuracy_directed_pairs'], 27)} | "
                     f"{score_with_count(baseline['exact_type_and_direction_accuracy'], 28)} | "
                     f"{baseline['macro_f1']:.4f} | {percentage(baseline['elaborates_prediction_rate'])} |")
    if paired:
        lines += ["", "## Paired exact comparison", "",
                  "An exact success requires both the relation type and its direction to be correct.", "",
                  "| Model A | Model B | Both correct | Only A correct | Only B correct | Both wrong |",
                  "|---|---|---:|---:|---:|---:|"]
        for row in paired:
            lines.append(f"| {row['model_a']} | {row['model_b']} | {row['both_correct']} | "
                         f"{row['only_model_a_correct']} | {row['only_model_b_correct']} | "
                         f"{row['both_wrong']} |")
    lines += ["", "## Per-relation metrics", ""]
    for model, value in models.items():
        if not value:
            continue
        lines += [f"### {model}", "", "| Relation | Support | Predicted | Precision | Recall | F1 |",
                  "|---|---:|---:|---:|---:|---:|"]
        for relation in RELATIONS:
            row = value["per_relation"][relation]
            lines.append(f"| {relation} | {row['support']} | {row['predicted']} | "
                         f"{row['precision']:.4f} | {row['recall']:.4f} | {row['f1']:.4f} |")
        lines += ["", "Confusion matrix (rows=gold, columns=predicted):", "", "```json",
                  json.dumps(value["confusion_matrix"], indent=2), "```", ""]
    (root / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(root / "comparison.md")


if __name__ == "__main__":
    main()
