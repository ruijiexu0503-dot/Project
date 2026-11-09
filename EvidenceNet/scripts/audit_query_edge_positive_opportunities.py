#!/usr/bin/env python3
"""Audit the already-mined opportunities without widening the search.

This report separates structural reachability, eligibility, and utility. Gold is
expanded only for offline diagnostics; it is never used to promote a route.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from mine_query_edge_positive_opportunities import (  # noqa: E402
    ORACLE, ROUTES, NODES, adjacency, find_paths, path_status, source_kind,
)


ROOT = Path(__file__).resolve().parents[2]
QUERIES = ROOT / "migration/vldocir_trace_inputs_20261023/queries.jsonl"
GOLD = ROOT / "migration/vldocir_trace_inputs_20261023/gold_evidence.jsonl"
MINED = ROOT / "EvidenceNet/output/query_edge_positive_opportunity_mining_v2_20261106"
DEFAULT_OUT = ROOT / "EvidenceNet/output/query_edge_positive_opportunity_audit_v1_20261106"
VERSION = "query-edge-positive-opportunity-audit-v1-20261106"


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def excerpt(node: dict, limit: int = 1800) -> str:
    return " ".join(str(member.get("text", "")) for member in node.get("members", []))[:limit]


def bbox(gold: dict) -> dict:
    return {
        "gold_id": gold["_id"],
        "document_id": gold["document_id"],
        "page_number": gold["page_number"],
        "evidence_type": gold.get("evidence_type"),
        "relative_bbox": gold["bounding_box"],
        "html_tag": gold.get("html_tag"),
        "html_unique_element_id": gold.get("html_unique_element_id"),
    }


def edge_detail(edge: dict, nodes: dict[str, dict]) -> dict:
    return {
        "edge_id": edge["edge_id"],
        "source_id": edge["oriented_source_id"],
        "target_id": edge["oriented_target_id"],
        "relation_type": edge.get("relation_type"),
        "relation_claim": edge.get("relation_text"),
        "conditions": edge.get("conditions"),
        "limitations": edge.get("limitations"),
        "eligibility": edge.get("eligibility"),
        "source_kind": source_kind(edge),
        "source_node": {
            "document": nodes.get(edge["oriented_source_id"], {}).get("document"),
            "page": nodes.get(edge["oriented_source_id"], {}).get("page"),
            "excerpt": excerpt(nodes.get(edge["oriented_source_id"], {})),
        },
        "target_node": {
            "document": nodes.get(edge["oriented_target_id"], {}).get("document"),
            "page": nodes.get(edge["oriented_target_id"], {}).get("page"),
            "excerpt": excerpt(nodes.get(edge["oriented_target_id"], {})),
        },
        "source_anchors": edge.get("source_anchors", []),
        "target_anchors": edge.get("target_anchors", []),
    }


def audit(out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite: {out}")
    matrix = rows(ORACLE)
    routes = rows(ROUTES)
    nodes = {str(row["id"]): row for row in rows(NODES)}
    queries = {row["question_id"]: row for row in rows(QUERIES)}
    gold = {row["_id"]: row for row in rows(GOLD)}
    mined = rows(MINED / "gold_guided_opportunities.jsonl")
    graph = adjacency(routes)
    # These are the four rows explicitly requested: two cutoff comparisons for
    # the same two target nodes on the Federer query.
    selected = [
        row for row in mined
        if row["classification"] in {
            "existing_relation_but_unreachable", "reachable_but_unverified"
        }
    ]
    audited = []
    for row in selected:
        qid = row["query_id"]
        target = row["target_id"]
        query = queries[qid]
        top10 = set(next(x for x in matrix if x["question_id"] == qid)["dense_top10_ids"])
        top20 = set(next(x for x in matrix if x["question_id"] == qid)["dense_top20_ids"])
        seeds = top10 if row["dense_cutoff"] == 10 else top20
        paths = find_paths(graph, sorted(seeds), target)
        path_rows = []
        for path in paths:
            path_rows.append({
                "hops": len(path),
                "structural_reachable": True,
                "path_status": path_status(path),
                "eligibility_gate": (
                    "reject" if any(e.get("eligibility") == "denied" for e in path)
                    else "inspection_only" if any(e.get("eligibility") == "unknown" for e in path)
                    else "admit"
                ),
                "edges": [edge_detail(edge, nodes) for edge in path],
            })
        candidate = next(
            item for item in next(x for x in matrix if x["question_id"] == qid)
            ["gold_item_diagnostics"] if item["gold_id"] == row["gold_id"]
        )
        audited.append({
            "query_id": qid,
            "query": query["question"],
            "question_type": query.get("question_type"),
            "dense_cutoff": row["dense_cutoff"],
            "dense_top10_ids": next(x for x in matrix if x["question_id"] == qid)["dense_top10_ids"],
            "dense_top20_ids": next(x for x in matrix if x["question_id"] == qid)["dense_top20_ids"],
            "target_id": target,
            "target_node": {
                "document": nodes[target].get("document"),
                "page": nodes[target].get("page"),
                "excerpt": excerpt(nodes[target]),
            },
            "gold_bbox": bbox(gold[row["gold_id"]]),
            "gold_spatial_mapping": candidate,
            "structural_reachability": {
                "within_two_hops": bool(paths),
                "path_count": len(paths),
                "paths": path_rows,
            },
            "independently_validated_utility": "not_available",
            "relation_validity": "uncertain",
            "query_applicability": "plausible_for_federer_2004_2005_comparison"
            if paths else "not_assessable_without_path",
            "marginal_utility": "plausible_but_not_independently_validated"
            if paths else "not_assessable",
            "navigation_opportunity": (
                "inspection_only_not_admissible" if paths else "not_reachable"
            ),
            "reason": (
                "The target is a Gold-spatial candidate and the path reaches it "
                "only through unknown Qwen routes; relation and utility require "
                "independent review. Gold is not a retrieval-time signal."
                if paths else
                "The target has an endpoint relation somewhere in the graph, but "
                "no directed path from this Dense seed set within two hops."
            ),
        })
    out.mkdir(parents=True)
    (out / "audit_only").mkdir()
    (out / "audited_opportunities.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in audited), encoding="utf-8"
    )
    controlled = rows(MINED / "edge_first_controlled_query_candidates.jsonl")
    controlled_audit = []
    for row in controlled:
        if row["edge_id"] == "MODEL_EDGE_fa40f954601a98d2878e":
            label, reason = "invalid", "denied KG edge and notation/application mismatch"
        elif row["edge_id"] == "REL_4ae0a8193f7a10f8":
            label, reason = "composition_opportunity", "eigenvalue result and derivation context may complement"
        elif row["edge_id"] == "REL_fe4ba5d7ca7fc46e":
            label, reason = "composition_opportunity", "method/time context may complement experimental result"
        elif row["edge_id"] in {"REL_c81bd10dffece8f0", "REL_06ab6f702f7821a9",
                                "REL_46bbfd66c0b8d49f"}:
            label, reason = "redundant_relation", "generic consent/funding/citation metadata is not answer complement"
        else:
            label, reason = "uncertain", "unknown eligibility and no independent query utility label"
        controlled_audit.append({
            "edge_id": row["edge_id"], "source_id": row["source_id"],
            "target_id": row["target_id"], "edge_source": row["edge_source"],
            "eligibility": row["eligibility"], "relation_type": row["relation_type"],
            "relation_claim": row["relation_text"],
            "source_anchor": row["source_anchor"], "target_anchor": row["target_anchor"],
            "source_excerpt": row["source_excerpt"], "target_excerpt": row["target_excerpt"],
            "classification": label, "reason": reason,
            "constructed_evaluation": True,
            "dense_baseline_run": False,
            "independent_utility": "not_validated",
        })
    (out / "edge_first_candidate_audit.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in controlled_audit), encoding="utf-8"
    )
    summary = {
        "version": VERSION,
        "audited_gold_guided_rows": len(audited),
        "structural_reachable_rows": sum(x["structural_reachability"]["within_two_hops"] for x in audited),
        "independently_validated_utility_rows": 0,
        "navigation_admissible_rows": 0,
        "unknown_not_negative": True,
        "hard_gate_diagnostic": {
            "zero_valid_and_possible_incremental_evidence_is_gate_derived": True,
            "structural_paths_ignoring_gate": sum(
                x["structural_reachability"]["within_two_hops"] for x in audited
            ),
            "allowed_paths": 0,
            "unknown_paths": sum(
                any(p["eligibility_gate"] == "inspection_only"
                    for p in x["structural_reachability"]["paths"])
                for x in audited
            ),
        },
        "controlled_candidates": len(controlled_audit),
        "controlled_dense_baseline_run": False,
        "inputs_sha256": {str(path): digest(path) for path in
                          (ORACLE, ROUTES, NODES, QUERIES, GOLD)},
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False,
                                                   sort_keys=True, indent=2) + "\n",
                                         encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(audit(args.out), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
