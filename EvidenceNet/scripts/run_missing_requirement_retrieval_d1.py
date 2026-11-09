#!/usr/bin/env python3
"""Run the independent, non-Gold Missing-Requirement Retrieval baseline (D1).

D0 is read from the frozen score cache. D1 creates a deterministic subquery
from the question and the retrieved evidence, encodes only those subqueries,
and ranks the same frozen 6,520-node universe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "migration/vldocir_trace_inputs_20261023"
SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
ORACLE = ROOT / "EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/query_coverage_matrix.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/missing_requirement_retrieval_d1_v1_20261106"
MODEL = ROOT / "EvidenceNet/models/Qwen3-Embedding-8B"


def rows(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def make_missing_requirement_subquery(question: str, top_nodes: list[dict]) -> str:
    """Make an inspectable query without labels, Gold, or node identifiers."""
    evidence = " ".join(
        " ".join(str(node.get("text", "")).split())[:240] for node in top_nodes
    )
    return (
        "Retrieve additional evidence needed to answer the question, especially "
        "answer conditions not explicit in the already retrieved passages. "
        f"Question: {question} Already retrieved evidence: {evidence}"
    )


def aggregate_view_scores(view_scores, views, allowed):
    scores = {}
    for score, view in zip(view_scores, views):
        node_id = view["node_id"]
        if node_id not in allowed:
            continue
        scores[node_id] = max(scores.get(node_id, -np.inf), float(score))
    return scores


def rank(scores, excluded, limit=3):
    return [
        node_id for node_id, _ in sorted(
            ((node, score) for node, score in scores.items() if node not in excluded),
            key=lambda item: (-item[1], item[0]),
        )[:limit]
    ]


def encode_subqueries(subqueries, model, device=None):
    import torch
    from transformers import AutoModel, AutoTokenizer
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True, padding_side="left")
    model_obj = AutoModel.from_pretrained(
        model, local_files_only=True, torch_dtype=dtype
    ).to(device).eval()
    # Frozen node vectors were produced with the 8B checkpoint without a
    # query instruction; use the same text contract for cosine ranking.
    inputs = list(subqueries)
    batch = tokenizer(inputs, padding=True, truncation=True, max_length=512, return_tensors="pt").to(device)
    with torch.inference_mode():
        vectors = model_obj(**batch).last_hidden_state[:, -1].float()
        vectors = torch.nn.functional.normalize(vectors, p=2, dim=1)
    return vectors.cpu().numpy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=MODEL)
    args = parser.parse_args()
    if args.output.exists() and any(
        not path.name.startswith("slurm-") for path in args.output.iterdir()
    ):
        raise ValueError("D1 output must be a fresh directory")
    args.output.mkdir(parents=True, exist_ok=True)

    queries = rows(TRACE / "queries.jsonl")
    units = rows(TRACE / "units.jsonl")
    windows = rows(TRACE / "windows.jsonl")
    views = rows(SOURCE / "views.jsonl")
    nodes = rows(SOURCE / "nodes.jsonl")
    oracle = {row["question_id"]: row for row in rows(ORACLE)}
    frozen_scores = np.load(SOURCE / "search/query_window_scores.npy", mmap_mode="r")
    view_vectors = np.load(SOURCE / "view_vectors.npy", mmap_mode="r")
    if len(views) != len(view_vectors):
        raise ValueError("view/vector mapping changed")
    allowed = {view["node_id"] for view in views}
    if len(allowed) != 6520:
        raise ValueError(f"expected 6,520 eligible nodes, got {len(allowed)}")
    unit_by_line = {i + 1: row for i, row in enumerate(units)}
    node_text = {row["node_id"]: row["quote"] for row in views}
    node_page = {row["id"]: (row["document"], int(row["page"])) for row in nodes
                 if row["id"] in allowed}
    records = []
    subqueries = []
    d0_by_query = {}
    for qi, query in enumerate(queries):
        node_scores = {}
        for wi, window in enumerate(windows):
            node_id = unit_by_line[window["unit_input_line"]]["unit_id"]
            if node_id in allowed:
                node_scores[node_id] = max(node_scores.get(node_id, -np.inf), float(frozen_scores[qi, wi]))
        d0 = [n for n, _ in sorted(node_scores.items(), key=lambda x: (-x[1], x[0]))[:10]]
        d0_by_query[query["question_id"]] = d0
        top_nodes = [{"node_id": n, "text": node_text.get(n, "")} for n in d0]
        subqueries.append(make_missing_requirement_subquery(query["question"], top_nodes))
    start = time.monotonic()
    sub_vectors = encode_subqueries(subqueries, args.model)
    costs = {"subquery_count": len(subqueries), "embedding_seconds": time.monotonic() - start}
    # Views are the frozen node representations; max pooling preserves D0's node
    # candidate semantics while avoiding any new corpus encoding.
    d1_scores = sub_vectors @ np.asarray(view_vectors).T
    for qi, query in enumerate(queries):
        node_scores = aggregate_view_scores(d1_scores[qi], views, allowed)
        d0 = d0_by_query[query["question_id"]]
        selected = rank(node_scores, set(d0), 3)
        d1 = d0 + selected
        original_rank = {node: i + 1 for i, node in enumerate(
            sorted(node_scores, key=lambda n: (-node_scores[n], n))
        )}
        records.append({
            "question_id": query["question_id"],
            "question": query["question"],
            "subquery": subqueries[qi],
            "d0_top10": [{"node_id": n, "rank": i + 1} for i, n in enumerate(d0)],
            "d1_added": [{
                "node_id": n, "subquery_dense_rank": original_rank[n],
                "page": list(node_page[n]), "duplicate_of_d0": n in d0,
            } for n in selected],
            "d1_top13_node_ids": d1,
            "added_count": len(selected),
            "deduplicated_count": len(d0) + len(selected),
            "graph_opportunity": "inspection_only; no Edge eligibility changed",
            "gold_evaluation_reference": oracle[query["question_id"]],
        })
    (args.output / "query_results.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    (args.output / "protocol.json").write_text(json.dumps({
        "experiment": "D1_missing_requirement_retrieval",
        "d0": "frozen query_window_scores.npy, exact original Top-10",
        "d1_embedding": "Qwen3-Embedding-8B last-token, matching frozen view_vectors",
        "candidate_universe": 6520,
        "subquery_generation": "deterministic query + D0 evidence; no Gold or labels",
        "additional_budget": 3,
        "gold_used_after_ranking_only": True,
        "cost": costs,
        "inputs": {"queries_sha256": sha(TRACE / "queries.jsonl"),
                   "views_sha256": sha(SOURCE / "views.jsonl"),
                   "vectors_sha256": sha(SOURCE / "view_vectors.npy")},
    }, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
