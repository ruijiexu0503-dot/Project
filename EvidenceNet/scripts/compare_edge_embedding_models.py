#!/usr/bin/env python3
"""Compare dense encoders inside the frozen evidence-edge retrieval policy."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gc
import json
from pathlib import Path
import time

import numpy as np

import run_hierarchical_edge_retrieval as retrieval
from run_node_context_edges import ROOT, jsonl, read, rows, sha, write


SOURCE = ROOT / "EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015"
RELATEDNESS = ROOT / "EvidenceNet/output/relatedness_ordinal_mixed_v1_20261015"
OVERLAY = ROOT / "data/benchmarks/evidence_edges_relatedness_v2_20261018/six_cases.jsonl"
DEFAULT = ROOT / "EvidenceNet/output/edge_embedding_model_comparison_v1_20261020"


def reference_levels(cases, references, overlay):
    """Map old ordinal readings into the simplified 0/1/2 RELATED contract."""
    old = {item["suite_case_id"]: item for item in references if item.get("suite_case_id")}
    revised = {item["suite_case_id"]: item for item in overlay}
    levels = {}
    for case in cases:
        case_id = case["suite_case_id"]
        if case_id in revised:
            levels[case_id] = revised[case_id]["relatedness"]
            continue
        allowed = old[case_id]["allowed_levels"]
        if min(allowed) >= 2:
            levels[case_id] = 2
        elif max(allowed) <= 1:
            levels[case_id] = 0
        else:
            levels[case_id] = None
    return levels


def evaluate(cases, levels, candidates, initial_pool, views, vectors):
    final_keys = {frozenset((item["source"], item["target"])) for item in candidates}
    pool_keys = {frozenset((item["source"], item["target"])) for item in initial_pool}
    by_node = defaultdict(list)
    for index, view in enumerate(views):
        by_node[view["node_id"]].append(index)
    records = []
    for case in cases:
        case_id = case["suite_case_id"]
        a, b = case["A"]["node_id"], case["B"]["node_id"]
        key = frozenset((a, b))
        ia, ib = by_node.get(a, []), by_node.get(b, [])
        best = None
        if ia and ib:
            best = float(np.max(vectors[np.asarray(ia)] @ vectors[np.asarray(ib)].T))
        records.append({
            "suite_case_id": case_id,
            "source": a,
            "target": b,
            "relatedness": levels[case_id],
            "initial_pool": key in pool_keys,
            "final_candidate": key in final_keys,
            "best_dense_view_similarity": best,
        })

    def bucket(level):
        selected = [item for item in records if item["relatedness"] == level]
        return {
            "total": len(selected),
            "initial_pool": sum(item["initial_pool"] for item in selected),
            "final_candidates": sum(item["final_candidate"] for item in selected),
            "final_recall": (sum(item["final_candidate"] for item in selected) / len(selected)
                             if selected else None),
        }

    linked = [item for item in records if item["relatedness"] in (1, 2)]
    return records, {
        "strong_relatedness_2": bucket(2),
        "weak_relatedness_1": bucket(1),
        "no_link_0": bucket(0),
        "unresolved": bucket(None),
        "all_links": {
            "total": len(linked),
            "initial_pool": sum(item["initial_pool"] for item in linked),
            "final_candidates": sum(item["final_candidate"] for item in linked),
            "final_recall": (sum(item["final_candidate"] for item in linked) / len(linked)
                             if linked else None),
        },
        "six_reannotated": [item for item in records if item["suite_case_id"]
                            in {"P02", "P09", "P10", "P11", "P12", "P26"}],
    }


def embed(texts, model_path, batch_size, max_length, device):
    import torch
    from transformers import AutoModel, AutoTokenizer

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(
        model_path, local_files_only=True, trust_remote_code=True, padding_side="left")
    kwargs = dict(local_files_only=True, trust_remote_code=True, torch_dtype=dtype)
    try:
        model = AutoModel.from_pretrained(model_path, attn_implementation="sdpa", **kwargs)
    except (TypeError, ValueError):
        model = AutoModel.from_pretrained(model_path, **kwargs)
    model = model.to(device).eval()
    result = []
    started = time.monotonic()
    for start in range(0, len(texts), batch_size):
        batch = tokenizer(texts[start:start + batch_size], padding=True, truncation=True,
                          max_length=max_length, return_tensors="pt").to(device)
        with torch.inference_mode():
            # Dense encoding never reuses autoregressive KV state.  Disabling it also
            # keeps older trust_remote_code encoders (notably gte-Qwen2) compatible
            # with newer transformers releases whose Cache API has changed.
            hidden = model(**batch, use_cache=False).last_hidden_state
            vector = torch.nn.functional.normalize(hidden[:, -1].float(), p=2, dim=1)
        result.append(vector.cpu().numpy())
        print("embedded", min(start + batch_size, len(texts)), len(texts), flush=True)
    metadata = {
        "elapsed_seconds": time.monotonic() - started,
        "device": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
        "dtype": "bfloat16" if device == "cuda" else "float32",
        "pooling": "last_token",
        "padding_side": "left",
        "max_length": max_length,
        "batch_size": batch_size,
    }
    del model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return np.concatenate(result), metadata


def source_files():
    return [
        SOURCE / "views.jsonl",
        SOURCE / "corpus_nodes.jsonl",
        SOURCE / "evaluation/cases.jsonl",
        RELATEDNESS / "evaluation/reference.jsonl",
        OVERLAY,
    ]


def prepare(out):
    if out.exists():
        check(out)
        return
    out.mkdir(parents=True)
    cases = rows(SOURCE / "evaluation/cases.jsonl")
    references = rows(RELATEDNESS / "evaluation/reference.jsonl")
    levels = reference_levels(cases, references, rows(OVERLAY))
    write(out / "protocol.json", {
        "experiment": "edge_embedding_model_comparison_v1",
        "source_views": len(rows(SOURCE / "views.jsonl")),
        "source_nodes": len(rows(SOURCE / "corpus_nodes.jsonl")),
        "reference_counts": dict(Counter(str(value) for value in levels.values())),
        "embedding_input": "symmetric retrieval view; no query instruction",
        "pooling": "last token with left padding and L2 normalization",
        "max_tokens": 512,
        "candidate_policy": "frozen hierarchical dense+BM25+identifier retrieval and fixed budgets",
        "labels_used_for_retrieval": False,
        "interpretation": "Candidate recall comparison, not final edge precision or MTEB reproduction.",
    })
    write(out / "manifest.json", {
        "source_sha256": {str(path.resolve()): sha(path) for path in source_files()},
        "code_sha256": sha(__file__),
    })
    print(json.dumps(read(out / "protocol.json"), indent=2), flush=True)


def check(out):
    manifest = read(out / "manifest.json")
    if manifest["code_sha256"] != sha(__file__):
        raise ValueError("comparison code changed after preparation")
    for path, digest in manifest["source_sha256"].items():
        if sha(path) != digest:
            raise ValueError("source changed after preparation: " + path)


def run_model(out, model_name, model_path, batch_size, max_length, device):
    check(out)
    destination = out / "models" / model_name
    if (destination / "summary.json").exists():
        print(json.dumps(read(destination / "summary.json"), indent=2), flush=True)
        return
    destination.mkdir(parents=True, exist_ok=True)
    views = rows(SOURCE / "views.jsonl")
    nodes = {item["id"]: item for item in rows(SOURCE / "corpus_nodes.jsonl")}
    cases = rows(SOURCE / "evaluation/cases.jsonl")
    levels = reference_levels(cases, rows(RELATEDNESS / "evaluation/reference.jsonl"), rows(OVERLAY))
    vectors, execution = embed([item["retrieval_text"] for item in views], model_path,
                               batch_size, max_length, device)
    np.save(destination / "view_vectors.npy", vectors)
    pool = retrieval.retrieve(views, vectors)
    article_candidates, candidates = retrieval.route_and_select(nodes, pool)
    jsonl(destination / "article_candidates.jsonl", article_candidates)
    jsonl(destination / "node_candidates.jsonl", candidates)
    records, metrics = evaluate(cases, levels, candidates, list(pool.values()), views, vectors)
    jsonl(destination / "case_coverage.jsonl", records)
    model_files = sorted(path for path in Path(model_path).glob("*.json") if path.is_file())
    summary = {
        "model_name": model_name,
        "model_path": str(Path(model_path).resolve()),
        "model_config_sha256": {path.name: sha(path) for path in model_files},
        "execution": execution,
        "views": len(views),
        "initial_pairs": len(pool),
        "final_candidates": len(candidates),
        "metrics": metrics,
    }
    write(destination / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


def report(out):
    summaries = []
    for path in sorted((out / "models").glob("*/summary.json")) if (out / "models").exists() else []:
        summaries.append(read(path))
    ranked = sorted(summaries, key=lambda item: (
        -item["metrics"]["strong_relatedness_2"]["final_recall"],
        item["metrics"]["no_link_0"]["final_candidates"],
        item["model_name"],
    ))
    write(out / "comparison.json", {
        "complete_models": len(ranked),
        "ranking_policy": "strong RELATED recall descending, then no-link candidate count ascending",
        "models": ranked,
    })
    lines = [
        "# Edge embedding model comparison",
        "",
        "Same source views and fixed candidate budget; only the dense encoder changes.",
        "",
        "| Model | Strong RELATED | Weak RELATED | All links | No-link candidates | Final pairs |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in ranked:
        metrics = item["metrics"]
        def fraction(key):
            value = metrics[key]
            return f'{value["final_candidates"]}/{value["total"]}'
        lines.append(f'| {item["model_name"]} | {fraction("strong_relatedness_2")} | '
                     f'{fraction("weak_relatedness_1")} | {fraction("all_links")} | '
                     f'{fraction("no_link_0")} | {item["final_candidates"]} |')
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "report"))
    parser.add_argument("--output", type=Path, default=DEFAULT)
    parser.add_argument("--model-name")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output.resolve())
    elif args.command == "report":
        check(args.output.resolve())
        report(args.output.resolve())
    else:
        if not args.model_name or not args.model_path:
            parser.error("run requires --model-name and --model-path")
        run_model(args.output.resolve(), args.model_name, args.model_path.resolve(),
                  args.batch_size, args.max_length, args.device)


if __name__ == "__main__":
    main()
