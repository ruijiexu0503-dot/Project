from __future__ import annotations

import json
from pathlib import Path

from .io_utils import read_json, read_jsonl, write_json


ROOT = Path("output/scientific_body_semantics_coarse")
DOC = "gw150914_detection"
MODELS = ("Qwen3.5-35B-A3B", "Qwen3.6-35B-A3B")
FAMILY = {"PROVIDES_BACKGROUND_FOR": "CONTEXTUALIZES", "EXPLAINS": "DEVELOPS",
          "ELABORATES": "DEVELOPS", "SUPPORTS": "SUPPORTS", "QUALIFIES": "MODIFIES",
          "CONTRASTS_WITH": "MODIFIES", "DEPENDS_ON": "DEPENDS_ON", "RESULTS_IN": "RESULTS_IN"}


def pair(a, b): return tuple(sorted((a, b)))


def main():
    candidates = read_jsonl(Path("output/scientific_body_semantics/shared_candidates") / DOC / "candidates.jsonl")
    candidate_pairs = {pair(row["node_a"], row["node_b"]) for row in candidates}
    gold_rows = read_jsonl(Path("evaluation/ground_truth") / DOC / "all_pairs_ground_truth.jsonl")
    gold = {pair(row["node_a"], row["node_b"]): row for row in gold_rows}
    positives = {key: row for key, row in gold.items() if row["gold_label"] == "RELATION"}
    available = set(gold) & candidate_pairs; available_positive = set(positives) & candidate_pairs
    report = {"doc_id": DOC, "candidate_pairs": len(candidates), "models": {}}
    for model in MODELS:
        path = ROOT / model / DOC
        accepted = read_jsonl(path / "accepted_edges.jsonl")
        predicted = {pair(row["source"], row["target"]): row for row in accepted}
        predicted_reference = set(predicted) & available
        tp = predicted_reference & set(positives); fp = predicted_reference - set(positives)
        fn = available_positive - predicted_reference; tn = (available - set(positives)) - predicted_reference
        precision = len(tp) / max(1, len(tp) + len(fp)); recall = len(tp) / max(1, len(tp) + len(fn))
        family_correct = sum(predicted[key]["relation_family"] == FAMILY[positives[key]["gold_relation"]] for key in tp)
        direction_correct = sum(predicted[key]["source"] == positives[key]["gold_source"]
                                and predicted[key]["target"] == positives[key]["gold_target"] for key in tp)
        exact = sum(predicted[key]["relation_family"] == FAMILY[positives[key]["gold_relation"]]
                    and predicted[key]["source"] == positives[key]["gold_source"]
                    and predicted[key]["target"] == positives[key]["gold_target"] for key in tp)
        report["models"][model] = {"status": read_json(path / "status.json"), "accepted_total": len(accepted),
            "evaluated_reference_pairs": len(available), "true_positives": len(tp), "false_positives": len(fp),
            "true_negatives": len(tn), "false_negatives": len(fn), "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(2*precision*recall/max(1e-12,precision+recall), 4),
            "error_rate": round((len(fp)+len(fn))/max(1,len(available)), 4),
            "false_negative_rate": round(len(fn)/max(1,len(tp)+len(fn)), 4),
            "candidate_generation_recall": round(len(available_positive)/max(1,len(positives)), 4),
            "end_to_end_recall": round(len(tp)/max(1,len(positives)), 4),
            "family_accuracy_on_true_pairs": round(family_correct/max(1,len(tp)), 4),
            "direction_accuracy_on_true_pairs": round(direction_correct/max(1,len(tp)), 4),
            "exact_family_and_direction_accuracy": round(exact/max(1,len(tp)), 4)}
    old_path = Path("output/scientific_body_semantics/comparison_statistics.json")
    if old_path.exists():
        old = read_json(old_path)
        report["fine_grained_baseline"] = {model: old["models"][model]["pilot_reference"] for model in MODELS}
    write_json(ROOT / "comparison_statistics.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
