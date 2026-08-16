from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl
from .run_sequential_long_range import _parse as parse_ranking


TASK_VERSION = "ranked-grounded-verification-v1"


def _pair_id(a: str, b: str) -> str:
    left, right = sorted((a, b))
    return hashlib.sha256(f"{TASK_VERSION}|{left}|{right}".encode()).hexdigest()[:20]


def prepare(ranking_tasks: list[dict], predictions: list[dict]) -> tuple[list[dict], dict]:
    task_by_id = {task["task_id"]: task for task in ranking_tasks}
    prediction_by_id = {row["task_id"]: row for row in predictions}
    verification: list[dict] = []
    invalid_tasks: list[str] = []
    missing_tasks: list[str] = []
    zero_cutoff = 0
    recovered_formatting_tasks: list[str] = []
    seen: set[tuple[str, str]] = set()

    for task_id, task in task_by_id.items():
        prediction = prediction_by_id.get(task_id)
        if prediction is None:
            missing_tasks.append(task_id)
            continue
        if not prediction.get("valid"):
            try:
                parsed = json.loads(prediction.get("raw_output") or "")
            except json.JSONDecodeError:
                parsed = None
            ranked, cutoff, recovered = parse_ranking(parsed, task)
            if recovered:
                prediction = {
                    **prediction,
                    "ranked_candidate_ids": ranked,
                    "edge_cutoff": cutoff,
                    "valid": True,
                }
                recovered_formatting_tasks.append(task_id)
            else:
                invalid_tasks.append(task_id)
                continue
        cutoff = prediction.get("edge_cutoff", 0)
        if cutoff == 0:
            zero_cutoff += 1
        candidates = {node["node_id"]: node for node in task["earlier_candidates"]}
        for earlier_id in prediction.get("ranked_candidate_ids", [])[:cutoff]:
            if earlier_id not in candidates:
                continue
            current = task["current_node"]
            pair = tuple(sorted((earlier_id, current["node_id"])))
            if pair in seen:
                continue
            seen.add(pair)
            verification.append({
                "task_id": f"detr_verify_{len(verification) + 1:04d}",
                "pair_id": _pair_id(*pair),
                "evidence_a": candidates[earlier_id],
                "evidence_b": current,
                "selection_provenance": {
                    "ranking_task_id": task_id,
                    "rank": prediction["ranked_candidate_ids"].index(earlier_id) + 1,
                    "edge_cutoff": cutoff,
                    "ranking_prompt_version": prediction.get("prompt_version"),
                },
            })

    manifest = {
        "task_version": TASK_VERSION,
        "ranking_tasks": len(ranking_tasks),
        "ranking_predictions": len(predictions),
        "valid_ranking_tasks": len(ranking_tasks) - len(invalid_tasks) - len(missing_tasks),
        "invalid_ranking_tasks": invalid_tasks,
        "recovered_formatting_tasks": recovered_formatting_tasks,
        "missing_ranking_tasks": missing_tasks,
        "zero_cutoff_tasks": zero_cutoff,
        "selected_pairs_for_grounded_verification": len(verification),
        "production_graph_modified": False,
    }
    return verification, manifest


def _write_shards(tasks: list[dict], output: Path, shard_count: int) -> list[int]:
    shards: list[list[dict]] = [[] for _ in range(shard_count)]
    loads = [0] * shard_count
    for task in sorted(
        tasks,
        key=lambda row: -len(json.dumps(row, ensure_ascii=False)),
    ):
        target = min(range(shard_count), key=lambda index: (loads[index], index))
        shards[target].append(task)
        loads[target] += len(json.dumps(task, ensure_ascii=False))
    for index, shard in enumerate(shards):
        shard.sort(key=lambda row: row["task_id"])
        root = output / f"shard_{index}"
        root.mkdir(parents=True, exist_ok=True)
        write_jsonl(root / "verification_tasks.jsonl", shard)
    return [len(shard) for shard in shards]


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare grounding checks from comparative ranking cutoffs")
    parser.add_argument("--ranking-tasks", required=True)
    parser.add_argument("--ranking-predictions", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()

    predictions = []
    for path in args.ranking_predictions:
        predictions.extend(read_jsonl(path))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    tasks, manifest = prepare(read_jsonl(args.ranking_tasks), predictions)
    write_jsonl(output / "verification_tasks.jsonl", tasks)
    manifest["shard_task_counts"] = _write_shards(tasks, output, args.shards)
    write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
