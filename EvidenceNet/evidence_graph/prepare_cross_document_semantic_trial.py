from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .embeddings import generate_document_embeddings, cosine
from .io_utils import read_jsonl, write_json, write_jsonl


TASK_VERSION = "cross-document-sequential-ranking-v1"


def _section(node: dict) -> str:
    path = node.get("section_path") or []
    return str(path[-1]) if path else "Abstract"


def _pair_id(a: str, b: str) -> str:
    left, right = sorted((a, b))
    return hashlib.sha256(f"{TASK_VERSION}|{left}|{right}".encode()).hexdigest()[:20]


def _compact_node(node: dict) -> dict:
    """Keep the prompt grounded while excluding large extraction metadata."""
    return {
        "node_id": node["node_id"],
        "document_order": node["document_order"],
        "section_path": node.get("section_path") or [],
        "evidence_type": node.get("evidence_type", "text"),
        "plain_text": node.get("plain_text") or node.get("original_markdown") or "",
    }


def prepare(
    nodes: list[dict],
    references: list[dict],
    body_order_start: int,
    body_order_end: int,
    retrieval_top_k: int,
    maximum_candidates_per_current: int,
) -> tuple[list[dict], list[dict], list[dict], list[dict], dict]:
    body = [node for node in nodes if body_order_start <= node["document_order"] <= body_order_end]
    body_ids = {node["node_id"] for node in body}
    body_references = [edge for edge in references if edge["source"] in body_ids]
    reference_target_ids = {edge["target"] for edge in body_references}
    scoped = sorted(
        [node for node in nodes if node["node_id"] in body_ids | reference_target_ids],
        key=lambda node: node["document_order"],
    )
    by_id = {node["node_id"]: node for node in scoped}

    embeddings, embedding_metadata = generate_document_embeddings(
        body, body_ids, mode="original_only", model_path=None,
    )
    vectors = {row["node_id"]: row["vector"] for row in embeddings}
    pair_rows: dict[tuple[str, str], dict] = {}

    def add_pair(a: str, b: str, reason: str, similarity: float | None = None) -> None:
        if a == b or a not in body_ids or b not in body_ids:
            return
        earlier, later = sorted((by_id[a], by_id[b]), key=lambda node: node["document_order"])
        distance = later["document_order"] - earlier["document_order"]
        cross_section = _section(earlier) != _section(later)
        if distance < 4 and not cross_section and reason != "explicit_reference_pair":
            return
        key = (earlier["node_id"], later["node_id"])
        row = pair_rows.setdefault(key, {
            "pair_id": _pair_id(*key),
            "earlier_node_id": key[0],
            "current_node_id": key[1],
            "reading_order_distance": distance,
            "cross_section": cross_section,
            "embedding_similarity": similarity,
            "candidate_reasons": [],
        })
        if reason not in row["candidate_reasons"]:
            row["candidate_reasons"].append(reason)
        if similarity is not None:
            row["embedding_similarity"] = max(row.get("embedding_similarity") or -1.0, similarity)

    # Symmetric document-local retrieval: a pair can be nominated by either endpoint.
    for node in body:
        scores = sorted(
            ((cosine(vectors[node["node_id"]], vectors[other["node_id"]]), other)
             for other in body if other["node_id"] != node["node_id"]),
            key=lambda item: (-item[0], item[1]["document_order"]),
        )
        for similarity, other in scores[:retrieval_top_k]:
            add_pair(node["node_id"], other["node_id"], "tfidf_top_k", round(similarity, 6))

    # Preserve the chance of two independent edges on the same pair: REFERENCES is
    # deterministic, while the semantic model still has to prove a substantive link.
    for edge in body_references:
        if edge["target"] in body_ids:
            add_pair(edge["source"], edge["target"], "explicit_reference_pair")

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in pair_rows.values():
        grouped[row["current_node_id"]].append(row)

    chosen: list[dict] = []
    tasks: list[dict] = []
    for current_id in sorted(grouped, key=lambda value: by_id[value]["document_order"]):
        ranked = sorted(
            grouped[current_id],
            key=lambda row: (
                "explicit_reference_pair" not in row["candidate_reasons"],
                -len(row["candidate_reasons"]),
                -(row.get("embedding_similarity") or 0.0),
                -row["reading_order_distance"],
                row["earlier_node_id"],
            ),
        )[:maximum_candidates_per_current]
        chosen.extend(ranked)
        tasks.append({
            "task_id": f"detr_rank_{len(tasks) + 1:03d}",
            "current_node": _compact_node(by_id[current_id]),
            "earlier_candidates": [_compact_node(by_id[row["earlier_node_id"]]) for row in ranked],
            "candidate_pair_ids": [row["pair_id"] for row in ranked],
            "candidate_policy": (
                "symmetric document-local TF-IDF retrieval; cross-section OR "
                "reading-order distance >= 4; explicit reference pairs retained; "
                f"maximum {maximum_candidates_per_current} earlier candidates"
            ),
        })

    chosen.sort(key=lambda row: (
        by_id[row["current_node_id"]]["document_order"],
        by_id[row["earlier_node_id"]]["document_order"],
    ))
    metadata = {
        "task_version": TASK_VERSION,
        "body_order_range": [body_order_start, body_order_end],
        "body_nodes": len(body),
        "scoped_nodes_including_reference_targets": len(scoped),
        "body_reference_edges": len(body_references),
        "body_reference_edges_with_external_target": sum(
            edge["target"] not in body_ids for edge in body_references
        ),
        "retrieval": embedding_metadata["model"],
        "retrieval_top_k_per_endpoint": retrieval_top_k,
        "maximum_candidates_per_current": maximum_candidates_per_current,
        "candidate_pairs_before_current_cap": len(pair_rows),
        "candidate_pairs_after_current_cap": len(chosen),
        "ranking_tasks": len(tasks),
        "production_graph_modified": False,
    }
    return scoped, body_references, chosen, tasks, metadata


def _write_balanced_shards(tasks: list[dict], output: Path, shard_count: int) -> list[int]:
    shards: list[list[dict]] = [[] for _ in range(shard_count)]
    loads = [0] * shard_count
    for task in sorted(tasks, key=lambda row: -len(row["earlier_candidates"])):
        target = min(range(shard_count), key=lambda index: (loads[index], index))
        shards[target].append(task)
        loads[target] += len(task["earlier_candidates"])
    for index, shard in enumerate(shards):
        shard.sort(key=lambda row: row["current_node"]["document_order"])
        shard_root = output / f"shard_{index}"
        shard_root.mkdir(parents=True, exist_ok=True)
        write_jsonl(shard_root / "ranking_tasks.jsonl", shard)
    return loads


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare an isolated cross-document semantic graph trial")
    parser.add_argument("--nodes", required=True)
    parser.add_argument("--references", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--body-order-start", type=int, default=3)
    parser.add_argument("--body-order-end", type=int, default=85)
    parser.add_argument("--retrieval-top-k", type=int, default=10)
    parser.add_argument("--maximum-candidates-per-current", type=int, default=12)
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    scoped, references, candidates, tasks, metadata = prepare(
        read_jsonl(args.nodes), read_jsonl(args.references),
        args.body_order_start, args.body_order_end,
        args.retrieval_top_k, args.maximum_candidates_per_current,
    )
    write_jsonl(output / "evidence_nodes.jsonl", scoped)
    write_jsonl(output / "discourse_edges.jsonl", references)
    write_jsonl(output / "semantic_candidates.jsonl", candidates)
    write_jsonl(output / "ranking_tasks.jsonl", tasks)
    metadata["shard_candidate_loads"] = _write_balanced_shards(tasks, output, args.shards)
    write_json(output / "manifest.json", metadata)
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
