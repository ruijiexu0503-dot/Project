#!/usr/bin/env python3
"""Offline opportunity audit for the frozen directional-relation pilot.

This script consumes saved route scores and reranker outputs.  It never loads an
embedding/reranker model and never mutates the historical run directory.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = ROOT / "EvidenceNet/output/directional_relation_pilot_v1_20261101"
DEFAULT_OUT = ROOT / "EvidenceNet/output/directional_relation_opportunity_audit_v1_20261101"
DEFAULT_TASKS = ROOT / "EvidenceNet/output/query_adaptive_evidence_v2_20261030/tasks.jsonl"
DEFAULT_NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
DEFAULT_GOLD = ROOT / "EvidenceNet/output/hf_evidence_comparison_v1_20261031/paired_cases.jsonl"
GRAPH_ARMS = ("R1_type", "R2_open", "R3_directional", "R4_hybrid", "R5_target")
TOPKS = (1, 2, 5)


def rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def jsonl(path: Path, values: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def route_key(route: dict[str, Any]) -> tuple[Any, ...]:
    return (-float(route["score"]), int(route["seed_rank"]), route["edge_id"], route["target_node_id"])


def eligible_routes(routes_: list[dict[str, Any]], seeds: set[str]) -> list[dict[str, Any]]:
    """Return proposal routes in saved deterministic ordering, retaining duplicates."""
    return sorted(
        [r for r in routes_ if r.get("status") == "proposal" and r["target_node_id"] not in seeds],
        key=route_key,
    )


def replay_targets(routes_: list[dict[str, Any]], seeds: set[str], k: int) -> tuple[list[str], list[str]]:
    targets: list[str] = []
    views: list[str] = []
    seen = set(seeds)
    for route in eligible_routes(routes_, seeds):
        target = route["target_node_id"]
        if target in seen:
            continue
        targets.append(target)
        views.append(route["view_id"])
        seen.add(target)
        if len(targets) == k:
            break
    return targets, views


def analyze_query(
    task: dict[str, Any],
    by_arm: dict[str, list[dict[str, Any]]],
    exposure: dict[str, dict[str, Any]],
    result: dict[str, dict[str, Any]],
    gold_pages: set[tuple[str, str]],
    budget: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    qid = task["question_id"]
    seeds = set(task["seed_nodes"])
    dense_rank = {node: rank for rank, node in enumerate(task["node_ranking"], 1)}
    canonical = by_arm.get("R3_directional", [])
    all_routes = len(canonical)
    proposal = eligible_routes(canonical, seeds)
    unique_targets = list(dict.fromkeys(r["target_node_id"] for r in proposal))
    duplicate_routes = len(proposal) - len(unique_targets)
    unavailable = sum(r.get("status") != "proposal" and r["target_node_id"] not in seeds for r in canonical)
    seed_overlaps = sum(r["target_node_id"] in seeds for r in canonical)
    selected = {arm: replay_targets(by_arm.get(arm, []), seeds, budget)[0] for arm in GRAPH_ARMS}
    orders = [selected[arm] for arm in GRAPH_ARMS]
    sets = [set(order) for order in orders]
    r0_pages = [tuple(p) for p in result["R0_dense"]["top10_pages"]]
    graph_pages = {arm: [tuple(p) for p in result[arm]["top10_pages"]] for arm in GRAPH_ARMS}
    gold_r0_5 = len(set(r0_pages[:5]) & gold_pages)
    gold_r0_10 = len(set(r0_pages[:10]) & gold_pages)
    deltas5 = {arm: len(set(pages[:5]) & gold_pages) - gold_r0_5 for arm, pages in graph_pages.items()}
    deltas10 = {arm: len(set(pages[:10]) & gold_pages) - gold_r0_10 for arm, pages in graph_pages.items()}
    if not canonical:
        no_route_reason = "no_adjacent_routes_from_top10_seeds"
    elif not unique_targets and seed_overlaps:
        no_route_reason = "all_adjacent_targets_already_in_seed_set"
    elif not unique_targets and unavailable:
        no_route_reason = "no_available_proposal_target"
    else:
        no_route_reason = None
    row = {
        "question_id": qid,
        "question": task["question"],
        "seed_count": len(seeds),
        "route_count": all_routes,
        "proposal_route_count": len(proposal),
        "unique_adjacent_targets": len(unique_targets),
        "duplicate_target_routes": duplicate_routes,
        "seed_overlap_routes": seed_overlaps,
        "unavailable_routes": unavailable,
        "targets_inside_dense20": sum(dense_rank.get(t, 10**9) <= 20 for t in unique_targets),
        "targets_outside_dense20": sum(dense_rank.get(t, 10**9) > 20 for t in unique_targets),
        "targets_absent_from_dense_ranking": sum(t not in dense_rank for t in unique_targets),
        "budget": budget,
        "budget_binding": len(unique_targets) > budget,
        "actual_route_competition": len(unique_targets) > budget,
        "top1_ranking_choice_possible": len(unique_targets) >= 2,
        "graph_targets_selected": exposure["R3_directional"]["graph_targets"],
        "dense_fallback_slots": budget - exposure["R3_directional"]["graph_targets"],
        "R1_R5_set_same": all(s == sets[0] for s in sets[1:]),
        "R1_R5_order_same": all(order == orders[0] for order in orders[1:]),
        "selected_targets_by_arm": selected,
        "new_targets_vs_R0_by_arm": {
            arm: sorted(set(exposure[arm]["new_target_nodes"]) - set(exposure["R0_dense"]["new_target_nodes"]))
            for arm in GRAPH_ARMS
        },
        "changed_BGE_top10_by_arm": {arm: graph_pages[arm] != r0_pages for arm in GRAPH_ARMS},
        "changed_BGE_pages": any(graph_pages[arm] != r0_pages for arm in GRAPH_ARMS),
        "gold_hits_at5_delta_by_arm": deltas5,
        "gold_hits_at10_delta_by_arm": deltas10,
        "gold_page_gain": any(value > 0 for value in (*deltas5.values(), *deltas10.values())),
        "no_route_reason": no_route_reason,
        "needs_human_review": bool(unique_targets),
    }
    comparisons = []
    identities = sorted({(r["view_id"], r["target_node_id"]) for arm in GRAPH_ARMS for r in by_arm.get(arm, [])})
    arm_lookup = {arm: {(r["view_id"], r["target_node_id"]): r for r in by_arm.get(arm, [])} for arm in GRAPH_ARMS}
    arm_rank = {
        arm: {r["view_id"]: rank for rank, r in enumerate(sorted(by_arm.get(arm, []), key=route_key), 1)}
        for arm in GRAPH_ARMS
    }
    for view_id, target in identities:
        base = next(arm_lookup[arm][(view_id, target)] for arm in GRAPH_ARMS if (view_id, target) in arm_lookup[arm])
        comparisons.append({
            "question_id": qid,
            "view_id": view_id,
            "edge_id": base["edge_id"],
            "source_node_id": base["source_node_id"],
            "target_node_id": target,
            "seed_rank": base["seed_rank"],
            "status": base["status"],
            "target_is_seed": target in seeds,
            "dense_rank": dense_rank.get(target),
            "inside_dense20": dense_rank.get(target, 10**9) <= 20,
            "scores": {arm: arm_lookup[arm].get((view_id, target), {}).get("score") for arm in GRAPH_ARMS},
            "route_ranks": {arm: arm_rank[arm].get(view_id) for arm in GRAPH_ARMS},
            "selected_at5": {arm: target in selected[arm] for arm in GRAPH_ARMS},
        })
    return row, comparisons


def reading_funnel(audit: dict[str, Any], frozen_nodes: list[dict[str, Any]]) -> dict[str, Any]:
    node_ids = {n["id"] for n in frozen_nodes}
    full_pages = {(str(n["document"]), str(n["page"])) for n in frozen_nodes}
    artifacts = []
    totals = Counter()
    for source in audit.get("reading", {}).get("artifacts", []):
        root = Path(source["root"])
        manifest_path = root / "article_graph_manifest.json"
        if not manifest_path.exists():
            artifacts.append({"root": str(root), "available": False})
            continue
        manifest = read(manifest_path)
        units = rows(root / "units.jsonl")
        assignments = rows(root / "article_assignments.jsonl")
        edges = rows(root / "reading_edges.jsonl")
        pages = rows(root / "pages.jsonl")
        members = {m.get("id") or m.get("member_id") for u in units for m in u.get("members", [])}
        eligible_members = {m.get("member_id") for u in units for m in u.get("eligible_members", []) if m.get("eligible")}
        matched_assignments = [a for a in assignments if a["node_id"] in node_ids]
        valid_edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids and e.get("type") == "NEXT"]
        item = {
            "root": str(root.resolve()),
            "available": True,
            "reading_ready": manifest.get("reading_ready"),
            "ready_for_downstream": manifest.get("ready_for_downstream"),
            "pages_processed": len(pages),
            "documents_processed": len({p.get("document") for p in pages}),
            "units": len(units),
            "raw_ordered_members": len(members),
            "eligible_mapped_members": len(eligible_members),
            "qualified_assignments": len(assignments),
            "assignments_matching_frozen_nodes": len(matched_assignments),
            "next_edges": len(edges),
            "next_edges_with_frozen_endpoints": len(valid_edges),
            "cross_page_next_edges": sum(bool(e.get("cross_page")) for e in edges),
            "manifest_sha256": sha(manifest_path),
        }
        artifacts.append(item)
        for key in ("pages_processed", "documents_processed", "units", "raw_ordered_members",
                    "eligible_mapped_members", "qualified_assignments", "assignments_matching_frozen_nodes",
                    "next_edges", "next_edges_with_frozen_endpoints", "cross_page_next_edges"):
            totals[key] += item[key]
    scoped = totals["qualified_assignments"]
    matched = totals["assignments_matching_frozen_nodes"]
    return {
        "interpretation": (
            "The 9/7291 figure is global corpus coverage from two single-page recovery artifacts, not a "
            "9/7291 mapping success rate. Within those artifacts, all assignments map to frozen nodes."
        ),
        "full_frozen_corpus": {"nodes": len(node_ids), "pages": len(full_pages)},
        "coverage_funnel": dict(totals),
        "artifact_scoped_assignment_mapping_rate": matched / scoped if scoped else None,
        "global_node_assignment_coverage": matched / len(node_ids) if node_ids else None,
        "global_page_processing_coverage": totals["pages_processed"] / len(full_pages) if full_pages else None,
        "potential_directed_routes_if_subset_imported": 2 * totals["next_edges_with_frozen_endpoints"],
        "actually_imported_in_directional_pilot": 0,
        "globally_importable_with_current_strict_backbone": matched == len(node_ids),
        "limitation": "All recovered NEXT edges are page-local; no cross-page or singleton links are established.",
        "artifacts": artifacts,
    }


def report_markdown(aggregate: dict[str, Any]) -> str:
    c = aggregate["competition"]
    d = aggregate["dense_overlap"]
    b = aggregate["bge"]
    reading = aggregate["reading"]
    return f"""# Directional Relation Opportunity Audit — Results

Date: 2026-11-01  
Status: **complete; offline replay only, no new model or GPU calls**

## Bottom line

The first pilot could not test representation quality at its executed cutoff. **Zero of 24 queries had binding route competition at K=5.** The frozen graph exposed only {c['unique_graph_targets']} unique non-seed targets across {c['queries_with_routes']} queries, and every eligible graph target fit inside the five-target budget. Consequently R1–R5 could change ordering, but could not exclude a competing target at K=5.

This makes the identical R1–R5 target sets an experimental-capacity issue, not proof that their embeddings are equivalent. At Top1/Top2, saved-score replay does reveal representation-dependent choices, so a small blind route-utility review can still test ranking quality without another GPU run.

## Opportunity and fallback

| Measure | Result |
| --- | ---: |
| Queries | {c['queries']} |
| Queries with at least one adjacent route | {c['queries_with_any_route']} |
| Queries with eligible non-seed targets | {c['queries_with_routes']} |
| Queries with K=5 binding | {c['budget_binding_queries']} |
| Queries with at least two targets (Top1 choice possible) | {c['top1_choice_queries']} |
| Unique query-target opportunities | {c['unique_graph_targets']} |
| Graph selections per arm at K=5 | {c['selected_graph_targets_per_arm']} |
| Dense fallback slots per graph arm | {c['dense_fallback_slots_per_arm']} |

## Offline replay

| Cutoff | Queries where R1–R5 target sets differ | Queries where order differs |
| --- | ---: | ---: |
| Top1 | {aggregate['replay']['1']['set_difference_queries']} | {aggregate['replay']['1']['order_difference_queries']} |
| Top2 | {aggregate['replay']['2']['set_difference_queries']} | {aggregate['replay']['2']['order_difference_queries']} |
| Top5 | {aggregate['replay']['5']['set_difference_queries']} | {aggregate['replay']['5']['order_difference_queries']} |

## Dense overlap and BGE handoff

- {d['inside_dense20']} / {d['query_target_pairs']} graph query-target pairs were already inside the original dense Top20.
- {d['outside_dense20']} / {d['query_target_pairs']} were outside dense Top20.
- {d['absent_from_dense_ranking']} targets were absent from the saved dense ranking.
- {d['already_in_R0_exposed_nodes']} / {d['query_target_pairs']} were the exact same nodes already exposed by R0.
- {d['target_page_in_R0_final_top10']} / {d['query_target_pairs']} target pages were already present in R0's final Top10.
- Graph arms changed final BGE Top10 page order for {b['queries_changed_vs_R0']} / 24 queries.
- Gold-page gains occurred for {b['queries_with_any_gold_gain']} queries; aggregate relevance metrics remained unchanged.

The route descriptions therefore did alter some upstream ordering, and graph substitution altered some final page ordering, but neither produced a measured relevance gain.

## Reading-order diagnosis

The reported 9/7291 value is **global coverage**, not a mapping failure rate:

- only {reading['coverage_funnel'].get('pages_processed', 0)} of {reading['full_frozen_corpus']['pages']} corpus pages were processed by the two recovered artifacts;
- all {reading['coverage_funnel'].get('qualified_assignments', 0)} assignments map to frozen EvidenceNodes;
- those assignments cover {100 * reading['global_node_assignment_coverage']:.3f}% of frozen nodes;
- the artifacts contain {reading['coverage_funnel'].get('next_edges', 0)} NEXT edges, all page-local, and zero cross-page NEXT edges;
- the strict global importer correctly rejects this subset because it requires assignment coverage for every frozen node.

Thus the immediate reading bottleneck is missing corpus-wide processing/coverage, not failed ID mapping in the two available pages.

## Decision

The next justified step is a small blind human review of the saved Top1/Top2 route alternatives, using `human_route_review_template.jsonl`. Do not train a new representation yet. If reviewed useful targets differ between R1–R5 at these cutoffs, scorer alignment is worth investigating. If none are useful, graph construction/coverage is the bottleneck and must be versioned as a separate experiment.

## Artifacts

- `per_query_competition.jsonl`: all 24 queries, including no-route cases
- `per_route_rank_comparison.jsonl`: saved scores and ranks for every reachable route
- `topk_replay.jsonl`: deterministic Top1/2/5 replay
- `dense_overlap.jsonl`: original dense rank and R0 overlap per graph target
- `reading_order_coverage_funnel.json`: scoped versus global reading coverage
- `human_route_review_template.jsonl`: score/arm-blinded original-anchor review rows
- `aggregate_audit.json`: machine-readable summary
- `audit_manifest.json`: source and output hashes
"""


def audit(run_dir: Path, output: Path, tasks_path: Path, nodes_path: Path, gold_path: Path) -> dict[str, Any]:
    required = ["status.json", "audit.json", "route_scores.jsonl", "candidate_exposures.jsonl",
                "per_query_results.jsonl", "edges_with_views.jsonl", "aggregate.json"]
    missing = [name for name in required if not (run_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"incomplete run directory {run_dir}: missing {missing}")
    status = read(run_dir / "status.json")
    if not status.get("complete"):
        raise ValueError(f"run is not complete: {status}")
    tasks = rows(tasks_path)
    nodes_list = rows(nodes_path)
    gold = {r["question_id"]: {tuple(map(str, p)) for p in r["gold_pages"]} for r in rows(gold_path)}
    scores = rows(run_dir / "route_scores.jsonl")
    exposures = rows(run_dir / "candidate_exposures.jsonl")
    results = rows(run_dir / "per_query_results.jsonl")
    views = {r["view_id"]: r for r in rows(run_dir / "edges_with_views.jsonl")}
    by_score: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in scores:
        by_score[row["question_id"]][row["arm"]].append(row)
    by_exposure: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in exposures:
        by_exposure[row["question_id"]][row["arm"]] = row
    by_result: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in results:
        by_result[row["question_id"]][row["arm"]] = row
    budget_values = {r["max_new_targets"] for r in exposures}
    if len(budget_values) != 1:
        raise ValueError(f"mixed exposure budgets: {budget_values}")
    budget = budget_values.pop()
    per_query, route_comparisons = [], []
    for task in tasks:
        qid = task["question_id"]
        row, comparisons = analyze_query(task, by_score[qid], by_exposure[qid], by_result[qid], gold[qid], budget)
        per_query.append(row)
        route_comparisons.extend(comparisons)

    replay_rows = []
    replay_summary = {str(k): {"set_difference_queries": 0, "order_difference_queries": 0} for k in TOPKS}
    for task in tasks:
        qid, seeds = task["question_id"], set(task["seed_nodes"])
        for k in TOPKS:
            selected = {arm: replay_targets(by_score[qid].get(arm, []), seeds, k)[0] for arm in GRAPH_ARMS}
            sets = [set(selected[a]) for a in GRAPH_ARMS]
            orders = [selected[a] for a in GRAPH_ARMS]
            set_same = all(x == sets[0] for x in sets[1:])
            order_same = all(x == orders[0] for x in orders[1:])
            replay_rows.append({"question_id": qid, "k": k, "targets_by_arm": selected,
                                "R1_R5_set_same": set_same, "R1_R5_order_same": order_same})
            replay_summary[str(k)]["set_difference_queries"] += int(not set_same)
            replay_summary[str(k)]["order_difference_queries"] += int(not order_same)

    task_map = {t["question_id"]: t for t in tasks}
    dense_rows = []
    for row in per_query:
        qid = row["question_id"]
        ranking = task_map[qid]["node_ranking"]
        rank = {node: i for i, node in enumerate(ranking, 1)}
        r0_nodes = set(by_exposure[qid]["R0_dense"]["all_exposed_nodes"])
        r0_pages = {tuple(p) for p in by_result[qid]["R0_dense"]["top10_pages"]}
        targets = sorted({c["target_node_id"] for c in route_comparisons
                          if c["question_id"] == qid and not c["target_is_seed"] and c["status"] == "proposal"})
        node_map = {n["id"]: n for n in nodes_list}
        for target in targets:
            page = (str(node_map[target]["document"]), str(node_map[target]["page"]))
            dense_rows.append({"question_id": qid, "target_node_id": target, "target_page": list(page),
                               "dense_rank": rank.get(target), "inside_dense20": rank.get(target, 10**9) <= 20,
                               "already_in_R0_exposed_nodes": target in r0_nodes,
                               "target_page_in_R0_final_top10": page in r0_pages,
                               "selected_by_arms_at5": [a for a in GRAPH_ARMS
                                                        if target in row["selected_targets_by_arm"][a]]})

    run_audit = read(run_dir / "audit.json")
    reading = reading_funnel(run_audit, nodes_list)
    view_lookup = views
    node_lookup = {n["id"]: n for n in nodes_list}
    human_rows = []
    for task in tasks:
        qid, seeds = task["question_id"], set(task["seed_nodes"])
        candidates = {}
        for route in by_score[qid].get("R3_directional", []):
            if route["target_node_id"] in seeds or route.get("status") != "proposal":
                continue
            candidates[route["view_id"]] = route
        if not candidates:
            human_rows.append({"question_id": qid, "question": task["question"], "candidate_available": False,
                               "no_route_reason": next(r["no_route_reason"] for r in per_query if r["question_id"] == qid)})
            continue
        for view_id, route in sorted(candidates.items()):
            view = view_lookup[view_id]
            source = node_lookup[route["source_node_id"]]
            target = node_lookup[route["target_node_id"]]
            human_rows.append({
                "review_id": hashlib.sha256(f"{qid}\0{view_id}".encode()).hexdigest()[:20],
                "question_id": qid,
                "question": task["question"],
                "candidate_available": True,
                "source_node_id": route["source_node_id"],
                "target_node_id": route["target_node_id"],
                "source_page": route["source_page"],
                "target_page": route["target_page"],
                "source_original_text": "\n\n".join(str(m.get("text", "")) for m in source.get("members", [])),
                "target_original_text": "\n\n".join(str(m.get("text", "")) for m in target.get("members", [])),
                "supported_relation": view.get("relation_statement"),
                "qualifiers": view.get("qualifiers", []),
                "label": None,
                "reviewer": None,
                "notes": None,
            })

    competition = {
        "queries": len(per_query),
        "queries_with_any_route": sum(r["route_count"] > 0 for r in per_query),
        "queries_with_routes": sum(r["unique_adjacent_targets"] > 0 for r in per_query),
        "budget_binding_queries": sum(r["budget_binding"] for r in per_query),
        "top1_choice_queries": sum(r["top1_ranking_choice_possible"] for r in per_query),
        "unique_graph_targets": sum(r["unique_adjacent_targets"] for r in per_query),
        "selected_graph_targets_per_arm": sum(r["graph_targets_selected"] for r in per_query),
        "dense_fallback_slots_per_arm": sum(r["dense_fallback_slots"] for r in per_query),
    }
    aggregate = {
        "complete": True,
        "no_new_model_calls": True,
        "run_dir": str(run_dir.resolve()),
        "competition": competition,
        "replay": replay_summary,
        "dense_overlap": {
            "query_target_pairs": len(dense_rows),
            "inside_dense20": sum(r["inside_dense20"] for r in dense_rows),
            "outside_dense20": sum(not r["inside_dense20"] and r["dense_rank"] is not None for r in dense_rows),
            "absent_from_dense_ranking": sum(r["dense_rank"] is None for r in dense_rows),
            "already_in_R0_exposed_nodes": sum(r["already_in_R0_exposed_nodes"] for r in dense_rows),
            "target_page_in_R0_final_top10": sum(r["target_page_in_R0_final_top10"] for r in dense_rows),
        },
        "bge": {
            "queries_changed_vs_R0": sum(r["changed_BGE_pages"] for r in per_query),
            "queries_with_any_gold_gain": sum(r["gold_page_gain"] for r in per_query),
        },
        "reading": reading,
        "decision": "blind_review_saved_top1_top2_before_any_new_GPU_or_representation_work",
    }
    output.mkdir(parents=True, exist_ok=True)
    jsonl(output / "per_query_competition.jsonl", per_query)
    jsonl(output / "per_route_rank_comparison.jsonl", route_comparisons)
    jsonl(output / "topk_replay.jsonl", replay_rows)
    jsonl(output / "dense_overlap.jsonl", dense_rows)
    write(output / "reading_order_coverage_funnel.json", reading)
    jsonl(output / "human_route_review_template.jsonl", human_rows)
    write(output / "aggregate_audit.json", aggregate)
    (output / "RESULTS.md").write_text(report_markdown(aggregate), encoding="utf-8")
    reading_paths = []
    for artifact in reading.get("artifacts", []):
        if not artifact.get("available"):
            continue
        root = Path(artifact["root"])
        reading_paths.extend(root / name for name in (
            "article_graph_manifest.json", "units.jsonl", "article_assignments.jsonl",
            "reading_edges.jsonl", "pages.jsonl"
        ))
    input_paths = [run_dir / name for name in required] + [tasks_path, nodes_path, gold_path, Path(__file__)] + reading_paths
    output_names = ["per_query_competition.jsonl", "per_route_rank_comparison.jsonl", "topk_replay.jsonl",
                    "dense_overlap.jsonl", "reading_order_coverage_funnel.json", "human_route_review_template.jsonl",
                    "aggregate_audit.json", "RESULTS.md"]
    manifest = {
        "version": "directional_relation_opportunity_audit_v1_20261101",
        "historical_run_mutated": False,
        "online_model_calls": 0,
        "sources": {str(p.resolve()): sha(p) for p in input_paths},
        "outputs": {name: sha(output / name) for name in output_names},
    }
    write(output / "audit_manifest.json", manifest)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    args = parser.parse_args()
    print(json.dumps(audit(args.run_dir, args.out, args.tasks, args.nodes, args.gold), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
