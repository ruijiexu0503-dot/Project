from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


TASK_VERSION = "current-accepted-pairs-split-retype-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _node_view(node: dict) -> dict:
    return {
        "node_id": node["node_id"],
        "document_order": node["document_order"],
        "section_path": node.get("section_path") or [],
        "evidence_type": node.get("evidence_type"),
        "discourse_role": node.get("discourse_role"),
        "text": node.get("original_markdown") or node.get("plain_text") or "",
    }


def build_tasks(nodes: list[dict], edges: list[dict]) -> list[dict]:
    by_id = {node["node_id"]: node for node in nodes}
    tasks = []
    seen = set()
    for edge in edges:
        endpoints = tuple(sorted((edge["source"], edge["target"])))
        if endpoints in seen:
            continue
        seen.add(endpoints)
        pair_id = "||".join(endpoints)
        reverse = hashlib.sha256(f"{TASK_VERSION}|{pair_id}".encode()).digest()[0] & 1
        a_id, b_id = endpoints[::-1] if reverse else endpoints
        tasks.append({
            "task_id": f"current_{len(tasks) + 1:03d}",
            "pair_id": pair_id,
            "evidence_a": _node_view(by_id[a_id]),
            "evidence_b": _node_view(by_id[b_id]),
        })
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create label-blind split-taxonomy retyping tasks from accepted semantic pairs"
    )
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--edges", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    nodes_path, edges_path, output = Path(args.nodes), Path(args.edges), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    tasks = build_tasks(read_jsonl(nodes_path), read_jsonl(edges_path))
    forbidden = {
        "rationale", "source_supporting_span", "target_supporting_span", "confidence",
        "relation", "edge_type", "semantic_status", "model", "prompt_version",
    }

    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    task_keys = set(keys(tasks))
    leaked = sorted(
        key for key in task_keys if key in forbidden or key.startswith("gold_")
    )
    if leaked:
        raise SystemExit(f"answer leakage in blind tasks: {leaked}")
    if len(tasks) != len({task["pair_id"] for task in tasks}):
        raise SystemExit("duplicate pair IDs in generated tasks")

    write_jsonl(output / "blind_tasks.jsonl", tasks)
    write_json(output / "manifest.json", {
        "task_version": TASK_VERSION,
        "task_count": len(tasks),
        "nodes_sha256": _sha256(nodes_path),
        "source_edges_sha256": _sha256(edges_path),
        "input_orientation": "label-blind SHA-256 parity",
        "excluded_answer_fields": sorted(forbidden),
    })
    print(json.dumps({
        "tasks": len(tasks),
        "output": str(output / "blind_tasks.jsonl"),
    }, indent=2))


if __name__ == "__main__":
    main()
