#!/usr/bin/env python3
"""Prepare a provenance-preserving KG link-prediction pilot for EvidenceNet.

This module deliberately does not turn model-proposed semantic edges into gold
labels.  It exports an auditable noisy observation graph, leakage-safe document
splits, a blind-review scaffold, and a strict candidate interchange contract.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any, Iterable


VERSION = "kg-link-prediction-pilot-v1-20261101"
OFFICIAL_MODELS = {
    "ULTRA": {
        "repository": "https://github.com/DeepGraphLearning/ULTRA",
        "commit": "427966ad8ed60420eef034063d44f3153addff90",
        "checkpoint": "ckpts/ultra_4g.pth",
        "checkpoint_sha256": "48a046e708adf5632d87c30eacae01f5f51466b2301effdc2cb42358d22854e0",
    },
    "TRIX_entity": {
        "repository": "https://github.com/yuchengz99/TRIX",
        "commit": "7596e14eefefe89e61396205a0550172cadeddb0",
        "checkpoint": "entity_prediction.pth",
        "checkpoint_sha256": "8f6e7266093c2d15ad88d41e9825e4b327171143543cf060cfee907d9a890342",
    },
    "TRIX_relation": {
        "repository": "https://github.com/yuchengz99/TRIX",
        "commit": "7596e14eefefe89e61396205a0550172cadeddb0",
        "checkpoint": "relation_prediction.pth",
        "checkpoint_sha256": "5d15d0b50c9df4e4ffeccda7f30aa941231126fbf660b6daeea1ba96dfb249e5",
    },
}
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
DEFAULT_READING = ROOT / "migration/horeka_verified_results_20261028_2MN9rZZ0/reading"
DEFAULT_OUT = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v1_20261101"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _write_jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def _node_text_sha(node: dict[str, Any]) -> str:
    text = "\n".join(str(m.get("text", "")) for m in node.get("members", []))
    return hashlib.sha256(text.encode()).hexdigest()


def _split_for_document(document: str) -> str:
    # Stable 70/15/15 buckets. This assigns whole documents, never individual edges.
    bucket = int(hashlib.sha256((VERSION + "\0" + document).encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 70 else ("valid" if bucket < 85 else "test")


def _edge_id(source: str, target: str, task_id: str = "") -> str:
    lo, hi = sorted((source, target))
    return "KGE_" + hashlib.sha256(f"{lo}\0{hi}\0{task_id}".encode()).hexdigest()[:20]


def _reading_audit(roots: list[Path], node_ids: set[str]) -> dict[str, Any]:
    artifacts, all_assignments, all_edges = [], set(), []
    for root in roots:
        manifest_path = root / "article_graph_manifest.json"
        item: dict[str, Any] = {"root": str(root.resolve()), "manifest_present": manifest_path.is_file()}
        if not manifest_path.is_file():
            item["usable"] = False
            item["reason"] = "missing_article_graph_manifest"
            artifacts.append(item)
            continue
        manifest = json.loads(manifest_path.read_text())
        item.update(ready_for_downstream=bool(manifest.get("ready_for_downstream")),
                    reading_ready=bool(manifest.get("reading_ready")))
        mismatches = []
        for name, expected in manifest.get("files", {}).items():
            candidate = root / name
            if not candidate.is_file() or _sha(candidate) != expected:
                mismatches.append(name)
        assignment_path, edge_path = root / "article_assignments.jsonl", root / "reading_edges.jsonl"
        assignments = _rows(assignment_path) if assignment_path.is_file() else []
        edges = _rows(edge_path) if edge_path.is_file() else []
        assigned = {str(a.get("node_id")) for a in assignments if a.get("node_id")}
        all_assignments |= assigned
        all_edges.extend(edges)
        item.update(usable=not mismatches and item["ready_for_downstream"] and item["reading_ready"],
                    checksum_mismatches=mismatches, assignments=len(assignments), next_edges=len(edges),
                    assignments_matching_evidence_nodes=len(assigned & node_ids),
                    page_local_edges=sum(1 for e in edges if e.get("source_page") == e.get("target_page")))
        artifacts.append(item)
    endpoints = {str(e.get(k)) for e in all_edges for k in ("source", "target") if e.get(k)}
    overlap = all_assignments & node_ids
    return {
        "artifacts": artifacts,
        "artifact_count": len(artifacts),
        "assignments": len(all_assignments),
        "next_edges": len(all_edges),
        "evidence_node_assignment_overlap": len(overlap),
        "evidence_node_coverage": len(overlap) / len(node_ids) if node_ids else 0.0,
        "edge_endpoint_overlap": len(endpoints & node_ids),
        "complete_for_evidence_corpus": all_assignments == node_ids,
        "import_decision": "eligible_for_backbone_import" if all_assignments == node_ids else "coverage_limited_do_not_mark_global_ready",
        "known_limitation": "Audited artifacts may be page-local and do not establish cross-page reading order.",
    }


def _validate_semantic_edges(edges: list[dict[str, Any]], node_ids: set[str]) -> None:
    for edge in edges:
        if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
            raise ValueError(f"semantic edge has unknown endpoint: {edge.get('task_id')}")
        if edge.get("source") == edge.get("target"):
            raise ValueError(f"semantic self edge: {edge.get('task_id')}")


def _semantic_record(edge: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source, target = edge["source"], edge["target"]
    result = edge.get("model_result") or {}
    anchors = result.get("anchors") or {}
    return {
        "edge_id": _edge_id(source, target, str(edge.get("task_id", ""))),
        "source_id": source,
        "target_id": target,
        "source_document": nodes[source]["document"],
        "target_document": nodes[target]["document"],
        "relation_id": "RELATED_OPEN",
        "relation_statement": result.get("matched_claim"),
        "basis": result.get("basis"),
        "limitations": result.get("limitation"),
        "source_anchors": anchors.get("A", []),
        "target_anchors": anchors.get("B", []),
        "proposer": "legacy_semantic_edge_pipeline",
        "model_version": "legacy_manifest_pinned",
        "graph_version": VERSION,
        "raw_score": None,
        "candidate_scope": "cross_document" if nodes[source]["document"] != nodes[target]["document"] else "same_document",
        "is_new_to_baseline": None,
        "verification_status": edge.get("status", "MODEL_PROPOSED_NOT_HUMAN_VERIFIED"),
        "supervision_eligible": False,
        "evidence_propagation_allowed": False,
    }


def _semantic_audit(nodes: dict[str, dict[str, Any]], edge_groups: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    related = edge_groups["related"]
    degrees = Counter()
    bases = Counter()
    anchored = 0
    cross = 0
    for edge in related:
        degrees.update((edge["source"], edge["target"]))
        result = edge.get("model_result") or {}
        bases[result.get("basis") or "UNKNOWN"] += 1
        anchors = result.get("anchors") or {}
        anchored += int(bool(anchors.get("A")) and bool(anchors.get("B")))
        cross += int(nodes[edge["source"]]["document"] != nodes[edge["target"]]["document"])
    values = sorted(degrees.values())
    return {
        "edge_counts": {name: len(rows) for name, rows in edge_groups.items()},
        "related_statuses": dict(Counter(e.get("status", "MISSING") for e in related)),
        "related_bases": dict(bases),
        "related_with_two_sided_anchors": anchored,
        "related_cross_document": cross,
        "related_same_document": len(related) - cross,
        "endpoint_nodes": len(degrees),
        "isolated_nodes": len(nodes) - len(degrees),
        "endpoint_coverage": len(degrees) / len(nodes) if nodes else 0.0,
        "degree": {
            "max": max(values, default=0),
            "mean_over_endpoints": statistics.mean(values) if values else 0.0,
            "median_over_endpoints": statistics.median(values) if values else 0.0,
        },
        "truth_policy": "All legacy semantic decisions remain noisy observations; none are human gold.",
    }


def _review_text(node: dict[str, Any], limit: int = 2400) -> str:
    text = "\n\n".join(str(member.get("text", "")) for member in node.get("members", []) if member.get("text"))
    return text[:limit]


def _review_scaffold(edge_groups: dict[str, list[dict[str, Any]]], nodes: dict[str, dict[str, Any]], per_group: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output, key = [], []
    for group, edges in edge_groups.items():
        ordered = sorted(edges, key=lambda e: hashlib.sha256((VERSION + str(e.get("task_id", ""))).encode()).hexdigest())
        for edge in ordered[:per_group]:
            record = _semantic_record(edge, nodes)
            blind_id = "BLIND_" + hashlib.sha256(record["edge_id"].encode()).hexdigest()[:16]
            source_node, target_node = nodes[record["source_id"]], nodes[record["target_id"]]
            output.append({
                "blind_id": blind_id,
                "source_id": record["source_id"], "target_id": record["target_id"],
                "proposed_relation": record["relation_statement"],
                "candidate_scope": record["candidate_scope"],
                "source": {"document": source_node["document"], "page": source_node["page"],
                           "modality": source_node.get("node_type", "UNKNOWN"),
                           "text": _review_text(source_node), "text_sha256": _node_text_sha(source_node)},
                "target": {"document": target_node["document"], "page": target_node["page"],
                           "modality": target_node.get("node_type", "UNKNOWN"),
                           "text": _review_text(target_node), "text_sha256": _node_text_sha(target_node)},
                "review_label": None,
                "review_reason": None,
                "allowed_labels": ["accepted", "rejected", "unknown"],
            })
            key.append({"blind_id": blind_id, "proposer_bucket": group, "legacy_task_id": edge.get("task_id"),
                        "legacy_status": edge.get("status"), "edge_id": record["edge_id"]})
    return (sorted(output, key=lambda row: row["blind_id"]),
            sorted(key, key=lambda row: row["blind_id"]))


def _candidate_schema() -> dict[str, Any]:
    required = ["source_id", "target_id", "proposed_relation", "proposer", "model_version",
                "graph_version", "raw_score", "candidate_scope", "is_new_to_baseline"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "EvidenceNet KG endpoint proposal",
        "type": "object", "required": required,
        "properties": {
            "source_id": {"type": "string", "minLength": 1},
            "target_id": {"type": "string", "minLength": 1},
            "proposed_relation": {"type": ["string", "null"]},
            "proposer": {"type": "string", "minLength": 1},
            "model_version": {"type": "string", "minLength": 1},
            "graph_version": {"type": "string", "minLength": 1},
            "raw_score": {"type": ["number", "null"]},
            "candidate_scope": {"enum": ["same_document", "cross_document", "restricted_entity_pool", "all_entities"]},
            "is_new_to_baseline": {"type": ["boolean", "null"]},
        },
        "additionalProperties": True,
    }


def prepare(source: Path, output: Path, reading_roots: list[Path], review_per_group: int) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output must be new or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    paths = {"nodes": source / "nodes.jsonl",
             "related": source / "graph/related.jsonl",
             "review": source / "graph/review.jsonl",
             "rejected": source / "graph/rejected.jsonl"}
    nodes_list = _rows(paths["nodes"])
    nodes = {str(row["id"]): row for row in nodes_list}
    if len(nodes) != len(nodes_list):
        raise ValueError("duplicate node id")
    edge_groups = {name: _rows(paths[name]) for name in ("related", "review", "rejected")}
    for edges in edge_groups.values():
        _validate_semantic_edges(edges, set(nodes))

    entities = [{"entity_id": node_id, "document": row["document"], "page": row["page"],
                 "modality": row.get("node_type", "UNKNOWN"), "original_text_sha256": _node_text_sha(row),
                 "source_image_sha256": row.get("source_image_sha256"), "source_collection": row.get("source_collection")}
                for node_id, row in sorted(nodes.items())]
    observed = [_semantic_record(edge, nodes) for edge in edge_groups["related"]]
    split_counts = Counter()
    triples: dict[str, list[str]] = {name: [] for name in ("train", "valid", "test", "cross_split_quarantine")}
    split_records = []
    for record in observed:
        source_split = _split_for_document(record["source_document"])
        target_split = _split_for_document(record["target_document"])
        split = source_split if source_split == target_split else "cross_split_quarantine"
        split_counts[split] += 1
        split_records.append({"edge_id": record["edge_id"], "source_split": source_split,
                              "target_split": target_split, "assigned_split": split})
        # RELATED_OPEN is symmetric; inverse materialization occurs only after split assignment.
        triples[split].append(f"{record['source_id']}\tRELATED_OPEN\t{record['target_id']}\n")
        triples[split].append(f"{record['target_id']}\tRELATED_OPEN\t{record['source_id']}\n")

    _write_jsonl(output / "entities.jsonl", entities)
    _write_jsonl(output / "noisy_observed_edges.jsonl", observed)
    _write_jsonl(output / "split_assignments.jsonl", split_records)
    review_pairs, review_key = _review_scaffold(edge_groups, nodes, review_per_group)
    _write_jsonl(output / "blind_review_pairs.jsonl", review_pairs)
    _write_jsonl(output / "blind_review_key.jsonl", review_key)
    _write_json(output / "candidate.schema.json", _candidate_schema())
    for split, lines in triples.items():
        (output / f"triples_{split}.tsv").write_text("".join(lines))

    documents = Counter(str(node["document"]) for node in nodes_list)
    modalities = Counter(str(node.get("node_type", "UNKNOWN")) for node in nodes_list)
    report = {
        "version": VERSION,
        "scope": "development selected-corpus graph preparation; not an official full-corpus KG result",
        "nodes": len(nodes), "documents": len(documents), "pages": len({(n["document"], n["page"]) for n in nodes_list}),
        "modalities": dict(modalities),
        "semantic": _semantic_audit(nodes, edge_groups),
        "reading": _reading_audit(reading_roots, set(nodes)),
        "split": {
            "unit": "whole document", "seed": VERSION, "target_ratio": {"train": .70, "valid": .15, "test": .15},
            "document_counts": dict(Counter(_split_for_document(doc) for doc in documents)),
            "undirected_edge_counts": dict(split_counts),
            "cross_split_policy": "quarantine; never use as train observations or evaluation truth",
            "inverse_policy": "assign original edge first, then materialize symmetric reverse in the same split",
        },
        "supervision": {
            "legacy_edges_are_gold": False,
            "unlabeled_pairs_are_negative": False,
            "review_pairs": review_per_group * len(edge_groups),
            "accepted_edges_file": None,
        },
        "model_readiness": {
            "generic_directed_tsv": True,
            "ultra_official_runtime_executed": False,
            "trix_checkpoint_confirmed": True,
            "official_artifacts": OFFICIAL_MODELS,
            "local_runtime_packaged": False,
            "reason": "Official repositories and checkpoint hashes are pinned; runtime remains separate from corpus preparation and awaits reviewed truth.",
        },
    }
    _write_json(output / "audit.json", report)
    _write_report(output / "REPORT.md", report)
    output_files = sorted(p for p in output.iterdir() if p.is_file())
    manifest = {
        "version": VERSION,
        "inputs": {str(path.resolve()): _sha(path) for path in paths.values()},
        "reading_inputs": {str((root / "article_graph_manifest.json").resolve()): _sha(root / "article_graph_manifest.json")
                           for root in reading_roots if (root / "article_graph_manifest.json").is_file()},
        "outputs": {path.name: _sha(path) for path in output_files},
        "code_sha256": _sha(Path(__file__)),
    }
    _write_json(output / "manifest.json", manifest)
    return report


def _write_report(path: Path, report: dict[str, Any]) -> None:
    sem, read, split = report["semantic"], report["reading"], report["split"]
    text = "# EvidenceNet KG link-prediction preparation\n\n"
    text += f"Scope: {report['scope']}\n\n"
    text += "## Structural audit\n\n"
    text += f"- Nodes: {report['nodes']}; documents: {report['documents']}; pages: {report['pages']}.\n"
    text += f"- Legacy proposed RELATED edges: {sem['edge_counts']['related']}; endpoint coverage: {sem['endpoint_coverage']:.2%}; isolated nodes: {sem['isolated_nodes']}.\n"
    text += f"- Two-sided source anchors: {sem['related_with_two_sided_anchors']}/{sem['edge_counts']['related']}.\n"
    text += f"- Reading assignment coverage: {read['evidence_node_coverage']:.2%}; decision: `{read['import_decision']}`.\n\n"
    text += "## Leakage and truth policy\n\n"
    text += "Legacy semantic edges are noisy model observations, not gold. Unlabelled pairs are unknown, not negatives. "
    text += "Documents are assigned atomically to train/valid/test; cross-split edges are quarantined before inverse materialization.\n\n"
    text += "## Split audit\n\n"
    text += f"- Documents: `{json.dumps(split['document_counts'], sort_keys=True)}`.\n"
    text += f"- Undirected observed edges: `{json.dumps(split['undirected_edge_counts'], sort_keys=True)}`.\n\n"
    text += "## Model boundary\n\nGeneric directed TSV files and a strict candidate schema are prepared. "
    text += "Official ULTRA and TRIX commits/checkpoint hashes are pinned, but no model result is claimed until the official runtime passes and a human-reviewed evaluation set exists.\n"
    path.write_text(text)


def check(output: Path) -> None:
    manifest = json.loads((output / "manifest.json").read_text())
    for raw, expected in manifest["inputs"].items():
        if _sha(Path(raw)) != expected:
            raise ValueError("changed input: " + raw)
    for raw, expected in manifest.get("reading_inputs", {}).items():
        if _sha(Path(raw)) != expected:
            raise ValueError("changed reading input: " + raw)
    for name, expected in manifest["outputs"].items():
        if _sha(output / name) != expected:
            raise ValueError("changed output: " + name)
    print("KG_LINK_PREDICTION_PREPARATION_OK")


def evaluate_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate reviewed proposals without treating unknown/unreviewed as negative."""
    by_proposer: dict[str, Counter[str]] = defaultdict(Counter)
    for row in candidates:
        label = row.get("review_label")
        if label not in ("accepted", "rejected", "unknown", None):
            raise ValueError("invalid review_label")
        by_proposer[str(row.get("proposer", row.get("proposer_bucket", "UNKNOWN")))][label or "unreviewed"] += 1
    result = {}
    for proposer, counts in sorted(by_proposer.items()):
        decided = counts["accepted"] + counts["rejected"]
        result[proposer] = {
            "counts": dict(counts),
            "decided_precision": counts["accepted"] / decided if decided else None,
            "unknown_and_unreviewed_excluded_from_precision": True,
        }
    return {"by_proposer": result, "candidate_recall": None,
            "recall_note": "Recall requires an explicitly enumerated labelled candidate universe."}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    prep.add_argument("--out", type=Path, default=DEFAULT_OUT)
    prep.add_argument("--reading-root", type=Path, action="append")
    prep.add_argument("--review-per-group", type=int, default=24)
    verify = sub.add_parser("check")
    verify.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.command == "prepare":
        roots = args.reading_root or sorted(p for p in DEFAULT_READING.glob("PAGE_*") if p.is_dir())
        print(json.dumps(prepare(args.source, args.out, roots, args.review_per_group), indent=2))
    else:
        check(args.out)


if __name__ == "__main__":
    main()
