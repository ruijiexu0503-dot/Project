from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def _pair(source: str, target: str) -> tuple[str, str]:
    return tuple(sorted((source, target)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare blind contribution-profile tasks from resolved edge-existence predictions"
    )
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--predictions", nargs="+", required=True)
    parser.add_argument("--structural-edges", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    tasks = read_jsonl(args.tasks)
    resolved: dict[str, dict] = {}
    for prediction_path in args.predictions:
        for row in read_jsonl(prediction_path):
            previous = resolved.get(row["task_id"])
            if previous is None or (not previous.get("valid") and row.get("valid")):
                resolved[row["task_id"]] = row

    continues_pairs = {
        _pair(row["source"], row["target"])
        for row in read_jsonl(args.structural_edges)
        if row.get("edge_type") == "CONTINUES_TO"
    }
    accepted, structural_overlaps = [], []
    for task in tasks:
        prediction = resolved.get(task["task_id"], {})
        if not prediction.get("valid") or prediction.get("status") != "RELATED_STRONG":
            continue
        pair = _pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])
        if pair in continues_pairs:
            structural_overlaps.append({
                "task_id": task["task_id"], "pair_id": task["pair_id"],
                "reason": "Pair also has CONTINUES_TO; keep it because structural and semantic relations may coexist.",
            })
        accepted.append(task)

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "blind_tasks.jsonl", accepted)
    write_jsonl(output / "structural_overlap_pairs.jsonl", structural_overlaps)
    report = {
        "existence_candidates": len(tasks),
        "resolved_predictions": len(resolved),
        "existence_positive": len(accepted),
        "continues_overlap_kept_for_typing": len(structural_overlaps),
        "semantic_typing_tasks": len(accepted),
        "relation_labels_exposed_to_typing": False,
    }
    write_json(output / "manifest.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
