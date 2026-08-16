from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


TASK_VERSION = "comparative-freeform-edge-selection-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_order(source: str, target: str) -> str:
    """Stable label-blind ordering that does not leak document order or retrieval rank."""
    return hashlib.sha256(f"{TASK_VERSION}|{source}|{target}".encode()).hexdigest()


def build_tasks(pair_tasks: list[dict]) -> list[dict]:
    nodes: dict[str, dict] = {}
    incident: dict[str, set[str]] = defaultdict(set)
    for task in pair_tasks:
        a, b = task["evidence_a"], task["evidence_b"]
        nodes[a["node_id"]], nodes[b["node_id"]] = a, b
        incident[a["node_id"]].add(b["node_id"])
        incident[b["node_id"]].add(a["node_id"])

    tasks = []
    for source in sorted(incident, key=lambda node_id: (nodes[node_id]["document_order"], node_id)):
        targets = sorted(incident[source], key=lambda target: _candidate_order(source, target))
        tasks.append({
            "task_id": f"center_{len(tasks) + 1:03d}",
            "source": nodes[source],
            "candidates": [nodes[target] for target in targets],
        })
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare label-blind comparative edge-selection tasks")
    parser.add_argument("--pair-tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shards", type=int, default=1)
    args = parser.parse_args()

    source, output = Path(args.pair_tasks), Path(args.output)
    if args.shards < 1:
        raise SystemExit("--shards must be positive")
    output.mkdir(parents=True, exist_ok=True)
    tasks = build_tasks(read_jsonl(source))
    write_jsonl(output / "center_tasks.jsonl", tasks)
    shard_counts = []
    for shard in range(args.shards):
        rows = [task for index, task in enumerate(tasks) if index % args.shards == shard]
        write_jsonl(output / f"center_tasks_shard_{shard}.jsonl", rows)
        shard_counts.append(len(rows))
    write_json(output / "manifest.json", {
        "task_version": TASK_VERSION,
        "task_count": len(tasks),
        "candidate_pair_count": sum(len(task["candidates"]) for task in tasks) // 2,
        "shards": args.shards,
        "shard_counts": shard_counts,
        "pair_tasks_sha256": _sha256(source),
        "candidate_order": "label-blind SHA-256",
        "maximum_selected_per_source": 3,
        "production_graph_modified": False,
    })
    print(json.dumps({"tasks": len(tasks), "shard_counts": shard_counts}, indent=2))


if __name__ == "__main__":
    main()
