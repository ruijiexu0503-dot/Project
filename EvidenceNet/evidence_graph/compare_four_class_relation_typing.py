from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .four_class_relation_typing import ABSTAIN, RELATIONS
from .io_utils import read_json, read_jsonl, write_json


MODELS = ("Qwen3.5-35B-A3B", "Qwen3.5-397B-A17B", "Qwen3.6-35B-A3B")


def exact_binomial_two_sided(discordant_a: int, discordant_b: int) -> float:
    total = discordant_a + discordant_b
    if total == 0:
        return 1.0
    lower = min(discordant_a, discordant_b)
    probability = 2 * sum(math.comb(total, k) for k in range(lower + 1)) / (2 ** total)
    return min(1.0, probability)


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def count_pct(value: float | None, denominator: int) -> str:
    return "—" if value is None else f"{round(value * denominator)}/{denominator} ({pct(value)})"


def matched_comparison(fine_diagnostics: list[dict], coarse_diagnostics: list[dict]) -> dict:
    fine = {row["task_id"]: row for row in fine_diagnostics}
    coarse = {row["task_id"]: row for row in coarse_diagnostics if row["resolved"]}
    both = fine_only = coarse_only = neither = 0
    for task_id, coarse_row in coarse.items():
        fine_correct = bool(fine[task_id]["exact_type_and_direction"])
        coarse_correct = bool(coarse_row["exact_type_and_direction"])
        if fine_correct and coarse_correct:
            both += 1
        elif fine_correct:
            fine_only += 1
        elif coarse_correct:
            coarse_only += 1
        else:
            neither += 1
    return {
        "pairs": len(coarse), "both_correct": both, "fine_only_correct": fine_only,
        "four_class_only_correct": coarse_only, "both_wrong": neither,
        "fine_exact_accuracy_matched": round((both + fine_only) / len(coarse), 4),
        "four_class_exact_accuracy": round((both + coarse_only) / len(coarse), 4),
        "exact_accuracy_delta": round((coarse_only - fine_only) / len(coarse), 4),
        "mcnemar_exact_p": round(exact_binomial_two_sided(fine_only, coarse_only), 6),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare four-class oracle-pair runs with the six-way benchmark")
    parser.add_argument("--root", default="output")
    args = parser.parse_args()
    root = Path(args.root)
    models = {}
    for model in MODELS:
        fine_root = root / "strict_relation_typing" / model / "gw150914_detection"
        new_root = root / "four_class_relation_typing" / model / "gw150914_detection"
        if not (new_root / "evaluation.json").exists():
            models[model] = None
            continue
        evaluation = read_json(new_root / "evaluation.json")
        fine_evaluation = read_json(fine_root / "evaluation.json")
        matched = matched_comparison(read_jsonl(fine_root / "diagnostics.jsonl"),
                                     read_jsonl(new_root / "diagnostics.jsonl"))
        models[model] = {"four_class": evaluation, "previous_six_way": fine_evaluation,
                         "matched_exact_comparison": matched}
    available = [row for row in models.values() if row]
    baseline = available[0]["four_class"]["always_contributes_to_baseline"] if available else None
    report = {
        "benchmark": "gw150914-strict-four-class-type-direction-v1",
        "oracle_pairs": 28, "evaluated_pairs": 27, "unresolved_depends_on": 1,
        "models": models, "always_contributes_to_baseline": baseline,
        "qwen35_397b_status": "not run: checkpoint and remote inference credentials unavailable",
    }
    target = root / "four_class_relation_typing"
    write_json(target / "comparison.json", report)

    lines = [
        "# Four-class strict oracle-pair comparison", "",
        "The same 28 label-blind oracle pairs and Evidence context are used for every model. One manually reviewed",
        "`DEPENDS_ON` edge is unresolved and excluded from type/exact scoring, leaving 27 evaluated pairs.", "",
        "| Model | Status | Type accuracy | Direction accuracy | Exact type+direction | Macro P / R / F1 | Rejects | Input A→source |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model, row in models.items():
        if not row:
            lines.append(f"| {model} | unavailable/not run | — | — | — | — | — | — |")
            continue
        value = row["four_class"]
        lines.append(
            f"| {model} | complete | {count_pct(value['relation_type_accuracy'], 27)} | "
            f"{count_pct(value['direction_accuracy'], value['directed_evaluated_pairs'])} | "
            f"{count_pct(value['exact_type_and_direction_accuracy'], 27)} | "
            f"{value['macro_precision']:.4f} / {value['macro_recall']:.4f} / {value['macro_f1']:.4f} | "
            f"{value['reject_uncertain_count']} | {value['input_a_as_source_count']}/"
            f"{value['predictions_with_direction']} ({pct(value['input_a_as_source_rate'])}) |"
        )
    if baseline:
        lines.append(
            f"| Always CONTRIBUTES_TO (input A→B) | baseline | {count_pct(baseline['relation_type_accuracy'], 27)} | "
            f"{count_pct(baseline['direction_accuracy'], baseline['directed_evaluated_pairs'])} | "
            f"{count_pct(baseline['exact_type_and_direction_accuracy'], 27)} | "
            f"{baseline['macro_precision']:.4f} / {baseline['macro_recall']:.4f} / {baseline['macro_f1']:.4f} | "
            f"0 | {baseline['input_a_as_source_count']}/{baseline['predictions_with_direction']} "
            f"({pct(baseline['input_a_as_source_rate'])}) |"
        )

    lines += ["", "## Direct comparison with the previous six-way taxonomy", "",
              "The comparison below uses the same 27 resolved task IDs. `p` is the exact two-sided McNemar test",
              "on pair-level exact correctness; p < 0.05 is treated as statistically significant.", "",
              "| Model | Previous six-way exact | Four-class exact | Change | Fine only / four-class only | McNemar p |",
              "|---|---:|---:|---:|---:|---:|"]
    for model, row in models.items():
        if not row:
            continue
        m = row["matched_exact_comparison"]
        lines.append(
            f"| {model} | {count_pct(m['fine_exact_accuracy_matched'], 27)} | "
            f"{count_pct(m['four_class_exact_accuracy'], 27)} | {100*m['exact_accuracy_delta']:+.1f} pp | "
            f"{m['fine_only_correct']} / {m['four_class_only_correct']} | {m['mcnemar_exact_p']:.4f} |"
        )

    lines += [
        "", "## Main conclusion", "",
        "The four-class taxonomy does **not** significantly improve exact classification on this benchmark.",
        "Exact accuracy decreases for both available models, and neither paired change is statistically significant",
        "(both McNemar p-values are above 0.05). The apparent 77.8% type accuracy equals the majority baseline because",
        "21 of the 27 resolved references are `CONTRIBUTES_TO`.", "",
        "The main regression is direction prediction: the broad `CONTRIBUTES_TO` class removes the directional cues",
        "previously supplied by fine labels such as SUPPORTS and EXPLAINS. Qwen3.5 chooses input A as source for",
        "26/28 pairs and Qwen3.6 for 25/28 pairs, reducing direction accuracy to 46.2% and 50.0%, respectively.", "",
        "For Qwen3.6, remaining type errors are concentrated in `CONTRIBUTES_TO` versus `REFERENCES`",
        "(three CONTRIBUTES_TO→REFERENCES and two REFERENCES→CONTRIBUTES_TO), plus the single MODIFIES edge",
        "being absorbed into CONTRIBUTES_TO. Its CONTRASTS_WITH edge is correct. No model uses REJECT_UNCERTAIN.",
    ]

    lines += ["", "## Per-class metrics", ""]
    for model, row in models.items():
        if not row:
            continue
        value = row["four_class"]
        lines += [f"### {model}", "", "| Class | Support | Predicted | Precision | Recall | F1 |",
                  "|---|---:|---:|---:|---:|---:|"]
        for relation in RELATIONS:
            metric = value["per_class"][relation]
            lines.append(f"| {relation} | {metric['support']} | {metric['predicted']} | "
                         f"{metric['precision']:.4f} | {metric['recall']:.4f} | {metric['f1']:.4f} |")
        proportions = value["prediction_proportions_all_oracle_pairs"]
        lines += ["", "Prediction proportions across all 28 oracle pairs:", "",
                  ", ".join(f"`{label}` {pct(proportions[label])}" for label in (*RELATIONS, ABSTAIN, "INVALID")),
                  "", "Confusion matrix (rows=gold; columns=prediction):", "", "```json",
                  json.dumps(value["confusion_matrix"], indent=2), "```", ""]
    (target / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(target / "comparison.md")


if __name__ == "__main__":
    main()
