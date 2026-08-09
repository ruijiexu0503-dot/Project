from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


MANDATORY_REASONS = {
    "anaphoric_reference_signal",
    "formula_context_signal",
    "explicit_figure_reference",
    "explicit_table_reference",
    "explicit_equation_reference",
    "cross_content_unit_bridge",
}

RELATION_SIGNALS = {
    "background_discourse_signal",
    "contrasts_with_language_signal",
    "depends_on_language_signal",
    "evidence_claim_signal",
    "explains_language_signal",
    "mention_detail_signal",
    "qualifies_language_signal",
    "results_in_language_signal",
}


def pair_key(row: dict) -> tuple[str, str]:
    return tuple(sorted((row["node_a"], row["node_b"])))


def candidate_score(row: dict, similarity_threshold: float) -> tuple[float, list[str]]:
    reasons = set(row.get("candidate_reasons", []))
    distance = row.get("reading_order_distance")
    similarity = row.get("embedding_similarity")
    score = 0.0
    evidence: list[str] = []
    if reasons & MANDATORY_REASONS:
        score += 100.0
        evidence.append("mandatory_reference_or_continuity")
    if distance == 1:
        score += 50.0
        evidence.append("immediate_neighbor")
    elif distance == 2:
        score += 1.0
    if similarity is not None and similarity >= similarity_threshold:
        score += 4.0 + 10.0 * (similarity - similarity_threshold)
        evidence.append("strong_embedding")
    if "shared_entities" in reasons:
        score += 2.0
        evidence.append("shared_entities")
    if "shared_anchor_signal" in reasons:
        score += 2.0
        evidence.append("shared_anchor")
    relation_count = len(reasons & RELATION_SIGNALS)
    if relation_count:
        score += min(3.0, 1.25 * relation_count)
        evidence.append("relation_language_or_role")
    if "same_section" in reasons:
        score += 0.25
    return score, evidence


def prune(rows: list[dict], per_node: int, similarity_threshold: float) -> list[dict]:
    ranked: list[tuple[float, tuple[str, str], dict, list[str]]] = []
    for row in rows:
        score, evidence = candidate_score(row, similarity_threshold)
        ranked.append((score, pair_key(row), row, evidence))
    ranked.sort(key=lambda x: (-x[0], x[2].get("reading_order_distance", 10**9), x[1]))

    counts: defaultdict[str, int] = defaultdict(int)
    kept: list[dict] = []
    for score, _, row, evidence in ranked:
        mandatory = score >= 50.0
        a, b = row["node_a"], row["node_b"]
        if not mandatory and (not evidence or counts[a] >= per_node or counts[b] >= per_node):
            continue
        item = dict(row)
        item["pruning_score"] = round(score, 6)
        item["pruning_evidence"] = evidence
        kept.append(item)
        counts[a] += 1
        counts[b] += 1
    return sorted(kept, key=pair_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Conservatively prune semantic candidates before LLM verification")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--reference-edges")
    parser.add_argument("--per-node", type=int, default=3)
    parser.add_argument("--similarity-threshold", type=float, default=0.85)
    args = parser.parse_args()

    rows = read_jsonl(Path(args.input))
    kept = prune(rows, args.per_node, args.similarity_threshold)
    kept_keys = {pair_key(row) for row in kept}
    report = {
        "input_candidates": len(rows),
        "kept_candidates": len(kept),
        "reduction_fraction": round(1.0 - len(kept) / max(1, len(rows)), 4),
        "per_node_nonmandatory_cap": args.per_node,
        "embedding_similarity_threshold": args.similarity_threshold,
    }
    if args.reference_edges:
        reference = read_jsonl(Path(args.reference_edges))
        reference_keys = {
            tuple(sorted((row.get("source"), row.get("target"))))
            for row in reference if row.get("source") and row.get("target")
        }
        available = reference_keys & {pair_key(row) for row in rows}
        retained = available & kept_keys
        report["reference_edges"] = len(reference_keys)
        report["reference_edges_available_in_input"] = len(available)
        report["available_reference_edges_retained"] = len(retained)
        report["available_reference_recall"] = round(len(retained) / max(1, len(available)), 4)
        report["dropped_available_reference_pairs"] = [list(pair) for pair in sorted(available - retained)]
    write_jsonl(Path(args.output), kept)
    write_json(Path(args.report), report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
