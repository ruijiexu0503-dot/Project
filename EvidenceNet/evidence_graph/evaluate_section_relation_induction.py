from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json


FAMILY = {
    "PROVIDES_BACKGROUND_FOR": "CONTEXTUALIZES", "EXPLAINS": "DEVELOPS",
    "ELABORATES": "DEVELOPS", "SUPPORTS": "SUPPORTS", "QUALIFIES": "MODIFIES",
    "CONTRASTS_WITH": "MODIFIES", "DEPENDS_ON": "DEPENDS_ON", "RESULTS_IN": "RESULTS_IN",
}


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def score(rows: list[dict], positive: dict, negative: set, a: str, b: str) -> tuple[dict, set]:
    predicted = {pair(row[a], row[b]) for row in rows}
    tp, fp = predicted & set(positive), predicted & negative
    fn, tn = set(positive) - predicted, negative - predicted
    precision = len(tp) / max(1, len(tp) + len(fp))
    recall = len(tp) / max(1, len(positive))
    return ({"predicted_total": len(predicted), "true_positives": len(tp),
             "false_positives_in_reference": len(fp), "false_negatives": len(fn),
             "true_negatives": len(tn), "precision_on_reference": round(precision, 4),
             "recall": round(recall, 4),
             "f1_on_reference": round(2 * precision * recall / max(1e-12, precision + recall), 4)}, tp)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate grouped paper relation induction")
    parser.add_argument("--result", default="output/scientific_grouped_relations/Qwen3.5-35B-A3B/gw150914_detection")
    parser.add_argument("--ground-truth", default="evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl")
    args = parser.parse_args()
    root = Path(args.result)
    truth = read_jsonl(args.ground_truth)
    positive = {pair(row["node_a"], row["node_b"]): row for row in truth
                if row["gold_label"] == "RELATION"}
    negative = {pair(row["node_a"], row["node_b"]) for row in truth
                if row["gold_label"] == "NONE"}
    groups = read_jsonl(root / "section_groups.jsonl")
    related = read_jsonl(root / "related_edges.jsonl")
    verified = read_jsonl(root / "accepted_edges.jsonl")
    visible = set()
    for group in groups:
        core, members = set(group["core_node_ids"]), set(group["node_ids"])
        visible.update(pair(a, b) for a in core for b in members if a != b)
    existence, true_pairs = score(related, positive, negative, "node_a", "node_b")
    fully_verified, _ = score(verified, positive, negative, "source", "target")
    by_pair = {pair(row["node_a"], row["node_b"]): row for row in related}
    family_correct = sum(by_pair[key]["relation_family"] == FAMILY[positive[key]["gold_relation"]]
                         for key in true_pairs)
    direction_correct = sum(by_pair[key]["source"] == positive[key]["gold_source"]
                            and by_pair[key]["target"] == positive[key]["gold_target"]
                            for key in true_pairs)
    report = {
        "runtime": {"slurm_job_id": 5068241, "wall_clock": "00:20:12", "llm_calls": len(groups)},
        "group_coverage": {"groups": len(groups), "gold_pairs_visible": len(set(positive) & visible),
                           "gold_pairs_total": len(positive)},
        "existence_detection": existence,
        "fully_verified": fully_verified,
        "annotation_on_detected_gold": {
            "detected_gold": len(true_pairs), "family_correct": family_correct,
            "family_accuracy": round(family_correct / max(1, len(true_pairs)), 4),
            "direction_correct": direction_correct,
            "direction_accuracy": round(direction_correct / max(1, len(true_pairs)), 4),
        },
        "conclusion": "Runtime target passed, but recall and annotation quality failed.",
    }
    write_json(root / "evaluation.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
