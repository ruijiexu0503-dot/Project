#!/usr/bin/env python3
"""Fuse long, physical-line, and soft-wrap candidate rankings at one budget."""

from __future__ import annotations

import json
from pathlib import Path

from compare_previous_edge_schemes import coverage
from run_node_context_edges import ROOT, jsonl, rows, sha, write


BASE = ROOT / "EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015"
PHYSICAL = ROOT / "EvidenceNet/output/edge_candidate_allocation_repair_v2_20261017"
SOFT = ROOT / "EvidenceNet/output/dolphin_softwrap_retrieval_v2_20261018"
OUT = ROOT / "EvidenceNet/output/dolphin_three_lane_retrieval_v2_20261018"
BUDGET = 1301
RRF_K = 60


def key(pair: dict) -> tuple[str, str]:
    return tuple(sorted((pair["source"], pair["target"])))


def main(out: Path) -> None:
    if out.exists():
        raise ValueError("fresh_output_required")
    out.mkdir(parents=True)
    control = rows(BASE / "hierarchical_candidates.jsonl")[:BUDGET]
    physical = rows(PHYSICAL / "eligible_only_candidates.jsonl")
    soft = rows(SOFT / "bounded_candidates.jsonl")
    arms = {"long_window": control, "physical_line": physical[:BUDGET], "softwrap_sentence": soft}
    pool = {}
    for arm, candidates in arms.items():
        for rank, pair in enumerate(candidates, 1):
            item = pool.setdefault(key(pair), {**pair, "arm_rrf": 0.0, "arm_ranks": {}})
            item["arm_rrf"] += 1 / (RRF_K + rank)
            item["arm_ranks"][arm] = rank
    combined = sorted(pool.values(), key=lambda pair: (-pair["arm_rrf"], *key(pair)))[:BUDGET]
    if len(combined) != BUDGET or len({key(pair) for pair in combined}) != BUDGET:
        raise ValueError("fixed budget/dedup failure")
    jsonl(out / "combined_candidates.jsonl", combined)
    write(out / "protocol.json", {
        "candidate_budget": BUDGET, "rrf_k": RRF_K,
        "policy": "RRF over eligible physical-line claims, source-mapped soft-wrap sentences, and frozen long windows",
        "labels_used_for_selection": False, "semantic_edges_exported": False,
    })
    write(out / "selection.json", {"combined_sha256": sha(out / "combined_candidates.jsonl")})
    # Reference labels are opened only after the candidate file is frozen.
    cases = rows(BASE / "evaluation/cases.jsonl")
    arms = {"control": control, "physical_line": physical[:BUDGET],
            "softwrap_bounded": soft, "three_lane_rrf": combined}
    results, details = {}, {}
    for name, candidates in arms.items():
        results[name], details[name] = coverage(cases, candidates)
    write(out / "summary.json", {"complete": True, "results": results,
        "interpretation": "Fixed-pair development candidate coverage; not semantic precision. Identity verification remains downstream."})
    write(out / "case_coverage.json", details)
    print(json.dumps({"protocol": json.loads((out / "protocol.json").read_text()), "results": results}), flush=True)


if __name__ == "__main__":
    main(OUT)
