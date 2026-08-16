from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from .io_utils import read_jsonl, write_json, write_jsonl


TOP_K_SETTINGS = (1, 2, 3, 4, 5)
GLOBAL_BUDGETS = (80, 120, 150, 180, 220, 260)
MANDATORY_REASONS = {
    "explicit_equation_reference", "explicit_figure_reference", "explicit_table_reference",
    "formula_context_signal", "anaphoric_reference_signal",
}
STRONG_REASONS = {
    "embedding_top_k", "shared_entities", "evidence_claim_signal", "formula_context_signal",
    "anaphoric_reference_signal", "explains_language_signal", "depends_on_language_signal",
    "qualifies_language_signal", "contrasts_with_language_signal", "results_in_language_signal",
}

FROZEN_POLICY = {
    "policy_id": "scientific-comparative-ranking-v1-gw150914-frozen",
    "ranking_input": "9B absolute-screening rows classified RELATED",
    "degree_normalization": "(degree - rank + 1) / degree",
    "global_score": {
        "stronger_endpoint_percentile_weight": 1.0,
        "weaker_endpoint_reciprocal_bonus_weight": 0.05,
        "strong_retrieval_signal_weight": 0.1,
        "strong_retrieval_signal_cap": 3,
        "adjacency_only_penalty": 0.1,
    },
    "mandatory": {
        "direct_reasons": sorted(MANDATORY_REASONS),
        "contrast_or_qualification_max_distance": 1,
        "evidence_roles": ["evidence", "observation", "result"],
        "claim_roles": ["conclusion", "discussion", "motivation", "other", "result"],
        "evidence_claim_embedding_threshold": 0.85,
        "evidence_claim_shared_entities_alternative": True,
    },
    "important_nodes": {
        "evidence_type": "formula",
        "roles": ["conclusion", "discussion", "evidence", "method", "result"],
        "section_name_fragments": ["conclusion", "outlook"],
    },
    "coverage_repair": "for each isolated important node, add its highest frozen-score incident RELATED pair",
    "budget_order": "mandatory first, then descending frozen score; degree-preserving replacement after repair",
}
POLICY_HASH = hashlib.sha256(
    json.dumps(FROZEN_POLICY, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def is_mandatory(candidate: dict, by_id: dict[str, dict]) -> tuple[bool, list[str]]:
    reasons = set(candidate.get("candidate_reasons") or [])
    matched = sorted(reasons & MANDATORY_REASONS)
    roles = {by_id[candidate["node_a"]].get("discourse_role"),
             by_id[candidate["node_b"]].get("discourse_role")}
    # Language-marker flags are generated when either endpoint contains a cue.
    # They become mandatory only for the adjacent pair that can plausibly ground it.
    if candidate.get("reading_order_distance") == 1:
        if "contrasts_with_language_signal" in reasons:
            matched.append("grounded_explicit_contrast")
        if "qualifies_language_signal" in reasons:
            matched.append("grounded_explicit_qualification")
    evidence_claim = ("evidence_claim_signal" in reasons
                      and bool(roles & {"observation", "result", "evidence"})
                      and bool(roles & {"result", "conclusion", "discussion", "motivation", "other"})
                      and ((candidate.get("embedding_similarity") or 0) >= .85
                           or "shared_entities" in reasons))
    if evidence_claim:
        matched.append("high_confidence_evidence_claim")
    return bool(matched), matched


def important_nodes(nodes: list[dict]) -> set[str]:
    result = set()
    for node in nodes:
        path = " ".join(node.get("section_path") or []).casefold()
        if (node.get("evidence_type") == "formula"
                or node.get("discourse_role") in {"evidence", "result", "method", "conclusion", "discussion"}
                or "conclusion" in path or "outlook" in path):
            result.add(node["node_id"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate comparative scientific-candidate rankings")
    parser.add_argument("--screening", required=True)
    parser.add_argument("--ranking", required=True)
    parser.add_argument("--ground-truth", default="evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl")
    parser.add_argument("--initial-candidates",
                        default="output/scientific_body_cascade/shared_candidates/gw150914_detection/candidates.jsonl")
    args = parser.parse_args()
    screening, ranking = Path(args.screening), Path(args.ranking)
    nodes = read_jsonl(screening / "evidence_nodes.jsonl")
    by_id = {node["node_id"]: node for node in nodes}
    decisions = read_jsonl(screening / "screening_decisions.jsonl")
    related = [row for row in decisions if row["classification"] == "RELATED"]
    candidates = {pair(row["candidate"]["node_a"], row["candidate"]["node_b"]): row["candidate"]
                  for row in related}
    rankings = read_jsonl(ranking / "node_rankings.jsonl")
    rank_by_source = {row["source"]: {target: index + 1 for index, target in enumerate(row["ranked_target_ids"])}
                      for row in rankings}
    truth = read_jsonl(args.ground_truth)
    gold = {pair(row["node_a"], row["node_b"]) for row in truth if row["gold_label"] == "RELATION"}
    all_initial = read_jsonl(args.initial_candidates)
    initial_count = len(all_initial)
    mandatory = {}
    for key, candidate in candidates.items():
        keep, reasons = is_mandatory(candidate, by_id)
        if keep:
            mandatory[key] = reasons
    important = important_nodes(nodes)

    pair_features = {}
    for key, candidate in candidates.items():
        a, b = key
        rank_a = rank_by_source.get(a, {}).get(b, 10_000)
        rank_b = rank_by_source.get(b, {}).get(a, 10_000)
        degree_a = len(rank_by_source.get(a, {}))
        degree_b = len(rank_by_source.get(b, {}))
        reasons = set(candidate.get("candidate_reasons") or [])
        strong = len(reasons & STRONG_REASONS)
        adjacency_only = (candidate.get("reading_order_distance") == 1 and not strong)
        # Keep the initial raw reciprocal score as a baseline. It is biased toward
        # low-degree nodes because (for example) rank 8 has the same value whether
        # a source has 8 or 27 candidates.
        reciprocal_score = (2 / rank_a if rank_a < 10_000 else 0) + (2 / rank_b if rank_b < 10_000 else 0)
        raw_score = reciprocal_score + (1.2 if key in mandatory else 0) + min(strong, 3) * .2
        if adjacency_only:
            raw_score -= .5
        percentile_a = ((degree_a - rank_a + 1) / degree_a) if degree_a and rank_a <= degree_a else 0
        percentile_b = ((degree_b - rank_b + 1) / degree_b) if degree_b and rank_b <= degree_b else 0
        # Degree-normalized endpoint strength is the primary signal. A small
        # reciprocal term rewards agreement without suppressing strong unilateral
        # links from high-degree source nodes.
        normalized_score = (max(percentile_a, percentile_b)
                            + .05 * min(percentile_a, percentile_b)
                            + min(strong, 3) * .1
                            - (.1 if adjacency_only else 0))
        pair_features[key] = {"rank_a": rank_a, "rank_b": rank_b,
                              "degree_a": degree_a, "degree_b": degree_b,
                              "rank_percentile_a": round(percentile_a, 6),
                              "rank_percentile_b": round(percentile_b, 6),
                              "mutual_rank_score": reciprocal_score,
                              "raw_reciprocal_score": round(raw_score, 6),
                              "score": round(normalized_score, 6),
                              "mandatory": key in mandatory, "mandatory_reasons": mandatory.get(key, []),
                              "strong_signal_count": strong, "adjacency_only": adjacency_only}

    def repair(selected: set[tuple[str, str]], score_field: str = "score") -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
        degree = Counter(node_id for key in selected for node_id in key)
        additions = set()
        for node_id in sorted(important, key=lambda value: by_id[value]["document_order"]):
            if degree[node_id] > 0:
                continue
            incident = [key for key in candidates if node_id in key and key not in selected]
            if incident:
                best = max(incident, key=lambda key: pair_features[key][score_field])
                additions.add(best); degree[best[0]] += 1; degree[best[1]] += 1
        return selected | additions, additions

    def stage_stats(selected: set[tuple[str, str]]) -> dict:
        selected_gold = selected & gold
        covered_important = {node_id for key in selected for node_id in key} & important
        return {
            "unique_pairs": len(selected),
            "gold_retrieved": len(selected_gold), "gold_recall": round(len(selected_gold) / max(1, len(gold)), 4),
            "compression_from_initial": round(1 - len(selected) / max(1, initial_count), 4),
            "compression_from_related": round(1 - len(selected) / max(1, len(candidates)), 4),
            "important_nodes": len(important), "important_nodes_covered": len(covered_important),
            "important_node_coverage": round(len(covered_important) / max(1, len(important)), 4),
        }

    def metrics(selected: set[tuple[str, str]], additions: set[tuple[str, str]], ranked_only: set,
                selection_sides: Counter, setting: str) -> dict:
        after_mandatory = ranked_only | set(mandatory)
        mutual = {key for key in ranked_only if selection_sides[key] == 2}
        unilateral = {key for key in ranked_only if selection_sides[key] == 1}
        mandatory_only = set(mandatory) - ranked_only
        return {
            "setting": setting,
            **stage_stats(selected),
            "comparative_ranking_stage": stage_stats(ranked_only),
            "mandatory_union_stage": stage_stats(after_mandatory),
            "coverage_repair_stage": stage_stats(selected),
            "ranked_only_pairs": len(ranked_only), "mandatory_pairs": len(selected & set(mandatory)),
            "mandatory_added_pairs": len(mandatory_only), "repair_added_pairs": len(additions),
            "mutually_selected_pairs": len(mutual), "unilaterally_selected_pairs": len(unilateral),
            "gold_in_mutual": len(mutual & gold), "gold_in_unilateral": len(unilateral & gold),
            "gold_in_mandatory": len(set(mandatory) & selected & gold),
            "gold_in_mandatory_only": len(mandatory_only & gold),
            "gold_in_repair": len(additions & gold),
        }

    top_k_results = []
    diagnostics = []
    for top_k in TOP_K_SETTINGS:
        directed = {(source, target) for source, ranks in rank_by_source.items()
                    for target, rank in ranks.items() if rank <= top_k}
        ranked_pairs = {pair(source, target) for source, target in directed}
        selection_sides = Counter(pair(source, target) for source, target in directed)
        selected_before_repair = ranked_pairs | set(mandatory)
        selected, additions = repair(selected_before_repair)
        top_k_results.append(metrics(selected, additions, ranked_pairs, selection_sides, f"Top-{top_k}"))
        for source, ranks in rank_by_source.items():
            rows = []
            for target, rank_value in sorted(ranks.items(), key=lambda item: item[1]):
                key = pair(source, target)
                rows.append({"target": target, "rank": rank_value,
                             "selected": key in selected,
                             "reciprocal_selected": ranks[target] <= top_k and
                                 rank_by_source.get(target, {}).get(source, 10_000) <= top_k,
                             "mandatory": key in mandatory, "repair_added": key in additions,
                             "is_gold": key in gold})
            diagnostics.append({"setting": f"Top-{top_k}", "source": source, "candidates": rows})

    def evaluate_budgets(score_field: str, scoring_method: str) -> tuple[list[dict], list[dict]]:
        ordered_pairs = sorted(candidates, key=lambda key: (-pair_features[key][score_field], key))
        budget_results = []
        shortlist_rows = []
        for budget in GLOBAL_BUDGETS:
            # Mandatory rows consume budget; remaining slots take highest comparative scores.
            selected = set(mandatory)
            for key in ordered_pairs:
                if len(selected) >= budget:
                    break
                selected.add(key)
            # Coverage repair may replace the lowest nonmandatory rows to remain inside budget.
            repaired, additions = repair(selected, score_field)
            if len(repaired) > budget:
                removable = sorted((key for key in repaired if key not in mandatory and key not in additions),
                                   key=lambda key: pair_features[key][score_field])
                degree = Counter(node_id for key in repaired for node_id in key)
                for key in removable:
                    if len(repaired) <= budget:
                        break
                    if any(node_id in important and degree[node_id] <= 1 for node_id in key):
                        continue
                    repaired.remove(key)
                    degree[key[0]] -= 1
                    degree[key[1]] -= 1
            ranked_only = repaired - set(mandatory) - additions
            # At global budgets, reciprocal means both endpoints placed the pair in their Top-5;
            # unilateral means exactly one did. Lower-ranked score-only pairs remain uncategorized.
            budget_selection_sides = Counter()
            for key in ranked_only:
                budget_selection_sides[key] = ((pair_features[key]["rank_a"] <= 5)
                                               + (pair_features[key]["rank_b"] <= 5))
            result = metrics(repaired, additions, ranked_only, budget_selection_sides,
                             f"Budget-{budget}")
            result["scoring_method"] = scoring_method
            budget_results.append(result)
            for key in sorted(repaired):
                shortlist_rows.append({"budget": budget, "scoring_method": scoring_method,
                                       "node_a": key[0], "node_b": key[1],
                                       **pair_features[key], "is_gold": key in gold,
                                       "repair_added": key in additions})
        return budget_results, shortlist_rows

    budget_results, budget_shortlists = evaluate_budgets("score", "degree_normalized")
    raw_budget_results, raw_budget_shortlists = evaluate_budgets(
        "raw_reciprocal_score", "raw_reciprocal_baseline")
    budget_shortlists += raw_budget_shortlists

    absolute_pairs = set(candidates)
    report = {
        "frozen_policy": FROZEN_POLICY,
        "frozen_policy_sha256": POLICY_HASH,
        "initial_candidates": initial_count,
        "related_candidates": len(candidates),
        "gold_total": len(gold),
        "gold_after_absolute_filter": len(absolute_pairs & gold),
        "gold_recall_after_absolute_filter": round(len(absolute_pairs & gold) / max(1, len(gold)), 4),
        "mandatory_candidates": len(mandatory),
        "ranking_completion": {"nodes": len(rankings),
                               "complete": sum(row["complete_model_ranking"] for row in rankings),
                               "fallback": sum(not row["complete_model_ranking"] for row in rankings)},
        "top_k_curve": top_k_results,
        "global_budget_curve": budget_results,
        "raw_reciprocal_budget_curve": raw_budget_results,
        "gate_target": {"minimum_gold_recall": .90,
                        "smallest_passing_top_k": next((row["setting"] for row in top_k_results
                                                        if row["gold_recall"] >= .90), None),
                        "smallest_passing_budget": next((row["setting"] for row in budget_results
                                                         if row["gold_recall"] >= .90), None)},
        "raw_reciprocal_gate": {
            "smallest_passing_budget": next((row["setting"] for row in raw_budget_results
                                               if row["gold_recall"] >= .90), None)},
        "scoring_note": ("The primary global curve normalizes rank by each source node's candidate degree. "
                         "The original raw reciprocal-rank curve is retained as a baseline."),
        "note": "is_gold exists only in offline diagnostics and was never included in ranking prompts.",
    }
    write_json(ranking / "evaluation.json", report)
    write_json(ranking / "policy_manifest.json", {
        "frozen_policy": FROZEN_POLICY,
        "frozen_policy_sha256": POLICY_HASH,
    })
    write_jsonl(ranking / "ranking_diagnostics.jsonl", diagnostics)
    write_jsonl(ranking / "budget_shortlists.jsonl", budget_shortlists)
    write_jsonl(ranking / "mandatory_candidates.jsonl", [
        {"node_a": key[0], "node_b": key[1], "mandatory_reasons": reasons,
         "is_gold": key in gold} for key, reasons in sorted(mandatory.items())])
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
