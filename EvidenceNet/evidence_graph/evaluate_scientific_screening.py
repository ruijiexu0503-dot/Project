from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate and gate high-recall pair screening")
    parser.add_argument("--source", required=True)
    parser.add_argument("--screening", required=True)
    parser.add_argument("--ground-truth", default="evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl")
    parser.add_argument("--minimum-recall", type=float, default=.90)
    parser.add_argument("--maximum-forwarded", type=int, default=180)
    args = parser.parse_args()
    source, screening = Path(args.source), Path(args.screening)
    candidates = read_jsonl(source / "candidates.jsonl")
    decisions = read_jsonl(screening / "screening_decisions.jsonl")
    truth = read_jsonl(args.ground_truth)
    positive = {pair(row["node_a"], row["node_b"]) for row in truth if row["gold_label"] == "RELATION"}
    negative = {pair(row["node_a"], row["node_b"]) for row in truth if row["gold_label"] == "NONE"}
    candidate_pairs = {pair(row["node_a"], row["node_b"]) for row in candidates}
    forwarded = {pair(row["candidate"]["node_a"], row["candidate"]["node_b"])
                 for row in decisions if row["classification"] in {"RELATED", "POSSIBLE"}}
    tp, fp, fn = forwarded & positive, forwarded & negative, positive - forwarded
    recall = len(tp) / max(1, len(positive))
    precision = len(tp) / max(1, len(tp) + len(fp))
    complete = len(decisions) == len(candidates)
    passed = complete and recall >= args.minimum_recall and len(forwarded) <= args.maximum_forwarded
    report = {
        "complete": complete, "candidate_total": len(candidates),
        "candidate_gold_recall": round(len(candidate_pairs & positive) / max(1, len(positive)), 4),
        "forwarded_total": len(forwarded), "reduction": round(1 - len(forwarded) / max(1, len(candidates)), 4),
        "true_positives": len(tp), "false_positives_in_reference": len(fp), "false_negatives": len(fn),
        "screening_recall": round(recall, 4), "screening_precision_on_reference": round(precision, 4),
        "gate": {"minimum_recall": args.minimum_recall, "maximum_forwarded": args.maximum_forwarded,
                 "passed": passed},
        "missed_gold_pairs": [list(value) for value in sorted(fn)],
    }
    write_json(screening / "evaluation.json", report)
    write_json(screening / "gate.json", report["gate"])
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
