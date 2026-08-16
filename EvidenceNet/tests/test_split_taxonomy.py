from __future__ import annotations

import json
from pathlib import Path

from evidence_graph.evaluate_split_taxonomy import score_predictions
from evidence_graph.run_split_taxonomy_relation_typing import parse


ROOT = Path(__file__).resolve().parents[1]
GT_DIR = ROOT / "evaluation/ground_truth/gw150914_detection"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def perfect_predictions(tasks: list[dict], truth: list[dict]) -> list[dict]:
    by_pair = {tuple(sorted((row["node_a"], row["node_b"]))): row for row in truth}
    predictions = []
    for task in tasks:
        key = tuple(sorted((task["evidence_a"]["node_id"], task["evidence_b"]["node_id"])))
        gold = by_pair[key]
        semantic = gold["semantic"]
        references = gold["references"]
        predictions.append({
            "task_id": task["task_id"],
            "semantic": {
                "relation": semantic["relation"] if semantic["status"] == "RESOLVED" else "REJECT_UNCERTAIN",
                "source_node_id": semantic["source"],
                "target_node_id": semantic["target"],
            },
            "references": {
                "exists": references["exists"],
                "source_node_id": references["source"],
                "target_node_id": references["target"],
            },
        })
    return predictions


def test_split_taxonomy_distribution_and_independence() -> None:
    truth = read_jsonl(GT_DIR / "split_taxonomy_relation_ground_truth.jsonl")
    assert len(truth) == 28
    assert sum(row["semantic"]["status"] == "RESOLVED" for row in truth) == 27
    assert sum(row["references"]["exists"] for row in truth) == 6
    assert sum(row["continues_audit"]["exists"] for row in truth) == 4
    assert sum(
        row["semantic"]["status"] == "RESOLVED" and row["references"]["exists"]
        for row in truth
    ) == 5


def test_perfect_dual_task_predictions_score_one() -> None:
    tasks = read_jsonl(GT_DIR / "split_taxonomy_oracle_pairs.jsonl")
    truth = read_jsonl(GT_DIR / "split_taxonomy_relation_ground_truth.jsonl")
    report, diagnostics = score_predictions(tasks, perfect_predictions(tasks, truth), truth)
    assert len(diagnostics) == 28
    assert report["semantic"]["type_accuracy"] == 1.0
    assert report["semantic"]["direction_accuracy"] == 1.0
    assert report["semantic"]["exact_type_and_direction_accuracy"] == 1.0
    assert report["semantic"]["macro_f1"] == 1.0
    assert report["reference"]["precision"] == 1.0
    assert report["reference"]["recall"] == 1.0
    assert report["reference"]["f1"] == 1.0
    assert report["reference"]["direction_accuracy"] == 1.0
    assert report["joint"]["both_correct"] == 27
    assert report["joint"]["semantic_only"] == 0
    assert report["joint"]["reference_only"] == 0
    assert report["joint"]["both_wrong"] == 0


def test_reference_direction_is_independent_from_semantic_direction() -> None:
    tasks = read_jsonl(GT_DIR / "split_taxonomy_oracle_pairs.jsonl")
    truth = read_jsonl(GT_DIR / "split_taxonomy_relation_ground_truth.jsonl")
    predictions = perfect_predictions(tasks, truth)
    target_pair = tuple(sorted((
        "gw150914_detection_EV_000007",
        "gw150914_detection_EV_000010",
    )))
    task = next(
        task for task in tasks
        if tuple(sorted((task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]))) == target_pair
    )
    prediction = next(row for row in predictions if row["task_id"] == task["task_id"])
    source = prediction["references"]["source_node_id"]
    prediction["references"]["source_node_id"] = prediction["references"]["target_node_id"]
    prediction["references"]["target_node_id"] = source
    report, _ = score_predictions(tasks, predictions, truth)
    assert report["semantic"]["exact_type_and_direction_accuracy"] == 1.0
    assert report["reference"]["direction_accuracy"] < 1.0
    assert report["joint"]["semantic_only"] == 1


def test_split_runner_accepts_opposite_semantic_and_reference_directions() -> None:
    task = {
        "task_id": "strict_003",
        "evidence_a": {"node_id": "gw150914_detection_EV_000010"},
        "evidence_b": {"node_id": "gw150914_detection_EV_000007"},
    }
    parsed = {
        "task_id": "strict_003",
        "semantic": {
            "relation": "EXPLAINS_OR_ELABORATES",
            "source_node_id": "gw150914_detection_EV_000010",
            "target_node_id": "gw150914_detection_EV_000007",
            "confidence": 0.9,
        },
        "references": {
            "exists": True,
            "source_node_id": "gw150914_detection_EV_000007",
            "target_node_id": "gw150914_detection_EV_000010",
            "cue": "shown in Fig. 1",
            "confidence": 0.95,
        },
    }
    result, valid = parse(parsed, task)
    assert valid
    assert result["semantic"]["source_node_id"] != result["references"]["source_node_id"]
