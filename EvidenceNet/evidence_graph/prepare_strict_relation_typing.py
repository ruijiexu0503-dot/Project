from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


BENCHMARK_VERSION = "gw150914-strict-type-direction-v1"
PROMPT_VERSION = "known-related-six-way-type-direction-v1"
RELATIONS = ("ELABORATES", "SUPPORTS", "EXPLAINS", "QUALIFIES", "DEPENDS_ON", "CONTRASTS_WITH")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def node_view(node: dict) -> dict:
    return {
        "node_id": node["node_id"],
        "document_order": node["document_order"],
        "section_path": node.get("section_path") or [],
        "evidence_type": node.get("evidence_type"),
        "discourse_role": node.get("discourse_role"),
        "text": node.get("original_markdown") or node.get("plain_text") or "",
    }


def build_tasks(strict_rows: list[dict], nodes: list[dict]) -> list[dict]:
    by_id = {node["node_id"]: node for node in nodes}
    tasks = []
    for row in strict_rows:
        endpoints = sorted((row["node_a"], row["node_b"]))
        pair_id = "||".join(endpoints)
        # Input orientation is deterministic and label-blind. It does not inspect
        # gold_source, gold_target, relation type, rationale, or supporting spans.
        reverse = hashlib.sha256(f"{BENCHMARK_VERSION}|{pair_id}".encode()).digest()[0] & 1
        a_id, b_id = (endpoints[::-1] if reverse else endpoints)
        tasks.append({
            "task_id": f"strict_{len(tasks) + 1:03d}",
            "pair_id": pair_id,
            "evidence_a": node_view(by_id[a_id]),
            "evidence_b": node_view(by_id[b_id]),
        })
    return tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Create label-blind strict relation-typing tasks")
    parser.add_argument("--strict-ground-truth",
                        default="evaluation/ground_truth/gw150914_detection/strict_relation_ground_truth.jsonl")
    parser.add_argument("--nodes", default=(
        "output/scientific_body_cascade/Qwen3.5-9B-adaptive/gw150914_detection/evidence_nodes.jsonl"))
    parser.add_argument("--output", default="output/strict_relation_typing/shared")
    args = parser.parse_args()
    strict_path, nodes_path, output = Path(args.strict_ground_truth), Path(args.nodes), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    strict_rows, nodes = read_jsonl(strict_path), read_jsonl(nodes_path)
    tasks = build_tasks(strict_rows, nodes)
    serialized = json.dumps(tasks, ensure_ascii=False).casefold()
    forbidden = ("gold_relation", "gold_source", "gold_target", "supporting_span",
                 "annotation_status", "rationale", "is_gold")
    leaked = [field for field in forbidden if field in serialized]
    if leaked:
        raise SystemExit(f"gold leakage in blind tasks: {leaked}")
    if len(tasks) != 28 or len({task["pair_id"] for task in tasks}) != 28:
        raise SystemExit("expected 28 unique strict tasks")
    write_jsonl(output / "blind_tasks.jsonl", tasks)
    write_json(output / "manifest.json", {
        "benchmark_version": BENCHMARK_VERSION,
        "prompt_version": PROMPT_VERSION,
        "task_count": len(tasks),
        "relation_choices": list(RELATIONS),
        "strict_ground_truth_sha256": sha256(strict_path),
        "evidence_nodes_sha256": sha256(nodes_path),
        "input_orientation": "label-blind SHA-256 parity",
        "prompt_excludes": list(forbidden),
    })
    print(json.dumps({"tasks": len(tasks), "output": str(output / "blind_tasks.jsonl")}, indent=2))


if __name__ == "__main__":
    main()
