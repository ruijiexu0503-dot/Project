from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


def _load_many(paths: list[str]) -> list[dict]:
    rows = []
    for path in paths:
        rows.extend(read_jsonl(path))
    return rows


def _write_graph(root: Path, document_id: str, nodes: list[dict], references: list[dict],
                 structural: list[dict], semantic: list[dict], report: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    write_jsonl(root / "evidence_nodes.jsonl", nodes)
    write_jsonl(root / "discourse_edges.jsonl", references)
    write_jsonl(root / "structural_edges.jsonl", structural)
    write_jsonl(root / "semantic_edges.jsonl", semantic)
    write_json(root / "report.json", report)
    write_json(root / "graph.json", {
        "document_id": document_id, "nodes": nodes,
        "edges": references + structural + semantic, "report": report,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Build profile and fixed-type graphs over one frozen pair set")
    parser.add_argument("--document-id", default="gw150914_detection")
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--references", required=True)
    parser.add_argument("--structural-edges", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--profile-predictions", nargs="+", required=True)
    parser.add_argument("--fixed-predictions", nargs="*", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    nodes, references = read_jsonl(args.nodes), read_jsonl(args.references)
    structural, tasks = read_jsonl(args.structural_edges), {row["task_id"]: row for row in read_jsonl(args.tasks)}
    profile_predictions = {
        row["task_id"]: row for row in _load_many(args.profile_predictions)
        if row.get("valid") and row.get("status") == "RELATED" and row["task_id"] in tasks
    }
    fixed_predictions = {row["task_id"]: row for row in _load_many(args.fixed_predictions)}

    profile_edges = []
    for task_id, row in profile_predictions.items():
        task = tasks[task_id]
        endpoints = sorted((task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]))
        signals = row.get("signals") or []
        modes = []
        if "EVIDENCE_OR_QUANTIFICATION" in signals:
            modes.append("EVIDENTIAL")
        if "EXPLANATION_OR_MECHANISM" in signals:
            modes.append("EXPLANATORY")
        profile_edges.append({
            "source": endpoints[0], "target": endpoints[1], "edge_family": "semantic",
            "relation": "PROFILED_RELATED", "directed": False, "direction_status": "UNRESOLVED",
            "semantic_signals": signals, "contribution_modes": modes,
            "confidence": row.get("relationship_probability"),
            "rationale": row.get("best_relation_hypothesis"),
            "model": row.get("model"),
            "metadata": {"semantic_status": "existence_multisignal_v2", "task_id": task_id,
                         "pair_id": task["pair_id"], "prompt_version": row.get("prompt_version")},
        })

    fixed_edges, rejected = [], []
    for task_id in profile_predictions:
        task, row = tasks[task_id], fixed_predictions.get(task_id)
        endpoints = sorted((task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]))
        if not row or not row.get("valid") or row.get("relation") == "REJECT_UNCERTAIN":
            reason = (
                row.get("relation_description") if row else
                "No valid fixed-type output was available for this screened pair."
            )
            rejected.append({"task_id": task_id, "pair_id": task["pair_id"], "prediction": row})
            fixed_edges.append({
                "source": endpoints[0], "target": endpoints[1], "edge_family": "semantic",
                "relation": "RELATED", "directed": False, "direction_status": "UNRESOLVED",
                "confidence": row.get("confidence", 0.0) if row else 0.0,
                "rationale": reason,
                "metadata": {"semantic_status": "fixed_type_rejected_or_invalid", "task_id": task_id,
                             "pair_id": task["pair_id"]},
            })
            continue
        directed = row["direction_status"] == "DIRECTED"
        fixed_edges.append({
            "source": row["source_node_id"] if directed else endpoints[0],
            "target": row["target_node_id"] if directed else endpoints[1],
            "edge_family": "semantic", "relation": row["relation"],
            "secondary_relation": row.get("secondary_relation"),
            "directed": directed, "direction_status": row["direction_status"],
            "confidence": row["confidence"], "rationale": row["relation_description"],
            "model": row.get("model"),
            "metadata": {"semantic_status": "fixed_type_direction_v2", "task_id": task_id,
                         "pair_id": task["pair_id"], "prompt_version": row.get("prompt_version")},
        })

    reference_pairs = {tuple(sorted((row["source"], row["target"]))) for row in references}
    base_report = {"nodes": len(nodes), "reference_edges": len(references), "pair_set": len(profile_edges),
                   "production_graph_modified": False}
    profile_report = {
        **base_report, "version": "A_nonexclusive_profile", "semantic_edges": len(profile_edges),
        "signal_counts": dict(Counter(signal for row in profile_edges for signal in row["semantic_signals"])),
        "multi_signal_edges": sum(len(row["semantic_signals"]) > 1 for row in profile_edges),
        "reference_and_semantic_pair_overlap": len(
            reference_pairs & {tuple(sorted((row["source"], row["target"]))) for row in profile_edges}
        ),
    }
    fixed_report = {
        **base_report, "version": "B_exclusive_fixed_type", "semantic_edges": len(fixed_edges),
        "fixed_type_counts": dict(Counter(row["relation"] for row in fixed_edges)),
        "secondary_relation_edges": sum(bool(row.get("secondary_relation")) for row in fixed_edges),
        "rejected_or_invalid_retained_as_related": len(rejected),
        "reference_and_semantic_pair_overlap": len(
            reference_pairs & {tuple(sorted((row["source"], row["target"]))) for row in fixed_edges}
        ),
    }
    output = Path(args.output)
    _write_graph(output / "version_a_profile", args.document_id, nodes, references, structural,
                 profile_edges, profile_report)
    _write_graph(output / "version_b_fixed", args.document_id, nodes, references, structural,
                 fixed_edges, fixed_report)
    write_jsonl(output / "version_b_fixed" / "rejected_or_invalid.jsonl", rejected)
    print(json.dumps({"version_a": profile_report, "version_b": fixed_report}, indent=2))


if __name__ == "__main__":
    main()
