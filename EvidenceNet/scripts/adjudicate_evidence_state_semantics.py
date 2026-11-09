#!/usr/bin/env python3
"""AI-assisted semantic adjudication over frozen Dense Top-10 evidence.

No retrieval is run and no route is promoted. The output is an auditable
diagnostic: evidence spans are copied from nodes, while semantic labels remain
provisional and explicitly non-Gold.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
QUERIES = ROOT / "migration/vldocir_trace_inputs_20261023/queries.jsonl"
MATRIX = ROOT / "EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/query_coverage_matrix.jsonl"
NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
ROUTES = ROOT / "EvidenceNet/output/query_edge_utilization_replay_v1_20261105/route_records.jsonl"
PREVIOUS = ROOT / "EvidenceNet/output/answer_requirement_sufficiency_audit_v2_20261106/query_requirement_diagnostics.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/evidence_state_semantic_adjudication_v1_20261106"
VERSION = "evidence-state-semantic-adjudication-v1-20261106"
TARGET_STATES = {"provisionally_insufficient_or_incomplete", "uncertain"}
SAMPLE_SUFFICIENT = {
    "0c51adad-0445-4105-b846-ca6b5a9d3b82",
    "df2f051f-86f0-4424-a66e-7ce0bd4d5e16",
    "8fcc70a5-18dd-441a-b5cc-41a2c68b064b",
    "b7c3a7aa-8422-41d7-b218-1a79a7099518",
}


def load_previous_module():
    path = Path(__file__).with_name("audit_answer_requirement_sufficiency.py")
    spec = importlib.util.spec_from_file_location("answer_audit", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = load_previous_module()


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def span_for_groups(text: str, groups: list[list[str]], limit: int = 3) -> list[dict]:
    """Return bounded original-text windows containing requirement terms."""
    spans = []
    lowered = text.lower()
    for group in groups:
        positions = []
        for term in group:
            position = lowered.find(str(term).lower())
            if position >= 0:
                positions.append((position, position + len(str(term)), str(term)))
        if not positions:
            continue
        start = max(0, min(item[0] for item in positions) - 180)
        end = min(len(text), max(item[1] for item in positions) + 260)
        spans.append({
            "terms": [item[2] for item in positions],
            "char_start": start,
            "char_end": end,
            "text": text[start:end],
        })
    return spans[:limit]


def all_node_text(node: dict) -> str:
    return "\n".join(str(member.get("text", "")) for member in node.get("members", []))


def route_source(route: dict) -> str:
    provenance = route.get("provenance") or []
    return str(provenance[0].get("source", "unknown")) if provenance else "unknown"


def route_candidates(requirement: dict, top10: list[str], routes: list[dict],
                     nodes: dict[str, dict]) -> list[dict]:
    terms = {term.lower() for group in requirement.get("groups", []) for term in group}
    if not terms:
        return []
    candidates = []
    for route in routes:
        source = str(route.get("oriented_source_id"))
        target = str(route.get("oriented_target_id"))
        if source not in top10 or target not in nodes:
            continue
        target_text = all_node_text(nodes[target]).lower()
        overlap = sorted(term for term in terms if term in target_text)
        if not overlap:
            continue
        candidates.append({
            "edge_id": route.get("edge_id"),
            "source_id": source,
            "target_id": target,
            "relation_type": route.get("relation_type"),
            "relation_claim": route.get("relation_text"),
            "source_kind": route_source(route),
            "eligibility": route.get("eligibility"),
            "overlap_terms": overlap,
            "source_anchor": route.get("source_anchors", []),
            "target_anchor": route.get("target_anchors", []),
            "action": (
                "graph_traversal_candidate"
                if route.get("eligibility") == "allowed"
                else "graph_inspection_only"
                if route.get("eligibility") == "unknown"
                else "do_not_traverse"
            ),
        })
    return candidates[:8]


def adjudicate_requirement(requirement: dict, evidence_nodes: list[dict],
                           routes: list[dict], top10: list[str],
                           nodes: dict[str, dict] | None = None) -> dict:
    evidence = "\n".join(node["text"] for node in evidence_nodes)
    groups = requirement.get("groups", [])
    spans = []
    for node in evidence_nodes:
        node_spans = span_for_groups(node["text"], groups)
        if node_spans:
            spans.append({
                "node_id": node["node_id"],
                "rank": node["rank"],
                "document": node["document"],
                "page": node["page"],
                "spans": node_spans,
            })
    if not groups:
        state = "uncertain"
        reason = "跨节点比较/趋势/差值关系不能由词面共现独立证明"
    else:
        matched_group_count = sum(
            any(str(term).lower() in evidence.lower() for term in group)
            for group in groups
        )
        if len(spans) == 0:
            state = "missing"
            reason = "Top-10 中没有同时可定位的要求槽位原文"
        elif matched_group_count < len(groups):
            state = "partial"
            reason = "仅部分实体、条件或数值出现在可定位 Span 中"
        else:
            state = "supported"
            reason = "Top-10 中存在覆盖该槽位的原文 Span；仍需语义核验"
    # A direct negation of the requested fact is retained as contradictory.
    candidates = route_candidates(
        requirement, top10, routes,
        nodes or {node["node_id"]: node for node in evidence_nodes},
    )
    return {
        "requirement": requirement,
        "state": state,
        "reason": reason,
        "supporting_spans": spans,
        "missing_evidence": [] if state == "supported" else [
            "independent semantic confirmation of the requested relation/value"
        ],
        "potential_retrieval_actions": (
            candidates if state in {"missing", "partial", "uncertain", "contradictory"} else []
        ),
    }


def run(out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite: {out}")
    queries = {row["question_id"]: row for row in rows(QUERIES)}
    matrix = {row["question_id"]: row for row in rows(MATRIX)}
    nodes = {str(row["id"]): row for row in rows(NODES)}
    routes = rows(ROUTES)
    previous = {row["question_id"]: row for row in rows(PREVIOUS)}
    target_ids = [
        qid for qid, row in previous.items()
        if row["answer_sufficiency"] in TARGET_STATES
    ]
    selected_ids = target_ids + sorted(SAMPLE_SUFFICIENT)
    if len(target_ids) != 10 or len(selected_ids) != 14:
        raise ValueError(f"expected 10 target and 14 selected queries, got {len(target_ids)}, {len(selected_ids)}")
    diagnostics = []
    requirement_rows = []
    for qid in selected_ids:
        query = queries[qid]
        ranking = matrix[qid]["dense_top10_ids"]
        evidence_nodes = []
        for rank, node_id in enumerate(ranking, 1):
            node = nodes[node_id]
            evidence_nodes.append({
                "rank": rank, "node_id": node_id,
                "document": node.get("document"), "page": node.get("page"),
                "text": all_node_text(node),
            })
        if qid in AUDIT.MANUAL_REQUIREMENTS:
            requirements = [
                {"id": f"manual_{index}", "label": label, "groups": groups,
                 "kind": "cross_evidence_relation" if not groups else "answer_slot"}
                for index, (label, groups) in enumerate(AUDIT.MANUAL_REQUIREMENTS[qid], 1)
            ]
        else:
            requirements = AUDIT.generic_requirements(query["question"])
        adjudications = [
            adjudicate_requirement(requirement, evidence_nodes, routes, ranking, nodes)
            for requirement in requirements
        ]
        for item in adjudications:
            requirement_rows.append({
                "question_id": qid,
                "question": query["question"],
                "requirement_id": item["requirement"]["id"],
                "requirement_label": item["requirement"]["label"],
                "state": item["state"],
                "supporting_spans": item["supporting_spans"],
                "missing_evidence": item["missing_evidence"],
                "potential_retrieval_actions": item["potential_retrieval_actions"],
                "review_basis": item["reason"],
                "ai_assisted_not_human_gold": True,
            })
        states = [item["state"] for item in adjudications]
        if "missing" in states or "partial" in states or "contradictory" in states:
            answer_state = "insufficient_or_conflicted"
        elif "uncertain" in states:
            answer_state = "uncertain"
        else:
            answer_state = "sufficient_subject_to_semantic_review"
        diagnostics.append({
            "question_id": qid,
            "question": query["question"],
            "question_type": query.get("question_type"),
            "answer_state": answer_state,
            "requirements": adjudications,
            "dense_top10_nodes": evidence_nodes,
            "gold_page_fields": {
                "top10_page_complete": matrix[qid]["top10_page_complete"],
                "top10_region_complete": matrix[qid]["top10_region_complete"],
                "gold_pages_total": matrix[qid]["gold_pages_total"],
            },
            "ai_assisted_not_human_gold": True,
        })
    out.mkdir(parents=True)
    (out / "query_requirement_diagnostic_table.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in requirement_rows), encoding="utf-8"
    )
    (out / "selected_query_full_evidence.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in diagnostics), encoding="utf-8"
    )
    summary = {
        "version": VERSION,
        "target_queries": len(target_ids),
        "sufficient_query_spot_check": len(SAMPLE_SUFFICIENT),
        "selected_queries": len(selected_ids),
        "requirement_rows": len(requirement_rows),
        "answer_state_counts": dict(Counter(row["answer_state"] for row in diagnostics)),
        "requirement_state_counts": dict(Counter(row["state"] for row in requirement_rows)),
        "graph_actions": dict(Counter(
            action["action"]
            for row in requirement_rows
            for action in row["potential_retrieval_actions"]
        )),
        "gold_page_recovery_not_answer_sufficiency": True,
        "retrieval_run": False,
        "new_edges": 0,
        "new_scorer": False,
        "ai_assisted_not_human_gold": True,
        "inputs_sha256": {str(path): digest(path) for path in
                          (QUERIES, MATRIX, NODES, ROUTES, PREVIOUS)},
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False,
                                                   sort_keys=True, indent=2) + "\n",
                                         encoding="utf-8")
    (out / "README.md").write_text(
        f"""# Evidence-State Semantic Adjudication

Version: `{VERSION}`. This is an AI-assisted, non-Gold semantic review of the
10 incomplete/uncertain Queries plus a deterministic spot check of 4 previously
sufficient Queries. It includes full Dense Top-10 node text, requirement-level
spans, states, missing evidence, and existing-Edge action candidates.

No retrieval was run. Unknown Edges remain inspection-only and denied Edges are
never traversal actions. Gold page fields are retained only as offline
comparison metadata.
""",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(run(args.out), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
