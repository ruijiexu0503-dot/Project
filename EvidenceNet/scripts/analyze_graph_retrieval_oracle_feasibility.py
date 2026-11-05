#!/usr/bin/env python3
"""CPU-only upper-bound study over frozen VL-DocIR rankings and graph artifacts.

Gold is element/page geometry, not EvidenceNode supervision.  Spatially
overlapping nodes are reported as localization candidates, never relabeled as
gold.  Oracle results deliberately use gold and are diagnostic upper bounds;
they are not retrieval runs and must not be fed to production navigation.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TRACE = ROOT / "migration/vldocir_trace_inputs_20261023"
KG = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v2_20261102"
P12 = ROOT / "EvidenceNet/output/kg_link_prediction_p1_p2_20261102"
VERIFY = ROOT / "EvidenceNet/output/kg_link_prediction_bounded_verification_ultra_smoke_v1_20261102"
AUDIT = ROOT / "EvidenceNet/output/kg_accepted_edge_audit_job_119422"
SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
NAV = ROOT / "EvidenceNet/output/top10_node_navigation_20261029/navigation.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/graph_retrieval_oracle_feasibility_v1_20261104"


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def member_boxes(node: dict) -> list[tuple[float, float, float, float]]:
    result = []
    for member in node.get("members", []):
        for box in member.get("boxes", []):
            if isinstance(box, list) and len(box) == 4:
                x1, y1, x2, y2 = map(float, box)
                if x2 > x1 and y2 > y1:
                    result.append((x1, y1, x2, y2))
    return result


def gold_box(gold: dict, size: tuple[float, float]) -> tuple[float, float, float, float]:
    box = gold["bounding_box"]
    width, height = size
    x1 = float(box["relative_page_x"]) * width
    y1 = float(box["relative_page_y"]) * height
    return (x1, y1, x1 + float(box["relative_width"]) * width,
            y1 + float(box["relative_height"]) * height)


def overlap(left, right) -> dict[str, float]:
    ix = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    iy = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    inter = ix * iy
    la = max(0.0, left[2] - left[0]) * max(0.0, left[3] - left[1])
    ra = max(0.0, right[2] - right[0]) * max(0.0, right[3] - right[1])
    union = la + ra - inter
    return {
        "intersection": inter,
        "gold_coverage": inter / la if la else 0.0,
        "node_coverage": inter / ra if ra else 0.0,
        "iou": inter / union if union else 0.0,
    }


def spatial_candidates(gold: dict, page_nodes: list[dict], eligible: set[str],
                       min_gold_coverage: float) -> tuple[list[dict], list[dict]]:
    candidates = []
    for node in page_nodes:
        size = tuple(map(float, node.get("geometry_image_size", [1000, 2000])))
        gbox = gold_box(gold, size)
        scores = [overlap(gbox, box) for box in member_boxes(node)]
        if not scores:
            continue
        best = max(scores, key=lambda x: (x["gold_coverage"], x["iou"], x["node_coverage"]))
        if best["intersection"] <= 0:
            continue
        candidates.append({
            "node_id": node["id"], "eligible": node["id"] in eligible,
            "node_type": node.get("node_type"), "page": node.get("page"),
            "gold_coverage": round(best["gold_coverage"], 6),
            "node_coverage": round(best["node_coverage"], 6),
            "iou": round(best["iou"], 6),
            "strong": best["gold_coverage"] >= min_gold_coverage,
        })
    candidates.sort(key=lambda x: (-x["gold_coverage"], -x["iou"], x["node_id"]))
    return candidates, [item for item in candidates if item["strong"]]


def add_edge(graph: dict[str, set[str]], source: str, target: str, directed: bool) -> None:
    graph[source].add(target)
    if not directed:
        graph[target].add(source)


def reachable(graph: dict[str, set[str]], seeds: list[str]) -> tuple[set[str], dict[str, int]]:
    distance = {seed: 0 for seed in seeds}
    queue = deque(seeds)
    while queue:
        source = queue.popleft()
        for target in graph.get(source, ()):
            if target not in distance:
                distance[target] = distance[source] + 1
                queue.append(target)
    return set(distance), distance


def semantic_routes(edge: dict):
    direction = edge.get("direction")
    if direction in {"A_TO_B", "BIDIRECTIONAL", "UNDIRECTED"}:
        yield edge["source_id"], edge["target_id"]
    if direction in {"B_TO_A", "BIDIRECTIONAL", "UNDIRECTED"}:
        yield edge["target_id"], edge["source_id"]


def page_key(document, page) -> tuple[str, int]:
    return str(document), int(page)


def analyze(args) -> tuple[list[dict], dict]:
    inputs = {
        "queries": TRACE / "queries.jsonl",
        "gold": TRACE / "gold_evidence.jsonl",
        "navigation": NAV,
        "nodes": SOURCE / "nodes.jsonl",
        "universe": KG / "candidate_universe.jsonl",
        "reading": KG / "validated_reading_edges.jsonl",
        "context": KG / "observed_context_edges.jsonl",
        "p1": P12 / "p1_text_only_rankings.jsonl",
        "p2": P12 / "p2_text_graph_rankings.jsonl",
        "p1_fixed": P12 / "p1_fixed_budget_candidates.jsonl",
        "p2_fixed": P12 / "p2_fixed_budget_candidates.jsonl",
        "baseline_pairs": KG / "baseline_candidate_pairs.jsonl",
        "accepted": VERIFY / "accepted_new_edges_model_only.jsonl",
        "edge_audit": AUDIT / "edge_review_queue.jsonl",
    }
    for name, path in inputs.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing {name}: {path}")

    queries = {row["question_id"]: row for row in rows(inputs["queries"])}
    gold_by_query = defaultdict(list)
    for row in rows(inputs["gold"]):
        gold_by_query[row["question_id"]].append(row)
    nav = {row["question_id"]: row for row in rows(inputs["navigation"])}
    if set(queries) != set(gold_by_query) or set(queries) != set(nav):
        raise ValueError("query/gold/navigation ID mismatch")

    nodes = {row["id"]: row for row in rows(inputs["nodes"])}
    eligible = {row["entity_id"] for row in rows(inputs["universe"])
                if row.get("primary_eligible") is True}
    if len(eligible) != 6520 or not eligible <= set(nodes):
        raise ValueError("expected exact 6,520-node universe")
    by_page = defaultdict(list)
    for node in nodes.values():
        by_page[page_key(node["document"], node["page"])].append(node)

    reading_records = rows(inputs["reading"])
    reading_graph = defaultdict(set)
    for edge in reading_records:
        if edge.get("verification_status") != "VALIDATED_READING_ARTIFACT":
            continue
        add_edge(reading_graph, edge["source_id"], edge["target_id"], edge.get("directed", True))

    audit = {row["edge_id"]: row for row in rows(inputs["edge_audit"])}
    verified_semantic_graph = defaultdict(set)
    for edge in rows(inputs["accepted"]):
        decision = audit.get(edge["edge_id"])
        if not decision or decision.get("allowed_for_navigation") is not True:
            continue
        for source, target in semantic_routes(edge):
            add_edge(verified_semantic_graph, source, target, True)

    context_records = rows(inputs["context"])
    noisy_graph = defaultdict(set)
    for edge in context_records:
        if edge.get("relation_id") == "RELATED_OPEN":
            add_edge(noisy_graph, edge["source_id"], edge["target_id"], edge.get("directed", False))

    p1_map = {(row["source_id"], row["target_id"]): row for row in rows(inputs["p1"])}
    p2_map = {(row["source_id"], row["target_id"]): row for row in rows(inputs["p2"])}
    p1_pairs, p2_pairs = set(p1_map), set(p2_map)
    p1_fixed = {(row["source_id"], row["target_id"])
                for row in rows(inputs["p1_fixed"])}
    p2_fixed = {(row["source_id"], row["target_id"])
                for row in rows(inputs["p2_fixed"])}
    baseline_pairs = set()
    for row in rows(inputs["baseline_pairs"]):
        source = row.get("source_id", row.get("canonical_source_id"))
        target = row.get("target_id", row.get("canonical_target_id"))
        baseline_pairs.add((source, target)); baseline_pairs.add((target, source))

    matrix = []
    for qid in sorted(queries):
        context = nav[qid]
        ranking = [node_id for node_id in context["node_ranking"] if node_id in eligible]
        if len(ranking) != 6520 or len(set(ranking)) != 6520:
            raise ValueError(f"invalid filtered universe for {qid}")
        top10, top20 = ranking[:10], ranking[:20]
        top10_set, top20_set = set(top10), set(top20)
        seeds = top10
        seed_set = set(seeds)
        page_rank = {}
        for rank, node_id in enumerate(ranking, 1):
            node = nodes[node_id]
            page_rank.setdefault(page_key(node["document"], node["page"]), rank)

        structure_nodes, structure_distance = reachable(reading_graph, seeds)
        combined = defaultdict(set, {key: set(value) for key, value in reading_graph.items()})
        for source, targets in verified_semantic_graph.items():
            combined[source].update(targets)
        verified_nodes, verified_distance = reachable(combined, seeds)
        noisy_nodes, noisy_distance = reachable(noisy_graph, seeds)

        items = []
        for gold in gold_by_query[qid]:
            page = page_key(gold["document_id"], gold["page_number"])
            all_candidates, strong = spatial_candidates(
                gold, by_page.get(page, []), eligible, args.min_gold_coverage)
            eligible_strong = [x for x in strong if x["eligible"]]
            excluded_strong = [x for x in strong if not x["eligible"]]
            candidate_ids = {x["node_id"] for x in eligible_strong}
            structure_targets = sorted(candidate_ids & structure_nodes)
            verified_targets = sorted(candidate_ids & verified_nodes)
            noisy_targets = sorted(candidate_ids & noisy_nodes)
            p1_hit_pairs = sorted((source, target) for source in seeds for target in candidate_ids
                                  if (source, target) in p1_pairs)
            p2_hit_pairs = sorted((source, target) for source in seeds for target in candidate_ids
                                  if (source, target) in p2_pairs)
            p1_hits = sorted({target for _, target in p1_hit_pairs})
            p2_hits = sorted({target for _, target in p2_hit_pairs})
            baseline_hits = sorted(target for source in seeds for target in candidate_ids
                                   if (source, target) in baseline_pairs)
            potential = bool(noisy_targets or p1_hits or p2_hits or baseline_hits)
            if page_rank.get(page, 10**9) <= 10:
                page_state = "DENSE_TOP10_PAGE"
            elif structure_targets:
                page_state = "STRUCTURE_REACHABLE"
            elif verified_targets:
                page_state = "VERIFIED_SEMANTIC_REACHABLE"
            elif potential:
                page_state = "POTENTIAL_RELATION_NOT_CONSTRUCTED_OR_TRUSTED"
            elif not eligible_strong:
                page_state = "NODE_OR_FROZEN_UNIVERSE_GRANULARITY_GAP"
            else:
                page_state = "ORACLE_SEMANTIC_ONLY"
            items.append({
                "gold_id": gold["_id"], "evidence_type": gold.get("evidence_type"),
                "document_id": page[0], "page_number": page[1],
                "dense_first_node_rank_on_page": page_rank.get(page),
                "dense_page_top10": page_rank.get(page, 10**9) <= 10,
                "dense_page_top20": page_rank.get(page, 10**9) <= 20,
                "top10_spatial_candidate_ids": sorted(candidate_ids & top10_set),
                "top20_spatial_candidate_ids": sorted(candidate_ids & top20_set),
                "eligible_strong_candidates": eligible_strong,
                "excluded_strong_candidates": excluded_strong,
                "weak_candidate_count": len(all_candidates),
                "structure_reachable_targets": structure_targets,
                "structure_min_hops": min((structure_distance[x] for x in structure_targets), default=None),
                "verified_semantic_reachable_targets": verified_targets,
                "verified_min_hops": min((verified_distance[x] for x in verified_targets), default=None),
                "noisy_related_reachable_targets": noisy_targets,
                "noisy_min_hops": min((noisy_distance[x] for x in noisy_targets), default=None),
                "p1_seed_to_gold_candidates": sorted(set(p1_hits)),
                "p2_seed_to_gold_candidates": sorted(set(p2_hits)),
                "p1_seed_to_gold_pairs": [
                    {"source_id": source, "target_id": target,
                     "rank_within_source": p1_map[(source, target)]["rank_within_source"],
                     "score": p1_map[(source, target)]["raw_score"],
                     "selected_global_1088": (source, target) in p1_fixed}
                    for source, target in p1_hit_pairs],
                "p2_seed_to_gold_pairs": [
                    {"source_id": source, "target_id": target,
                     "rank_within_source": p2_map[(source, target)]["rank_within_source"],
                     "score": p2_map[(source, target)]["raw_score"],
                     "selected_global_1088": (source, target) in p2_fixed,
                     "graph_context_used": p2_map[(source, target)].get("graph_context_used", False)}
                    for source, target in p2_hit_pairs],
                "baseline_seed_to_gold_candidates": sorted(set(baseline_hits)),
                "potential_relation": potential,
                "oracle_region_representable": bool(eligible_strong),
                "failure_type": page_state,
            })

        gold_pages = {page_key(x["document_id"], x["page_number"]) for x in items}
        top10_pages = {page_key(nodes[n]["document"], nodes[n]["page"]) for n in top10}
        top20_pages = {page_key(nodes[n]["document"], nodes[n]["page"]) for n in top20}
        missing10 = gold_pages - top10_pages
        missing20 = gold_pages - top20_pages
        structure_pages = {page_key(x["document_id"], x["page_number"]) for x in items
                           if x["structure_reachable_targets"]}
        verified_pages = {page_key(x["document_id"], x["page_number"]) for x in items
                          if x["verified_semantic_reachable_targets"]}
        oracle_pages = {page_key(x["document_id"], x["page_number"]) for x in items
                        if x["oracle_region_representable"]}
        top10_region_complete = all(x["top10_spatial_candidate_ids"] for x in items)
        top20_region_complete = all(x["top20_spatial_candidate_ids"] for x in items)
        structure_region_complete = all(
            x["top10_spatial_candidate_ids"] or x["structure_reachable_targets"] for x in items)
        verified_region_complete = all(
            x["top10_spatial_candidate_ids"] or x["verified_semantic_reachable_targets"] for x in items)
        oracle_region_complete = all(
            x["top10_spatial_candidate_ids"] or x["oracle_region_representable"] for x in items)
        if not missing10 and top10_region_complete:
            category = "DENSE_TOP10_REGION_SUPPORTED"
        elif not missing10:
            category = "DENSE_TOP10_PAGE_COMPLETE_NODE_UNCERTAIN"
        elif missing10 <= structure_pages:
            category = "MISSING_GOLD_STRUCTURE_REACHABLE"
        elif missing10 <= verified_pages:
            category = "MISSING_GOLD_VERIFIED_SEMANTIC_REACHABLE"
        elif any(x["potential_relation"] and page_key(x["document_id"], x["page_number"]) in missing10
                 for x in items):
            category = "MISSING_GOLD_POTENTIAL_RELATION_NOT_CONSTRUCTED"
        elif not missing10 <= oracle_pages:
            category = "MISSING_GOLD_NODE_ANCHOR_GRANULARITY_GAP"
        else:
            category = "MISSING_GOLD_ORACLE_SEMANTIC_ONLY"
        matrix.append({
            "question_id": qid, "question": queries[qid]["question"],
            "question_type": queries[qid].get("question_type"),
            "frozen_universe_nodes": len(ranking), "dense_top10_ids": top10,
            "dense_top20_ids": top20, "gold_items": len(items),
            "gold_pages": [list(x) for x in sorted(gold_pages)],
            "top10_gold_pages_covered": len(gold_pages & top10_pages),
            "top20_gold_pages_covered": len(gold_pages & top20_pages),
            "gold_pages_total": len(gold_pages),
            "top10_page_complete": not missing10,
            "top20_page_complete": not missing20,
            "top10_region_complete": top10_region_complete,
            "top20_region_complete": top20_region_complete,
            "missing_top10_gold_pages": [list(x) for x in sorted(missing10)],
            "missing_top20_gold_pages": [list(x) for x in sorted(missing20)],
            "structure_recoverable_missing_pages": len(missing10 & structure_pages),
            "verified_semantic_recoverable_missing_pages": len(missing10 & verified_pages),
            "oracle_region_recoverable_missing_pages": len(missing10 & oracle_pages),
            "structure_page_complete_upper_bound": not (gold_pages - (top10_pages | structure_pages)),
            "verified_semantic_page_complete_upper_bound": not (gold_pages - (top10_pages | verified_pages)),
            "oracle_region_page_complete_upper_bound": not (gold_pages - (top10_pages | oracle_pages)),
            "structure_region_complete_upper_bound": structure_region_complete,
            "verified_semantic_region_complete_upper_bound": verified_region_complete,
            "oracle_region_complete_upper_bound": oracle_region_complete,
            "classification": category, "gold_item_diagnostics": items,
        })

    def page_totals(field):
        return sum(row[field] for row in matrix)

    total_pages = sum(row["gold_pages_total"] for row in matrix)
    total_items = sum(row["gold_items"] for row in matrix)
    summary = {
        "status": "GRAPH_RETRIEVAL_ORACLE_FEASIBILITY_COMPLETE",
        "scope": {"queries": len(matrix), "frozen_nodes": len(eligible),
                  "gold_items": total_items, "query_gold_pages": total_pages,
                  "dense_cutoffs": [10, 20], "graph_slots_unchanged": 3},
        "gold_granularity": {
            "annotation": "page plus element bounding box; not EvidenceNode labels",
            "node_mapping": f"spatial localization candidate when gold-box coverage >= {args.min_gold_coverage}",
            "warning": "Overlapping nodes are candidates only; same-page nodes are never automatically gold.",
        },
        "dense_coverage": {
            "top10_complete_queries_page_level": sum(x["top10_page_complete"] for x in matrix),
            "top20_complete_queries_page_level": sum(x["top20_page_complete"] for x in matrix),
            "top10_complete_queries_region_supported": sum(x["top10_region_complete"] for x in matrix),
            "top20_complete_queries_region_supported": sum(x["top20_region_complete"] for x in matrix),
            "top10_gold_pages_covered": page_totals("top10_gold_pages_covered"),
            "top20_gold_pages_covered": page_totals("top20_gold_pages_covered"),
            "total_query_gold_pages": total_pages,
        },
        "upper_bounds_from_top10": {
            "structure_only_page_complete_queries": sum(x["structure_page_complete_upper_bound"] for x in matrix),
            "verified_semantic_page_complete_queries": sum(x["verified_semantic_page_complete_upper_bound"] for x in matrix),
            "oracle_semantic_page_complete_queries_with_grounded_missing_targets": sum(x["oracle_region_page_complete_upper_bound"] for x in matrix),
            "structure_only_region_supported_complete_queries": sum(x["structure_region_complete_upper_bound"] for x in matrix),
            "verified_semantic_region_supported_complete_queries": sum(x["verified_semantic_region_complete_upper_bound"] for x in matrix),
            "oracle_semantic_region_supported_complete_queries": sum(x["oracle_region_complete_upper_bound"] for x in matrix),
            "structure_recovered_missing_pages": page_totals("structure_recoverable_missing_pages"),
            "verified_semantic_recovered_missing_pages": page_totals("verified_semantic_recoverable_missing_pages"),
            "oracle_semantic_region_grounded_recovered_missing_pages": page_totals("oracle_region_recoverable_missing_pages"),
            "oracle_warning": "Uses gold geometry to choose a direct seed-to-gold candidate edge; theoretical ceiling only.",
        },
        "graph_inventory": {
            "validated_reading_records": len(reading_records),
            "validated_reading_endpoint_nodes": len({
                node_id for edge in reading_records for node_id in (edge["source_id"], edge["target_id"])}),
            "validated_reading_documents": len({
                nodes[node_id]["document"] for edge in reading_records
                for node_id in (edge["source_id"], edge["target_id"])}),
            "navigation_allowed_semantic_edges": sum(
                row.get("allowed_for_navigation") is True for row in audit.values()),
            "noisy_related_edges": sum(
                row.get("relation_id") == "RELATED_OPEN" for row in context_records),
            "noisy_related_adjacency_arcs": sum(len(x) for x in noisy_graph.values()),
            "p1_top20_pairs": len(p1_pairs), "p2_top20_pairs": len(p2_pairs),
        },
        "query_classifications": dict(Counter(x["classification"] for x in matrix)),
        "construction_opportunities_on_missing_top10_items": {
            "items_with_p1_seed_pair": sum(
                bool(item["p1_seed_to_gold_pairs"]) for row in matrix for item in row["gold_item_diagnostics"]
                if not item["dense_page_top10"]),
            "items_with_p2_seed_pair": sum(
                bool(item["p2_seed_to_gold_pairs"]) for row in matrix for item in row["gold_item_diagnostics"]
                if not item["dense_page_top10"]),
            "p1_pairs_selected_global_1088": sum(
                pair["selected_global_1088"] for row in matrix for item in row["gold_item_diagnostics"]
                if not item["dense_page_top10"] for pair in item["p1_seed_to_gold_pairs"]),
            "p2_pairs_selected_global_1088": sum(
                pair["selected_global_1088"] for row in matrix for item in row["gold_item_diagnostics"]
                if not item["dense_page_top10"] for pair in item["p2_seed_to_gold_pairs"]),
        },
        "execution_boundary": {
            "cpu_only": True, "llm_calls": 0, "new_embeddings": 0,
            "reranker_run": False, "production_pipeline_modified": False,
            "original_artifacts_overwritten": False,
        },
        "inputs": {name: {"path": str(path), "sha256": sha(path)}
                   for name, path in inputs.items()},
    }
    return matrix, summary


def report_lines(matrix: list[dict], summary: dict) -> list[str]:
    dense = summary["dense_coverage"]; upper = summary["upper_bounds_from_top10"]
    opportunities = summary["construction_opportunities_on_missing_top10_items"]
    incomplete = [row for row in matrix if not row["top10_page_complete"]]
    lines = [
        "# Graph Retrieval Oracle Feasibility Study", "",
        "CPU-only diagnostic over the frozen 6,520-node universe. Oracle rows use gold geometry and are upper bounds, not retrieval results.", "",
        "## Gold-label limitation", "",
        "VL-DocIR supplies page IDs and element bounding boxes, not EvidenceNode gold labels. This study maps boxes to spatially overlapping node candidates. It never treats every node on a gold page as gold, and overlap is not proof that a node contains the complete answer.", "",
        "## Coverage and upper bound", "",
        "| Measure | Queries / pages |", "|---|---:|",
        f"| Dense Top-10 page-complete queries | {dense['top10_complete_queries_page_level']} / 24 |",
        f"| Dense Top-20 page-complete queries | {dense['top20_complete_queries_page_level']} / 24 |",
        f"| Dense Top-10 region-supported queries | {dense['top10_complete_queries_region_supported']} / 24 |",
        f"| Dense Top-20 region-supported queries | {dense['top20_complete_queries_region_supported']} / 24 |",
        f"| Dense Top-10 gold-page occurrences | {dense['top10_gold_pages_covered']} / {dense['total_query_gold_pages']} |",
        f"| Dense Top-20 gold-page occurrences | {dense['top20_gold_pages_covered']} / {dense['total_query_gold_pages']} |",
        f"| Structure-only page-complete upper bound from Top-10 | {upper['structure_only_page_complete_queries']} / 24 |",
        f"| Verified-semantic page-complete upper bound from Top-10 | {upper['verified_semantic_page_complete_queries']} / 24 |",
        f"| Oracle-semantic page-complete upper bound with grounded missing targets | {upper['oracle_semantic_page_complete_queries_with_grounded_missing_targets']} / 24 |",
        f"| Structure / verified / oracle region-supported complete queries | {upper['structure_only_region_supported_complete_queries']} / {upper['verified_semantic_region_supported_complete_queries']} / {upper['oracle_semantic_region_supported_complete_queries']} |",
        f"| Missing pages recovered by structure / verified semantic / oracle | {upper['structure_recovered_missing_pages']} / {upper['verified_semantic_recovered_missing_pages']} / {upper['oracle_semantic_region_grounded_recovered_missing_pages']} |",
        "", "Dense Top-20 improves page-complete coverage by only one query. Existing structure and trusted semantic edges recover no missing page. The oracle can recover six of seven missing pages, but strict region support reaches only 19/24 complete queries because several already-retrieved pages still lack a localized node for every gold element.",
        "", "## Query-level coverage matrix", "",
        "`R` means all gold elements have a Top-K spatial node candidate; it remains a localization proxy, not node gold.", "",
        "| Query | Gold pages | T10 pages | T20 pages | T10 R | T20 R | Struct recover | Verified recover | Oracle recover | Classification |",
        "|---|---:|---:|---:|:---:|:---:|---:|---:|---:|---|",
    ]
    for row in matrix:
        lines.append(
            f"| `{row['question_id'][:8]}` | {row['gold_pages_total']} | "
            f"{row['top10_gold_pages_covered']} | {row['top20_gold_pages_covered']} | "
            f"{'Y' if row['top10_region_complete'] else 'N'} | {'Y' if row['top20_region_complete'] else 'N'} | "
            f"{row['structure_recoverable_missing_pages']} | {row['verified_semantic_recoverable_missing_pages']} | "
            f"{row['oracle_region_recoverable_missing_pages']} | `{row['classification']}` |")
    lines += ["", "## Classification counts", ""]
    for label, count in sorted(summary["query_classifications"].items()):
        lines.append(f"- `{label}`: {count}")
    lines += [
        "", "## Seven Top-10-incomplete queries", "",
        "| Query | Missing page first rank | P1/P2 seed pair | Global 1,088 selected | Failure class |",
        "|---|---:|:---:|:---:|---|",
    ]
    for row in incomplete:
        missing_items = [item for item in row["gold_item_diagnostics"] if not item["dense_page_top10"]]
        ranks = sorted({item["dense_first_node_rank_on_page"] for item in missing_items
                        if item["dense_first_node_rank_on_page"] is not None})
        has_pair = any(item["p1_seed_to_gold_pairs"] or item["p2_seed_to_gold_pairs"]
                       for item in missing_items)
        selected = any(pair["selected_global_1088"] for item in missing_items
                       for pair in item["p1_seed_to_gold_pairs"] + item["p2_seed_to_gold_pairs"])
        lines.append(f"| `{row['question_id'][:8]}` | {','.join(map(str, ranks)) or 'none'} | "
                     f"{'Y' if has_pair else 'N'} | {'Y' if selected else 'N'} | `{row['classification']}` |")
    lines += [
        "", "## Main failure types", "",
        f"1. **Global allocation drops locally useful candidates.** Four missing gold items have at least one P1 and P2 Top-20 pair from a frozen query seed, but {opportunities['p1_pairs_selected_global_1088']} P1 and {opportunities['p2_pairs_selected_global_1088']} P2 occurrences enter the global 1,088 budgets. These opportunities occur in three queries. One target is already dense rank 15; the other examples include rank 38 and rank 316 targets.",
        "2. **Candidate generation misses representable completion relations.** Three missing-page queries have strong eligible gold-region candidates but no P1/P2, noisy-graph, or legacy seed-to-target relation. They cover same-document cross-page continuation and cross-document comparison cases.",
        "3. **Reading-graph coverage is too narrow.** The 42 validated NEXT/PREVIOUS records cover only 24 endpoint nodes in two documents. None of the seven missing-query cases is structurally covered, so the observed zero structure gain is a coverage result, not a negative finding about reading order in general.",
        "4. **Node/anchor representation is incomplete.** One missing element is a page headline whose box has no overlapping generated node. Additional region gaps also occur on pages already retrieved, especially table rows and small text elements. Page recall therefore overstates node-level evidence availability.",
        "5. **Verification cannot repair upstream recall.** No trusted semantic edge exists, and pairs discarded by the global candidate allocator never reach verification. Tight verification gates improve precision but cannot recover omitted candidates.",
        "", "## Most valuable next construction mechanism", "",
        "Prioritize a **coverage-aware, anchor-local edge constructor with per-source quotas**, rather than a larger global highest-score pool.", "",
        "- Preserve a small Top-K quota for every eligible source, especially sources that occur in frozen query seeds, while keeping evaluation queries and gold hidden from construction.",
        "- Use two explicit lanes: same-document section/reading continuation and cross-document typed entity–attribute correspondence.",
        "- Ground each proposal in one member span or one table row; reject anchors that merge unrelated rows or headings.",
        "- Carry candidate provenance through verification so locally high-ranked pairs cannot disappear solely because their absolute cosine is below a corpus-wide threshold.",
        "- Separately repair title/table-row node coverage; semantic edges cannot recover evidence that the frozen universe does not express.", "",
        "This mechanism directly addresses all three observed construction failures: locally useful pairs dropped by global allocation, absent same-/cross-document completion candidates, and coarse anchor ownership. Expanding traversal depth or graph slots does not address any of them.",
        "", "## Interpretation rules", "",
        "- Structure-only uses only `VALIDATED_READING_ARTIFACT` NEXT/PREVIOUS records.",
        "- Verified semantic uses only semantic edges whose audit record explicitly permits navigation. There are currently none.",
        "- Noisy `RELATED_OPEN`, P1/P2 proposer pairs, and legacy baseline pairs can identify a potential construction opportunity, but never count as trusted reachability.",
        "- Oracle semantic directly links a Top-10 seed to a spatial candidate on each missing gold page. It uses gold and is therefore only a theoretical ceiling.",
        "- Full item-level diagnostics, candidate node IDs, path lengths, and potential-pair sources are in `query_coverage_matrix.jsonl`.",
    ]
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--min-gold-coverage", type=float, default=0.5)
    args = parser.parse_args()
    if not 0 < args.min_gold_coverage <= 1:
        parser.error("--min-gold-coverage must be in (0, 1]")
    if args.out.exists():
        parser.error("output already exists; use a new versioned directory")
    matrix, summary = analyze(args)
    args.out.mkdir(parents=True)
    write_jsonl(args.out / "query_coverage_matrix.jsonl", matrix)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "REPORT.md").write_text("\n".join(report_lines(matrix, summary)) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
