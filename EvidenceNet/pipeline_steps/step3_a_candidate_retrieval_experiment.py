#!/usr/bin/env python3
"""Step 3A experiment: compare embedding-only retrieval with multichannel retrieval.

This script is intentionally evaluation-only. It does not modify the production
semantic pipeline or call an LLM. It compares:

1. embedding-only per-node Top-K retrieval;
2. multichannel retrieval with separate quotas for semantic similarity,
   discourse-role complementarity, and long-range cross-section candidates,
   plus deterministic anchor candidates.

The output is designed to be easy to paste back into ChatGPT/Codex:
`retrieval_report.json` is the main summary and `missed_gold.jsonl` contains the
remaining gold misses with their distance/section diagnostics.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys
from typing import Any

EVIDENCENET_ROOT = Path(__file__).resolve().parents[1]
if str(EVIDENCENET_ROOT) not in sys.path:
    sys.path.insert(0, str(EVIDENCENET_ROOT))

from evidence_graph.candidate_generator import relation_hypotheses
from evidence_graph.embeddings import cosine
from evidence_graph.io_utils import read_jsonl, write_json, write_jsonl


ROLE_COMPLEMENTS = {
    frozenset(("method", "result")),
    frozenset(("method", "observation")),
    frozenset(("method", "evidence")),
    frozenset(("evidence", "conclusion")),
    frozenset(("evidence", "discussion")),
    frozenset(("evidence", "motivation")),
    frozenset(("observation", "conclusion")),
    frozenset(("observation", "discussion")),
    frozenset(("result", "conclusion")),
    frozenset(("result", "discussion")),
    frozenset(("background", "discussion")),
    frozenset(("background", "conclusion")),
}

ANCHOR_REASONS = {
    "formula_context_signal",
    "anaphoric_reference_signal",
    "evidence_claim_signal",
    "qualifies_language_signal",
    "contrasts_with_language_signal",
    "depends_on_language_signal",
    "results_in_language_signal",
    "explains_language_signal",
}


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def _shared_entities(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    ea = {str(x).strip().casefold() for x in a.get("entities", []) if str(x).strip()}
    eb = {str(x).strip().casefold() for x in b.get("entities", []) if str(x).strip()}
    return sorted(ea & eb)


def _distance(a: dict[str, Any], b: dict[str, Any]) -> int:
    return abs(int(a.get("document_order", 0)) - int(b.get("document_order", 0)))


def _same_section(a: dict[str, Any], b: dict[str, Any]) -> bool:
    sa, sb = a.get("section_id"), b.get("section_id")
    return bool(sa and sb and sa == sb)


def _role_complement(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ra, rb = a.get("discourse_role"), b.get("discourse_role")
    if not ra or not rb:
        return False
    return frozenset((str(ra), str(rb))) in ROLE_COMPLEMENTS


def _pair_rows(nodes: list[dict[str, Any]], embeddings: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    by_vector = {row["node_id"]: row["vector"] for row in embeddings}
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for i, a in enumerate(nodes):
        if a["node_id"] not in by_vector:
            continue
        for b in nodes[i + 1:]:
            if b["node_id"] not in by_vector:
                continue
            key = pair(a["node_id"], b["node_id"])
            hypotheses, relation_reasons = relation_hypotheses(a, b)
            shared = _shared_entities(a, b)
            rows[key] = {
                "node_a": key[0],
                "node_b": key[1],
                "embedding_similarity": round(cosine(by_vector[a["node_id"]], by_vector[b["node_id"]]), 8),
                "distance": _distance(a, b),
                "same_section": _same_section(a, b),
                "cross_section": not _same_section(a, b),
                "role_complement": _role_complement(a, b),
                "shared_entities": shared,
                "relation_hypotheses": hypotheses,
                "relation_reasons": relation_reasons,
                "anchor": bool(set(relation_reasons) & ANCHOR_REASONS),
            }
    return rows


def _incident(rows: dict[tuple[str, str], dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows.values():
        result[row["node_a"]].append(row)
        result[row["node_b"]].append(row)
    return result


def _other(row: dict[str, Any], node_id: str) -> str:
    return row["node_b"] if row["node_a"] == node_id else row["node_a"]


def embedding_topk(rows: dict[tuple[str, str], dict[str, Any]], top_k: int) -> set[tuple[str, str]]:
    selected: set[tuple[str, str]] = set()
    for node_id, values in _incident(rows).items():
        ranked = sorted(values, key=lambda r: (-r["embedding_similarity"], r["distance"], _other(r, node_id)))
        for row in ranked[:top_k]:
            selected.add(pair(row["node_a"], row["node_b"]))
    return selected


def multichannel(rows: dict[tuple[str, str], dict[str, Any]], similarity_k: int,
                 role_k: int, cross_section_k: int, long_distance: int,
                 include_anchors: bool = True) -> tuple[set[tuple[str, str]], dict[tuple[str, str], set[str]]]:
    selected: set[tuple[str, str]] = set()
    reasons: dict[tuple[str, str], set[str]] = defaultdict(set)
    incident = _incident(rows)

    def keep(row: dict[str, Any], reason: str) -> None:
        key = pair(row["node_a"], row["node_b"])
        selected.add(key)
        reasons[key].add(reason)

    for node_id, values in incident.items():
        similarity = sorted(values, key=lambda r: (-r["embedding_similarity"], r["distance"], _other(r, node_id)))
        for row in similarity[:similarity_k]:
            keep(row, "similarity_quota")

        role_values = [r for r in values if r["role_complement"]]
        role_values.sort(key=lambda r: (-r["embedding_similarity"], -r["distance"], _other(r, node_id)))
        for row in role_values[:role_k]:
            keep(row, "role_complement_quota")

        cross = [r for r in values if r["cross_section"] and r["distance"] >= long_distance]
        cross.sort(key=lambda r: (-r["embedding_similarity"], -r["distance"], _other(r, node_id)))
        for row in cross[:cross_section_k]:
            keep(row, "long_cross_section_quota")

    if include_anchors:
        for row in rows.values():
            if row["anchor"]:
                keep(row, "deterministic_anchor")

    return selected, reasons


def _gold_pairs(path: str) -> dict[tuple[str, str], dict[str, Any]]:
    result = {}
    for row in read_jsonl(path):
        if str(row.get("gold_label", "")).upper() != "RELATION":
            continue
        result[pair(row["node_a"], row["node_b"])] = row
    return result


def _metrics(name: str, selected: set[tuple[str, str]], gold: dict[tuple[str, str], dict[str, Any]],
             rows: dict[tuple[str, str], dict[str, Any]], long_distance: int) -> dict[str, Any]:
    gold_keys = set(gold)
    retrieved = selected & gold_keys
    long_gold = {key for key in gold_keys if rows.get(key, {}).get("distance", 0) >= long_distance}
    cross_gold = {key for key in gold_keys if rows.get(key, {}).get("cross_section")}
    weak_entity_gold = {key for key in gold_keys if not rows.get(key, {}).get("shared_entities")}

    def recall(target: set[tuple[str, str]]) -> float | None:
        return round(len(selected & target) / len(target), 4) if target else None

    return {
        "name": name,
        "candidate_pairs": len(selected),
        "gold_total": len(gold_keys),
        "gold_retrieved": len(retrieved),
        "overall_recall": recall(gold_keys),
        "long_distance_threshold": long_distance,
        "long_distance_gold": len(long_gold),
        "long_distance_retrieved": len(selected & long_gold),
        "long_distance_recall": recall(long_gold),
        "cross_section_gold": len(cross_gold),
        "cross_section_retrieved": len(selected & cross_gold),
        "cross_section_recall": recall(cross_gold),
        "weak_entity_overlap_gold": len(weak_entity_gold),
        "weak_entity_overlap_retrieved": len(selected & weak_entity_gold),
        "weak_entity_overlap_recall": recall(weak_entity_gold),
        "compression_vs_all_pairs": round(1 - len(selected) / max(1, len(rows)), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare embedding-only and long-range multichannel candidate retrieval")
    parser.add_argument("--nodes", required=True, help="evidence_nodes.jsonl")
    parser.add_argument("--embeddings", required=True, help="embedding_vectors.jsonl")
    parser.add_argument("--ground-truth", required=True, help="gold pair JSONL with gold_label=RELATION")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--baseline-top-k", type=int, default=13)
    parser.add_argument("--similarity-k", type=int, default=5)
    parser.add_argument("--role-k", type=int, default=4)
    parser.add_argument("--cross-section-k", type=int, default=4)
    parser.add_argument("--long-distance", type=int, default=6)
    parser.add_argument("--no-anchors", action="store_true")
    args = parser.parse_args()

    nodes = sorted(read_jsonl(args.nodes), key=lambda n: n.get("document_order", 0))
    embeddings = read_jsonl(args.embeddings)
    gold = _gold_pairs(args.ground_truth)
    rows = _pair_rows(nodes, embeddings)

    missing_gold_from_pair_space = sorted(set(gold) - set(rows))
    baseline = embedding_topk(rows, args.baseline_top_k)
    multi, route_reasons = multichannel(
        rows,
        similarity_k=args.similarity_k,
        role_k=args.role_k,
        cross_section_k=args.cross_section_k,
        long_distance=args.long_distance,
        include_anchors=not args.no_anchors,
    )

    baseline_metrics = _metrics("embedding_only", baseline, gold, rows, args.long_distance)
    multi_metrics = _metrics("multichannel", multi, gold, rows, args.long_distance)
    added = multi - baseline
    removed = baseline - multi
    added_gold = added & set(gold)

    route_counts = Counter(reason for key in multi for reason in route_reasons.get(key, set()))
    route_gold_counts = Counter(reason for key in (multi & set(gold)) for reason in route_reasons.get(key, set()))

    misses = []
    for key in sorted(set(gold) - multi):
        feature = rows.get(key, {})
        misses.append({
            "node_a": key[0], "node_b": key[1],
            "gold_relation": gold[key].get("gold_relation"),
            "distance": feature.get("distance"),
            "cross_section": feature.get("cross_section"),
            "embedding_similarity": feature.get("embedding_similarity"),
            "role_complement": feature.get("role_complement"),
            "shared_entities": feature.get("shared_entities"),
            "relation_reasons": feature.get("relation_reasons"),
        })

    added_gold_rows = []
    for key in sorted(added_gold):
        feature = rows[key]
        added_gold_rows.append({
            "node_a": key[0], "node_b": key[1],
            "gold_relation": gold[key].get("gold_relation"),
            "distance": feature["distance"],
            "cross_section": feature["cross_section"],
            "embedding_similarity": feature["embedding_similarity"],
            "role_complement": feature["role_complement"],
            "shared_entities": feature["shared_entities"],
            "retrieval_routes": sorted(route_reasons.get(key, set())),
        })

    report = {
        "experiment": "step3_a_multichannel_candidate_retrieval_v1",
        "inputs": {
            "nodes": args.nodes,
            "embeddings": args.embeddings,
            "ground_truth": args.ground_truth,
        },
        "settings": {
            "baseline_top_k": args.baseline_top_k,
            "similarity_k": args.similarity_k,
            "role_k": args.role_k,
            "cross_section_k": args.cross_section_k,
            "long_distance": args.long_distance,
            "include_anchors": not args.no_anchors,
        },
        "population": {
            "nodes": len(nodes),
            "all_possible_pairs_with_embeddings": len(rows),
            "gold_pairs": len(gold),
            "gold_missing_from_pair_space": len(missing_gold_from_pair_space),
        },
        "baseline": baseline_metrics,
        "multichannel": multi_metrics,
        "delta": {
            "candidate_pairs": multi_metrics["candidate_pairs"] - baseline_metrics["candidate_pairs"],
            "gold_retrieved": multi_metrics["gold_retrieved"] - baseline_metrics["gold_retrieved"],
            "overall_recall": None if baseline_metrics["overall_recall"] is None else round(multi_metrics["overall_recall"] - baseline_metrics["overall_recall"], 4),
            "long_distance_recall": None if baseline_metrics["long_distance_recall"] is None else round((multi_metrics["long_distance_recall"] or 0) - (baseline_metrics["long_distance_recall"] or 0), 4),
            "cross_section_recall": None if baseline_metrics["cross_section_recall"] is None else round((multi_metrics["cross_section_recall"] or 0) - (baseline_metrics["cross_section_recall"] or 0), 4),
            "weak_entity_overlap_recall": None if baseline_metrics["weak_entity_overlap_recall"] is None else round((multi_metrics["weak_entity_overlap_recall"] or 0) - (baseline_metrics["weak_entity_overlap_recall"] or 0), 4),
        },
        "multichannel_routes": {
            "candidate_counts": dict(route_counts),
            "gold_counts": dict(route_gold_counts),
        },
        "added_vs_embedding_baseline": len(added),
        "removed_vs_embedding_baseline": len(removed),
        "added_gold_vs_embedding_baseline": len(added_gold),
        "remaining_gold_misses": len(misses),
        "gold_missing_from_pair_space": [list(key) for key in missing_gold_from_pair_space],
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "retrieval_report.json", report)
    write_jsonl(output_dir / "added_gold.jsonl", added_gold_rows)
    write_jsonl(output_dir / "missed_gold.jsonl", misses)

    candidate_rows = []
    for key in sorted(multi):
        feature = dict(rows[key])
        feature["retrieval_routes"] = sorted(route_reasons.get(key, set()))
        feature["is_gold"] = key in gold
        candidate_rows.append(feature)
    write_jsonl(output_dir / "multichannel_candidates.jsonl", candidate_rows)

    print(json.dumps(report, indent=2))
    print(f"\nMain result: {output_dir / 'retrieval_report.json'}")
    print(f"New gold recovered vs embedding baseline: {output_dir / 'added_gold.jsonl'}")
    print(f"Remaining gold misses: {output_dir / 'missed_gold.jsonl'}")


if __name__ == "__main__":
    main()
