from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def _pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _distance_bin(task: dict) -> str:
    distance = abs(task["evidence_a"]["document_order"] - task["evidence_b"]["document_order"])
    return "1-3" if distance <= 3 else "4-6" if distance <= 6 else "7+"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context_for(node_id: str, other_id: str, nodes: list[dict]) -> dict:
    by_id = {node["node_id"]: node for node in nodes}
    focal = by_id[node_id]
    section = focal.get("section_path") or []
    candidates = [
        node for node in nodes
        if node["node_id"] not in {node_id, other_id}
        and (node.get("section_path") or []) == section
        and node.get("evidence_type") == "text"
        and len((node.get("plain_text") or "").strip()) >= 40
    ]
    before = [node for node in candidates if node["document_order"] < focal["document_order"]]
    after = [node for node in candidates if node["document_order"] > focal["document_order"]]

    def compact(node: dict | None) -> dict | None:
        if not node:
            return None
        return {
            "node_id": node["node_id"], "document_order": node["document_order"],
            "text": node.get("plain_text") or "",
        }

    return {
        "before": compact(max(before, key=lambda row: row["document_order"], default=None)),
        "after": compact(min(after, key=lambda row: row["document_order"], default=None)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a blind, diagnostic existence-prompt-v2 pilot")
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--v1-diagnostics", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--true-negative-sample", type=int, default=12)
    parser.add_argument("--shards", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    nodes_path, tasks_path = Path(args.nodes), Path(args.tasks)
    gt_path, diagnostics_path = Path(args.ground_truth), Path(args.v1_diagnostics)
    nodes, tasks = read_jsonl(nodes_path), read_jsonl(tasks_path)
    truth = {_pair(row["node_a"], row["node_b"]): row for row in read_jsonl(gt_path)}
    diagnostics = {row["task_id"]: row for row in read_jsonl(diagnostics_path)}

    positives, prior_false_positives = [], []
    true_negative_pool: dict[str, list[dict]] = defaultdict(list)
    for task in tasks:
        gold = truth[_pair(task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])]
        previous = diagnostics[task["task_id"]]
        if gold["gold_label"] == "RELATION":
            positives.append(task)
        elif previous["production_positive"]:
            prior_false_positives.append(task)
        else:
            true_negative_pool[_distance_bin(task)].append(task)

    rng = random.Random(args.seed)
    sampled_true_negatives = []
    bins = ("1-3", "4-6", "7+")
    per_bin = args.true_negative_sample // len(bins)
    remainder = args.true_negative_sample % len(bins)
    for index, name in enumerate(bins):
        rows = sorted(true_negative_pool[name], key=lambda row: row["pair_id"])
        sampled_true_negatives.extend(rng.sample(rows, min(len(rows), per_bin + (index < remainder))))

    selected = positives + prior_false_positives + sampled_true_negatives
    selected.sort(key=lambda row: row["task_id"])
    blind = []
    for task in selected:
        row = dict(task)
        a_id, b_id = task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]
        row["context_a"] = _context_for(a_id, b_id, nodes)
        row["context_b"] = _context_for(b_id, a_id, nodes)
        blind.append(row)

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "blind_tasks.jsonl", blind)
    for shard in range(args.shards):
        write_jsonl(output / f"blind_tasks_shard_{shard}.jsonl", blind[shard::args.shards])
    manifest = {
        "task_version": "existence-multisignal-context-v2-pilot",
        "task_count": len(blind), "shards": args.shards,
        "selection": {
            "all_candidate_gold_positives": len(positives),
            "all_v1_false_positives": len(prior_false_positives),
            "sampled_v1_true_negatives": len(sampled_true_negatives),
        },
        "true_negative_sample_distance_bins": {
            name: sum(_distance_bin(row) == name for row in sampled_true_negatives) for name in bins
        },
        "labels_exposed_to_model": False,
        "neighbor_context": "nearest eligible text node before and after each endpoint in the same section",
        "seed": args.seed,
        "hashes": {
            "nodes": _sha256(nodes_path), "all_tasks": _sha256(tasks_path),
            "ground_truth": _sha256(gt_path), "v1_diagnostics": _sha256(diagnostics_path),
        },
    }
    write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
