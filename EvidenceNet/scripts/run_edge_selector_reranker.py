#!/usr/bin/env python3
"""Shadow reranking experiment for the frozen cross-article edge candidate pool.

This never writes production graph edges. It scores source-mapped retrieval-view
pairs with the existing BGE reranker and compares fixed-budget candidate selectors.
Reference labels are read only by ``report``, after every candidate list is frozen.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import time

from run_node_context_edges import ROOT, read, rows, write, jsonl, sha


SOURCE = ROOT / "EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015"
OUT = ROOT / "EvidenceNet/output/edge_selector_reranker_v1_20261016"
MODEL = ROOT / "EvidenceNet/models/bge-reranker-v2-m3"
BUDGET = 1301


def pair_key(row: dict) -> tuple[str, str]:
    return tuple(sorted((row["source"], row["target"])))


def alignment_ids(pair: dict) -> list[tuple[str, str]]:
    """Return unique, source-mapped view pairs without using evaluation labels."""
    result = set()
    for match in pair.get("best_views", {}).values():
        a, b = match.get("source_view"), match.get("target_view")
        if a and b:
            result.add(tuple(sorted((a, b))))
    return sorted(result)


def verify_manifest(out: Path) -> None:
    for path, digest in read(out / "manifest.json")["files"].items():
        if sha(path) != digest:
            raise ValueError("Changed frozen input/code: " + path)


def prepare(out: Path) -> None:
    if (out / "manifest.json").exists():
        verify_manifest(out)
        return
    out.mkdir(parents=True, exist_ok=True)
    pool = rows(SOURCE / "initial_pool.jsonl")
    views = {row["view_id"]: row for row in rows(SOURCE / "views.jsonl")}
    inputs = []
    alignment_count = 0
    for pair in pool:
        alignments = []
        for a, b in alignment_ids(pair):
            if a not in views or b not in views:
                raise ValueError(f"Missing retrieval view: {a}, {b}")
            alignments.append({
                "view_a": a,
                "view_b": b,
                "text_a": views[a]["retrieval_text"],
                "text_b": views[b]["retrieval_text"],
            })
        if not alignments:
            raise ValueError("Candidate has no source-mapped alignment: " + str(pair_key(pair)))
        alignment_count += len(alignments)
        inputs.append({
            "source": pair["source"],
            "target": pair["target"],
            "source_article": pair["source_article"],
            "target_article": pair["target_article"],
            "retrieval_score": pair["retrieval_score"],
            "signals": pair["signals"],
            "shared_identifiers": pair.get("shared_identifiers", []),
            "alignments": alignments,
        })
    jsonl(out / "inputs.jsonl", inputs)
    write(out / "protocol.json", {
        "experiment": "edge_selector_reranker_v1",
        "purpose": "shadow candidate selection only; no semantic edge export",
        "source_candidates": len(inputs),
        "source_alignments": alignment_count,
        "candidate_budget": BUDGET,
        "model": str(MODEL.resolve()),
        "representation": "best source-mapped view pairs already present in frozen retrieval records",
        "labels_used_for_scoring_or_selection": False,
        "labels_read_only_by_report": True,
        "inference": {"max_length": 384, "batch_size": 128, "dtype": "bfloat16"},
    })
    files = [
        Path(__file__), SOURCE / "initial_pool.jsonl", SOURCE / "views.jsonl",
        SOURCE / "article_candidates.jsonl", SOURCE / "evaluation/cases.jsonl",
        out / "inputs.jsonl", out / "protocol.json", MODEL / "config.json",
        MODEL / "model.safetensors",
    ]
    write(out / "manifest.json", {"files": {str(path.resolve()): sha(path) for path in files}})
    print(json.dumps({"pairs": len(inputs), "alignments": alignment_count, "output": str(out)}))


def infer_pairs(model, tokenizer, pairs, device: str, batch_size: int = 128) -> list[float]:
    import torch

    result = []
    for start in range(0, len(pairs), batch_size):
        batch = pairs[start:start + batch_size]
        encoded = tokenizer(
            [a for a, _ in batch], [b for _, b in batch], padding=True,
            truncation=True, max_length=384, return_tensors="pt",
        ).to(device)
        with torch.inference_mode():
            logits = model(**encoded).logits.reshape(-1).float().cpu().tolist()
        result.extend(logits)
    return result


def run(out: Path) -> None:
    verify_manifest(out)
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("An allocated GPU is required for the 62k-pair reranker run")
    torch.set_num_threads(16)
    inputs = rows(out / "inputs.jsonl")
    existing = rows(out / "scores.jsonl") if (out / "scores.jsonl").exists() else []
    if [pair_key(row) for row in existing] != [pair_key(row) for row in inputs[:len(existing)]]:
        raise ValueError("Checkpoint does not match frozen input order")
    tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL, local_files_only=True, dtype=torch.bfloat16,
    ).cuda().eval()
    write(out / "execution.json", {
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "partition": os.environ.get("SLURM_JOB_PARTITION"),
        "gpu": torch.cuda.get_device_name(0),
        "input_manifest_sha256": sha(out / "manifest.json"),
    })
    started = time.monotonic()
    scored = list(existing)
    for chunk_start in range(len(existing), len(inputs), 256):
        chunk = inputs[chunk_start:chunk_start + 256]
        flat, owners = [], []
        for owner, row in enumerate(chunk):
            for alignment in row["alignments"]:
                flat.append((alignment["text_a"], alignment["text_b"]))
                owners.append((owner, alignment["view_a"], alignment["view_b"]))
        logits = infer_pairs(model, tokenizer, flat, "cuda")
        by_owner = defaultdict(list)
        for (owner, view_a, view_b), logit in zip(owners, logits):
            by_owner[owner].append({"view_a": view_a, "view_b": view_b, "logit": logit})
        for owner, row in enumerate(chunk):
            best = max(by_owner[owner], key=lambda value: value["logit"])
            scored.append({
                "source": row["source"], "target": row["target"],
                "source_article": row["source_article"], "target_article": row["target_article"],
                "retrieval_score": row["retrieval_score"],
                "shared_identifiers": row["shared_identifiers"],
                "reranker_logit": best["logit"],
                "reranker_score": 1 / (1 + math.exp(-max(-80, min(80, best["logit"])))),
                "best_alignment": best,
            })
        jsonl(out / "scores.jsonl", scored)
        print(json.dumps({
            "scored": len(scored), "total": len(inputs),
            "elapsed_seconds": round(time.monotonic() - started, 1),
        }), flush=True)
    select(out)


def unique_prefix(ranked: list[dict], budget: int) -> list[dict]:
    selected, seen = [], set()
    for row in ranked:
        key = pair_key(row)
        if key in seen:
            continue
        seen.add(key); selected.append(row)
        if len(selected) == budget:
            break
    return selected


def routed_adaptive(scored: list[dict], selected_articles: set[tuple[str, str]], budget: int) -> list[dict]:
    """Reserve real off-route escape slots, then allocate routed pairs adaptively."""
    ranked = sorted(scored, key=lambda row: (-row["reranker_logit"], *pair_key(row)))
    selected, seen = [], set()

    def take(rows_: list[dict], limit: int, per_article_cap: int | None = None) -> None:
        article_counts = Counter()
        for row in rows_:
            if len(selected) >= budget or limit <= 0:
                return
            key = pair_key(row)
            article_key = tuple(sorted((row["source_article"], row["target_article"])))
            if key in seen or (per_article_cap is not None and article_counts[article_key] >= per_article_cap):
                continue
            seen.add(key); selected.append(row); article_counts[article_key] += 1; limit -= 1

    # Preserve a bounded same-article lane and make escape mean genuinely off-route.
    intra = [row for row in ranked if row["source_article"] == row["target_article"]]
    take(intra, 312, per_article_cap=8)
    off_route = [row for row in ranked if row["source_article"] != row["target_article"]
                 and tuple(sorted((row["source_article"], row["target_article"]))) not in selected_articles]
    take(off_route, 96)
    routed = [row for row in ranked if row["source_article"] != row["target_article"]
              and tuple(sorted((row["source_article"], row["target_article"]))) in selected_articles]
    take(routed, budget - len(selected), per_article_cap=64)
    take(ranked, budget - len(selected))
    return selected


def select(out: Path) -> None:
    verify_manifest(out)
    scored = rows(out / "scores.jsonl")
    expected = len(rows(out / "inputs.jsonl"))
    if len(scored) != expected:
        raise ValueError(f"Incomplete scores: {len(scored)}/{expected}")
    reranked = sorted(scored, key=lambda row: (-row["reranker_logit"], *pair_key(row)))
    retrieval = sorted(scored, key=lambda row: (-row["retrieval_score"], *pair_key(row)))
    rerank_position = {pair_key(row): index for index, row in enumerate(reranked, 1)}
    retrieval_position = {pair_key(row): index for index, row in enumerate(retrieval, 1)}
    fused = sorted(scored, key=lambda row: (
        -(1 / (60 + rerank_position[pair_key(row)]) + 1 / (60 + retrieval_position[pair_key(row)])),
        *pair_key(row),
    ))
    selected_articles = {
        tuple(sorted((row["source_article"], row["target_article"])))
        for row in rows(SOURCE / "article_candidates.jsonl") if row["selected_for_node_search"]
    }
    variants = {
        "reranker_global": unique_prefix(reranked, BUDGET),
        "retrieval_reranker_rrf": unique_prefix(fused, BUDGET),
        "reranker_routed_adaptive": routed_adaptive(scored, selected_articles, BUDGET),
    }
    for name, candidates in variants.items():
        if len(candidates) != BUDGET or len({pair_key(row) for row in candidates}) != BUDGET:
            raise ValueError("Selector did not produce a unique fixed budget: " + name)
        jsonl(out / f"candidates_{name}.jsonl", candidates)
    write(out / "selection_manifest.json", {
        "complete": True, "budget": BUDGET,
        "variants": {name: {"pairs": len(value), "sha256": sha(out / f"candidates_{name}.jsonl")}
                     for name, value in variants.items()},
        "labels_used": False,
    })
    report(out)


def coverage(cases: list[dict], candidates: list[dict]) -> dict:
    keys = {pair_key(row) for row in candidates}
    counts = Counter()
    hits = []
    for case in cases:
        key = tuple(sorted((case["A"]["node_id"], case["B"]["node_id"])))
        hit = key in keys
        counts[case["label"] + "_total"] += 1
        counts[case["label"] + "_retrieved"] += int(hit)
        if hit:
            hits.append(case["suite_case_id"])
    return {"counts": dict(counts), "hits": sorted(hits), "candidate_pairs": len(keys)}


def report(out: Path) -> None:
    selection = read(out / "selection_manifest.json")
    cases = rows(SOURCE / "evaluation/cases.jsonl")
    baseline = rows(SOURCE / "hierarchical_candidates.jsonl")
    results = {"current_hierarchical": coverage(cases, baseline)}
    for name in selection["variants"]:
        results[name] = coverage(cases, rows(out / f"candidates_{name}.jsonl"))
    summary = {
        "complete": True, "candidate_budget": BUDGET, "results": results,
        "interpretation": "Candidate inclusion only. Labels were read after frozen scoring and selection; selected pairs are not semantic edges.",
    }
    write(out / "summary.json", summary)
    lines = ["# Edge selector reranker shadow experiment", "", summary["interpretation"], "",
             "| Selector | Positive | Negative candidates |", "| --- | ---: | ---: |"]
    for name, value in results.items():
        c = value["counts"]
        lines.append(f"| {name} | {c.get('POSITIVE_retrieved', 0)}/{c.get('POSITIVE_total', 0)} | "
                     f"{c.get('NEGATIVE_retrieved', 0)}/{c.get('NEGATIVE_total', 0)} |")
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "run", "select", "report"])
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    globals()[args.stage](args.output.resolve())
