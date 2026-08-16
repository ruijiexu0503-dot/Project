from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import write_json


MODELS = ("Qwen3.5-35B-A3B", "Qwen3.5-397B-A17B", "Qwen3.6-35B-A3B")


def load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.1f}%"


def count_pct(value: float | None, denominator: int) -> str:
    return "—" if value is None else f"{round(value * denominator)}/{denominator} ({pct(value)})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare fine, post-hoc collapsed, and coarse-prompt results")
    parser.add_argument("--root", default="output")
    args = parser.parse_args()
    root = Path(args.root)
    results = {}
    for model in MODELS:
        fine_root = root / "strict_relation_typing" / model / "gw150914_detection"
        coarse_root = root / "coarse_relation_typing" / model / "gw150914_detection"
        results[model] = {
            "fine_prompt": load(fine_root / "evaluation.json"),
            "fine_prompt_posthoc_collapsed": load(coarse_root / "posthoc_coarse_evaluation.json"),
            "coarse_prompt": load(coarse_root / "coarse_evaluation.json"),
        }
    available = [row["fine_prompt_posthoc_collapsed"] for row in results.values()
                 if row["fine_prompt_posthoc_collapsed"]]
    baseline = available[0]["always_expands_baseline"] if available else None
    report = {"benchmark": "gw150914-strict-coarse-type-direction-v1", "pairs": 28,
              "mapping": {"EXPANDS": ["ELABORATES", "EXPLAINS"], "SUPPORTS": ["SUPPORTS"],
                          "CONDITIONS": ["QUALIFIES", "DEPENDS_ON"],
                          "CONTRASTS_WITH": ["CONTRASTS_WITH"]},
              "models": results, "always_expands_baseline": baseline}
    target = root / "coarse_relation_typing"
    write_json(target / "comparison.json", report)

    lines = [
        "# Hierarchical coarse relation comparison", "",
        "All rows use the same 28 known-related, label-blind pairs and the same input orientation.",
        "The coarse terminal labels are `EXPANDS`, `SUPPORTS`, `CONDITIONS`, and `CONTRASTS_WITH`;",
        "the prompt treats contrast as the first hierarchical decision and otherwise selects one of three families.", "",
        "| Model | Evaluation | Type accuracy | Direction accuracy | Exact type+direction | Macro F1 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for model, stages in results.items():
        for label, key in [("original six-way prompt", "fine_prompt"),
                           ("six-way output, post-hoc collapsed", "fine_prompt_posthoc_collapsed"),
                           ("hierarchical coarse prompt", "coarse_prompt")]:
            value = stages[key]
            if value is None:
                if key == "coarse_prompt":
                    lines.append(f"| {model} | {label} | unavailable/not run | — | — | — |")
                continue
            lines.append(f"| {model} | {label} | {count_pct(value['type_accuracy'], 28)} | "
                         f"{count_pct(value['direction_accuracy_directed_pairs'], 27)} | "
                         f"{count_pct(value['exact_type_and_direction_accuracy'], 28)} | "
                         f"{value['macro_f1']:.4f} |")
    if baseline:
        lines.append(f"| Always EXPANDS (input A→B) | baseline | {count_pct(baseline['type_accuracy'], 28)} | "
                     f"{count_pct(baseline['direction_accuracy_directed_pairs'], 27)} | "
                     f"{count_pct(baseline['exact_type_and_direction_accuracy'], 28)} | "
                     f"{baseline['macro_f1']:.4f} |")

    lines += ["", "## Exact-accuracy changes", "",
              "Positive values mean more pairs have both the terminal relation and direction correct.", "",
              "| Model | Fine → post-hoc collapse | Fine → coarse prompt | Post-hoc collapse → coarse prompt |",
              "|---|---:|---:|---:|"]
    for model, stages in results.items():
        fine = stages["fine_prompt"]
        posthoc = stages["fine_prompt_posthoc_collapsed"]
        coarse = stages["coarse_prompt"]
        if not (fine and posthoc and coarse):
            continue
        fine_score = fine["exact_type_and_direction_accuracy"]
        posthoc_score = posthoc["exact_type_and_direction_accuracy"]
        coarse_score = coarse["exact_type_and_direction_accuracy"]
        lines.append(f"| {model} | {100 * (posthoc_score - fine_score):+.1f} pp | "
                     f"{100 * (coarse_score - fine_score):+.1f} pp | "
                     f"{100 * (coarse_score - posthoc_score):+.1f} pp |")

    lines += ["", "## Coarse-prompt per-relation results", ""]
    for model, stages in results.items():
        value = stages["coarse_prompt"]
        if not value:
            continue
        lines += [f"### {model}", "", "| Relation | Support | Predicted | Precision | Recall | F1 |",
                  "|---|---:|---:|---:|---:|---:|"]
        for relation, row in value["per_relation"].items():
            lines.append(f"| {relation} | {row['support']} | {row['predicted']} | "
                         f"{row['precision']:.4f} | {row['recall']:.4f} | {row['f1']:.4f} |")
        lines += ["", "Confusion matrix (rows=gold, columns=predicted):", "", "```json",
                  json.dumps(value["confusion_matrix"], indent=2), "```", ""]
    (target / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(target / "comparison.md")


if __name__ == "__main__":
    main()
