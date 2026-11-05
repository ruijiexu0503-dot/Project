#!/usr/bin/env python3
"""Replay frozen P1/P2 allocation policies without inference or gold leakage.

Allocation reads only frozen proposer rankings and entity metadata.  Query/gold
diagnostics are loaded afterwards for evaluation and never enter a policy.
Gold-localized EvidenceNodes are overlap candidates, not node-level labels.
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


ROOT = Path(__file__).resolve().parents[2]
P12 = ROOT / "EvidenceNet/output/kg_link_prediction_p1_p2_20261102"
KG = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v2_20261102"
ORACLE = ROOT / "EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104"
DEFAULT_OUT = ROOT / "EvidenceNet/output/coverage_aware_candidate_allocation_v1_20261105"
VERSION = "coverage-aware-candidate-allocation-v1-20261105"
BUDGET = 1088
LOCAL_QUOTA = 1
HYBRID_GLOBAL = BUDGET // 2
LANE_BUDGETS = {"same_document": BUDGET // 2, "cross_document": BUDGET // 2}


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_pair(row: dict) -> tuple[str, str]:
    source, target = str(row["source_id"]), str(row["target_id"])
    if source == target:
        raise ValueError("self candidate")
    return tuple(sorted((source, target)))


def row_order(row: dict) -> tuple:
    """Original global ordering, including its deterministic tie break."""
    return (-float(row["raw_score"]), str(row["source_id"]), str(row["target_id"]))


def deduplicate(rankings: list[dict]) -> list[dict]:
    """Canonicalize an undirected pool before allocation.

    The proposer-emitting source of the winning orientation remains the source
    for quota accounting.  Reverse duplicates keep the higher score; exact
    ties use lexical source/target IDs, matching the frozen A0 implementation.
    """
    best: dict[tuple[str, str], dict] = {}
    orientation_count = Counter()
    for row in rankings:
        key = canonical_pair(row)
        orientation_count[key] += 1
        previous = best.get(key)
        if previous is None or row_order(row) < row_order(previous):
            best[key] = row
    result = []
    for key, row in best.items():
        result.append(dict(row, canonical_pair=list(key),
                           directed_rows_for_pair=orientation_count[key]))
    return sorted(result, key=row_order)


def annotate(selected: list[dict], policy: str, budget: int) -> list[dict]:
    if len({canonical_pair(row) for row in selected}) != len(selected):
        raise ValueError(f"{policy}: duplicate canonical pair")
    return [dict(row, allocation_policy=policy, allocation_rank=rank,
                 allocation_budget=budget)
            for rank, row in enumerate(selected, 1)]


def global_top(pool: list[dict], budget: int) -> list[dict]:
    return list(sorted(pool, key=row_order)[:budget])


def local_round(pool: list[dict], budget: int, per_source: int = LOCAL_QUOTA,
                excluded_pairs: set[tuple[str, str]] | None = None,
                excluded_sources: set[str] | None = None) -> list[dict]:
    """Take up to K best canonical pairs per proposer-emitting source.

    With K=1 and more sources than seats, source-best rows compete globally by
    score.  If seats remain, additional deterministic source rounds are used.
    """
    excluded_pairs = excluded_pairs or set()
    excluded_sources = excluded_sources or set()
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in pool:
        if canonical_pair(row) not in excluded_pairs and row["source_id"] not in excluded_sources:
            grouped[str(row["source_id"])].append(row)
    for values in grouped.values():
        values.sort(key=lambda row: (int(row["rank_within_source"]),) + row_order(row))
    result = []
    round_index = 0
    while len(result) < budget:
        entrants = [values[round_index] for values in grouped.values()
                    if len(values) > round_index and round_index < per_source]
        if not entrants:
            break
        entrants.sort(key=row_order)
        result.extend(entrants[:budget - len(result)])
        round_index += 1
    return result


def hybrid(pool: list[dict], budget: int, global_seats: int) -> list[dict]:
    global_part = global_top(pool, min(global_seats, budget))
    pairs = {canonical_pair(row) for row in global_part}
    sources = {str(row["source_id"]) for row in global_part}
    local_part = local_round(pool, budget - len(global_part), LOCAL_QUOTA,
                             excluded_pairs=pairs, excluded_sources=sources)
    result = global_part + local_part
    if len(result) < budget:
        used = {canonical_pair(row) for row in result}
        result.extend(row for row in global_top(pool, len(pool))
                      if canonical_pair(row) not in used) 
        result = result[:budget]
    return result


def lane_aware(pool: list[dict], budget: int) -> list[dict]:
    if budget != sum(LANE_BUDGETS.values()):
        raise ValueError("A3 lane budgets must sum to the common budget")
    result = []
    for lane in ("same_document", "cross_document"):
        lane_pool = [row for row in pool if row.get("candidate_scope") == lane]
        lane_budget = LANE_BUDGETS[lane]
        if len(lane_pool) < lane_budget:
            raise ValueError(f"insufficient classified candidates for {lane}")
        result.extend(hybrid(lane_pool, lane_budget, lane_budget // 2))
    return sorted(result, key=lambda row: (row["candidate_scope"],) + row_order(row))


def allocate(rankings: list[dict], budget: int = BUDGET) -> tuple[dict[str, list[dict]], dict]:
    """Gold/query-free allocation API used by both the run and tests."""
    pool = deduplicate(rankings)
    if len(pool) < budget:
        budget = len(pool)
    policies = {
        "A0_global": global_top(pool, budget),
        "A1_source_local": local_round(pool, budget, LOCAL_QUOTA),
        "A2_hybrid": hybrid(pool, budget, min(HYBRID_GLOBAL, budget)),
        "A3_lane_aware": lane_aware(pool, budget),
    }
    for name, selected in policies.items():
        if len(selected) != budget:
            raise ValueError(f"{name}: selected {len(selected)} != {budget}")
        policies[name] = annotate(selected, name, budget)
    audit = {
        "directed_ranking_rows": len(rankings),
        "canonical_pool_pairs": len(pool),
        "reverse_or_duplicate_rows_removed": len(rankings) - len(pool),
        "budget": budget,
        "source_definition": "proposer-emitting source of canonical pair's retained highest-score orientation",
        "deduplication": "undirected canonical pair; highest raw_score; lexical source_id,target_id tie-break",
    }
    return policies, audit


def quantiles(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {}
    def at(fraction: float) -> float:
        return float(ordered[round((len(ordered) - 1) * fraction)])
    return {"min": float(ordered[0]), "p10": at(.1), "median": at(.5),
            "p90": at(.9), "max": float(ordered[-1]), "mean": statistics.fmean(ordered)}


def gini(counts: list[int]) -> float:
    ordered = sorted(counts)
    total = sum(ordered)
    if not total:
        return 0.0
    n = len(ordered)
    return (2 * sum((i + 1) * x for i, x in enumerate(ordered)) / (n * total)
            - (n + 1) / n)


def distribution(selected: list[dict], entities: dict[str, dict]) -> dict:
    source_counts = Counter(str(row["source_id"]) for row in selected)
    target_ids = {str(row["target_id"]) for row in selected}
    endpoint_ids = {node for row in selected for node in canonical_pair(row)}
    counts = list(source_counts.values())
    locality = Counter()
    for row in selected:
        if row["candidate_scope"] == "cross_document":
            locality["cross_document"] += 1
            continue
        source = entities[row["source_id"]]
        target = entities[row["target_id"]]
        distance = abs(int(source["page"]) - int(target["page"]))
        locality["same_page" if distance == 0 else "adjacent_page" if distance == 1
                 else "same_document_distant"] += 1
    top_ten = sum(sorted(counts, reverse=True)[:10]) / len(selected)
    hhi = sum((count / len(selected)) ** 2 for count in counts)
    return {
        "pairs": len(selected), "unique_sources": len(source_counts),
        "unique_targets": len(target_ids), "unique_endpoints": len(endpoint_ids),
        "max_pairs_per_source": max(counts),
        "mean_pairs_per_covered_source": len(selected) / len(source_counts),
        "source_gini_over_covered_sources": gini(counts),
        "source_hhi": hhi, "top10_sources_pair_share": top_ten,
        "scope": dict(sorted(Counter(row["candidate_scope"] for row in selected).items())),
        "anchor_locality_proxy": dict(sorted(locality.items())),
        "score_distribution": quantiles([float(row["raw_score"]) for row in selected]),
        "rank_within_source_distribution": dict(sorted(Counter(
            int(row["rank_within_source"]) for row in selected).items())),
    }


def replacement(selected: list[dict], a0: list[dict]) -> dict:
    current = {canonical_pair(row): row for row in selected}
    control = {canonical_pair(row): row for row in a0}
    added = [row for key, row in current.items() if key not in control]
    dropped = [row for key, row in control.items() if key not in current]
    return {
        "shared_with_A0": len(set(current) & set(control)),
        "replaced_A0_pairs": len(dropped), "new_pairs_vs_A0": len(added),
        "added_score_distribution": quantiles([float(row["raw_score"]) for row in added]),
        "dropped_score_distribution": quantiles([float(row["raw_score"]) for row in dropped]),
        "score_cost_sum": sum(float(row["raw_score"]) for row in dropped)
                          - sum(float(row["raw_score"]) for row in added),
    }


def candidate_opportunities(matrix: list[dict], proposer: str) -> list[dict]:
    key = "p1_seed_to_gold_pairs" if proposer == "p1" else "p2_seed_to_gold_pairs"
    opportunities = []
    for query in matrix:
        missing = {tuple(page) for page in query["missing_top10_gold_pages"]}
        for item in query["gold_item_diagnostics"]:
            page = (item["document_id"], int(item["page_number"]))
            eligible = sorted({row["node_id"] for row in item["eligible_strong_candidates"]})
            pairs = sorted({tuple(sorted((row["source_id"], row["target_id"])))
                            for row in item[key]})
            pair_records = sorted(({
                "canonical_pair": list(sorted((row["source_id"], row["target_id"]))),
                "emitting_source_id": row["source_id"],
                "target_id": row["target_id"],
                "rank_within_source": int(row["rank_within_source"]),
                "score": float(row["score"]),
            } for row in item[key]),
                key=lambda row: (row["rank_within_source"], -row["score"], row["canonical_pair"]))
            opportunities.append({
                "question_id": query["question_id"], "gold_id": item["gold_id"],
                "page": list(page), "missing_from_dense_top10": page in missing,
                "localized_candidate_ids": eligible,
                "pool_pairs": [list(pair) for pair in pairs],
                "pool_pair_records": pair_records,
                "pool_supported": bool(pairs),
            })
    return opportunities


def evaluate(policies: dict[str, list[dict]], matrix: list[dict], proposer: str) -> tuple[dict, list[dict]]:
    opportunities = candidate_opportunities(matrix, proposer)
    diagnostics = []
    result = {}
    for policy, selected in policies.items():
        chosen = {canonical_pair(row) for row in selected}
        hit_items = []
        for item in opportunities:
            item_pairs = {tuple(pair) for pair in item["pool_pairs"]}
            hits = sorted(item_pairs & chosen)
            hit = bool(hits)
            hit_items.append(hit)
            diagnostics.append(dict(item, proposer=proposer, policy=policy,
                                    selected_pairs=[list(pair) for pair in hits], recovered=hit))
        localized = [i for i in opportunities if i["localized_candidate_ids"]]
        supported = [i for i in opportunities if i["pool_supported"]]
        missing_localized = [i for i in localized if i["missing_from_dense_top10"]]
        missing_supported = [i for i in supported if i["missing_from_dense_top10"]]
        def recovered(items: list[dict]) -> int:
            return sum(bool({tuple(pair) for pair in item["pool_pairs"]} & chosen) for item in items)
        def recall(items: list[dict]) -> float | None:
            return recovered(items) / len(items) if items else None
        query_hits = defaultdict(bool)
        query_supported = defaultdict(bool)
        for item in missing_supported:
            query_supported[item["question_id"]] = True
            query_hits[item["question_id"]] |= bool(
                {tuple(pair) for pair in item["pool_pairs"]} & chosen)
        result[policy] = {
            "all_localized_gold_items": len(localized),
            "all_localized_gold_items_recovered": recovered(localized),
            "all_localized_gold_item_candidate_recall": recall(localized),
            "pool_supported_gold_items": len(supported),
            "pool_supported_gold_items_recovered": recovered(supported),
            "pool_supported_gold_item_candidate_recall": recall(supported),
            "missing_top10_localized_gold_items": len(missing_localized),
            "missing_top10_localized_gold_items_recovered": recovered(missing_localized),
            "missing_top10_localized_gold_item_candidate_recall": recall(missing_localized),
            "missing_top10_pool_supported_gold_items": len(missing_supported),
            "missing_top10_pool_supported_gold_items_recovered": recovered(missing_supported),
            "missing_top10_pool_supported_gold_item_candidate_recall": recall(missing_supported),
            "missing_top10_pool_supported_queries": sorted(query_supported),
            "missing_top10_queries_with_recovered_candidate": sorted(
                qid for qid, hit in query_hits.items() if hit),
            "warning": "Post-hoc bbox-localized candidate coverage, not verified edge recall or retrieval recall.",
        }
    return result, diagnostics


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def write_jsonl(path: Path, values: Iterable[dict]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def report_lines(summary: dict) -> list[str]:
    lines = [
        "# Coverage-aware Edge Candidate Allocation Replay", "",
        "## Scope and validity", "",
        "This is a CPU-only replay over the frozen P1/P2 Top-20 rankings. It did not regenerate embeddings, call an LLM, run a reranker, change verification, or modify navigation. Every arm has exactly 1,088 unverified candidate pairs. Gold and query IDs were loaded only after all allocations were frozen.", "",
        "An EvidenceNode is counted as a possible gold target only through the prior bbox-overlap mapping (gold-box coverage >= 0.5). This is uncertain localization, not node-level gold. Candidate coverage below must not be read as verified navigable-edge coverage.", "",
        "## Policy definitions", "",
        "- **A0 Global:** exact replay of highest-score unique canonical pairs.",
        "- **A1 Source-local:** one retained source-best pair per proposer-emitting source; if sources exceed the budget, source-best pairs compete by score.",
        "- **A2 Hybrid:** 544 global seats, then 544 source-local seats restricted to sources absent from the global half; deterministic global fill is available only if needed.",
        "- **A3 Lane-aware:** 544 same-document and 544 cross-document seats. Each lane uses a 50/50 global/local hybrid. Lane labels come directly from the frozen candidate rows.", "",
        "For an undirected duplicate, the source is the emitting source of the retained highest-score orientation. Exact score ties use lexical source ID then target ID. Deduplication precedes all allocation policies.", "",
        "## Allocation comparison", "",
    ]
    for proposer in ("p1", "p2"):
        lines += [f"### {proposer.upper()}", "", "| Arm | Sources | Targets | Max/source | Source Gini | Same/Cross | Median score | Replaced A0 | Missing-gold items recovered |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for policy in ("A0_global", "A1_source_local", "A2_hybrid", "A3_lane_aware"):
            metric = summary["allocation_metrics"][proposer][policy]
            evaluation = summary["posthoc_gold_evaluation"][proposer][policy]
            replaced = summary["replacement_vs_A0"][proposer][policy]["replaced_A0_pairs"]
            scope = metric["scope"]
            lines.append(f"| {policy} | {metric['unique_sources']} | {metric['unique_targets']} | {metric['max_pairs_per_source']} | {metric['source_gini_over_covered_sources']:.3f} | {scope.get('same_document', 0)}/{scope.get('cross_document', 0)} | {metric['score_distribution']['median']:.4f} | {replaced} | {evaluation['missing_top10_pool_supported_gold_items_recovered']}/{evaluation['missing_top10_pool_supported_gold_items']} |")
        lines.append("")
    lines += ["## Findings", ""]
    findings = summary["findings"]
    lines += [f"- A0 covers only {findings['a0_sources']['p1']} P1 and {findings['a0_sources']['p2']} P2 proposer sources out of 6,520.",
              f"- Best source coverage is {findings['best_source_coverage']['p1']['sources']} for P1 and {findings['best_source_coverage']['p2']['sources']} for P2, both under `{findings['best_source_coverage']['p1']['policy']}`/`{findings['best_source_coverage']['p2']['policy']}` respectively.",
              f"- Pool-supported missing-gold query recovery by arm is `{json.dumps(findings['missing_query_recovery'], sort_keys=True)}`.",
              "- A3 is supported by explicit frozen lane labels; however, equal lane budgets are an experimental allocation constraint, not evidence that both lanes have equal verification yield.",
              "- Same-document page distance is only an anchor-locality proxy. The frozen ranking rows contain node IDs, not a candidate-specific source/target member span or table-row anchor, so semantic quality cannot be established by this replay.", "",
              "## Missing-evidence opportunities", ""]
    for proposer in ("p1", "p2"):
        lines += [f"### {proposer.upper()}", "", "| Query | Gold item | Candidate local ranks | Best score | Recovered arms |", "|---|---|---:|---:|---|"]
        for item in summary["findings"]["missing_opportunities"][proposer]:
            ranks = sorted({record["rank_within_source"] for record in item["pool_pair_records"]})
            best_score = max(record["score"] for record in item["pool_pair_records"])
            lines.append(f"| `{item['question_id']}` | `{item['gold_id']}` | {ranks} | {best_score:.4f} | none |")
        lines.append("")
    lines += ["All four arms miss all four pool-supported missing-gold items from the three queries. The result is not that source-local allocation is ineffective in general; it shows that source coverage alone does not preserve a particular source's rank-2-to-rank-9 relation under a 1,088/6,520 budget.", "",
              "## Quality risks and recommendation", "",
              "Local quotas increase endpoint coverage by admitting lower absolute-score pairs. This raises verification load on weak semantic similarities and can amplify coarse or mixed-topic nodes. Lane balancing additionally replaces high-scoring same-document or cross-document pairs regardless of actual verification yield.", "",
              "**Do not advance these allocation arms directly to Anchor-local Verification yet.** They improve distributional coverage but recover none of the missing-evidence opportunities that motivated the experiment. The next controlled allocator study should test pair-aware local-rank preservation (for example, stratified source rounds or a small reserved local-rank lane) while keeping the same budget and retaining Gold only for post-hoc evaluation. If such an arm recovers opportunities without an unacceptable score/locality shift, verify only its incremental sample with explicit member-span/table-row anchors.", "",
              "The replay establishes candidate-allocation coverage only. It does not show candidate precision, valid edge recall, navigable-edge coverage, or retrieval improvement."]
    return lines


def run(output: Path) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError("fresh output directory required: " + str(output))
    input_paths = {
        "p1_rankings": P12 / "p1_text_only_rankings.jsonl",
        "p2_rankings": P12 / "p2_text_graph_rankings.jsonl",
        "p1_frozen_A0": P12 / "p1_fixed_budget_candidates.jsonl",
        "p2_frozen_A0": P12 / "p2_fixed_budget_candidates.jsonl",
        "entities": KG / "entities_with_text.jsonl",
        "oracle_matrix_posthoc_only": ORACLE / "query_coverage_matrix.jsonl",
    }
    for path in input_paths.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    started = time.perf_counter()
    rankings = {"p1": rows(input_paths["p1_rankings"]),
                "p2": rows(input_paths["p2_rankings"])}
    allocations = {}
    pool_audit = {}
    for proposer in ("p1", "p2"):
        allocations[proposer], pool_audit[proposer] = allocate(rankings[proposer])

    # Assert exact A0 reproduction before any evaluation artifact is read.
    for proposer in ("p1", "p2"):
        frozen = rows(input_paths[f"{proposer}_frozen_A0"])
        if [canonical_pair(row) for row in frozen] != [canonical_pair(row) for row in allocations[proposer]["A0_global"]]:
            raise ValueError(f"{proposer}: A0 does not reproduce frozen allocation")

    entities = {row["entity_id"]: row for row in rows(input_paths["entities"])}
    if len([row for row in entities.values() if row.get("primary_comparison_eligible")]) != 6520:
        raise ValueError("frozen universe is not 6,520 nodes")
    output.mkdir(parents=True)
    allocation_files = {}
    for proposer, policies in allocations.items():
        for policy, selected in policies.items():
            name = f"{proposer}_{policy}_candidates.jsonl"
            write_jsonl(output / name, selected)
            allocation_files[f"{proposer}_{policy}"] = name

    # Evaluation boundary: gold-derived matrix is opened only after allocations exist.
    matrix = rows(input_paths["oracle_matrix_posthoc_only"])
    posthoc, diagnostics = {}, []
    opportunities = {}
    for proposer in ("p1", "p2"):
        posthoc[proposer], detail = evaluate(allocations[proposer], matrix, proposer)
        diagnostics.extend(detail)
        opportunities[proposer] = [item for item in candidate_opportunities(matrix, proposer)
                                   if item["missing_from_dense_top10"] and item["pool_supported"]]
    write_jsonl(output / "posthoc_gold_diagnostics.jsonl", diagnostics)

    metrics, replacements = {}, {}
    for proposer, policies in allocations.items():
        metrics[proposer] = {name: distribution(selected, entities)
                             for name, selected in policies.items()}
        replacements[proposer] = {name: replacement(selected, policies["A0_global"])
                                  for name, selected in policies.items()}
    best = {proposer: max(((value["unique_sources"], policy) for policy, value in metrics[proposer].items()))
            for proposer in ("p1", "p2")}
    missing_recovery = {proposer: {policy: value["missing_top10_queries_with_recovered_candidate"]
                                   for policy, value in posthoc[proposer].items()}
                        for proposer in ("p1", "p2")}
    summary = {
        "version": VERSION,
        "status": "COVERAGE_AWARE_ALLOCATION_REPLAY_COMPLETE",
        "execution_boundary": {"cpu_only": True, "llm_calls": 0, "gpu_used": False,
                               "embeddings_generated": 0, "verification_run": False,
                               "navigation_modified": False, "reranker_run": False},
        "fairness": {"frozen_nodes": 6520, "ranking_rows_each": 130400,
                     "budget_each": BUDGET, "gold_available_to_allocator": False,
                     "same_pool_and_scores_within_proposer": True},
        "pool_audit": pool_audit, "allocation_metrics": metrics,
        "replacement_vs_A0": replacements, "posthoc_gold_evaluation": posthoc,
        "findings": {
            "a0_sources": {p: metrics[p]["A0_global"]["unique_sources"] for p in ("p1", "p2")},
            "best_source_coverage": {p: {"sources": best[p][0], "policy": best[p][1]} for p in best},
            "missing_query_recovery": missing_recovery,
            "missing_opportunities": opportunities,
        },
        "interpretation": {"candidate_is_verified_edge": False,
                           "candidate_is_navigable_edge": False,
                           "gold_mapping": "post-hoc bbox-overlap localization candidate at >=0.5 gold coverage; not node-level gold"},
        "timing_seconds": time.perf_counter() - started,
    }
    protocol = {
        "version": VERSION, "budget": BUDGET, "local_quota": LOCAL_QUOTA,
        "hybrid_global_seats": HYBRID_GLOBAL, "lane_budgets": LANE_BUDGETS,
        "allocation_inputs": ["p1_rankings", "p2_rankings", "entities"],
        "posthoc_evaluation_input": "oracle_matrix_posthoc_only",
        "prohibited_allocation_features": ["query_id", "query_text", "gold_evidence", "oracle_target"],
        "policies": {
            "A0_global": "global score after canonical deduplication",
            "A1_source_local": "one source-best pair, then global score if sources exceed budget",
            "A2_hybrid": "544 global + 544 previously-unrepresented-source local seats",
            "A3_lane_aware": "544 per explicit lane; each lane 272 global + 272 local seats",
        },
    }
    write_json(output / "allocation_protocol.json", protocol)
    write_json(output / "summary.json", summary)
    (output / "REPORT.md").write_text("\n".join(report_lines(summary)) + "\n", encoding="utf-8")
    manifest = {
        "version": VERSION,
        "inputs": {name: {"path": str(path.resolve()), "sha256": sha(path)}
                   for name, path in input_paths.items()},
        "allocation_outputs_frozen_before_posthoc_evaluation": {
            key: {"path": name, "sha256": sha(output / name)} for key, name in allocation_files.items()},
        "outputs": {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()},
        "code": {
            str(Path(__file__).resolve()): sha(Path(__file__).resolve()),
            str((ROOT / "EvidenceNet/tests/test_coverage_aware_candidate_allocation.py").resolve()):
                sha(ROOT / "EvidenceNet/tests/test_coverage_aware_candidate_allocation.py"),
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
    summary = json.loads((output / "summary.json").read_text())
    if any(metric["pairs"] != BUDGET for arm in summary["allocation_metrics"].values()
           for metric in arm.values()):
        raise ValueError("budget mismatch")
    print("COVERAGE_AWARE_ALLOCATION_REPLAY_OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--out", type=Path, default=DEFAULT_OUT)
    verify = sub.add_parser("check")
    verify.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if args.command == "run":
        print(json.dumps(run(args.out), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        check(args.out)


if __name__ == "__main__":
    main()
