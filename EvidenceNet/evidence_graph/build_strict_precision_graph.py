from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a strict precision graph from A profile edges")
    parser.add_argument("--document-id", default="gw150914_detection")
    parser.add_argument("--a-graph", required=True)
    parser.add_argument("--predictions", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source, output = Path(args.a_graph), Path(args.output)
    predictions = {}
    for path in args.predictions:
        for row in read_jsonl(path):
            predictions[row["task_id"]] = row
    nodes = read_jsonl(source / "evidence_nodes.jsonl")
    discourse = read_jsonl(source / "discourse_edges.jsonl")
    structural = read_jsonl(source / "structural_edges.jsonl")
    semantic = read_jsonl(source / "semantic_edges.jsonl")
    kept, rejected = [], []
    for edge in semantic:
        task_id = (edge.get("metadata") or {}).get("task_id")
        prediction = predictions.get(task_id)
        if prediction and prediction.get("valid") and prediction.get("verdict") == "KEEP_EDGE":
            row = dict(edge)
            metadata = dict(row.get("metadata") or {})
            metadata["strict_direct_validation"] = {
                "verdict": "KEEP_EDGE", "directness": prediction.get("directness"),
                "confidence": prediction.get("confidence"),
                "shared_atomic_subject": prediction.get("shared_atomic_subject"),
                "contribution_a_to_b": prediction.get("contribution_a_to_b"),
                "contribution_b_to_a": prediction.get("contribution_b_to_a"),
                "prompt_version": prediction.get("prompt_version"),
            }
            row["metadata"] = metadata
            kept.append(row)
        else:
            rejected.append({"edge": edge, "strict_prediction": prediction})

    report = {
        "version": "strict_direct_edge_precision_v1", "nodes": len(nodes),
        "a_semantic_edges": len(semantic), "semantic_edges_kept": len(kept),
        "semantic_edges_rejected_or_invalid": len(rejected),
        "reference_edges": len(discourse),
        "rejection_directness_counts": dict(Counter(
            ((row.get("strict_prediction") or {}).get("directness") or "INVALID") for row in rejected
        )),
        "production_graph_modified": False,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "evidence_nodes.jsonl", nodes)
    write_jsonl(output / "discourse_edges.jsonl", discourse)
    write_jsonl(output / "structural_edges.jsonl", structural)
    write_jsonl(output / "semantic_edges.jsonl", kept)
    write_jsonl(output / "rejected_semantic_edges.jsonl", rejected)
    write_json(output / "report.json", report)
    write_json(output / "graph.json", {
        "document_id": args.document_id, "nodes": nodes,
        "edges": discourse + structural + kept, "report": report,
    })
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
