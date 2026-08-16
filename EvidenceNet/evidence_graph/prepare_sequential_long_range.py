from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


TASK_VERSION = "sequential-long-range-ranking-v1"


def _section(node: dict) -> str:
    path = node.get("section_path") or []
    return str(path[0]) if path else "ROOT"


def _order(source: str, target: str) -> str:
    return hashlib.sha256(f"{TASK_VERSION}|{source}|{target}".encode()).hexdigest()


def build_tasks(pair_tasks: list[dict]) -> list[dict]:
    nodes: dict[str, dict] = {}
    earlier_by_current: dict[str, list[str]] = defaultdict(list)
    for task in pair_tasks:
        a, b = task["evidence_a"], task["evidence_b"]
        nodes[a["node_id"]], nodes[b["node_id"]] = a, b
        earlier, current = sorted((a, b), key=lambda node: (node["document_order"], node["node_id"]))
        distance = current["document_order"] - earlier["document_order"]
        cross_section = _section(current) != _section(earlier)
        if distance >= 4 or cross_section:
            earlier_by_current[current["node_id"]].append(earlier["node_id"])

    tasks = []
    for current in sorted(earlier_by_current, key=lambda node_id: nodes[node_id]["document_order"]):
        candidates = sorted(set(earlier_by_current[current]), key=lambda target: _order(current, target))
        tasks.append({
            "task_id": f"long_center_{len(tasks) + 1:03d}",
            "current_node": nodes[current],
            "earlier_candidates": [nodes[target] for target in candidates],
            "candidate_policy": "cross_section OR original_document_order_distance>=4",
        })
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare sequential long-range ranking tasks")
    parser.add_argument("--pair-tasks", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source, output = Path(args.pair_tasks), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    tasks = build_tasks(read_jsonl(source))
    write_jsonl(output / "ranking_tasks.jsonl", tasks)
    counts = [len(task["earlier_candidates"]) for task in tasks]
    write_json(output / "manifest.json", {
        "task_version": TASK_VERSION,
        "center_tasks": len(tasks),
        "long_range_candidate_pairs": sum(counts),
        "minimum_candidates": min(counts) if counts else 0,
        "maximum_candidates": max(counts) if counts else 0,
        "candidate_policy": "cross_section OR original_document_order_distance>=4",
        "pair_seen_once": True,
        "fixed_edge_quota": False,
        "production_graph_modified": False,
    })
    print(json.dumps({"tasks": len(tasks), "candidate_pairs": sum(counts), "counts": counts}, indent=2))


if __name__ == "__main__":
    main()
