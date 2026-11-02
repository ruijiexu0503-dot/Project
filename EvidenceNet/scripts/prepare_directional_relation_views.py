#!/usr/bin/env python3
"""Build query-independent directed retrieval views over frozen G0 edges."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
VERSION = "directional_relation_v1_20261101"
DEFAULT_OUT = ROOT / "EvidenceNet/output/directional_relation_pilot_v1_20261101"
EDGE_RECORDS = ROOT / "EvidenceNet/output/vldocir_edge_embedding_v1_20261025/edge_records.jsonl"
RELATED = ROOT / "migration/vldocir-edge-20261022/results/graph/related.jsonl"
NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
ROLE_AUDIT = ROOT / "EvidenceNet/output/query_edge_repair_v2_20261023/role_audit.json"
TASKS = ROOT / "EvidenceNet/output/query_adaptive_evidence_v2_20261030/tasks.jsonl"
KG_AUDIT = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v1_20261101/audit.json"
HF_MANIFEST = ROOT / "EvidenceNet/output/hf_evidence_comparison_v1_20261031/eval_manifest.json"
OLD_EDGE_STATUS = ROOT / "EvidenceNet/output/vldocir_edge_embedding_v1_20261025/status.json"
FROZEN_VIEWS = ROOT / "migration/vldocir-edge-20261022/results/views.jsonl"
FROZEN_VIEW_VECTORS = ROOT / "migration/vldocir-edge-20261022/results/view_vectors.npy"
FROZEN_ENCODING = ROOT / "migration/vldocir-edge-20261022/results/embedding_manifest.json"
FROZEN_QUERY_SCORES = ROOT / "migration/vldocir-edge-20261022/results/search/query_window_scores.npy"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def endpoint_text(endpoint: dict[str, Any]) -> str:
    return "\n\n".join(span["text"] for span in endpoint.get("spans", []) if span.get("text")).strip()


def validate_span(span: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> None:
    node = nodes[span["node_id"]]
    members = {member["id"]: member for member in node["members"]}
    member = members[span["member_id"]]
    text = member.get("text", "")
    start, end = span["char_start"], span["char_end"]
    if text[start:end] != span["text"]:
        raise ValueError("anchor offset mismatch: " + span["span_id"])
    if hashlib.sha256(text.encode()).hexdigest() != span["member_sha256"]:
        raise ValueError("anchor member hash mismatch: " + span["span_id"])


def relation_family(legacy: dict[str, Any]) -> str:
    basis = (legacy.get("model_result") or {}).get("basis")
    return basis if basis in {"SAME_SPECIFIC_SUBJECT", "CLAIM_CORRESPONDENCE"} else "RELATED"


def build_direction(record: dict[str, Any], legacy: dict[str, Any], source_side: str) -> dict[str, Any]:
    target_side = "B" if source_side == "A" else "A"
    source, target = record["endpoints"][source_side], record["endpoints"][target_side]
    source_text, target_text = endpoint_text(source), endpoint_text(target)
    result = legacy.get("model_result") or {}
    statement = (result.get("matched_claim") or "").strip()
    limitation = (result.get("limitation") or "").strip()
    shared = result.get("shared_identity") or {}
    shared_subject = (shared.get("canonical_name") or statement or None)
    family = relation_family(legacy)
    status = "proposal" if source_text and target_text and statement else "insufficient_anchor"
    direction = source_side + "_to_" + target_side
    r1 = f"Relation family: {family}. Navigate from the source node to its linked target node."
    r2 = statement + ((" Qualifiers: " + limitation) if limitation else "")
    r3 = ("Known source original evidence:\n" + source_text +
          "\n\nRetrieve the linked target original evidence:\n" + target_text +
          (("\n\nSupported relation: " + statement) if statement else "") +
          (("\nQualifiers: " + limitation) if limitation else ""))
    r4 = r1 + "\n\n" + r3
    r5 = "Target original evidence:\n" + target_text
    return {
        "view_id": f"{record['edge_id']}:{direction}", "edge_id": record["edge_id"],
        "source_node_id": source["node_id"], "target_node_id": target["node_id"],
        "source_page": [source["document_id"], str(source["page_number"])],
        "target_page": [target["document_id"], str(target["page_number"])],
        "direction": direction, "relation_family": family, "shared_subject": shared_subject,
        "known_source_contribution": source_text, "target_contribution": target_text,
        "directional_retrieval_text": r3, "relation_statement": statement,
        "qualifiers": [limitation] if limitation else [],
        "source_anchor_ids": [span["span_id"] for span in source.get("spans", [])],
        "target_anchor_ids": [span["span_id"] for span in target.get("spans", [])],
        "verifier_status": legacy.get("status", "MODEL_PROPOSED_NOT_HUMAN_VERIFIED"),
        "semantic_truth_verified": False, "parent_edge_sha256": digest(legacy),
        "representation_version": VERSION, "generation_method": "deterministic_grounded_template_v1",
        "status": status, "representations": {"R1_type": r1, "R2_open": r2,
            "R3_directional": r3, "R4_hybrid": r4, "R5_target": r5},
    }


def prepare(out: Path = DEFAULT_OUT) -> dict[str, Any]:
    if out.exists() and any(out.iterdir()):
        raise ValueError("output must be new or empty: " + str(out))
    out.mkdir(parents=True, exist_ok=True)
    graph = rows(EDGE_RECORDS)
    legacy = {row["task_id"]: row for row in rows(RELATED)}
    nodes_list = rows(NODES); nodes = {node["id"]: node for node in nodes_list}
    audit = json.loads(ROLE_AUDIT.read_text())
    expected = {edge_id for edge_id, item in audit["edges"].items() if item["route"] == "semantic"}
    if len(expected) != 187 or {row["edge_id"] for row in graph} != expected:
        raise ValueError("frozen G0 semantic edge identity mismatch")
    views = []
    for record in graph:
        if record["edge_id"] not in legacy:
            raise ValueError("missing parent legacy edge: " + record["edge_id"])
        for side in ("A", "B"):
            for span in record["endpoints"][side].get("spans", []):
                validate_span(span, nodes)
        views.extend((build_direction(record, legacy[record["edge_id"]], "A"),
                      build_direction(record, legacy[record["edge_id"]], "B")))
    if len({view["view_id"] for view in views}) != 2 * len(graph):
        raise ValueError("directed view identity mismatch")
    jsonl(out / "edges_with_views.jsonl", views)
    jsonl(out / "queries.jsonl", ({"question_id": row["question_id"], "question": row["question"]}
                                   for row in rows(TASKS)))
    protocol = {
        "version": VERSION, "graph_version": "vldocir_G0_semantic_20261025",
        "graph_edges": len(graph), "directed_views": len(views),
        "arms": ["R0_dense", "R1_type", "R2_open", "R3_directional", "R4_hybrid", "R5_target"],
        "reading": "off; current audited artifacts cover only 9/7291 nodes",
        "offline_generation_reads_queries_or_gold": False,
        "online_route_or_stop_llm_calls": 0,
        "seed_nodes": 10, "max_new_targets": [5, 10], "hop_limit": 1,
        "primary_route_score": "cosine(query_vector, directed_view_vector)",
        "tie_break": "(-score, seed_rank, edge_id, target_node_id)",
        "R0": "next dense nodes outside seed set at matched target exposure",
        "final_source_ranker": "separate shared BGE reranker; relation score never becomes page bonus",
        "development_scope": "24-query / 518-page inspected pilot",
    }
    write(out / "protocol.json", protocol)
    kg_audit = json.loads(KG_AUDIT.read_text())
    hf_manifest = json.loads(HF_MANIFEST.read_text())
    audit_report = {
        "branch_expected": "feature/evidence-edges",
        "graph": {"historical_related": len(legacy), "semantic_G0": len(graph),
                  "semantic_endpoint_nodes": len({v for r in graph for v in (r["source_node_id"], r["target_node_id"])}),
                  "all_nodes": len(nodes)},
        "reading": kg_audit["reading"],
        "frozen_node_vectors": {"views": len(rows(FROZEN_VIEWS)),
                                "view_vectors_sha256": sha(FROZEN_VIEW_VECTORS),
                                "embedding_manifest_sha256": sha(FROZEN_ENCODING)},
        "frozen_query_window_scores_sha256": sha(FROZEN_QUERY_SCORES),
        "existing_edge_embedding_status": json.loads(OLD_EDGE_STATUS.read_text()),
        "embedding_instruction": "Instruct: Rank reachable evidence-graph routes useful for answering the question\\nQuery: ",
        "page_aggregation": hf_manifest["tie_policy"],
        "H0_historical_metrics_checked": hf_manifest["historical_H0_metrics_checked"],
        "missing_local_required_artifacts": [],
        "conclusion": "G0 and anchors are local; reading remains coverage-limited and is disabled for primary arms."
    }
    write(out / "audit.json", audit_report)
    source_paths = [EDGE_RECORDS, RELATED, NODES, ROLE_AUDIT, TASKS, KG_AUDIT, HF_MANIFEST, OLD_EDGE_STATUS]
    manifest = {"version": VERSION, "sources": {str(path.resolve()): sha(path) for path in source_paths},
                "audit_only_sources": {str(path.resolve()): sha(path) for path in
                    (FROZEN_VIEWS, FROZEN_VIEW_VECTORS, FROZEN_ENCODING, FROZEN_QUERY_SCORES)},
                "outputs": {name: sha(out / name) for name in ("edges_with_views.jsonl", "queries.jsonl", "protocol.json", "audit.json")},
                "code_sha256": sha(Path(__file__)),
                "counts": {"eligible_edges": len(graph), "created_views": len(views),
                           "skipped_views": sum(v["status"] != "proposal" for v in views),
                           "families": dict(Counter(v["relation_family"] for v in views)),
                           "directions": dict(Counter(v["direction"] for v in views))}}
    write(out / "relation_representation_manifest.json", manifest)
    write(out / "status.json", {"stage": "views_prepared", "complete": True,
                                 "edges": len(graph), "directed_views": len(views)})
    return {"output": str(out), **manifest["counts"]}


def check(out: Path = DEFAULT_OUT) -> None:
    manifest = json.loads((out / "relation_representation_manifest.json").read_text())
    for raw, expected in manifest["sources"].items():
        path = Path(raw)
        if not path.exists():
            marker = "/Project/"
            if marker not in raw: raise ValueError("missing source: " + raw)
            path = ROOT / raw.split(marker, 1)[1]
        if sha(path) != expected: raise ValueError("changed source: " + str(path))
    for name, expected in manifest["outputs"].items():
        if sha(out / name) != expected: raise ValueError("changed output: " + name)
    print("DIRECTIONAL_RELATION_VIEWS_OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "check"))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.stage == "prepare": print(json.dumps(prepare(args.out), indent=2))
    else: check(args.out)


if __name__ == "__main__": main()
