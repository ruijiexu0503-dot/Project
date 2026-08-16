from __future__ import annotations

import argparse
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze one prompt-v2 pair set for two taxonomy variants")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--predictions", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shards", type=int, default=2)
    args = parser.parse_args()

    tasks = {row["task_id"]: row for row in read_jsonl(args.tasks)}
    predictions = {}
    for path in args.predictions:
        for row in read_jsonl(path):
            predictions[row["task_id"]] = row
    accepted_ids = sorted(
        task_id for task_id, row in predictions.items()
        if row.get("valid") and row.get("status") == "RELATED"
    )
    blind = [tasks[task_id] for task_id in accepted_ids]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "blind_tasks.jsonl", blind)
    for shard in range(args.shards):
        write_jsonl(output / f"blind_tasks_shard_{shard}.jsonl", blind[shard::args.shards])
    manifest = {
        "pair_set_version": "prompt-v2-related-pilot-v1",
        "accepted_pairs": len(blind), "shards": args.shards,
        "shard_counts": [len(blind[shard::args.shards]) for shard in range(args.shards)],
        "existence_policy": "valid AND status == RELATED",
        "possible_relation_excluded": sum(
            row.get("status") == "POSSIBLE_RELATION" for row in predictions.values()
        ),
        "version_a": "non-exclusive semantic signals from existence prompt v2",
        "version_b": "exclusive fixed semantic type plus role direction",
        "same_pair_set": True, "labels_exposed_to_typing": False,
        "production_graph_modified": False,
    }
    write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
