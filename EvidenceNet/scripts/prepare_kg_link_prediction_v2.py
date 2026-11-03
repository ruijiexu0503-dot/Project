#!/usr/bin/env python3
"""Freeze the full VL-DocIR KG pilot inputs without running a proposer.

V2 keeps all 7,291 EvidenceNodes, adds only the validated v5 reading subgraph,
preserves legacy semantic edges as noisy context, and freezes the original ANN
candidate pool for later new-endpoint accounting.  It never parses documents,
runs OCR, creates embeddings, or executes a KG model.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any, Iterable

import numpy as np


VERSION = "kg-link-prediction-pilot-v2-20261102"
SPLIT_SEED = "kg-link-prediction-pilot-v1-20261101"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
DEFAULT_READING = Path(
    "/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs/"
    "vldocir-reading-flow-fix-v5-20261102/EvidenceNet/output/"
    "vldocir_reading_import_navigation_v5_20261102"
)
DEFAULT_OUT = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v2_20261102"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path) -> list[dict[str, Any]]:
    with Path(path).open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def node_text(node: dict[str, Any]) -> str:
    return "\n\n".join(
        str(member.get("text", "")).strip()
        for member in node.get("members", [])
        if str(member.get("text", "")).strip()
    )


def split_for_document(document: str) -> str:
    bucket = int(hashlib.sha256((SPLIT_SEED + "\0" + document).encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else ("valid" if bucket < 85 else "test")


def canonical_pair(source: str, target: str) -> tuple[str, str]:
    if source == target:
        raise ValueError("self pair is not a candidate")
    return tuple(sorted((source, target)))


def pair_id(source: str, target: str, prefix: str = "PAIR_") -> str:
    left, right = canonical_pair(source, target)
    return prefix + hashlib.sha256((left + "\0" + right).encode()).hexdigest()[:20]


def entity_record(node: dict[str, Any]) -> dict[str, Any]:
    text = node_text(node)
    return {
        "entity_id": str(node["id"]),
        "document": str(node["document"]),
        "page": node["page"],
        "modality": str(node.get("node_type", "UNKNOWN")),
        "text": text,
        "text_available": bool(text),
        "text_source": "members[].text",
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "member_count": len(node.get("members", [])),
        "source_image_sha256": node.get("source_image_sha256"),
        "source_collection": node.get("source_collection"),
        "document_split": split_for_document(str(node["document"])),
    }


def normalize_baseline_candidates(
    candidates: list[dict[str, Any]], nodes: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    output = []
    for row in candidates:
        source, target = str(row["source"]), str(row["target"])
        if source not in nodes or target not in nodes:
            raise ValueError("baseline candidate endpoint outside entity universe")
        key = canonical_pair(source, target)
        if key in seen:
            raise ValueError("duplicate baseline candidate pair")
        seen.add(key)
        output.append({
            "pair_id": row.get("pair_id") or pair_id(source, target, "ANN_"),
            "source_id": source,
            "target_id": target,
            "canonical_source_id": key[0],
            "canonical_target_id": key[1],
            "retrieval_score": row.get("retrieval_score"),
            "routes": row.get("routes", []),
            "selection_routes": row.get("selection_routes", []),
            "shared_identifiers": row.get("shared_identifiers", []),
            "source_document": nodes[source]["document"],
            "target_document": nodes[target]["document"],
            "candidate_scope": "same_document" if nodes[source]["document"] == nodes[target]["document"] else "cross_document",
            "is_new_to_baseline": False,
            "baseline_name": "frozen_embedding_identifier_candidate_pool_20261022",
        })
    return output


def semantic_record(edge: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source, target = str(edge["source"]), str(edge["target"])
    result = edge.get("model_result") or {}
    anchors = result.get("anchors") or {}
    return {
        "edge_id": pair_id(source, target, "SEM_"),
        "source_id": source,
        "target_id": target,
        "relation_id": "RELATED_OPEN",
        "directed": False,
        "graph_layer": "semantic_noisy_observation",
        "relation_statement": result.get("matched_claim"),
        "basis": result.get("basis"),
        "limitations": result.get("limitation"),
        "source_anchors": anchors.get("A", []),
        "target_anchors": anchors.get("B", []),
        "verification_status": edge.get("status", "MODEL_PROPOSED_NOT_HUMAN_VERIFIED"),
        "context_eligible": True,
        "target_supervision_eligible": False,
        "evidence_propagation_allowed": False,
        "source_document": nodes[source]["document"],
        "target_document": nodes[target]["document"],
        "graph_version": VERSION,
    }


def load_reading_graph(reading_root: Path, node_ids: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any], set[str]]:
    report_path = reading_root / "integration_report.json"
    bounded_path = reading_root / "bounded_nodes.jsonl"
    edge_path = reading_root / "graph/reading_edges.jsonl"
    graph_manifest_path = reading_root / "graph/reading_manifest.json"
    integration_manifest_path = reading_root / "integration_manifest.json"
    for path in (report_path, bounded_path, edge_path, graph_manifest_path, integration_manifest_path):
        if not path.is_file():
            raise ValueError("missing validated reading input: " + str(path))

    integration_manifest = json.loads(integration_manifest_path.read_text())
    for name, expected in integration_manifest.get("files", {}).items():
        if sha(reading_root / name) != expected:
            raise ValueError("changed integration artifact: " + name)
    graph_manifest = json.loads(graph_manifest_path.read_text())
    for name, expected in graph_manifest.get("files", {}).items():
        if sha(reading_root / "graph" / name) != expected:
            raise ValueError("changed reading graph artifact: " + name)

    report = json.loads(report_path.read_text())
    if not report.get("complete") or report.get("navigated_paths") != report.get("directed_edges"):
        raise ValueError("reading integration did not complete")
    bounded = {str(row["id"]) for row in rows(bounded_path)}
    if not bounded or not bounded <= node_ids:
        raise ValueError("validated reading nodes are outside the full EvidenceNode universe")
    edges = rows(edge_path)
    if len(edges) != report.get("directed_edges"):
        raise ValueError("reading edge/report count mismatch")

    directed_keys = set()
    next_pairs, previous_pairs = set(), set()
    output = []
    endpoints = set()
    for edge in edges:
        source, target = str(edge["source"]), str(edge["target"])
        relation = str(edge.get("edge_type", edge.get("type")))
        if source not in bounded or target not in bounded or relation not in {"NEXT", "PREVIOUS"}:
            raise ValueError("invalid validated reading edge")
        key = (source, relation, target)
        if key in directed_keys:
            raise ValueError("duplicate validated reading edge")
        directed_keys.add(key); endpoints.update((source, target))
        (next_pairs if relation == "NEXT" else previous_pairs).add((source, target))
        output.append({
            "edge_id": "READ_" + hashlib.sha256((source + "\0" + relation + "\0" + target).encode()).hexdigest()[:20],
            "source_id": source,
            "target_id": target,
            "relation_id": relation,
            "directed": True,
            "graph_layer": "reading_validated_v5",
            "verification_status": "VALIDATED_READING_ARTIFACT",
            "context_eligible": True,
            "target_supervision_eligible": False,
            "evidence_propagation_allowed": False,
            "cross_page": bool(edge.get("cross_page")),
            "article_id": edge.get("article_id"),
            "decision_id": edge.get("decision_id"),
            "graph_version": VERSION,
        })
    if {(target, source) for source, target in next_pairs} != previous_pairs:
        raise ValueError("NEXT/PREVIOUS inverse mismatch")
    audit = {
        "validated_assignment_nodes": len(bounded),
        "assignment_coverage": len(bounded) / len(node_ids),
        "edge_endpoint_nodes": len(endpoints),
        "endpoint_coverage": len(endpoints) / len(node_ids),
        "next_edges": len(next_pairs),
        "previous_edges": len(previous_pairs),
        "directed_edges": len(edges),
        "cross_page_next": sum(row["relation_id"] == "NEXT" and row["cross_page"] for row in output),
        "missing_reading_is_negative": False,
        "scope": "validated v5 subset only; no inferred ordering for other nodes",
    }
    return output, audit, bounded


def candidate_schema() -> dict[str, Any]:
    required = ["source_id", "target_id", "proposed_relation", "proposer", "model_version",
                "graph_version", "raw_score", "candidate_scope", "is_new_to_baseline"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "EvidenceNet KG endpoint proposal v2",
        "type": "object",
        "required": required,
        "properties": {
            "source_id": {"type": "string", "minLength": 1},
            "target_id": {"type": "string", "minLength": 1},
            "proposed_relation": {"const": "RELATED_OPEN"},
            "proposer": {"enum": ["text_only", "text_graph", "ultra"]},
            "model_version": {"type": "string", "minLength": 1},
            "graph_version": {"const": VERSION},
            "raw_score": {"type": "number"},
            "candidate_scope": {"enum": ["same_document", "cross_document"]},
            "is_new_to_baseline": {"type": "boolean"},
            "rank_within_source": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": True,
    }


def review_scaffold(edge_groups: dict[str, list[dict[str, Any]]], nodes: dict[str, dict[str, Any]], per_group: int):
    public, key = [], []
    for group, values in sorted(edge_groups.items()):
        ordered = sorted(values, key=lambda row: hashlib.sha256((VERSION + str(row.get("task_id", ""))).encode()).hexdigest())
        for edge in ordered[:per_group]:
            source, target = str(edge["source"]), str(edge["target"])
            blind_id = "BLIND_" + hashlib.sha256((group + "\0" + source + "\0" + target).encode()).hexdigest()[:16]
            public.append({
                "blind_id": blind_id,
                "source_id": source,
                "target_id": target,
                "source": {"document": nodes[source]["document"], "page": nodes[source]["page"],
                           "modality": nodes[source].get("node_type", "UNKNOWN"), "text": node_text(nodes[source])[:2400]},
                "target": {"document": nodes[target]["document"], "page": nodes[target]["page"],
                           "modality": nodes[target].get("node_type", "UNKNOWN"), "text": node_text(nodes[target])[:2400]},
                "review_label": None,
                "review_reason": None,
                "allowed_labels": ["accepted", "rejected", "unknown"],
            })
            key.append({"blind_id": blind_id, "legacy_bucket": group, "legacy_task_id": edge.get("task_id"),
                        "legacy_status": edge.get("status")})
    return sorted(public, key=lambda row: row["blind_id"]), sorted(key, key=lambda row: row["blind_id"])


def prepare(source: Path, reading_root: Path, output: Path, review_per_group: int = 24) -> dict[str, Any]:
    source, reading_root, output = Path(source).resolve(), Path(reading_root).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("fresh v2 output required: " + str(output))
    output.mkdir(parents=True, exist_ok=True)
    inputs = {
        "nodes": source / "nodes.jsonl",
        "views": source / "views.jsonl",
        "view_vectors": source / "view_vectors.npy",
        "embedding_manifest": source / "embedding_manifest.json",
        "baseline_candidates": source / "node_candidates.jsonl",
        "related": source / "graph/related.jsonl",
        "review": source / "graph/review.jsonl",
        "rejected": source / "graph/rejected.jsonl",
        "reading_report": reading_root / "integration_report.json",
        "reading_nodes": reading_root / "bounded_nodes.jsonl",
        "reading_edges": reading_root / "graph/reading_edges.jsonl",
        "reading_graph_manifest": reading_root / "graph/reading_manifest.json",
        "reading_integration_manifest": reading_root / "integration_manifest.json",
    }
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise ValueError("missing frozen inputs: " + ", ".join(missing))

    node_values = rows(inputs["nodes"])
    nodes = {str(row["id"]): row for row in node_values}
    if len(nodes) != len(node_values):
        raise ValueError("duplicate EvidenceNode ID")
    entities = [entity_record(nodes[node_id]) for node_id in sorted(nodes)]
    text_ids = {row["entity_id"] for row in entities if row["text_available"]}

    edge_groups = {name: rows(inputs[name]) for name in ("related", "review", "rejected")}
    for values in edge_groups.values():
        for edge in values:
            if edge.get("source") not in nodes or edge.get("target") not in nodes:
                raise ValueError("semantic edge endpoint outside entity universe")
            canonical_pair(str(edge["source"]), str(edge["target"]))
    semantics = [semantic_record(edge, nodes) for edge in edge_groups["related"]]
    semantic_pairs = {canonical_pair(row["source_id"], row["target_id"]) for row in semantics}

    baseline = normalize_baseline_candidates(rows(inputs["baseline_candidates"]), nodes)
    baseline_pairs = {canonical_pair(row["source_id"], row["target_id"]) for row in baseline}
    reading, reading_audit, reading_nodes = load_reading_graph(reading_root, set(nodes))
    reading_split_counts = Counter(split_for_document(nodes[edge["source_id"]]["document"]) for edge in reading)
    reading_audit["directed_edges_by_split"] = dict(reading_split_counts)
    reading_audit["heldout_reading_edge_coverage"] = bool(reading_split_counts.get("valid") or reading_split_counts.get("test"))
    observed = sorted(semantics + reading, key=lambda row: (row["graph_layer"], row["edge_id"]))

    views = rows(inputs["views"])
    vectors = np.load(inputs["view_vectors"], mmap_mode="r")
    if len(views) != vectors.shape[0]:
        raise ValueError("view/vector row mismatch")
    view_nodes = {str(row["node_id"]) for row in views}
    if not view_nodes <= set(nodes):
        raise ValueError("view endpoint outside entity universe")
    primary_ids = text_ids & view_nodes
    baseline_endpoints = {node for pair in baseline_pairs for node in pair}
    if not baseline_endpoints <= primary_ids:
        raise ValueError("frozen baseline endpoint outside the fair comparison universe")
    for entity in entities:
        entity["frozen_view_available"] = entity["entity_id"] in view_nodes
        entity["primary_comparison_eligible"] = entity["entity_id"] in primary_ids
    universe = []
    for entity in entities:
        reason = None
        if not entity["text_available"]:
            reason = "EMPTY_MEMBERS_TEXT"
        elif not entity["frozen_view_available"]:
            reason = "NO_FROZEN_TEXT_VIEW"
        universe.append({"entity_id": entity["entity_id"], "document": entity["document"],
            "document_split": entity["document_split"],
            "text_available": entity["text_available"],
            "frozen_view_available": entity["frozen_view_available"],
            "primary_eligible": entity["primary_comparison_eligible"],
            "exclusion_reason": reason})

    split_lines = {name: [] for name in ("train", "valid", "test", "cross_split_quarantine")}
    split_counts = Counter()
    for edge in semantics:
        source_split = split_for_document(edge["source_document"])
        target_split = split_for_document(edge["target_document"])
        split = source_split if source_split == target_split else "cross_split_quarantine"
        split_counts[split] += 1
        split_lines[split].append(f"{edge['source_id']}\tRELATED_OPEN\t{edge['target_id']}\n")
        split_lines[split].append(f"{edge['target_id']}\tRELATED_OPEN\t{edge['source_id']}\n")
    for edge in reading:
        document = nodes[edge["source_id"]]["document"]
        if nodes[edge["target_id"]]["document"] != document:
            raise ValueError("validated reading edge crosses document")
        split_lines[split_for_document(document)].append(
            f"{edge['source_id']}\t{edge['relation_id']}\t{edge['target_id']}\n")

    protocol = {
        "version": VERSION,
        "entity_universe": {"all_nodes": len(nodes),
                            "all_text_bearing_nodes": len(text_ids),
                            "frozen_view_nodes": len(view_nodes),
                            "primary_fair_comparison_nodes": len(primary_ids),
                            "empty_text_nodes": len(nodes) - len(text_ids),
                            "text_nodes_without_frozen_view": len(text_ids - view_nodes)},
        "prediction_task": "endpoint prediction for RELATED_OPEN",
        "proposers": ["text_only", "text_graph", "ultra"],
        "common_candidate_space": {
            "source_nodes": "text-bearing nodes with a frozen baseline view in the active document split",
            "target_nodes": "text-bearing nodes with a frozen baseline view in the same active document split",
            "exclude_self": True,
            "exclude_observed_related_pairs": True,
            "missing_reading_edge_is_negative": False,
            "same_and_cross_document_targets_allowed_within_split": True,
        },
        "budget": {"top_k_per_source": 20, "global_verifier_budget": len(baseline),
                   "budget_basis": "actual frozen baseline candidate count"},
        "baseline": {"name": "frozen 2026-10-22 embedding/lexical/identifier pool",
                     "pairs": len(baseline), "membership_file": "baseline_candidate_pairs.jsonl",
                     "new_definition": "canonical pair absent from baseline_candidate_pairs.jsonl"},
        "score_policy": "Raw scores are proposer-specific and must not be added or compared across models.",
        "truth_policy": {"legacy_related_is_gold": False, "unlabelled_is_negative": False,
                         "candidate_recall_available": False,
                         "reason": "independent reviewed candidate universe not yet completed"},
        "reading_ablation_boundary": {
            "validated_edges_by_split": dict(reading_split_counts),
            "heldout_reading_edge_coverage": reading_audit["heldout_reading_edge_coverage"],
            "claim_allowed": "bounded development plumbing/ablation only until validated reading edges exist in held-out documents",
        },
        "execution": {"candidate_generation_run": False, "kg_model_run": False,
                      "document_parsing_run": False, "ocr_run": False, "embedding_run": False},
    }

    write_jsonl(output / "entities_with_text.jsonl", entities)
    write_jsonl(output / "candidate_universe.jsonl", universe)
    write_jsonl(output / "proposal_sources.jsonl", [row for row in universe if row["primary_eligible"]])
    write_jsonl(output / "baseline_candidate_pairs.jsonl", baseline)
    write_jsonl(output / "noisy_semantic_edges.jsonl", semantics)
    write_jsonl(output / "validated_reading_edges.jsonl", reading)
    write_jsonl(output / "observed_context_edges.jsonl", observed)
    review_public, review_key = review_scaffold(edge_groups, nodes, review_per_group)
    write_jsonl(output / "blind_review_pairs.jsonl", review_public)
    write_jsonl(output / "blind_review_key.jsonl", review_key)
    write_json(output / "candidate.schema.json", candidate_schema())
    write_json(output / "experiment_protocol.json", protocol)
    for split, values in split_lines.items():
        (output / f"context_triples_{split}.tsv").write_text("".join(values))

    modality = Counter(row["modality"] for row in entities)
    modality_text = Counter(row["modality"] for row in entities if row["text_available"])
    documents = {row["document"]: row["document_split"] for row in entities}
    semantic_degrees = Counter()
    for edge in semantics:
        semantic_degrees.update((edge["source_id"], edge["target_id"]))
    degree_values = list(semantic_degrees.values())
    report = {
        "version": VERSION,
        "scope": "full frozen VL-DocIR development corpus; preparation only",
        "corpus": {"documents": len({row["document"] for row in entities}),
                   "pages": len({(row["document"], str(row["page"])) for row in entities}),
                   "nodes": len(entities), "modalities": dict(modality)},
        "text": {"source": "members[].text", "available": len(text_ids),
                 "empty": len(nodes) - len(text_ids),
                 "coverage": len(text_ids) / len(nodes),
                 "by_modality": {name: {"nodes": modality[name], "available": modality_text[name]}
                                 for name in sorted(modality)}},
        "reading": reading_audit,
        "semantic": {"noisy_related_edges": len(semantics), "endpoint_nodes": len(semantic_degrees),
                     "isolated_from_semantic": len(nodes) - len(semantic_degrees),
                     "endpoint_coverage": len(semantic_degrees) / len(nodes),
                     "mean_degree_over_endpoints": statistics.mean(degree_values) if degree_values else 0.0,
                     "ground_truth": False},
        "baseline": {"candidate_pairs": len(baseline), "endpoint_nodes": len({node for pair in baseline_pairs for node in pair}),
                     "all_endpoints_known": True, "exhaustive_ann_ranking": False,
                     "interpretation": "fixed-budget selected pool, not every possible ANN neighbour"},
        "frozen_embeddings": {"views": len(views), "view_node_coverage": len(view_nodes),
                              "vectors_shape": list(vectors.shape), "vectors_dtype": str(vectors.dtype),
                              "text_bearing_nodes_without_view": len(text_ids - view_nodes),
                              "primary_fair_comparison_nodes": len(primary_ids),
                              "recomputed": False},
        "split": {"seed": SPLIT_SEED, "unit": "whole document",
                  "document_counts": dict(Counter(documents.values()))},
        "observed_context": {"semantic_edges": len(semantics), "directed_reading_edges": len(reading),
                             "semantic_pairs_also_in_baseline": len(semantic_pairs & baseline_pairs)},
        "review": {"blind_pairs": len(review_public), "completed": 0, "candidate_recall_available": False},
        "protocol": protocol,
    }
    report["split"]["noisy_semantic_edge_counts"] = dict(split_counts)
    write_json(output / "audit.json", report)
    write_report(output / "REPORT.md", report)

    output_files = sorted(path for path in output.iterdir() if path.is_file())
    manifest = {
        "version": VERSION,
        "inputs": {name: {"path": str(path), "sha256": sha(path)} for name, path in inputs.items()},
        "outputs": {path.name: sha(path) for path in output_files},
        "code": {str(Path(__file__).resolve()): sha(Path(__file__).resolve())},
    }
    write_json(output / "manifest.json", manifest)
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    corpus, text, reading = report["corpus"], report["text"], report["reading"]
    semantic, baseline = report["semantic"], report["baseline"]
    lines = [
        "# EvidenceNet KG link-prediction pilot v2 preparation", "",
        "No model, OCR, parsing, node generation, or embedding computation was run.", "",
        "## Frozen scope", "",
        f"- Corpus: {corpus['documents']} documents, {corpus['pages']} pages, {corpus['nodes']} EvidenceNodes.",
        f"- Text from `members[].text`: {text['available']}/{corpus['nodes']} ({text['coverage']:.2%}); {text['empty']} have no text.",
        f"- Fair frozen-baseline comparison universe: {report['frozen_embeddings']['primary_fair_comparison_nodes']} nodes; {report['frozen_embeddings']['text_bearing_nodes_without_view']} additional text-bearing nodes have no frozen view and remain in the graph but outside the primary comparison.",
        f"- Original selected ANN/lexical/identifier pool: {baseline['candidate_pairs']} canonical pairs; it is not an exhaustive ANN ranking.", "",
        "## Observed graph", "",
        f"- Noisy `RELATED_OPEN`: {semantic['noisy_related_edges']} edges over {semantic['endpoint_nodes']} endpoint nodes; never treated as gold.",
        f"- Validated v5 reading subset: {reading['validated_assignment_nodes']} assigned nodes, {reading['next_edges']} NEXT, {reading['previous_edges']} PREVIOUS, including {reading['cross_page_next']} cross-page NEXT.",
        f"- Reading directed edges by frozen document split: {json.dumps(reading['directed_edges_by_split'], sort_keys=True)}; held-out reading coverage is {reading['heldout_reading_edge_coverage']}.",
        "- Nodes outside the validated reading subset receive no inferred reading edges; missing reading is not a negative label.", "",
        "## Frozen comparison protocol", "",
        "Text-only, Text+Graph, and ULTRA must use the same text-bearing source/target universe within each document split, exclude self and already-observed semantic pairs, emit TopK=20 per source, and share the same global verifier budget.",
        "A proposal is new only when its canonical pair is absent from `baseline_candidate_pairs.jsonl`. Raw scores remain proposer-specific.", "",
        "## Truth boundary", "",
        "The exported review scaffold is unfinished. Candidate recall and verified precision must not be reported until independent review labels exist.",
    ]
    path.write_text("\n".join(lines) + "\n")


def check(output: Path) -> None:
    output = Path(output).resolve()
    manifest = json.loads((output / "manifest.json").read_text())
    for item in manifest["inputs"].values():
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("changed v2 input: " + item["path"])
    for name, expected in manifest["outputs"].items():
        if sha(output / name) != expected:
            raise ValueError("changed v2 output: " + name)
    for raw, expected in manifest["code"].items():
        if sha(Path(raw)) != expected:
            raise ValueError("changed v2 preparation code: " + raw)
    print("KG_LINK_PREDICTION_V2_PREPARATION_OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    prep.add_argument("--reading-integration", type=Path, default=DEFAULT_READING)
    prep.add_argument("--out", type=Path, default=DEFAULT_OUT)
    prep.add_argument("--review-per-group", type=int, default=24)
    verify = sub.add_parser("check")
    verify.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.command == "prepare":
        print(json.dumps(prepare(args.source, args.reading_integration, args.out, args.review_per_group), indent=2))
    else:
        check(args.out)


if __name__ == "__main__":
    main()
