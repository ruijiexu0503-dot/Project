#!/usr/bin/env python3
"""CPU-only recovery replay over discarded frozen P1/P2 Top-20 pairs.

Ranking is completed before the gold-derived oracle matrix is opened.  The
cached query-window dot products are reused as the query-to-node signal; no
embedding, verifier, reranker, LLM, or production pipeline is run.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import time
from typing import Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "migration/vldocir_trace_inputs_20261023"
SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
P12 = ROOT / "EvidenceNet/output/kg_link_prediction_p1_p2_20261102"
KG = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v2_20261102"
NAV = ROOT / "EvidenceNet/output/top10_node_navigation_20261029/navigation.jsonl"
ALLOCATION = ROOT / "EvidenceNet/output/coverage_aware_candidate_allocation_v2_20261105"
ORACLE = ROOT / "EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/query_coverage_matrix.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/query_conditioned_discarded_pair_recovery_v1_20261105"
VERSION = "query-conditioned-discarded-pair-recovery-v1-20261105"
BUDGETS = (3, 5, 10)
RRF_K = 60
ARMS = ("B0_pair_score", "B1_source_local_rank", "Q0_query_target", "Q1_query_pair_structure_rrf")


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(source: str, target: str) -> tuple[str, str]:
    if source == target:
        raise ValueError("self pair")
    return tuple(sorted((str(source), str(target))))


def dense_scores_by_query() -> tuple[dict[str, dict[str, float]], dict]:
    """Rebuild the exact max-window node scores used by frozen navigation."""
    query_rows = rows(TRACE / "queries.jsonl")
    units = rows(TRACE / "units.jsonl")
    windows = rows(TRACE / "windows.jsonl")
    scores = np.load(SOURCE / "search/query_window_scores.npy", mmap_mode="r", allow_pickle=False)
    encoding = json.loads((SOURCE / "search/encoding.json").read_text())
    if sha(SOURCE / "search/query_window_scores.npy") != encoding["score_sha256"]:
        raise ValueError("changed query-window score cache")
    for name in ("queries.jsonl", "units.jsonl", "windows.jsonl"):
        if sha(TRACE / name) != encoding["inputs_sha256"][name]:
            raise ValueError("changed score row mapping: " + name)
    if scores.shape != (len(query_rows), len(windows)):
        raise ValueError("query-window score shape mismatch")
    result = {}
    for qi, query in enumerate(query_rows):
        node_scores = {}
        for wi, window in enumerate(windows):
            node_id = units[int(window["unit_input_line"]) - 1]["unit_id"]
            score = float(scores[qi, wi])
            if score > node_scores.get(node_id, -float("inf")):
                node_scores[node_id] = score
        result[query["question_id"]] = node_scores
    return result, {
        "cache_shape": list(scores.shape),
        "cache_model": encoding["model"],
        "signal": "max frozen query-window dot product per EvidenceNode",
        "raw_query_vector_file_available": False,
        "note": "The cached dot products preserve query-to-window similarities; query vectors themselves are absent.",
    }


def build_adjacency(edges: list[dict], eligible: set[str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source, target = str(edge["source_id"]), str(edge["target_id"])
        if source not in eligible or target not in eligible:
            continue
        graph[source].add(target)
        if edge.get("relation_id") == "RELATED_OPEN" or not edge.get("directed", True):
            graph[target].add(source)
    return graph


def rank_positions(values: list[dict], key) -> dict[int, int]:
    order = sorted(range(len(values)), key=lambda index: key(values[index]))
    return {index: rank for rank, index in enumerate(order, 1)}


def attach_scores(candidates: list[dict], seed_rank: dict[str, int], node_scores: dict[str, float],
                  adjacency: dict[str, set[str]]) -> list[dict]:
    enriched = []
    for row in candidates:
        neighbors = adjacency.get(row["source_id"], set())
        neighbor_scores = [node_scores[node] for node in neighbors if node in node_scores]
        enriched.append(dict(
            row,
            seed_rank=seed_rank[row["source_id"]],
            query_source_score=node_scores[row["source_id"]],
            query_target_score=node_scores[row["target_id"]],
            source_graph_degree=len(neighbors),
            query_neighbor_support=max(neighbor_scores) if neighbor_scores else None,
            selected_global_1088=False,
        ))
    if not enriched:
        return enriched
    pair_rank = rank_positions(enriched, lambda row: (-float(row["raw_score"]), row["source_id"], row["target_id"]))
    local_rank = rank_positions(enriched, lambda row: (int(row["rank_within_source"]), -float(row["raw_score"]), row["source_id"], row["target_id"]))
    target_rank = rank_positions(enriched, lambda row: (-float(row["query_target_score"]), row["target_id"], row["source_id"]))
    seed_order = rank_positions(enriched, lambda row: (int(row["seed_rank"]), row["source_id"], row["target_id"]))
    neighbor_rank = rank_positions(enriched, lambda row: (
        row["query_neighbor_support"] is None,
        -float(row["query_neighbor_support"] or -1e30), row["source_id"], row["target_id"]))
    for index, row in enumerate(enriched):
        components = {
            "pair_score_rank": pair_rank[index],
            "source_local_rank_order": local_rank[index],
            "query_target_rank": target_rank[index],
            "seed_rank_order": seed_order[index],
            "query_neighbor_support_rank": neighbor_rank[index],
        }
        row["rrf_components"] = components
        row["query_pair_structure_rrf"] = sum(1 / (RRF_K + rank) for rank in components.values())
    return enriched


def arm_order(arm: str, row: dict) -> tuple:
    lexical = (row["source_id"], row["target_id"])
    if arm == "B0_pair_score":
        return (-float(row["raw_score"]), int(row["rank_within_source"])) + lexical
    if arm == "B1_source_local_rank":
        return (int(row["rank_within_source"]), -float(row["raw_score"])) + lexical
    if arm == "Q0_query_target":
        return (-float(row["query_target_score"]), -float(row["raw_score"])) + lexical
    if arm == "Q1_query_pair_structure_rrf":
        return (-float(row["query_pair_structure_rrf"]), -float(row["query_target_score"])) + lexical
    raise ValueError(arm)


def rank_and_select(candidates: list[dict], arm: str, budget: int) -> tuple[list[dict], list[dict]]:
    """Rank directed seed routes, then expose at most one route per target."""
    ranked = sorted(candidates, key=lambda row: arm_order(arm, row))
    selected, seen_targets = [], set()
    decisions = []
    for pair_rank, row in enumerate(ranked, 1):
        if row["target_id"] in seen_targets:
            decision = "duplicate_target"
        elif len(selected) >= budget:
            decision = "budget_full"
        else:
            decision = "selected"
            seen_targets.add(row["target_id"])
            selected.append(dict(row, arm=arm, budget=budget,
                                 selected_target_rank=len(selected) + 1,
                                 pair_rank_for_arm=pair_rank))
        decisions.append(dict(row, arm=arm, budget=budget,
                              pair_rank_for_arm=pair_rank, decision=decision))
    return selected, decisions


def make_query_pools(rankings: list[dict], global_rows: list[dict], navigation: list[dict],
                     node_scores: dict[str, dict[str, float]], adjacency: dict[str, set[str]],
                     eligible: set[str]) -> tuple[dict[str, list[dict]], dict]:
    selected_global = {canonical(row["source_id"], row["target_id"]) for row in global_rows}
    by_source = defaultdict(list)
    directed_keys = set()
    rank_errors = []
    for row in rankings:
        key = (row["source_id"], row["target_id"])
        if key in directed_keys:
            raise ValueError("duplicate directed proposer row: " + str(key))
        directed_keys.add(key)
        by_source[row["source_id"]].append(row)
    for source, values in by_source.items():
        ranks = sorted(int(row["rank_within_source"]) for row in values)
        if ranks != list(range(1, 21)):
            rank_errors.append(source)
    if rank_errors:
        raise ValueError("ambiguous/incomplete source-local ranks")

    pools = {}
    seed_filter_changes = []
    for context in navigation:
        qid = context["question_id"]
        ranking = [node for node in context["node_ranking"] if node in eligible]
        seeds = ranking[:10]
        original_eligible_seeds = [node for node in context["seed_nodes"] if node in eligible]
        if seeds != original_eligible_seeds:
            seed_filter_changes.append({
                "question_id": qid,
                "original_seed_count_after_eligibility_filter": len(original_eligible_seeds),
                "replacement_count": len(set(seeds) - set(original_eligible_seeds)),
            })
        if sorted(ranking, key=lambda node: (-node_scores[qid][node], node)) != ranking:
            raise ValueError("cached query scores do not reconstruct navigation: " + qid)
        seed_set = set(seeds)
        raw = []
        for source in seeds:
            for row in by_source[source]:
                pair = canonical(row["source_id"], row["target_id"])
                if pair in selected_global or row["target_id"] in seed_set:
                    continue
                raw.append(dict(row, canonical_pair=list(pair),
                                allocation_status="discarded_by_global_top1088"))
        pools[qid] = attach_scores(raw, {node: rank for rank, node in enumerate(seeds, 1)},
                                   node_scores[qid], adjacency)
    reverse = defaultdict(list)
    for row in rankings:
        reverse[canonical(row["source_id"], row["target_id"])].append(row)
    reverse_pairs = [values for values in reverse.values() if len(values) > 1]
    ambiguity = {
        "ranking_rows": len(rankings), "sources": len(by_source),
        "directed_rank_is_complete_1_to_20": True,
        "canonical_pairs_with_multiple_directed_rows": len(reverse_pairs),
        "canonical_pairs_with_different_reverse_local_ranks": sum(
            len({int(row["rank_within_source"]) for row in values}) > 1 for values in reverse_pairs),
        "resolution": "retain directed Top10-seed source rank; canonical pair is used only for allocation-status and evaluation matching",
        "seed_definition": "first 10 nodes after preserving dense order and filtering to the frozen 6,520-node universe",
        "queries_where_filtering_replaced_an_original_navigation_seed": seed_filter_changes,
    }
    return pools, ambiguity


def freeze_rankings(pools_by_proposer: dict[str, dict[str, list[dict]]]) -> tuple[list[dict], list[dict]]:
    selections, decisions = [], []
    for proposer in ("p1", "p2"):
        for qid in sorted(pools_by_proposer[proposer]):
            pool = pools_by_proposer[proposer][qid]
            for arm in ARMS:
                for budget in BUDGETS:
                    selected, trace = rank_and_select(pool, arm, budget)
                    selections.extend(dict(row, proposer=proposer, question_id=qid) for row in selected)
                    decisions.extend(dict(row, proposer=proposer, question_id=qid) for row in trace)
    return selections, decisions


def gold_opportunities(matrix: list[dict], proposer: str) -> list[dict]:
    field = "p1_seed_to_gold_pairs" if proposer == "p1" else "p2_seed_to_gold_pairs"
    result = []
    for query in matrix:
        missing_pages = {tuple(page) for page in query["missing_top10_gold_pages"]}
        for item in query["gold_item_diagnostics"]:
            page = (item["document_id"], int(item["page_number"]))
            if page not in missing_pages:
                continue
            result.append({
                "question_id": query["question_id"], "gold_id": item["gold_id"],
                "page": list(page), "classification": query["classification"],
                "localized_candidate_ids": sorted(row["node_id"] for row in item["eligible_strong_candidates"]),
                "pool_pairs": sorted({canonical(row["source_id"], row["target_id"]) for row in item[field]}),
            })
    return result


def evaluate(selections: list[dict], matrix: list[dict], navigation: dict[str, dict],
             eligible: set[str]) -> tuple[dict, list[dict], dict]:
    selected_by_arm = defaultdict(list)
    for row in selections:
        selected_by_arm[(row["proposer"], row["arm"], int(row["budget"]), row["question_id"])].append(row)
    summary, diagnostics = {}, []
    for proposer in ("p1", "p2"):
        opportunities = gold_opportunities(matrix, proposer)
        supported = [item for item in opportunities if item["pool_pairs"]]
        summary[proposer] = {}
        for arm in ARMS:
            summary[proposer][arm] = {}
            for budget in BUDGETS:
                recovered = 0
                query_recovered = set()
                selected_total = 0
                beyond20 = 0
                on_gold_page = 0
                for query in matrix:
                    qid = query["question_id"]
                    chosen = selected_by_arm[(proposer, arm, budget, qid)]
                    selected_total += len(chosen)
                    frozen_ranking = [node for node in navigation[qid]["node_ranking"] if node in eligible]
                    dense_rank = {node: rank for rank, node in enumerate(frozen_ranking, 1)}
                    gold_pages = {tuple(page) for page in query["gold_pages"]}
                    for row in chosen:
                        beyond20 += dense_rank[row["target_id"]] > 20
                        page = tuple(navigation[qid]["node_pages"][row["target_id"]])
                        page = (page[0], int(page[1]))
                        on_gold_page += page in gold_pages
                for item in supported:
                    chosen = selected_by_arm[(proposer, arm, budget, item["question_id"])]
                    chosen_pairs = {canonical(row["source_id"], row["target_id"]) for row in chosen}
                    hits = sorted(chosen_pairs & set(item["pool_pairs"]))
                    if hits:
                        recovered += 1
                        query_recovered.add(item["question_id"])
                    diagnostics.append({**item, "proposer": proposer, "arm": arm, "budget": budget,
                                        "recovered": bool(hits), "selected_matching_pairs": [list(x) for x in hits]})
                summary[proposer][arm][str(budget)] = {
                    "selected_candidate_routes": selected_total,
                    "missing_top10_pool_supported_gold_items": len(supported),
                    "missing_top10_pool_supported_gold_items_recovered": recovered,
                    "candidate_recall_on_pool_supported_missing_items": recovered / len(supported) if supported else None,
                    "queries_with_recovery": sorted(query_recovered),
                    "selected_targets_beyond_dense_top20": beyond20,
                    "selected_targets_on_any_annotated_gold_page": on_gold_page,
                    "annotated_gold_page_rate_weak_proxy": on_gold_page / selected_total if selected_total else None,
                    "warning": "Unverified candidate coverage only; annotated-page match is not a relevance/precision label.",
                }
    generation_absent = []
    for query in matrix:
        if query["classification"] != "MISSING_GOLD_ORACLE_SEMANTIC_ONLY":
            continue
        for item in query["gold_item_diagnostics"]:
            page = [item["document_id"], int(item["page_number"])]
            if page not in query["missing_top10_gold_pages"]:
                continue
            generation_absent.append({
                "question_id": query["question_id"], "question": query["question"],
                "gold_id": item["gold_id"], "page": page,
                "eligible_localized_targets": sorted(row["node_id"] for row in item["eligible_strong_candidates"]),
                "p1_seed_pair_count": len(item["p1_seed_to_gold_pairs"]),
                "p2_seed_pair_count": len(item["p2_seed_to_gold_pairs"]),
                "reason": "No Top10-seed-to-localized-target route exists in the frozen per-source Top20 proposer pool; allocation replay cannot recover a pair that was never generated.",
            })
    separate = {
        "oracle_semantic_only_items": generation_absent,
        "queries": sorted({item["question_id"] for item in generation_absent}),
        "excluded_from_allocation_recovery_denominator": True,
        "node_anchor_gap_query_separately_excluded": sorted(
            query["question_id"] for query in matrix
            if query["classification"] == "MISSING_GOLD_NODE_ANCHOR_GRANULARITY_GAP"),
    }
    return summary, diagnostics, separate


def quantiles(values: list[float]) -> dict:
    if not values:
        return {}
    values = sorted(values)
    at = lambda p: float(values[round((len(values) - 1) * p)])
    return {"min": float(values[0]), "p10": at(.1), "median": at(.5),
            "p90": at(.9), "max": float(values[-1]), "mean": statistics.fmean(values)}


def pool_summary(pools: dict[str, list[dict]]) -> dict:
    sizes = [len(value) for value in pools.values()]
    targets = [len({row["target_id"] for row in value}) for value in pools.values()]
    return {
        "queries": len(pools), "route_count": sum(sizes),
        "routes_per_query": quantiles([float(x) for x in sizes]),
        "unique_targets_per_query": quantiles([float(x) for x in targets]),
        "scope": dict(sorted(Counter(row["candidate_scope"] for value in pools.values() for row in value).items())),
        "graph_context_routes": sum(bool(row.get("graph_context_used")) for value in pools.values() for row in value),
    }


def report_lines(summary: dict) -> list[str]:
    lines = [
        "# Query-conditioned Recovery from Discarded P1/P2 Pairs", "",
        "## Feasibility and frozen inputs", "",
        "The experiment is feasible over the complete frozen proposer Top-20 pool: 130,400 directed rows per proposer (6,520 sources × 20), not an exhaustive all-pairs universe. Every row retains source, target, pair score, source-local rank, scope, and P2 graph provenance. Global allocation status is reconstructed by canonical-pair membership in the frozen Top-1,088 outputs.", "",
        "Directed source-local ranks are exactly 1–20 and unambiguous. Reverse directions can have different local ranks after undirected canonicalization, so this replay keeps the Top-10 seed as the route source and deduplicates only target exposure.", "",
        "Raw 0.6B query vectors were not retained. The frozen 24×10,301 query-window dot-product cache remains intact and exactly reconstructs the frozen node ranking, so its max-per-node score is reused. The 8B node similarity is the existing P1/P2 pair score. No cross-model vector dot product is attempted.", "",
        "## Arms", "",
        "- `B0_pair_score`: query-agnostic raw pair score.",
        "- `B1_source_local_rank`: query-agnostic source-local rank, then pair score.",
        "- `Q0_query_target`: frozen query→target node score, then pair score.",
        "- `Q1_query_pair_structure_rrf`: fixed RRF(k=60) over target-query rank, pair-score rank, source-local-rank order, dense seed rank, and query relevance of the source's observed graph neighborhood.", "",
        "All arms rank the same globally discarded, Top-10-seed-originated routes. Top-3/5/10 budgets expose unique targets. Gold is opened only after rankings are serialized.", "",
        "## Missing-item recovery", "",
    ]
    for proposer in ("p1", "p2"):
        lines += [f"### {proposer.upper()}", "", "| Arm | Top-3 | Top-5 | Top-10 | Beyond Top-20 at K=10 | Gold-page proxy at K=10 |", "|---|---:|---:|---:|---:|---:|"]
        for arm in ARMS:
            values = summary["posthoc_evaluation"][proposer][arm]
            cells = [f"{values[str(k)]['missing_top10_pool_supported_gold_items_recovered']}/4" for k in BUDGETS]
            k10 = values["10"]
            lines.append(f"| {arm} | {cells[0]} | {cells[1]} | {cells[2]} | {k10['selected_targets_beyond_dense_top20']}/{k10['selected_candidate_routes']} | {k10['annotated_gold_page_rate_weak_proxy']:.3f} |")
        lines.append("")
    lines += [
        "The denominator contains only the four missing Gold items whose localized target already has a frozen P1/P2 route from a Top-10 seed. Recovery means only that an unverified pair/target was exposed; it is not verified-edge recovery or evidence recall.", "",
        "## Exact Q1 Top-3 recoveries", "",
        "| Proposer | Query | Gold item | Source → target | Pair score / local rank | Target dense rank | Graph context |", "|---|---|---|---|---:|---:|---|"
    ]
    for item in summary["top3_q1_recovered_routes"]:
        lines.append(f"| {item['proposer'].upper()} | `{item['question_id']}` | `{item['gold_id']}` | `{item['source_id']}` → `{item['target_id']}` | {item['pair_score']:.4f} / {item['source_local_rank']} | {item['target_dense_rank']} | {item['graph_context_used']} |")
    lines += [
        "", "P1 and P2 recover the same two routes at Top-3. This agreement does not validate either relation; it only shows that the query-conditioned ordering is stable across the two frozen proposer views for these cases.", "",
        "## Candidate-generation absences (separate)", "",
        "These cases are excluded from allocation-recovery metrics because no eligible route exists in the frozen Top-20 pool:", "",
        "| Query | Gold item | Localized target | P1/P2 seed pairs | Reason |", "|---|---|---|---:|---|"]
    for item in summary["candidate_generation_absent"]["oracle_semantic_only_items"]:
        target = ", ".join(f"`{value}`" for value in item["eligible_localized_targets"])
        lines.append(f"| `{item['question_id']}` | `{item['gold_id']}` | {target} | {item['p1_seed_pair_count']}/{item['p2_seed_pair_count']} | Target never entered any Top-10 seed's proposer Top-20. |")
    lines += ["", "The headline/anchor-granularity gap is also excluded: " + ", ".join(
        f"`{qid}`" for qid in summary["candidate_generation_absent"]["node_anchor_gap_query_separately_excluded"]) + ". It has no reliable localized target node and is not a candidate-generation allocation failure.", "",
        "## Interpretation", "",
        "- **Unverified Candidate Recovery:** what this replay measures.",
        "- **Verified Edge Recovery:** not measured; no verifier or human audit was run.",
        "- **Final Evidence Recall:** not measured; no navigation, reranker, or answer evaluation was run.",
        "- A selected target not matching an annotated gold page is only a risk proxy, not an irrelevant/negative label. VL-DocIR annotations do not license treating every other node as irrelevant.", "",
        "**Recommendation:** Q1 qualifies for a tightly bounded anchor-local verification pilot of the two distinct recovered routes above. Do not verify all 72 Top-3 exposures and do not promote either route to navigation. Freeze the Q1 ranking first, then independently audit the source/target spans and factual relation. The unrecovered H₂/H₀ item and the second Federer item remain ranking/construction failures; the three Oracle-only queries remain candidate-construction failures."]
    return lines


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: Iterable[dict]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def run(output: Path) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError("fresh output required: " + str(output))
    inputs = {
        "p1_rankings": P12 / "p1_text_only_rankings.jsonl",
        "p2_rankings": P12 / "p2_text_graph_rankings.jsonl",
        "p1_global": P12 / "p1_fixed_budget_candidates.jsonl",
        "p2_global": P12 / "p2_fixed_budget_candidates.jsonl",
        "navigation": NAV,
        "candidate_universe": KG / "candidate_universe.jsonl",
        "context_edges": KG / "observed_context_edges.jsonl",
        "query_window_scores": SOURCE / "search/query_window_scores.npy",
        "score_encoding": SOURCE / "search/encoding.json",
        "queries": TRACE / "queries.jsonl", "units": TRACE / "units.jsonl", "windows": TRACE / "windows.jsonl",
        "oracle_matrix_posthoc_only": ORACLE,
    }
    for path in inputs.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    started = time.perf_counter()
    eligible = {row["entity_id"] for row in rows(inputs["candidate_universe"])
                if row.get("primary_eligible") is True}
    if len(eligible) != 6520:
        raise ValueError("frozen universe changed")
    navigation_rows = rows(inputs["navigation"])
    navigation = {row["question_id"]: row for row in navigation_rows}
    node_scores, score_audit = dense_scores_by_query()
    adjacency = build_adjacency(rows(inputs["context_edges"]), eligible)
    rankings = {"p1": rows(inputs["p1_rankings"]), "p2": rows(inputs["p2_rankings"])}
    globals_ = {"p1": rows(inputs["p1_global"]), "p2": rows(inputs["p2_global"])}
    pools, rank_audit = {}, {}
    for proposer in ("p1", "p2"):
        pools[proposer], rank_audit[proposer] = make_query_pools(
            rankings[proposer], globals_[proposer], navigation_rows, node_scores, adjacency, eligible)
    selections, decisions = freeze_rankings(pools)

    output.mkdir(parents=True)
    # Allocation-free rankings are persisted before the gold-derived matrix is opened.
    write_jsonl(output / "discarded_pair_pools.jsonl", (
        dict(row, proposer=proposer, question_id=qid)
        for proposer in ("p1", "p2") for qid in sorted(pools[proposer]) for row in pools[proposer][qid]))
    write_jsonl(output / "recovery_selections.jsonl", selections)
    write_jsonl(output / "recovery_ranking_decisions.jsonl", decisions)
    frozen_hashes = {name: sha(output / name) for name in
                     ("discarded_pair_pools.jsonl", "recovery_selections.jsonl", "recovery_ranking_decisions.jsonl")}

    matrix = rows(inputs["oracle_matrix_posthoc_only"])
    evaluation, diagnostics, absent = evaluate(selections, matrix, navigation, eligible)
    write_jsonl(output / "posthoc_gold_diagnostics.jsonl", diagnostics)
    selection_index = {(row["proposer"], row["question_id"], row["arm"], int(row["budget"]),
                        canonical(row["source_id"], row["target_id"])): row for row in selections}
    top3_recovered = []
    for item in diagnostics:
        if item["arm"] != "Q1_query_pair_structure_rrf" or item["budget"] != 3 or not item["recovered"]:
            continue
        for pair_list in item["selected_matching_pairs"]:
            pair = tuple(pair_list)
            selected = selection_index[(item["proposer"], item["question_id"], item["arm"], 3, pair)]
            frozen_ranking = [node for node in navigation[item["question_id"]]["node_ranking"]
                              if node in eligible]
            dense_rank = frozen_ranking.index(selected["target_id"]) + 1
            top3_recovered.append({
                "proposer": item["proposer"], "question_id": item["question_id"],
                "gold_id": item["gold_id"], "source_id": selected["source_id"],
                "target_id": selected["target_id"], "pair_score": float(selected["raw_score"]),
                "source_local_rank": int(selected["rank_within_source"]),
                "target_dense_rank": dense_rank, "candidate_scope": selected["candidate_scope"],
                "graph_context_used": bool(selected.get("graph_context_used")),
                "rrf_score": float(selected["query_pair_structure_rrf"]),
            })
    top3_recovered.sort(key=lambda row: (row["proposer"], row["question_id"], row["gold_id"]))
    summary = {
        "version": VERSION, "status": "QUERY_CONDITIONED_DISCARDED_PAIR_REPLAY_COMPLETE",
        "execution_boundary": {"cpu_only": True, "llm_calls": 0, "gpu_used": False,
                               "embeddings_generated": 0, "reranker_run": False,
                               "verification_run": False, "production_pipeline_modified": False},
        "scope": {"frozen_nodes": len(eligible), "queries": len(navigation),
                  "budgets_per_query": list(BUDGETS), "arms": list(ARMS)},
        "query_signal_audit": score_audit,
        "source_local_rank_audit": rank_audit,
        "discarded_pool": {proposer: pool_summary(pools[proposer]) for proposer in ("p1", "p2")},
        "posthoc_evaluation": evaluation,
        "top3_q1_recovered_routes": top3_recovered,
        "candidate_generation_absent": absent,
        "interpretation": {
            "measured": "unverified candidate recovery",
            "not_measured": ["verified edge recovery", "navigable edge coverage", "final evidence recall", "retrieval improvement"],
            "non_gold_is_negative": False,
        },
        "timing_seconds": time.perf_counter() - started,
    }
    protocol = {
        "version": VERSION, "rrf_k": RRF_K, "arms": list(ARMS), "budgets": list(BUDGETS),
        "candidate_rule": "directed source in frozen Dense Top10; P1/P2 Top20 row; canonical pair absent from frozen global Top1088; target outside seeds",
        "target_deduplication": "rank routes first, expose first route per unique target",
        "ranking_inputs": [name for name in inputs if name != "oracle_matrix_posthoc_only"],
        "posthoc_only_input": "oracle_matrix_posthoc_only",
        "gold_or_query_id_used_for_parameter_selection": False,
        "parameters_fixed_without_gold": {"rrf_k": RRF_K, "budgets": list(BUDGETS)},
        "frozen_ranking_hashes_before_gold_read": frozen_hashes,
    }
    write_json(output / "replay_protocol.json", protocol)
    write_json(output / "summary.json", summary)
    (output / "REPORT.md").write_text("\n".join(report_lines(summary)) + "\n", encoding="utf-8")
    manifest = {
        "version": VERSION,
        "inputs": {name: {"path": str(path.resolve()), "sha256": sha(path)} for name, path in inputs.items()},
        "pre_gold_outputs": frozen_hashes,
        "outputs": {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()},
        "code": {
            str(Path(__file__).resolve()): sha(Path(__file__).resolve()),
            str((ROOT / "EvidenceNet/tests/test_query_conditioned_discarded_pairs.py").resolve()):
                sha(ROOT / "EvidenceNet/tests/test_query_conditioned_discarded_pairs.py"),
        },
    }
    write_json(output / "manifest.json", manifest)
    return summary


def check(output: Path) -> None:
    manifest = json.loads((output / "manifest.json").read_text())
    for item in manifest["inputs"].values():
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("changed input: " + item["path"])
    for name, expected in manifest["outputs"].items():
        if sha(output / name) != expected:
            raise ValueError("changed output: " + name)
    for raw, expected in manifest["code"].items():
        if sha(Path(raw)) != expected:
            raise ValueError("changed code: " + raw)
    print("QUERY_CONDITIONED_DISCARDED_PAIR_REPLAY_OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run"); execute.add_argument("--out", type=Path, default=DEFAULT_OUT)
    verify = sub.add_parser("check"); verify.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.command == "run":
        print(json.dumps(run(args.out), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        check(args.out)


if __name__ == "__main__":
    main()
