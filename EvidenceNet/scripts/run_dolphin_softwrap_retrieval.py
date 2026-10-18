#!/usr/bin/env python3
"""Shadow retrieval with sentence recovery across Dolphin soft line wraps."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

import compare_node_dedup_edge_retrieval as dedup
from compare_previous_edge_schemes import coverage
from dolphin_softwrap import make_views
import run_hierarchical_edge_retrieval as hierarchy
from run_node_context_edges import ROOT, jsonl, read, rows, sha, write
from run_traffic_relevance_cpu import cpu_embed


SOURCE = ROOT / "EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015"
OLD_LINE = ROOT / "EvidenceNet/output/line_aware_edge_retrieval_v1_20261017"
OUT = ROOT / "EvidenceNet/output/dolphin_softwrap_retrieval_v2_20261018"
ENCODER = ROOT / "EvidenceNet/models/Qwen3-Embedding-0.6B"
BUDGET = 1301
LANE_BUDGET = 96


def pair_key(pair: dict) -> tuple[str, str]:
    return tuple(sorted((pair["source"], pair["target"])))


def verify(out: Path) -> None:
    for path, digest in read(out / "manifest.json")["files"].items():
        if sha(path) != digest:
            raise ValueError("Changed frozen input/code: " + path)


def prepare(out: Path) -> None:
    if out.exists():
        raise ValueError("fresh_output_required")
    out.mkdir(parents=True)
    nodes = rows(SOURCE / "corpus_nodes.jsonl")
    policies = read(SOURCE / "corpus_policies.json")
    soft_views, boundary_counts = make_views(nodes, policies)
    for view in soft_views:
        view["identifiers"] = hierarchy.identifiers(view["retrieval_text"])
    jsonl(out / "softwrap_views.jsonl", soft_views)
    write(out / "protocol.json", {
        "experiment": "dolphin_softwrap_retrieval_v2", "base_views": len(rows(SOURCE / "views.jsonl")),
        "softwrap_views": len(soft_views), "boundary_counts": boundary_counts,
        "single_newline_policy": "soft wrap inside a recovered sentence; never a node/sentence boundary by itself",
        "hard_boundary_policy": "blank line only in this pilot",
        "hyphen_policy": "parallel dehyphenated and hyphen-preserved retrieval views; immutable source quote unchanged",
        "offset_policy": "every view stores exact char_start/char_end and raw quote",
        "selection": f"{LANE_BUDGET}-pair bounded softwrap lane plus frozen control fill at total {BUDGET}",
        "labels_used_for_retrieval_or_selection": False,
        "semantic_edges_exported": False,
    })
    files = [Path(__file__), Path(__file__).with_name("dolphin_softwrap.py"),
             Path(dedup.__file__), Path(hierarchy.__file__), SOURCE / "views.jsonl",
             SOURCE / "view_vectors.npy", SOURCE / "corpus_nodes.jsonl",
             SOURCE / "corpus_policies.json", SOURCE / "hierarchical_candidates.jsonl",
             SOURCE / "evaluation/cases.jsonl", out / "softwrap_views.jsonl",
             out / "protocol.json", ENCODER / "config.json"]
    write(out / "manifest.json", {"files": {str(path.resolve()): sha(path) for path in files}})
    print(json.dumps(read(out / "protocol.json")), flush=True)


def bounded_lane(pool: list[dict], control: list[dict], soft_ids: set[str]) -> tuple[list[dict], list[dict]]:
    control_keys = {pair_key(pair) for pair in control}
    degree = Counter()
    lane = []
    for pair in sorted(pool, key=lambda item: (-item["retrieval_score"], *pair_key(item))):
        key = pair_key(pair)
        if key in control_keys:
            continue
        best = pair.get("best_views", {}).values()
        if not any(item.get("source_view") in soft_ids or item.get("target_view") in soft_ids for item in best):
            continue
        a, b = key
        if degree[a] >= 4 or degree[b] >= 4:
            continue
        lane.append({**pair, "selection_routes": ["bounded_dolphin_softwrap_lane"]})
        degree[a] += 1
        degree[b] += 1
        if len(lane) == LANE_BUDGET:
            break
    selected, seen = list(lane), {pair_key(pair) for pair in lane}
    for pair in control:
        if len(selected) == BUDGET:
            break
        if pair_key(pair) not in seen:
            selected.append(pair)
            seen.add(pair_key(pair))
    if len(selected) != BUDGET:
        raise ValueError("bounded lane could not fill common budget")
    return lane, selected


def run(out: Path) -> None:
    verify(out)
    base_views = rows(SOURCE / "views.jsonl")
    soft_views = rows(out / "softwrap_views.jsonl")
    base_vectors = np.load(SOURCE / "view_vectors.npy", allow_pickle=False)
    soft_vectors = np.asarray(cpu_embed([v["retrieval_text"] for v in soft_views], ENCODER), dtype=np.float32)
    np.save(out / "softwrap_vectors.npy", soft_vectors, allow_pickle=False)
    views = base_views + soft_views
    vectors = np.concatenate((base_vectors, soft_vectors), axis=0)
    pool = list(dedup.retrieve(views, vectors).values())
    nodes = {node["id"]: node for node in rows(SOURCE / "corpus_nodes.jsonl")}
    articles, native = hierarchy.route_and_select(nodes, {pair_key(pair): pair for pair in pool})
    control = rows(SOURCE / "hierarchical_candidates.jsonl")[:BUDGET]
    lane, bounded = bounded_lane(pool, control, {view["view_id"] for view in soft_views})
    jsonl(out / "initial_pool.jsonl", pool)
    jsonl(out / "article_candidates.jsonl", articles)
    jsonl(out / "native_candidates.jsonl", native)
    jsonl(out / "softwrap_lane.jsonl", lane)
    jsonl(out / "bounded_candidates.jsonl", bounded)
    write(out / "selection.json", {
        "views": len(views), "softwrap_views": len(soft_views), "initial_pairs": len(pool),
        "native_pairs": len(native), "softwrap_lane_pairs": len(lane), "bounded_pairs": len(bounded),
        "files": {name: sha(out / name) for name in ("softwrap_vectors.npy", "initial_pool.jsonl",
            "native_candidates.jsonl", "softwrap_lane.jsonl", "bounded_candidates.jsonl")},
    })
    report(out)


def report(out: Path) -> None:
    verify(out)
    selection = read(out / "selection.json")
    for name, digest in selection["files"].items():
        if sha(out / name) != digest:
            raise ValueError("Changed frozen result: " + name)
    cases = rows(SOURCE / "evaluation/cases.jsonl")
    arms = {
        "control_hierarchical_1301": rows(SOURCE / "hierarchical_candidates.jsonl")[:BUDGET],
        "old_physical_line_1301": rows(OLD_LINE / "node_candidates.jsonl")[:BUDGET],
        "softwrap_native_1301": rows(out / "native_candidates.jsonl")[:BUDGET],
        "softwrap_bounded_lane_1301": rows(out / "bounded_candidates.jsonl"),
    }
    results, details = {}, {}
    for name, candidates in arms.items():
        results[name], details[name] = coverage(cases, candidates)
    write(out / "summary.json", {"complete": True, "selection": selection, "results": results,
        "interpretation": "Candidate coverage only; labels read after candidate files were frozen. No semantic edges exported."})
    write(out / "case_coverage.json", details)
    print(json.dumps(read(out / "summary.json")), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "run", "report"))
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    globals()[args.stage](args.output.resolve())
