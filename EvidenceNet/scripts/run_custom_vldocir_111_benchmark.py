#!/usr/bin/env python3
"""Run the frozen D0/D0+/D1 protocol on custom 111-query manifests."""
from __future__ import annotations

import argparse
import gc
import json
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "migration/vldocir_trace_inputs_20261023"
SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
MODEL06 = ROOT / "EvidenceNet/models/Qwen3-Embedding-0.6B"
MODEL8 = ROOT / "EvidenceNet/models/Qwen3-Embedding-8B"
OUT = ROOT / "EvidenceNet/output/custom_vldocir_benchmark_v1_20261106"
STRUCTURES = (
    "single-page_single-evidence", "single-page_multi-evidence",
    "multi-page_connected", "multi-page_disconnected-close",
    "multi-page_disconnected-distant", "cross-document_same-type",
)


def rows(path):
    return [json.loads(line) for line in Path(path).open(encoding="utf-8") if line.strip()]


def encode_ids(records, model_path, batch_size=16):
    import torch
    from transformers import AutoModel, AutoTokenizer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, padding_side="left")
    model = AutoModel.from_pretrained(model_path, local_files_only=True, torch_dtype=dtype).to(device).eval()
    chunks = []
    with torch.inference_mode():
        for start in range(0, len(records), batch_size):
            batch = tokenizer.pad(
                {"input_ids": [record["input_ids"] for record in records[start:start + batch_size]]},
                padding=True, return_tensors="pt",
            ).to(device)
            vector = model(**batch).last_hidden_state[:, -1].float()
            chunks.append(torch.nn.functional.normalize(vector, p=2, dim=1).cpu().numpy())
    del model, tokenizer
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return np.concatenate(chunks, axis=0)


def encode_texts(texts, model_path, batch_size=8):
    import torch
    from transformers import AutoModel, AutoTokenizer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True, padding_side="left")
    model = AutoModel.from_pretrained(model_path, local_files_only=True, torch_dtype=dtype).to(device).eval()
    chunks = []
    with torch.inference_mode():
        for start in range(0, len(texts), batch_size):
            batch = tokenizer(
                texts[start:start + batch_size], padding=True, truncation=True,
                max_length=512, return_tensors="pt",
            ).to(device)
            vector = model(**batch).last_hidden_state[:, -1].float()
            chunks.append(torch.nn.functional.normalize(vector, p=2, dim=1).cpu().numpy())
    del model, tokenizer
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return np.concatenate(chunks, axis=0)


def subquery(question, d0_nodes, text_by_node):
    evidence = " ".join(" ".join(text_by_node[n].split())[:240] for n in d0_nodes)
    return (
        "Retrieve additional evidence needed to answer the question, especially "
        "answer conditions not explicit in the already retrieved passages. "
        f"Question: {question} Already retrieved evidence: {evidence}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-manifest", type=Path, required=True)
    parser.add_argument("--bbox-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.out.exists() and any(
        not path.name.startswith("slurm-") for path in args.out.iterdir()
    ):
        raise ValueError("benchmark output must be fresh")
    args.out.mkdir(parents=True, exist_ok=True)
    doc_manifest = {r["question_id"]: r for r in rows(args.doc_manifest)}
    bbox_manifest = {r["question_id"]: r for r in rows(args.bbox_manifest)}
    if len(doc_manifest) != 111 or len(bbox_manifest) != 111:
        raise ValueError("both manifests must contain 111 unique queries")
    if set(doc_manifest) & {r["question_id"] for r in rows(TRACE / "queries.jsonl")}:
        raise ValueError("development query leaked into Doc/Page manifest")
    if set(bbox_manifest) & {r["question_id"] for r in rows(TRACE / "queries.jsonl")}:
        raise ValueError("development query leaked into BBox manifest")
    query_meta = {r["question_id"]: r for r in rows(ROOT / "data/benchmarks/VL-DocIR/questions.jsonl")}
    queries = {qid: query_meta[qid] for qid in set(doc_manifest) | set(bbox_manifest)}
    units = rows(TRACE / "units.jsonl")
    windows = rows(TRACE / "windows.jsonl")
    window_tokens = rows(TRACE / "window_tokens.jsonl")
    views = rows(SOURCE / "views.jsonl")
    nodes = {r["id"]: (r["document"], int(r["page"])) for r in rows(SOURCE / "nodes.jsonl")}
    text_by_node = {r["node_id"]: r.get("quote", "") for r in views}
    allowed = {r["node_id"] for r in views}
    vectors8 = np.load(SOURCE / "view_vectors.npy", mmap_mode="r")
    if vectors8.shape != (len(views), 4096):
        raise ValueError("frozen 8B node vectors changed")
    unit_by_line = {i + 1: row for i, row in enumerate(units)}
    query_records = []
    for qid, query in sorted(queries.items()):
        from retrieve_vldocir import query_model_input
        tokenizer_input = query_model_input({"question": query["question"]})
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(MODEL06 / "tokenizer.json"))
        query_records.append({"question_id": qid, "input_ids": tokenizer.encode(tokenizer_input).ids})
    window_vectors = encode_ids(window_tokens, MODEL06, batch_size=32)
    query_vectors = encode_ids(query_records, MODEL06, batch_size=32)
    rankings = {}
    for qi, record in enumerate(query_records):
        scores = query_vectors[qi] @ window_vectors.T
        node_scores = {}
        for wi, window in enumerate(windows):
            node_id = unit_by_line[window["unit_input_line"]]["unit_id"]
            if node_id in allowed:
                node_scores[node_id] = max(node_scores.get(node_id, -np.inf), float(scores[wi]))
        rankings[record["question_id"]] = [
            node for node, _ in sorted(node_scores.items(), key=lambda x: (-x[1], x[0]))
        ]
    subqueries = {
        qid: subquery(queries[qid]["question"], rankings[qid][:10], text_by_node)
        for qid in queries
    }
    sub_vectors = encode_texts([subqueries[qid] for qid in sorted(queries)], MODEL8, batch_size=4)
    records = []
    for qi, qid in enumerate(sorted(queries)):
        d0 = rankings[qid][:10]
        sub_scores = sub_vectors[qi] @ np.asarray(vectors8).T
        node_scores = {}
        for score, view in zip(sub_scores, views):
            node_scores[view["node_id"]] = max(node_scores.get(view["node_id"], -np.inf), float(score))
        added = [
            node for node, _ in sorted(
                ((n, s) for n, s in node_scores.items() if n not in d0),
                key=lambda x: (-x[1], x[0]),
            )[:3]
        ]
        dense_rank = {node: rank + 1 for rank, node in enumerate(rankings[qid])}
        records.append({
            "question_id": qid, "question": queries[qid]["question"],
            "question_type": queries[qid]["question_type"],
            "subquery": subqueries[qid],
            "d0_top10": d0, "dense_top13": rankings[qid][:13],
            "d1_added": [{"node_id": n, "original_dense_rank": dense_rank[n],
                          "page": list(nodes[n])} for n in added],
            "d1_top13": d0 + added,
            "manifests": {"doc_page_complete": qid in doc_manifest, "bbox_complete": qid in bbox_manifest},
        })
    (args.out / "retrieval_records.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    (args.out / "protocol.json").write_text(json.dumps({
        "dataset": "Custom VL-DocIR Subset", "query_count_union": len(records),
        "doc_page_manifest_count": len(doc_manifest), "bbox_manifest_count": len(bbox_manifest),
        "d0_encoder": "Qwen3-Embedding-0.6B, frozen window protocol",
        "d1_encoder": "Qwen3-Embedding-8B, frozen node vectors, subqueries only",
        "candidate_universe": 6520, "budget": 13,
        "gold_used_for_ranking": False, "edge_construction_changed": False,
    }, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
