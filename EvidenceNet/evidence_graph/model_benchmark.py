from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import TransformersLLM
from .relation_verifier import verify_semantic_relations


DOCUMENTS = {
    "magazine": "CERNCourier2025JanFeb-digitaledition",
    "paper": "gw150914_detection",
    "slides": "CyberPhysicalModelingChapter4",
    "illustrated_booklet": "Luminous Garden Agnes Northrop and the Women of Tiffany Studios",
}


def _pair_id(candidate):
    return f"{candidate['node_a']}||{candidate['node_b']}"


def _sample(candidates, size, seed):
    """Deterministic coverage-first sample, shared by every compared model."""
    rng = random.Random(seed)
    pool = sorted(candidates, key=_pair_id)
    rng.shuffle(pool)
    selected, seen = [], set()
    dimensions = []
    for candidate in pool:
        dimensions.extend(("reason", value) for value in candidate.get("candidate_reasons", []))
        dimensions.extend(("hypothesis", value) for value in candidate.get("relation_hypotheses", []))
        dimensions.append(("scope", candidate.get("content_unit_scope", "UNSCOPED")))
    for dimension in sorted(set(dimensions)):
        for candidate in pool:
            values = candidate.get("candidate_reasons", []) if dimension[0] == "reason" else (
                candidate.get("relation_hypotheses", []) if dimension[0] == "hypothesis" else
                [candidate.get("content_unit_scope", "UNSCOPED")])
            if dimension[1] in values and _pair_id(candidate) not in seen:
                selected.append(candidate); seen.add(_pair_id(candidate)); break
        if len(selected) >= size:
            break
    for candidate in pool:
        if len(selected) >= size: break
        if _pair_id(candidate) not in seen:
            selected.append(candidate); seen.add(_pair_id(candidate))
    return sorted(selected, key=_pair_id)


def _slug(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.rstrip("/").split("/")[-1])


def run(args):
    graph_root = Path(args.graph_root)
    benchmark_root = Path(args.output_root) / args.benchmark
    sample_root = benchmark_root / "frozen_samples"
    result_root = benchmark_root / _slug(args.model)
    sample_root.mkdir(parents=True, exist_ok=True); result_root.mkdir(parents=True, exist_ok=True)
    llm = None if args.prepare_only else TransformersLLM(
        args.model, args.dtype, args.max_new_tokens, args.device_map, True)
    summary = {"benchmark": args.benchmark, "model": args.model, "documents": {},
               "started_at": datetime.now(timezone.utc).isoformat()}
    for kind, doc_id in DOCUMENTS.items():
        source = graph_root / doc_id
        sample_path = sample_root / f"{kind}.jsonl"
        if sample_path.exists():
            candidates = read_jsonl(sample_path)
        else:
            candidates = _sample(read_jsonl(source / "semantic_candidates.jsonl"), args.pairs_per_document, args.seed)
            write_jsonl(sample_path, candidates)
        if args.prepare_only:
            summary["documents"][kind] = {"doc_id": doc_id, "candidates": len(candidates)}
            continue
        nodes = read_jsonl(source / "evidence_nodes.jsonl")
        needed = {x for c in candidates for x in (c["node_a"], c["node_b"])}
        nodes = [n for n in nodes if n["node_id"] in needed]
        accepted, rejected, unsupported, malformed = verify_semantic_relations(
            candidates, nodes, llm, args.threshold, args.batch_size,
            args.generation_tokens, args.retry_generation_tokens)
        doc_root = result_root / kind; doc_root.mkdir(exist_ok=True)
        write_jsonl(doc_root / "accepted.jsonl", accepted)
        write_jsonl(doc_root / "rejected.jsonl", rejected)
        write_jsonl(doc_root / "unsupported.jsonl", unsupported)
        write_jsonl(doc_root / "malformed.jsonl", malformed)
        summary["documents"][kind] = {"doc_id": doc_id, "candidates": len(candidates),
            "accepted": len(accepted), "rejected": len(rejected), "unsupported": len(unsupported),
            "malformed": len(malformed), "relations": dict(Counter(e["edge_type"] for e in accepted))}
        write_json(result_root / "summary.json", summary)
    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(result_root / "summary.json", summary)
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Compare relation verifiers on an immutable four-document sample")
    parser.add_argument("--model", default="sample-preparation")
    parser.add_argument("--benchmark", default="qwen_new_models_v1")
    parser.add_argument("--graph-root", default="output/evidence_graph")
    parser.add_argument("--output-root", default="output/model_benchmarks")
    parser.add_argument("--pairs-per-document", type=int, default=40)
    parser.add_argument("--seed", type=int, default=3352)
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--threshold", type=float, default=.8)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    parser.add_argument("--generation-tokens", type=int, default=1000)
    parser.add_argument("--retry-generation-tokens", type=int, default=1400)
    parser.add_argument("--prepare-only", action="store_true")
    run(parser.parse_args())


if __name__ == "__main__": main()
