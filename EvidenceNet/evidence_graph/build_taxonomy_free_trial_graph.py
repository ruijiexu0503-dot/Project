from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


SPACE = re.compile(r"\s+")


def _normalized(value: str) -> str:
    return SPACE.sub(" ", value).strip().casefold()


def _span_is_grounded(span: str | None, text: str) -> bool:
    return bool(span and _normalized(span) in _normalized(text))


def build(
    nodes: list[dict],
    references: list[dict],
    tasks: list[dict],
    predictions: list[dict],
    minimum_confidence: float,
) -> tuple[list[dict], list[dict], list[dict], dict]:
    task_by_id = {task["task_id"]: task for task in tasks}
    by_id = {node["node_id"]: node for node in nodes}
    semantic: list[dict] = []
    excluded: list[dict] = []
    status_counts = Counter()
    outgoing_reference_targets: dict[str, set[str]] = defaultdict(set)
    direct_reference_pairs = set()
    for edge in references:
        outgoing_reference_targets[edge["source"]].add(edge["target"])
        direct_reference_pairs.add(tuple(sorted((edge["source"], edge["target"]))))

    for prediction in predictions:
        status_counts[prediction.get("status") or "MISSING"] += 1
        task = task_by_id.get(prediction.get("task_id"))
        if not task:
            excluded.append({**prediction, "exclusion_reason": "missing_task"})
            continue
        if not prediction.get("valid") or prediction.get("status") != "RELATED_STRONG":
            continue
        confidence = float(prediction.get("confidence") or 0.0)
        evidence_a, evidence_b = task["evidence_a"], task["evidence_b"]
        grounded_a = _span_is_grounded(
            prediction.get("supporting_span_a"),
            evidence_a.get("plain_text") or evidence_a.get("text") or "",
        )
        grounded_b = _span_is_grounded(
            prediction.get("supporting_span_b"),
            evidence_b.get("plain_text") or evidence_b.get("text") or "",
        )
        if confidence < minimum_confidence or not grounded_a or not grounded_b:
            excluded.append({
                **prediction,
                "exclusion_reason": (
                    "confidence_below_threshold" if confidence < minimum_confidence
                    else "supporting_span_not_exactly_grounded"
                ),
                "span_a_grounded": grounded_a,
                "span_b_grounded": grounded_b,
            })
            continue
        pair = tuple(sorted((evidence_a["node_id"], evidence_b["node_id"])))
        shared_third_targets = (
            outgoing_reference_targets[evidence_a["node_id"]]
            & outgoing_reference_targets[evidence_b["node_id"]]
        ) - set(pair)
        if shared_third_targets and pair not in direct_reference_pairs:
            excluded.append({
                **prediction,
                "exclusion_reason": "shared_third_node_reference_only",
                "shared_reference_targets": sorted(shared_third_targets),
                "span_a_grounded": grounded_a,
                "span_b_grounded": grounded_b,
            })
            continue
        semantic.append({
            "source": evidence_a["node_id"],
            "target": evidence_b["node_id"],
            "edge_family": "semantic",
            "relation": "RELATED",
            "directed": False,
            "confidence": confidence,
            "rationale": prediction.get("relation_description"),
            "source_supporting_span": prediction.get("supporting_span_a"),
            "target_supporting_span": prediction.get("supporting_span_b"),
            "model": prediction.get("model"),
            "metadata": {
                "semantic_status": "taxonomy_free_grounded_v1",
                "existence_status": "RELATED_STRONG",
                "verification_task_id": task["task_id"],
                "pair_id": task["pair_id"],
                "selection_provenance": task.get("selection_provenance"),
            },
        })

    valid_ids = set(by_id)
    kept_references = [
        edge for edge in references
        if edge.get("source") in valid_ids and edge.get("target") in valid_ids
    ]
    degrees = Counter()
    cross_section_edges = 0
    distance_bins = Counter()
    for edge in semantic:
        degrees[edge["source"]] += 1
        degrees[edge["target"]] += 1
        source, target = by_id[edge["source"]], by_id[edge["target"]]
        source_section = (source.get("section_path") or ["Abstract"])[-1]
        target_section = (target.get("section_path") or ["Abstract"])[-1]
        cross_section_edges += source_section != target_section
        distance = abs(source["document_order"] - target["document_order"])
        distance_bins[
            "1-3" if distance <= 3 else "4-6" if distance <= 6 else "7+"
        ] += 1
    exclusion_reasons = Counter(row["exclusion_reason"] for row in excluded)
    report = {
        "nodes": len(nodes),
        "reference_edges": len(kept_references),
        "semantic_predictions": len(predictions),
        "prediction_status_counts": dict(status_counts),
        "accepted_semantic_edges": len(semantic),
        "excluded_related_strong": len(excluded),
        "exclusion_reason_counts": dict(exclusion_reasons),
        "minimum_confidence": minimum_confidence,
        "exact_supporting_spans_required": True,
        "reference_and_semantic_pair_overlap": len(
            {tuple(sorted((e["source"], e["target"]))) for e in kept_references}
            & {tuple(sorted((e["source"], e["target"]))) for e in semantic}
        ),
        "semantic_connected_nodes": len(degrees),
        "semantic_isolated_nodes": len(nodes) - len(degrees),
        "average_semantic_degree": round(2 * len(semantic) / len(nodes), 3) if nodes else 0.0,
        "maximum_semantic_degree": max(degrees.values(), default=0),
        "cross_section_semantic_edges": cross_section_edges,
        "semantic_reading_order_distance_bins": dict(distance_bins),
        "production_graph_modified": False,
    }
    return kept_references, semantic, excluded, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an isolated taxonomy-free semantic + reference graph")
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--references", required=True)
    parser.add_argument("--verification-tasks", required=True)
    parser.add_argument("--predictions", nargs="+", required=True)
    parser.add_argument("--structural-edges")
    parser.add_argument("--output", required=True)
    parser.add_argument("--minimum-confidence", type=float, default=0.75)
    args = parser.parse_args()

    nodes = read_jsonl(args.nodes)
    predictions = []
    for path in args.predictions:
        predictions.extend(read_jsonl(path))
    references, semantic, excluded, report = build(
        nodes, read_jsonl(args.references), read_jsonl(args.verification_tasks),
        predictions, args.minimum_confidence,
    )
    valid_ids = {node["node_id"] for node in nodes}
    structural = []
    if args.structural_edges:
        structural = [
            edge for edge in read_jsonl(args.structural_edges)
            if edge.get("source") in valid_ids and edge.get("target") in valid_ids
        ]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "evidence_nodes.jsonl", nodes)
    write_jsonl(output / "discourse_edges.jsonl", references)
    write_jsonl(output / "semantic_edges.jsonl", semantic)
    write_jsonl(output / "structural_edges.jsonl", structural)
    write_jsonl(output / "excluded_semantic_edges.jsonl", excluded)
    write_json(output / "report.json", report)
    write_json(output / "graph.json", {
        "document_id": "detr",
        "nodes": nodes,
        "edges": references + semantic + structural,
        "report": report,
    })
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
