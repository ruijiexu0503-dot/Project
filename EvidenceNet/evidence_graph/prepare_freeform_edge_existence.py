from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


TASK_VERSION = "freeform-edge-existence-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _node_view(node: dict) -> dict:
    return {
        "node_id": node["node_id"],
        "document_order": node["document_order"],
        "section_path": node.get("section_path") or [],
        "evidence_type": node.get("evidence_type"),
        "text": node.get("original_markdown") or node.get("plain_text") or "",
    }


def build_tasks(nodes: list[dict], candidates: list[dict]) -> list[dict]:
    by_id = {node["node_id"]: node for node in nodes}
    tasks = []
    seen = set()
    for candidate in candidates:
        endpoints = tuple(sorted((candidate["node_a"], candidate["node_b"])))
        if endpoints in seen:
            continue
        seen.add(endpoints)
        pair_id = "||".join(endpoints)
        reverse = hashlib.sha256(f"{TASK_VERSION}|{pair_id}".encode()).digest()[0] & 1
        a_id, b_id = endpoints[::-1] if reverse else endpoints
        tasks.append({
            "task_id": f"existence_{len(tasks) + 1:03d}",
            "pair_id": pair_id,
            "evidence_a": _node_view(by_id[a_id]),
            "evidence_b": _node_view(by_id[b_id]),
        })
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare label-blind free-form edge-existence tasks")
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shards", type=int, default=2)
    args = parser.parse_args()

    nodes_path, candidates_path = Path(args.nodes), Path(args.candidates)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    tasks = build_tasks(read_jsonl(nodes_path), read_jsonl(candidates_path))
    if len(tasks) != len({task["pair_id"] for task in tasks}):
        raise SystemExit("duplicate pair IDs in generated tasks")
    if args.shards < 1:
        raise SystemExit("--shards must be positive")

    write_jsonl(output / "blind_tasks.jsonl", tasks)
    shard_counts = []
    for shard in range(args.shards):
        rows = [task for index, task in enumerate(tasks) if index % args.shards == shard]
        write_jsonl(output / f"blind_tasks_shard_{shard}.jsonl", rows)
        shard_counts.append(len(rows))
    write_json(output / "manifest.json", {
        "task_version": TASK_VERSION,
        "task_count": len(tasks),
        "shards": args.shards,
        "shard_counts": shard_counts,
        "nodes_sha256": _sha256(nodes_path),
        "candidates_sha256": _sha256(candidates_path),
        "input_orientation": "label-blind SHA-256 parity",
        "candidate_metadata_excluded": True,
        "relation_labels_excluded": True,
    })
    print(json.dumps({"tasks": len(tasks), "shard_counts": shard_counts}, indent=2))


if __name__ == "__main__":
    main()
