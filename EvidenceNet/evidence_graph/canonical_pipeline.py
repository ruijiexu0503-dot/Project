from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .canonical_evidence import canonicalize
from .io_utils import read_json, read_jsonl, write_json, write_jsonl
from .rule_based_reference_grounding import resolve_references


ABSORBED_PROVENANCE_TYPES = {
    "CAPTION_OF", "HAS_CAPTION", "TABLE_CONTENT_OF", "HAS_TABLE_CONTENT",
    "COLOCATED_WITH_VISUAL", "REFERENCES_FIGURE", "REFERENCES_TABLE", "REFERENCES_FORMULA",
}
ORDER_EDGE_TYPES = {"NEXT", "PREVIOUS"}
PRODUCTION_REFERENCE_RULES = {"explicit_label"}
SEMANTIC_RELATION_MAP = {
    "SUPPORTS": "SUPPORTS",
    "ELABORATES": "EXPLAINS_OR_ELABORATES",
    "EXPLAINS": "EXPLAINS_OR_ELABORATES",
    "PROVIDES_BACKGROUND_FOR": "EXPLAINS_OR_ELABORATES",
    "PROVIDES_CONTEXT_FOR": "EXPLAINS_OR_ELABORATES",
    "QUALIFIES": "MODIFIES",
    "MODIFIES": "MODIFIES",
    "CONTRASTS_WITH": "CONTRASTS_WITH",
}


def _remap_edges(
    rows: list[dict],
    aliases: dict[str, str],
    active_ids: set[str],
    drop_types: set[str] | None = None,
) -> tuple[list[dict], dict]:
    drop_types = drop_types or set()
    output = []
    seen = set()
    stats = Counter()
    for original in rows:
        if original.get("edge_type") in drop_types:
            stats["dropped_by_type"] += 1
            continue
        row = dict(original)
        row["source"] = aliases.get(row["source"], row["source"])
        row["target"] = aliases.get(row["target"], row["target"])
        if row["source"] == row["target"]:
            stats["dropped_self_loop_after_remap"] += 1
            continue
        if row["source"] not in active_ids or row["target"] not in active_ids:
            stats["dropped_dangling_after_remap"] += 1
            continue
        edge_name = row.get("edge_type") or row.get("relation")
        key = (row["source"], row["target"], edge_name)
        if key in seen:
            stats["dropped_duplicate_after_remap"] += 1
            continue
        seen.add(key)
        output.append(row)
    stats["output_edges"] = len(output)
    return output, dict(stats)


def _assignment_path(source: Path, explicit: str | Path | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    path = source / "structure_aware_content_unit_assignments.jsonl"
    return path if path.exists() else None


def _normalize_semantic_edges(
    rows: list[dict],
    *,
    taxonomy_mapping: str = "legacy_fine_grained_to_split_semantic_v1",
    semantic_status: str = "legacy_accepted_not_revalidated_under_coarse_taxonomy",
    source_path: str | None = None,
) -> tuple[list[dict], list[dict]]:
    normalized = []
    unresolved = []
    for original in rows:
        old_relation = original.get("edge_type") or original.get("relation")
        relation = SEMANTIC_RELATION_MAP.get(str(old_relation))
        if relation is None:
            unresolved.append({
                **original,
                "original_relation": old_relation,
                "unresolved_reason": (
                    "DEPENDS_ON_requires_manual_condition_or_prerequisite_review"
                    if old_relation == "DEPENDS_ON"
                    else "relation_not_mapped_to_split_taxonomy"
                ),
            })
            continue
        row = dict(original)
        metadata = dict(row.get("metadata") or {})
        metadata.update({
            "original_relation": old_relation,
            "taxonomy_mapping": taxonomy_mapping,
            "semantic_status": semantic_status,
        })
        if source_path:
            metadata["semantic_source_path"] = source_path
        row.update({
            "edge_layer": "semantic",
            "edge_family": "semantic",
            "edge_type": relation,
            "relation": relation,
            "directed": relation != "CONTRASTS_WITH",
            "metadata": metadata,
        })
        normalized.append(row)
    return normalized, unresolved


def _configured_semantic_path(doc_id: str, config: dict[str, Any]) -> Path | None:
    configured = (
        (config.get("canonicalization") or {}).get("semantic_sources") or {}
    ).get(doc_id)
    if not configured:
        return None
    path = Path(configured)
    if not path.exists():
        raise FileNotFoundError(f"Configured semantic source does not exist: {path}")
    return path


def _attach_assignments(nodes: list[dict], path: Path | None) -> None:
    if path is None:
        return
    assignments = {row["node_id"]: row for row in read_jsonl(path)}
    for node in nodes:
        assignment = assignments.get(node["node_id"])
        if not assignment:
            continue
        item_id = assignment.get("content_item_id") or assignment.get("content_unit_id")
        metadata = dict(node.get("metadata") or {})
        if item_id:
            metadata["content_item_id"] = item_id
        if assignment.get("segment_id"):
            metadata["segment_id"] = assignment["segment_id"]
        node["metadata"] = metadata


def _canonical_output_root(config: dict[str, Any]) -> Path:
    configured = (config.get("canonicalization") or {}).get("output_root")
    if configured:
        return Path(configured)
    return Path(config["output"]["graph_root"]).parent / "canonical_graph"


def materialize_canonical_graph(
    doc_id: str,
    config: dict[str, Any],
    assignments: str | Path | None = None,
) -> dict:
    source = Path(config["output"]["graph_root"]) / doc_id
    output = _canonical_output_root(config) / doc_id
    output.mkdir(parents=True, exist_ok=True)

    evidence = read_jsonl(source / "evidence_nodes.jsonl")
    visuals = read_jsonl(source / "visual_nodes.jsonl")
    structural = read_jsonl(source / "structural_edges.jsonl")
    documents = read_jsonl(source / "document_nodes.jsonl")
    sections = read_jsonl(source / "section_nodes.jsonl")
    legacy_semantic_path = source / "semantic_edges.jsonl"
    legacy_semantic_rows = (
        read_jsonl(legacy_semantic_path) if legacy_semantic_path.exists() else []
    )
    semantic_source_path = _configured_semantic_path(doc_id, config)
    production_semantic_rows = (
        read_jsonl(semantic_source_path) if semantic_source_path else []
    )
    assignment_source = _assignment_path(source, assignments)
    _attach_assignments(evidence, assignment_source)

    canonical, alias_rows, canonical_summary = canonicalize(evidence, visuals, structural)
    alias_map = {row["source_node_id"]: row["canonical_node_id"] for row in alias_rows}

    ambiguous_visual_ids = set(canonical_summary["ambiguous_visual_node_ids"])
    ambiguous_assets = set(canonical_summary["ambiguous_visual_asset_paths"])
    remaining_visuals = [
        row for row in visuals
        if row["node_id"] not in alias_map
        and row["node_id"] not in ambiguous_visual_ids
        and str(row.get("asset_path")) not in ambiguous_assets
    ]
    all_nodes = documents + sections + canonical + remaining_visuals
    active_ids = {row["node_id"] for row in all_nodes}

    canonical_structural, structural_stats = _remap_edges(
        structural,
        alias_map,
        active_ids,
        ABSORBED_PROVENANCE_TYPES | ORDER_EDGE_TYPES,
    )
    remapped_legacy_semantic, legacy_semantic_stats = _remap_edges(
        legacy_semantic_rows, alias_map, active_ids
    )
    legacy_semantic, legacy_unresolved_semantic = _normalize_semantic_edges(
        remapped_legacy_semantic,
        source_path=str(legacy_semantic_path),
    )
    remapped_production_semantic, production_semantic_stats = _remap_edges(
        production_semantic_rows, alias_map, active_ids
    )
    new_semantic, new_unresolved_semantic = _normalize_semantic_edges(
        remapped_production_semantic,
        taxonomy_mapping="model_fine_grained_to_split_semantic_v1",
        semantic_status="model_accepted_not_manually_revalidated_under_split_taxonomy",
        source_path=str(semantic_source_path) if semantic_source_path else None,
    )
    include_legacy_semantic = bool(
        (config.get("canonicalization") or {}).get("include_legacy_semantic", False)
    )
    canonical_semantic = list(new_semantic)
    unresolved_semantic = list(new_unresolved_semantic)
    if include_legacy_semantic:
        canonical_semantic.extend(legacy_semantic)
        unresolved_semantic.extend(legacy_unresolved_semantic)
    semantic_stats = {
        "configured_source": str(semantic_source_path) if semantic_source_path else None,
        "configured_source_remap": production_semantic_stats,
        "legacy_source_remap": legacy_semantic_stats,
        "legacy_included_in_production": include_legacy_semantic,
        "archived_legacy_edges": len(legacy_semantic),
        "archived_legacy_unresolved_edges": len(legacy_unresolved_semantic),
        "new_model_edges": len(new_semantic),
        "new_model_unresolved_edges": len(new_unresolved_semantic),
        "production_edges": len(canonical_semantic),
        "production_unresolved_edges": len(unresolved_semantic),
    }

    resolved, unresolved = resolve_references(canonical)
    discourse = []
    shadow = []
    for row in resolved:
        normalized = {
            **row,
            "edge_layer": "discourse",
            "edge_type": "REFERENCES",
        }
        if row["rule_family"] in PRODUCTION_REFERENCE_RULES:
            discourse.append(normalized)
        else:
            shadow.append(normalized)

    graph_edges = canonical_structural + discourse + canonical_semantic
    edge_keys = Counter(
        (row["source"], row["target"], row.get("edge_type") or row.get("relation"))
        for row in graph_edges
    )
    node_counts = Counter(row["node_id"] for row in all_nodes)
    errors = []
    duplicate_nodes = {node_id: count for node_id, count in node_counts.items() if count > 1}
    if duplicate_nodes:
        errors.append({"type": "duplicate_node_ids", "nodes": duplicate_nodes})
    dangling = [
        row for row in graph_edges
        if row["source"] not in active_ids or row["target"] not in active_ids
    ]
    if dangling:
        errors.append({"type": "dangling_edges", "count": len(dangling)})
    duplicate_edges = sum(count - 1 for count in edge_keys.values())
    if duplicate_edges:
        errors.append({"type": "duplicate_edges", "count": duplicate_edges})
    self_loops = sum(row["source"] == row["target"] for row in graph_edges)
    if self_loops:
        errors.append({"type": "self_loops", "count": self_loops})
    if not canonical_summary["valid"]:
        errors.append({"type": "canonicalization_invalid", "details": canonical_summary["errors"]})

    validation = {
        "doc_id": doc_id,
        "valid": not errors,
        "errors": errors,
        "warnings": canonical_summary["warnings"],
        "summary": {
            "node_count": len(all_nodes),
            "evidence_node_count": len(canonical),
            "remaining_visual_node_count": len(remaining_visuals),
            "structural_edge_count": len(canonical_structural),
            "discourse_edge_count": len(discourse),
            "semantic_edge_count": len(canonical_semantic),
            "unresolved_semantic_edge_count": len(unresolved_semantic),
            "archived_legacy_semantic_edge_count": len(legacy_semantic),
            "archived_legacy_unresolved_semantic_edge_count": len(legacy_unresolved_semantic),
            "shadow_discourse_edge_count": len(shadow),
            "unresolved_reference_cues": len(unresolved),
            "error_count": len(errors),
            "warning_count": len(canonical_summary["warnings"]),
        },
    }
    report = {
        "doc_id": doc_id,
        "source_graph": str(source),
        "output_graph": str(output),
        "production_graph": True,
        "raw_graph_preserved": True,
        "assignment_source": str(assignment_source) if assignment_source else None,
        "production_reference_rules": sorted(PRODUCTION_REFERENCE_RULES),
        "include_legacy_semantic": include_legacy_semantic,
        "semantic_source": str(semantic_source_path) if semantic_source_path else None,
        "canonicalization": canonical_summary,
        "structural_remap": structural_stats,
        "semantic_remap": semantic_stats,
        "validation": validation["summary"],
    }

    write_jsonl(output / "document_nodes.jsonl", documents)
    write_jsonl(output / "section_nodes.jsonl", sections)
    write_jsonl(output / "evidence_nodes.jsonl", canonical)
    write_jsonl(output / "visual_nodes.jsonl", remaining_visuals)
    write_jsonl(output / "node_aliases.jsonl", alias_rows)
    write_jsonl(output / "structural_edges.jsonl", canonical_structural)
    write_jsonl(output / "discourse_edges.jsonl", discourse)
    write_jsonl(output / "shadow_discourse_edges.jsonl", shadow)
    write_jsonl(output / "unresolved_reference_cues.jsonl", unresolved)
    write_jsonl(output / "semantic_edges.jsonl", canonical_semantic)
    write_jsonl(output / "unresolved_semantic_edges.jsonl", unresolved_semantic)
    write_jsonl(output / "legacy_semantic_edges.jsonl", legacy_semantic)
    write_jsonl(output / "legacy_unresolved_semantic_edges.jsonl", legacy_unresolved_semantic)
    write_json(output / "validation_report.json", validation)
    write_json(output / "canonicalization_report.json", report)
    write_json(output / "graph.json", {
        "doc_id": doc_id,
        "nodes": all_nodes,
        "edges": graph_edges,
        "phase": "canonical",
        "edge_families": [
            "structural",
            "discourse",
            *(["semantic"] if canonical_semantic else []),
        ],
        "raw_source_graph": str(source),
    })
    return report


def main() -> None:
    import argparse
    from .config import load_config

    parser = argparse.ArgumentParser(description="Materialize the production canonical Evidence graph")
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--assignments")
    args = parser.parse_args()
    print(json.dumps(
        materialize_canonical_graph(args.doc_id, load_config(args.config), args.assignments),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
