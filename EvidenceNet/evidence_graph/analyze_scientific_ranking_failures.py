from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from .evaluate_scientific_ranking import STRONG_REASONS, is_mandatory, pair
from .io_utils import read_jsonl, write_json


REFERENCE_PATTERN = re.compile(r"\b(?:fig(?:ure)?|table|eq(?:uation)?)\.?\s*\d+", re.I)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze gold relations missed by a frozen ranking budget")
    parser.add_argument("--screening", required=True)
    parser.add_argument("--ranking", required=True)
    parser.add_argument("--ground-truth", required=True)
    parser.add_argument("--budget", type=int, default=220)
    parser.add_argument("--scoring-method", default="degree_normalized")
    args = parser.parse_args()

    screening, ranking = Path(args.screening), Path(args.ranking)
    nodes = read_jsonl(screening / "evidence_nodes.jsonl")
    by_id = {node["node_id"]: node for node in nodes}
    decisions = read_jsonl(screening / "screening_decisions.jsonl")
    candidates = {
        pair(row["candidate"]["node_a"], row["candidate"]["node_b"]): row["candidate"]
        for row in decisions if row["classification"] == "RELATED"
    }
    ranking_rows = read_jsonl(ranking / "node_rankings.jsonl")
    ranks = {
        row["source"]: {target: index + 1 for index, target in enumerate(row["ranked_target_ids"])}
        for row in ranking_rows
    }
    degree = {source: len(values) for source, values in ranks.items()}
    gold = {
        pair(row["node_a"], row["node_b"]): row
        for row in read_jsonl(args.ground_truth) if row["gold_label"] == "RELATION"
    }
    shortlist_rows = [
        row for row in read_jsonl(ranking / "budget_shortlists.jsonl")
        if row["budget"] == args.budget and row["scoring_method"] == args.scoring_method
    ]
    selected = {pair(row["node_a"], row["node_b"]): row for row in shortlist_rows}
    score_cutoff = min(
        row["score"] for row in shortlist_rows
        if not row["mandatory"] and not row.get("repair_added")
    )

    failures = []
    for key in sorted(set(gold) - set(selected)):
        annotation, candidate = gold[key], candidates[key]
        source = annotation.get("gold_source") or key[0]
        target = annotation.get("gold_target") or key[1]
        source_rank = ranks[source][target]
        target_rank = ranks[target][source]
        source_percentile = (degree[source] - source_rank + 1) / degree[source]
        target_percentile = (degree[target] - target_rank + 1) / degree[target]
        reasons = set(candidate.get("candidate_reasons") or [])
        strong_count = min(3, len(reasons & STRONG_REASONS))
        adjacency_only = candidate.get("reading_order_distance") == 1 and strong_count == 0
        rank_component = max(source_percentile, target_percentile) + .05 * min(
            source_percentile, target_percentile)
        score = rank_component + .1 * strong_count - (.1 if adjacency_only else 0)
        source_top5, target_top5 = source_rank <= 5, target_rank <= 5
        selection_state = "mutual" if source_top5 and target_top5 else (
            "unilateral" if source_top5 or target_top5 else "unselected")
        mandatory, mandatory_reasons = is_mandatory(candidate, by_id)
        source_node, target_node = by_id[source], by_id[target]
        same_section = source_node.get("section_id") == target_node.get("section_id")
        source_text = source_node.get("plain_text") or source_node.get("original_markdown") or ""
        target_text = target_node.get("plain_text") or target_node.get("original_markdown") or ""
        shared_entities = candidate.get("shared_entities") or []
        structural_distance = candidate.get("reading_order_distance")
        taxonomy = []
        if structural_distance is not None and structural_distance >= 6:
            taxonomy.append("long-distance relation")
        if not same_section:
            taxonomy.append("cross-section relation")
        if not shared_entities:
            taxonomy.append("weak entity overlap")
        if {source_node.get("discourse_role"), target_node.get("discourse_role")} == {"method", "result"}:
            taxonomy.append("asymmetric method/result relation")
        if annotation.get("gold_relation") in {"QUALIFIES", "CONTRASTS_WITH"}:
            taxonomy.append("qualification/contrast relation")
        if not source_node.get("is_complete", True) or not target_node.get("is_complete", True):
            taxonomy.append("node atomicity problem")
        if max(degree[source], degree[target]) >= 20:
            taxonomy.append("high-degree-node ranking suppression")
        if candidate.get("embedding_similarity") is None:
            taxonomy.append("missing embedding score")
        failures.append({
            "node_a": key[0], "node_b": key[1],
            "source_node": source, "target_node": target,
            "gold_relation_type": annotation.get("gold_relation"),
            "gold_rationale": annotation.get("rationale"),
            "source_candidate_degree": degree[source], "target_candidate_degree": degree[target],
            "rank_from_source": source_rank, "rank_from_target": target_rank,
            "source_degree_normalized_rank": round(source_percentile, 6),
            "target_degree_normalized_rank": round(target_percentile, 6),
            "degree_normalized_rank_component": round(rank_component, 6),
            "top5_selection_state": selection_state,
            "mandatory": mandatory, "mandatory_reasons": mandatory_reasons,
            "embedding_similarity": candidate.get("embedding_similarity"),
            "shared_entities": shared_entities,
            "source_section": source_node.get("section_path") or [],
            "target_section": target_node.get("section_path") or [],
            "section_relationship": "same-section" if same_section else "cross-section",
            "structural_distance": structural_distance,
            "paragraph_distance_proxy": max(0, abs(source_node["document_order"] - target_node["document_order"]) - 1),
            "page_ids_source": source_node.get("page_ids") or [],
            "page_ids_target": target_node.get("page_ids") or [],
            "formula_signal": ("formula_context_signal" in reasons
                               or source_node.get("evidence_type") == "formula"
                               or target_node.get("evidence_type") == "formula"),
            "figure_or_table_signal": bool(reasons & {"explicit_figure_reference", "explicit_table_reference"}),
            "textual_figure_table_equation_mention": bool(REFERENCE_PATTERN.search(source_text)
                                                           or REFERENCE_PATTERN.search(target_text)),
            "anaphora_signal": "anaphoric_reference_signal" in reasons,
            "contrast_signal": "contrasts_with_language_signal" in reasons,
            "qualification_signal": "qualifies_language_signal" in reasons,
            "evidence_role_signal": "evidence_claim_signal" in reasons,
            "candidate_reasons": sorted(reasons),
            "source_discourse_role": source_node.get("discourse_role"),
            "target_discourse_role": target_node.get("discourse_role"),
            "source_is_complete": source_node.get("is_complete"),
            "target_is_complete": target_node.get("is_complete"),
            "strong_signal_count_capped": strong_count,
            "final_shortlist_score": round(score, 6),
            "budget_cutoff_score": score_cutoff,
            "score_margin_below_cutoff": round(score_cutoff - score, 6),
            "failure_taxonomy": taxonomy,
            "source_text": source_text,
            "target_text": target_text,
        })

    neighbors: dict[str, set[str]] = defaultdict(set)
    for a, b in selected:
        neighbors[a].add(b)
        neighbors[b].add(a)
    claim_roles = {"motivation", "discussion", "conclusion", "other"}
    evidence_roles = {"observation", "result", "evidence"}
    method_roles = {"method", "evidence", "observation"}
    role_gaps = {"claim_without_support": [], "result_without_method_or_evidence": [],
                 "formula_without_application_or_explanation": [],
                 "conclusion_without_preceding_support": []}
    for node_id, node in by_id.items():
        neighbor_roles = {by_id[value].get("discourse_role") for value in neighbors[node_id]}
        if node.get("discourse_role") in claim_roles and not neighbor_roles & evidence_roles:
            role_gaps["claim_without_support"].append(node_id)
        if node.get("discourse_role") == "result" and not neighbor_roles & method_roles:
            role_gaps["result_without_method_or_evidence"].append(node_id)
        if node.get("evidence_type") == "formula" and not neighbors[node_id]:
            role_gaps["formula_without_application_or_explanation"].append(node_id)
        if node.get("discourse_role") == "conclusion":
            preceding = [value for value in neighbors[node_id]
                         if by_id[value]["document_order"] < node["document_order"]
                         and by_id[value].get("discourse_role") in evidence_roles | {"method"}]
            if not preceding:
                role_gaps["conclusion_without_preceding_support"].append(node_id)

    report = {
        "budget": args.budget, "scoring_method": args.scoring_method,
        "gold_total": len(gold), "selected_gold": len(set(gold) & set(selected)),
        "missing_gold": len(failures), "budget_cutoff_score": score_cutoff,
        "failures": failures,
        "role_coverage_gaps_at_budget": role_gaps,
        "role_aware_repair_would_recover_missing_gold": False,
        "role_aware_repair_assessment": (
            "No coarse role gap exists at this budget. The result endpoint already has method/evidence neighbors, "
            "and the cross-section qualification joins two method nodes. Presence-only role repair would not "
            "select the three missing pairs."
        ),
    }
    output = ranking / f"failure_analysis_budget_{args.budget}.json"
    write_json(output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
