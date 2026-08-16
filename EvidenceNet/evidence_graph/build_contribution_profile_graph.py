from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an isolated graph from contribution-profile predictions")
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--references", required=True)
    parser.add_argument("--structural-edges", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--keep-semantic-continuations", action="store_true",
        help="Keep a semantic edge when the same pair also has CONTINUES_TO",
    )
    args = parser.parse_args()

    nodes, references = read_jsonl(args.nodes), read_jsonl(args.references)
    structural = read_jsonl(args.structural_edges)
    continues_pairs = {
        tuple(sorted((row["source"], row["target"])))
        for row in structural if row.get("edge_type") == "CONTINUES_TO"
    }
    tasks = {row["task_id"]: row for row in read_jsonl(args.tasks)}
    predictions = read_jsonl(args.predictions)
    semantic = []
    invalid = []
    suppressed_continuations = []
    for row in predictions:
        task = tasks[row["task_id"]]
        endpoints = sorted((task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]))
        if tuple(endpoints) in continues_pairs and not args.keep_semantic_continuations:
            suppressed_continuations.append({
                "task_id": task["task_id"], "pair_id": task["pair_id"],
                "source": endpoints[0], "target": endpoints[1],
                "reason": "Pair is already a CONTINUES_TO structural edge; do not duplicate it as semantic.",
                "typing_prediction": row,
            })
            continue
        if not row.get("valid"):
            invalid.append(row)
            semantic.append({
                "source": endpoints[0], "target": endpoints[1],
                "edge_family": "semantic", "relation": "RELATED",
                "contribution_modes": [], "directed": False, "direction_status": "UNRESOLVED",
                "confidence": 0.0, "rationale": "Typing output invalid; accepted pair retained without a forced type.",
                "metadata": {"semantic_status": "typing_invalid_retained_as_related", "task_id": task["task_id"]},
            })
            continue
        directed = row["direction_status"] == "DIRECTED"
        source = row["source_node_id"] if directed else endpoints[0]
        target = row["target_node_id"] if directed else endpoints[1]
        semantic.append({
            "source": source, "target": target,
            "edge_family": "semantic", "relation": row["primary_relation"],
            "contribution_modes": row["contribution_modes"],
            "directed": directed, "direction_status": row["direction_status"],
            "confidence": row["confidence"], "rationale": row["relation_description"],
            "model": row["model"],
            "metadata": {
                "semantic_status": "contribution_profile_typed_v1",
                "task_id": task["task_id"], "pair_id": task["pair_id"],
                "typing_prompt_version": row["prompt_version"],
            },
        })

    relation_counts = Counter(row["relation"] for row in semantic)
    mode_counts = Counter(
        "+".join(row["contribution_modes"]) if row["contribution_modes"] else "NONE"
        for row in semantic
    )
    direction_counts = Counter(row["direction_status"] for row in semantic)
    reference_pairs = {tuple(sorted((row["source"], row["target"]))) for row in references}
    semantic_pairs = {tuple(sorted((row["source"], row["target"]))) for row in semantic}
    report = {
        "nodes": len(nodes), "reference_edges": len(references), "semantic_edges": len(semantic),
        "relation_counts": dict(relation_counts), "contribution_mode_counts": dict(mode_counts),
        "direction_status_counts": dict(direction_counts), "invalid_typing_outputs": len(invalid),
        "semantic_duplicates_suppressed_by_continues": len(suppressed_continuations),
        "semantic_continuation_overlap_policy": (
            "kept" if args.keep_semantic_continuations else "suppressed"
        ),
        "semantic_and_continues_pair_overlap": len(semantic_pairs & continues_pairs),
        "suppressed_continuation_pairs": [row["pair_id"] for row in suppressed_continuations],
        "reference_and_semantic_pair_overlap": len(reference_pairs & semantic_pairs),
        "production_graph_modified": False,
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "evidence_nodes.jsonl", nodes)
    write_jsonl(output / "discourse_edges.jsonl", references)
    write_jsonl(output / "semantic_edges.jsonl", semantic)
    write_jsonl(output / "structural_edges.jsonl", structural)
    write_jsonl(output / "invalid_typing_outputs.jsonl", invalid)
    write_jsonl(output / "suppressed_semantic_continuations.jsonl", suppressed_continuations)
    write_json(output / "report.json", report)
    write_json(output / "graph.json", {
        "document_id": "gw150914_detection", "nodes": nodes,
        "edges": references + semantic, "report": report,
    })
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
