#!/usr/bin/env python3
"""Symmetric-scoring follow-up to the frozen edge selector reranker trial."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import time

import run_edge_selector_reranker as base
from run_node_context_edges import read, rows, write, jsonl, sha


OUT = base.ROOT / "EvidenceNet/output/edge_selector_reranker_symmetric_v1_20261016"


def prepare(out: Path) -> None:
    if (out / "manifest.json").exists():
        base.verify_manifest(out)
        return
    base.prepare(out)
    protocol = read(out / "protocol.json")
    protocol["experiment"] = "edge_selector_reranker_symmetric_v1"
    protocol["scoring"] = "mean of A-to-B and B-to-A logits for every source-mapped view pair"
    write(out / "protocol.json", protocol)
    manifest = read(out / "manifest.json")
    manifest["files"][str(Path(__file__).resolve())] = sha(__file__)
    manifest["files"][str((out / "protocol.json").resolve())] = sha(out / "protocol.json")
    write(out / "manifest.json", manifest)


def run(out: Path) -> None:
    base.verify_manifest(out)
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("An allocated GPU is required for symmetric reranking")
    torch.set_num_threads(16)
    inputs = rows(out / "inputs.jsonl")
    existing = rows(out / "scores.jsonl") if (out / "scores.jsonl").exists() else []
    if [base.pair_key(row) for row in existing] != [base.pair_key(row) for row in inputs[:len(existing)]]:
        raise ValueError("Checkpoint does not match frozen input order")
    tokenizer = AutoTokenizer.from_pretrained(base.MODEL, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        base.MODEL, local_files_only=True, dtype=torch.bfloat16,
    ).cuda().eval()
    write(out / "execution.json", {
        "job_id": os.environ.get("SLURM_JOB_ID"), "partition": os.environ.get("SLURM_JOB_PARTITION"),
        "gpu": torch.cuda.get_device_name(0), "input_manifest_sha256": sha(out / "manifest.json"),
    })
    started = time.monotonic(); scored = list(existing)
    for chunk_start in range(len(existing), len(inputs), 256):
        chunk = inputs[chunk_start:chunk_start + 256]
        flat, owners = [], []
        for owner, row in enumerate(chunk):
            for alignment in row["alignments"]:
                a, b = alignment["text_a"], alignment["text_b"]
                flat.extend([(a, b), (b, a)])
                owners.append((owner, alignment["view_a"], alignment["view_b"]))
        logits = base.infer_pairs(model, tokenizer, flat, "cuda")
        by_owner = defaultdict(list)
        for index, (owner, view_a, view_b) in enumerate(owners):
            ab, ba = logits[2 * index:2 * index + 2]
            by_owner[owner].append({
                "view_a": view_a, "view_b": view_b, "logit_ab": ab, "logit_ba": ba,
                "logit": (ab + ba) / 2,
            })
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
        print(json.dumps({"scored": len(scored), "total": len(inputs),
                          "elapsed_seconds": round(time.monotonic() - started, 1)}), flush=True)
    base.select(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "run", "select", "report"])
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.output.resolve())
    elif args.stage == "run":
        run(args.output.resolve())
    else:
        getattr(base, args.stage)(args.output.resolve())
