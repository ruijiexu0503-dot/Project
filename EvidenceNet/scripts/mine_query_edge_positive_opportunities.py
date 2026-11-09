#!/usr/bin/env python3
"""Mine possible Query–Edge positive opportunities without new model calls.

Gold is used only to locate missing spatial EvidenceNode candidates and to
diagnose reachability. Existing route records are never promoted: denied edges
remain rejected and unknown edges remain inspection-only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
ORACLE = ROOT / "EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/query_coverage_matrix.jsonl"
ROUTES = ROOT / "EvidenceNet/output/query_edge_utilization_replay_v1_20261105/route_records.jsonl"
NODES = ROOT / "migration/vldocir-edge-20261022/results/nodes.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/query_edge_positive_opportunity_mining_v1_20261106"
VERSION = "query-edge-positive-opportunity-mining-v1-20261106"
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with",
        "by", "is", "are", "was", "were", "be", "this", "that", "which", "what",
        "how", "does", "from", "as", "it", "its", "their"}


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path: Path, values: Iterable[dict]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        for value in values:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text(node: dict) -> str:
    return " ".join(str(member.get("text", "")) for member in node.get("members", []))


def tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]+", value.lower())
            if len(x) > 2 and x not in STOP}


def source_kind(route: dict) -> str:
    provenance = route.get("provenance") or []
    return str(provenance[0].get("source", "unknown")) if provenance else "unknown"


def route_key(route: dict) -> tuple[str, str, str]:
    return (str(route["edge_id"]), str(route["oriented_source_id"]),
            str(route["oriented_target_id"]))


def adjacency(routes: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    for route in routes:
        result[str(route["oriented_source_id"])].append(route)
    for values in result.values():
        values.sort(key=route_key)
    return result


def path_status(path: list[dict]) -> str:
    eligibility = [str(edge.get("eligibility")) for edge in path]
    if "denied" in eligibility:
        return "denied_path"
    if "unknown" in eligibility:
        return "inspection_only_path"
    if all(value == "allowed" for value in eligibility):
        return "allowed_path"
    return "unclassified_path"


def find_paths(graph: dict[str, list[dict]], seeds: list[str], target: str,
               max_hops: int = 2) -> list[list[dict]]:
    found: list[list[dict]] = []
    queue = deque((seed, []) for seed in sorted(set(seeds)))
    seen = {(seed, 0) for seed in set(seeds)}
    while queue:
        node, path = queue.popleft()
        if node == target and path:
            found.append(path)
            continue
        if len(path) >= max_hops:
            continue
        for edge in graph.get(node, []):
            next_node = str(edge["oriented_target_id"])
            state = (next_node, len(path) + 1)
            if state in seen:
                continue
            seen.add(state)
            queue.append((next_node, path + [edge]))
    found.sort(key=lambda path: (len(path), path_status(path),
                                 tuple(route_key(edge) for edge in path)))
    return found


def target_has_any_relation(routes: list[dict], target: str) -> bool:
    return any(target in {str(r["oriented_source_id"]), str(r["oriented_target_id"])}
               for r in routes)


def anchor_summary(route: dict) -> dict:
    return {
        "source": [
            {"node_id": x.get("node_id"), "member_id": x.get("member_id"),
             "quote": x.get("quote"), "kind": x.get("kind"),
             "localizable": x.get("localizable")}
            for x in route.get("source_anchors", [])
        ],
        "target": [
            {"node_id": x.get("node_id"), "member_id": x.get("member_id"),
             "quote": x.get("quote"), "kind": x.get("kind"),
             "localizable": x.get("localizable")}
            for x in route.get("target_anchors", [])
        ],
    }


def classify_path(path: list[dict], target: str, top10: set[str], nodes: dict[str, dict]) -> str:
    status = path_status(path)
    if status == "denied_path":
        return "reachable_but_relation_invalid"
    if status == "inspection_only_path":
        return "reachable_but_unverified"
    if status == "allowed_path" and target not in top10:
        return "valid_and_possible_incremental_evidence"
    if status == "allowed_path":
        return "dense_already_contains_target"
    return "uncertain"


def gold_mining(matrix: list[dict], routes: list[dict], nodes: dict[str, dict]) -> list[dict]:
    graph = adjacency(routes)
    result = []
    for query in matrix:
        if not query.get("missing_top10_gold_pages"):
            continue
        top10 = set(query["dense_top10_ids"])
        top20 = set(query["dense_top20_ids"])
        missing_pages = {tuple(page) for page in query["missing_top10_gold_pages"]}
        for item in query["gold_item_diagnostics"]:
            page = (str(item["document_id"]), int(item["page_number"]))
            if page not in missing_pages:
                continue
            candidates = [x for x in item.get("eligible_strong_candidates", [])
                          if x.get("eligible") is True]
            for candidate in candidates:
                target = str(candidate["node_id"])
                paths10 = find_paths(graph, sorted(top10), target)
                paths20 = find_paths(graph, sorted(top20), target)
                for cutoff, paths in ((10, paths10), (20, paths20)):
                    direct = [path for path in paths if len(path) == 1]
                    if paths:
                        classification = classify_path(
                            paths[0], target, top10 if cutoff == 10 else top20, nodes
                        )
                    elif target_has_any_relation(routes, target):
                        classification = "existing_relation_but_unreachable"
                    else:
                        classification = "no_existing_relation"
                    result.append({
                        "kind": "gold_guided_opportunity",
                        "query_id": query["question_id"],
                        "query": query["question"],
                        "gold_id": item["gold_id"],
                        "gold_page": [page[0], page[1]],
                        "target_id": target,
                        "target_node_type": nodes.get(target, {}).get("node_type"),
                        "target_document": nodes.get(target, {}).get("document"),
                        "target_page": nodes.get(target, {}).get("page"),
                        "gold_coverage": candidate.get("gold_coverage"),
                        "dense_cutoff": cutoff,
                        "target_dense_rank": (query["dense_top20_ids"].index(target) + 1
                                              if target in query["dense_top20_ids"] else None),
                        "paths_within_two_hops": [
                            {
                                "status": path_status(path),
                                "classification": classify_path(path, target, top10, nodes),
                                "routes": [
                                    {
                                        "edge_id": edge["edge_id"],
                                        "source_id": edge["oriented_source_id"],
                                        "target_id": edge["oriented_target_id"],
                                        "relation_type": edge.get("relation_type"),
                                        "eligibility": edge.get("eligibility"),
                                        "source_kind": source_kind(edge),
                                        "relation_text": edge.get("relation_text"),
                                        "anchors": anchor_summary(edge),
                                    }
                                    for edge in path
                                ],
                            }
                            for path in paths
                        ],
                        "classification": classification,
                        "direct_path_count": len(direct),
                        "reason": (
                            "Gold geometry identifies a strong spatial candidate; this is "
                            "a reachability opportunity, not proof that the node answers "
                            "the Query or that an Edge is valid."
                        ),
                    })
    return result


def edge_first_candidates(routes: list[dict], nodes: dict[str, dict], limit: int = 12) -> list[dict]:
    candidates = []
    for route in routes:
        source = nodes.get(str(route["oriented_source_id"]), {})
        target = nodes.get(str(route["oriented_target_id"]), {})
        source_tokens = tokens(text(source))
        target_tokens = tokens(text(target))
        shared = source_tokens & target_tokens
        union = source_tokens | target_tokens
        jaccard = len(shared) / len(union) if union else 1.0
        if len(shared) < 2 or jaccard >= 0.45:
            continue
        if not route.get("source_anchors") or not route.get("target_anchors"):
            continue
        candidates.append({
            "kind": "constructed_evaluation_candidate",
            "constructed_evaluation": True,
            "query": (
                "What additional condition, explanation, comparison, or definition "
                "in the target passage is needed beyond the source passage?"
            ),
            "source_id": route["oriented_source_id"],
            "target_id": route["oriented_target_id"],
            "edge_id": route["edge_id"],
            "edge_source": source_kind(route),
            "eligibility": route.get("eligibility"),
            "relation_type": route.get("relation_type"),
            "relation_text": route.get("relation_text"),
            "source_anchor": anchor_summary(route)["source"],
            "target_anchor": anchor_summary(route)["target"],
            "source_excerpt": text(source)[:1200],
            "target_excerpt": text(target)[:1200],
            "dense_rank_unknown": True,
            "manual_checks": {
                "source_alone_answers": None,
                "target_adds_required_information": None,
                "target_in_frozen_dense_top10": None,
                "anchor_supports_transition": None,
                "label": "uncertain",
                "notes": "",
            },
            "heuristic": {"shared_terms": sorted(shared), "jaccard": round(jaccard, 6)},
        })
    candidates.sort(key=lambda x: (
        x["eligibility"] != "allowed",
        x["heuristic"]["jaccard"],
        x["edge_id"],
        x["source_id"],
        x["target_id"],
    ))
    return candidates[:limit]


def run(out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f"refusing to overwrite: {out}")
    matrix = rows(ORACLE)
    routes = rows(ROUTES)
    nodes = {str(row["id"]): row for row in rows(NODES)}
    if len(matrix) != 24:
        raise ValueError(f"expected 24 frozen queries, got {len(matrix)}")
    if len(routes) != 474:
        raise ValueError(f"expected 474 oriented route records, got {len(routes)}")
    out.mkdir(parents=True)
    (out / "audit_only").mkdir()
    mining = gold_mining(matrix, routes, nodes)
    controlled = edge_first_candidates(routes, nodes)
    write_jsonl(out / "gold_guided_opportunities.jsonl", mining)
    write_jsonl(out / "edge_first_controlled_query_candidates.jsonl", controlled)
    counts = Counter(row["classification"] for row in mining)
    summary = {
        "version": VERSION,
        "frozen_queries": len(matrix),
        "oriented_routes": len(routes),
        "gold_guided_rows": len(mining),
        "gold_guided_classifications": dict(sorted(counts.items())),
        "potential_positive_rows": sum(
            row["classification"] == "valid_and_possible_incremental_evidence"
            for row in mining
        ),
        "controlled_query_candidates": len(controlled),
        "controlled_query_status": "constructed_evaluation_pending_manual_review",
        "llm_calls": 0,
        "gold_used_for": "missing-page spatial localization and reachability diagnosis only",
        "gold_not_used_for": "edge promotion, query selection, or validity certification",
        "production_modified": False,
        "inputs_sha256": {str(path): sha(path) for path in (ORACLE, ROUTES, NODES)},
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False,
                                                   sort_keys=True, indent=2) + "\n",
                                         encoding="utf-8")
    (out / "README.md").write_text(
        f"""# Query–Edge Positive Opportunity Mining

Version: `{VERSION}`. CPU-only, no new LLM calls, no Edge construction and no
production changes.

`gold_guided_opportunities.jsonl` starts from the seven Dense Top-10 incomplete
queries, maps missing Gold boxes to strong spatial EvidenceNode candidates, and
tests existing oriented routes from Dense Top-10/Top-20 seeds for at most two
hops. Spatial overlap is not an Edge-validity label. Denied routes remain
invalid and unknown routes remain inspection-only.

`edge_first_controlled_query_candidates.jsonl` contains a small, deterministic
set of constructed-evaluation candidates. Its `manual_checks` fields are
intentionally unfilled and must not be mixed with natural-query metrics.
""",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(run(args.out), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
