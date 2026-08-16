from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def scores(predicted: set[tuple[str, str]], positive: set[tuple[str, str]],
           negative: set[tuple[str, str]]) -> dict:
    tp = predicted & positive
    fp = predicted & negative
    fn = positive - predicted
    tn = negative - predicted
    precision = len(tp) / max(1, len(tp) + len(fp))
    recall = len(tp) / max(1, len(tp) + len(fn))
    return {
        "true_positives": len(tp), "false_positives": len(fp),
        "true_negatives": len(tn), "false_negatives": len(fn),
        "precision": round(precision, 4), "recall": round(recall, 4),
        "f1": round(2 * precision * recall / max(1e-12, precision + recall), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate staged scientific relation extraction")
    parser.add_argument("--source", default="output/scientific_body_high_recall/shared_candidates/gw150914_detection")
    parser.add_argument("--result", required=True)
    parser.add_argument("--ground-truth", default="evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl")
    parser.add_argument("--output")
    args = parser.parse_args()
    source, result = Path(args.source), Path(args.result)
    truth = read_jsonl(args.ground_truth)
    positive = {pair(row["node_a"], row["node_b"]) for row in truth if row["gold_label"] == "RELATION"}
    negative = {pair(row["node_a"], row["node_b"]) for row in truth if row["gold_label"] == "NONE"}
    candidates = read_jsonl(source / "candidates.jsonl")
    candidate_pairs = {pair(row["node_a"], row["node_b"]) for row in candidates}
    related_rows = read_jsonl(result / "related_edges.jsonl")
    verified_rows = read_jsonl(result / "accepted_edges.jsonl")
    related_pairs = {pair(row["node_a"], row["node_b"]) for row in related_rows}
    verified_pairs = {pair(row["source"], row["target"]) for row in verified_rows}
    report = {
        "candidate_generation": {
            "candidates": len(candidates), "gold_relations": len(positive),
            "gold_retrieved": len(candidate_pairs & positive),
            "recall": round(len(candidate_pairs & positive) / max(1, len(positive)), 4),
        },
        "existence_detection": {"predicted_total": len(related_pairs), **scores(related_pairs, positive, negative)},
        "fully_verified": {"predicted_total": len(verified_pairs), **scores(verified_pairs, positive, negative)},
        "scope_note": "Precision uses only annotated negative pairs; predictions outside the reference are unreviewed.",
    }
    target = Path(args.output) if args.output else result / "evaluation.json"
    write_json(target, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
