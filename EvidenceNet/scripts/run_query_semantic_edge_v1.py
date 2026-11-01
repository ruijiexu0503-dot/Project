#!/usr/bin/env python3
"""Independent query-semantic-edge v1 over frozen VL-DocIR nodes and graph."""
from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from pathlib import Path

import query_semantic_edge_policy as policy
import query_semantic_edge_core as core
import run_query_adaptive_evidence_v2 as legacy
from build_reader_anchor_ablation import ROOT, MODEL, SOURCE, sha

DEFAULT_OUT = ROOT / "EvidenceNet/output/query_semantic_edge_v1_20261030"
DESCRIPTION_ROOT = ROOT / "migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics"

@contextmanager
def semantic_protocol():
    """Inject the new protocol only for this version; never mutate v2 globally."""
    previous = legacy.policy
    legacy.policy = policy
    try:
        yield
    finally:
        legacy.policy = previous


def run_task(task, edges, mode, broker):
    with semantic_protocol():
        return legacy.run_task(task, edges, mode, broker)


def prepare(out: Path, model: Path, max_candidates: int = 40) -> None:
    legacy.prepare(out, model, max_candidates)
    pending = {edge["edge_id"]: edge for edge in legacy.rows(out / "edges.jsonl")}
    records, coverage = core.load_described_edges(
        DESCRIPTION_ROOT / "edge_records.jsonl",
        DESCRIPTION_ROOT / "description_predictions.jsonl")
    cards = [core.edge_card(row) for row in records]
    if set(pending) != {edge["edge_id"] for edge in cards}:
        raise ValueError("described graph differs from the graph prepared for query navigation")
    for edge in cards:
        old = pending[edge["edge_id"]]
        if (old["source_node_id"], old["target_node_id"]) != (edge["source_node_id"], edge["target_node_id"]):
            raise ValueError("described edge endpoints differ from prepared graph")
        old_anchors = sorted((a["node_id"], a["text"]) for a in old["anchors"])
        new_anchors = sorted((a["node_id"], a["text"]) for a in edge["anchors"])
        if not set(old_anchors) <= set(new_anchors):
            raise ValueError("described edge lost a source-verified prepared anchor")
    nodes = {node["id"]: node for node in legacy.rows(SOURCE / "nodes.jsonl")}
    for edge in cards:
        for anchor in edge["anchors"]:
            members = {member["id"]: member for member in nodes[anchor["node_id"]]["members"]}
            member = members[anchor["member_id"]]
            if (sha(member["text"]) != anchor["member_sha256"] or
                    member["text"][anchor["char_start"]:anchor["char_end"]] != anchor["text"]):
                raise ValueError("semantic edge source anchor failed node/member integrity check")
    legacy.jsonl(out / "edges.jsonl", cards)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest.update({
        "version": "query-semantic-edge-v1",
        "edges_sha256": legacy.digest(out / "edges.jsonl"),
        "description_coverage": coverage,
        "description_source": str(DESCRIPTION_ROOT / "description_predictions.jsonl"),
        "description_fallback": "INSUFFICIENT or invalid rows use endpoint anchors and are explicitly labelled",
        "support_protocol": "support_facts/observations/missing/validation_state-v1",
        "navigation_protocol": "semantic route decisions with grounded anchor IDs and expected-vs-actual trace",
        "joint_support": "selected original packets are audited as a union; descriptions are excluded as evidence",
        "arms": {"navigation_endpoint": "same graph/anchors with generated descriptions hidden",
                 "navigation_semantic": "same graph/anchors with validated descriptions visible",
                 "graph_adaptive_joint": "same semantic visit set with route-proposed original-source groups"},
        "source_sha256": {**manifest["source_sha256"], str(Path(__file__)): legacy.digest(Path(__file__)),
                          str(Path(policy.__file__)): legacy.digest(Path(policy.__file__)),
                          str(Path(core.__file__)): legacy.digest(Path(core.__file__))},
    })
    legacy.base.save(out / "manifest.json", manifest)
    check(out, model)
    print(json.dumps({"output": str(out), "queries": manifest["queries"],
                      "description_coverage": coverage}, ensure_ascii=False))


def check(out: Path, model: Path) -> None:
    legacy.check(out, model)
    manifest = json.loads((out / "manifest.json").read_text())
    coverage = manifest.get("description_coverage", {})
    if manifest.get("version") != "query-semantic-edge-v1":
        raise ValueError("wrong semantic-edge version")
    if coverage.get("described", 0) < 1:
        raise ValueError("semantic navigation has no validated nonempty description")
    edges = legacy.rows(out / "edges.jsonl")
    if len(edges) != coverage.get("total"):
        raise ValueError("description coverage no longer matches frozen edges")
    for edge in edges:
        if edge["relation_description"]["status"] == "PENDING":
            raise ValueError("PENDING description reached semantic preflight")
        if edge["relation_description"]["status"] == "DESCRIBED" and not edge["relation_description"]["text"].strip():
            raise ValueError("empty DESCRIBED relation")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "check", "infer", "report"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--edge-mode", choices=["endpoint", "semantic"], default="semantic")
    parser.add_argument("--minutes", type=float, default=25)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--query-id", action="append", dest="query_ids")
    args = parser.parse_args()
    if args.stage == "prepare": prepare(args.out, args.model)
    elif args.stage == "check": check(args.out, args.model); print("QUERY_SEMANTIC_EDGE_PREFLIGHT_OK")
    elif args.stage == "infer":
        check(args.out, args.model)
        with semantic_protocol():
            legacy.infer(args.out, args.model, "navigation_" + args.edge_mode,
                         args.minutes, args.limit, args.query_ids)
    else: legacy.report(args.out, "navigation_" + args.edge_mode)


if __name__ == "__main__":
    main()
