#!/usr/bin/env python3
"""Shadow retrieval with target-node deduplication before per-view top-k."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

import numpy as np

import run_hierarchical_edge_retrieval as old
from compare_previous_edge_schemes import coverage
from run_node_context_edges import ROOT, read, rows, write, jsonl, sha, tokens


SOURCE = ROOT / "EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015"
OUT = ROOT / "EvidenceNet/output/node_dedup_edge_retrieval_v1_20261016"


def bm25_node_top(views: list[dict], k: int = 30) -> list[list[tuple[int, float]]]:
    """Return at most one best target view per target node for each query view."""
    bags = [Counter(tokens(view["retrieval_text"])) for view in views]
    n = len(bags)
    lengths = np.asarray([sum(bag.values()) for bag in bags], dtype=np.float32)
    average = max(float(lengths.mean()), 1.0)
    postings = defaultdict(list)
    for index, bag in enumerate(bags):
        for term, frequency in bag.items():
            postings[term].append((index, frequency))
    result = []
    for query_index, query in enumerate(bags):
        scores = defaultdict(float)
        for term in query:
            hits = postings[term]
            if len(hits) > n * 0.35:
                continue
            inverse = math.log(1 + (n - len(hits) + 0.5) / (len(hits) + 0.5))
            for target_index, frequency in hits:
                if views[target_index]["node_id"] == views[query_index]["node_id"]:
                    continue
                scores[target_index] += inverse * frequency * 2.5 / (
                    frequency + 1.5 * (0.25 + 0.75 * lengths[target_index] / average)
                )
        by_node = {}
        for target_index, score in scores.items():
            node = views[target_index]["node_id"]
            if node not in by_node or score > by_node[node][1]:
                by_node[node] = (target_index, score)
        result.append(sorted(by_node.values(), key=lambda item: (-item[1], item[0]))[:k])
    return result


def retrieve(views: list[dict], vectors: np.ndarray, dense_k: int = 30) -> dict:
    pair_signals = {}

    def add(i: int, j: int, route: str, rank: int, score: float) -> None:
        if views[i]["node_id"] == views[j]["node_id"]:
            return
        a, b = sorted((views[i]["node_id"], views[j]["node_id"]))
        record = pair_signals.setdefault((a, b), {
            "source": a, "target": b, "signals": {}, "best_views": {},
        })
        direction = "ab" if a == views[i]["node_id"] else "ba"
        key = route + "_" + direction
        value = 1 / (60 + rank)
        if value > record["signals"].get(key, 0):
            record["signals"][key] = value
            record["best_views"][key] = {
                "source_view": views[i]["view_id"], "target_view": views[j]["view_id"],
                "raw_score": float(score), "rank": rank,
            }

    for start in range(0, len(views), 128):
        block = vectors[start:start + 128] @ vectors.T
        for offset, row in enumerate(block):
            query_index = start + offset
            by_node = {}
            for target_index, score in enumerate(row):
                node = views[target_index]["node_id"]
                if node == views[query_index]["node_id"]:
                    continue
                if node not in by_node or score > by_node[node][1]:
                    by_node[node] = (target_index, float(score))
            for rank, (target_index, score) in enumerate(
                sorted(by_node.values(), key=lambda item: (-item[1], item[0]))[:dense_k], 1
            ):
                add(query_index, target_index, "dense", rank, score)
    for query_index, hits in enumerate(bm25_node_top(views, dense_k)):
        for rank, (target_index, score) in enumerate(hits, 1):
            add(query_index, target_index, "bm25", rank, score)
    by_identifier = defaultdict(dict)
    for index, view in enumerate(views):
        for identifier in view["identifiers"]:
            by_identifier[identifier].setdefault(view["node_id"], index)
    for identifier, hits in by_identifier.items():
        node_ids = sorted(hits)
        if len(node_ids) < 2 or len(node_ids) > 40:
            continue
        for position, a in enumerate(node_ids):
            for b in node_ids[position + 1:]:
                i, j = hits[a], hits[b]
                record = pair_signals.setdefault((a, b), {
                    "source": a, "target": b, "signals": {}, "best_views": {},
                })
                record["signals"]["identifier"] = max(record["signals"].get("identifier", 0), 1 / 60)
                record.setdefault("shared_identifiers", []).append(identifier)
                record["best_views"].setdefault("identifier", {
                    "source_view": views[i]["view_id"], "target_view": views[j]["view_id"],
                })
    for record in pair_signals.values():
        record["retrieval_score"] = sum(record["signals"].values())
        record["routes"] = sorted({key.split("_")[0] for key in record["signals"]})
    return pair_signals


def prepare(out: Path) -> None:
    if out.exists():
        raise ValueError("fresh_output_required")
    out.mkdir(parents=True)
    source_files = [SOURCE / name for name in (
        "views.jsonl", "view_vectors.npy", "corpus_nodes.jsonl", "evaluation/cases.jsonl",
    )]
    files = source_files + [Path(__file__)]
    write(out / "manifest.json", {
        "files": {str(path.resolve()): sha(path) for path in files},
        "labels_used_for_retrieval_or_selection": False,
        "change": "deduplicate target nodes before dense/BM25 top-30; all other retrieval and selector defaults retained",
    })


def verify(out: Path) -> None:
    for path, digest in read(out / "manifest.json")["files"].items():
        if sha(path) != digest:
            raise ValueError("Changed input/code: " + path)


def run(out: Path) -> None:
    verify(out)
    views = rows(SOURCE / "views.jsonl")
    vectors = np.load(SOURCE / "view_vectors.npy")
    nodes = {row["id"]: row for row in rows(SOURCE / "corpus_nodes.jsonl")}
    pool = retrieve(views, vectors)
    article_rows, candidates = old.route_and_select(nodes, pool)
    jsonl(out / "initial_pool.jsonl", pool.values())
    jsonl(out / "article_candidates.jsonl", article_rows)
    jsonl(out / "node_candidates.jsonl", candidates)
    write(out / "selection.json", {
        "initial_pairs": len(pool), "final_pairs": len(candidates),
        "initial_sha256": sha(out / "initial_pool.jsonl"),
        "final_sha256": sha(out / "node_candidates.jsonl"),
    })
    report(out)


def report(out: Path) -> None:
    verify(out)
    frozen = read(out / "selection.json")
    if frozen["initial_sha256"] != sha(out / "initial_pool.jsonl") or frozen["final_sha256"] != sha(out / "node_candidates.jsonl"):
        raise ValueError("Candidate output changed")
    cases = rows(SOURCE / "evaluation/cases.jsonl")
    initial_counts, initial_cases = coverage(cases, rows(out / "initial_pool.jsonl"))
    final_counts, final_cases = coverage(cases, rows(out / "node_candidates.jsonl"))
    current = read(SOURCE / "retrieval_summary.json")["results"]["hierarchical_76411_replay"]
    summary = {
        "complete": True, "current_final": current,
        "node_dedup_initial": initial_counts, "node_dedup_final": final_counts,
        "interpretation": "Candidate inclusion only; labels read after candidate files were frozen.",
    }
    write(out / "summary.json", summary)
    write(out / "case_coverage.json", {"initial": initial_cases, "final": final_cases})
    (out / "REPORT.md").write_text(
        "# Target-node-deduplicated retrieval\n\n" + summary["interpretation"] + "\n\n```json\n" +
        json.dumps(summary, indent=2) + "\n```\n"
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "run", "report"])
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    globals()[args.stage](args.output.resolve())
