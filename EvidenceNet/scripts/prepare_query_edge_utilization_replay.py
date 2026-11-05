#!/usr/bin/env python3
"""Prepare audited RouteRecords and CPU-only R1/R2 query-edge replay.

This is an isolated research adapter.  It never promotes unknown/denied edges,
does not read gold, and does not modify navigation or production consumers.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "migration/vldocir-edge-20261022/results"
TRACE = ROOT / "migration/vldocir_trace_inputs_20261023"
KG = ROOT / "EvidenceNet/output/kg_link_prediction_pilot_v2_20261102"
QWEN = SOURCE / "graph/related.jsonl"
QWEN_ROLE = ROOT / "EvidenceNet/output/edge_role_repaired_v1_20261023/graph/related.jsonl"
KG_NEW = ROOT / "EvidenceNet/output/kg_link_prediction_bounded_verification_ultra_smoke_v1_20261102/accepted_new_edges_model_only.jsonl"
KG_REVIEW = ROOT / "EvidenceNet/output/kg_accepted_edge_audit_job_119422/edge_review_queue.jsonl"
NAV = ROOT / "EvidenceNet/output/top10_node_navigation_20261029/navigation.jsonl"
DEFAULT_OUT = ROOT / "EvidenceNet/output/query_edge_utilization_replay_v1_20261105"
VERSION = "query-edge-utilization-replay-v1-20261105"
ARMS = ("R1_static", "R2_target_only", "R2_anchor_proxy")
INSPECTION_BUDGET = 6
TARGET_BUDGET = 3

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "by", "is", "are",
        "was", "were", "be", "been", "being", "that", "this", "these", "those", "how", "what", "which",
        "does", "do", "did", "from", "at", "as", "it", "its", "their", "one", "more", "all"}
GENERIC = {"vote", "voting", "votes", "proposal", "proposals", "share", "shares", "company", "effect",
           "evidence", "information", "related", "target", "source", "node"}


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((str(a), str(b))))


def tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w]+(?:[.-][\w]+)*", text.lower(), flags=re.UNICODE)
            if len(token) > 1 and token not in STOP and token not in GENERIC}


def member_map(node: dict) -> dict[str, dict]:
    return {str(member["id"]): member for member in node.get("members", [])}


def normalize_anchor(anchor: dict, edge_id: str, side: str, index: int,
                     expected_node: str, nodes: dict[str, dict]) -> dict:
    node_id = str(anchor.get("node_id"))
    member_id = str(anchor.get("member_id"))
    start, end = int(anchor.get("char_start", -1)), int(anchor.get("char_end", -1))
    quote = str(anchor.get("quote", ""))
    localizable, reasons = True, []
    if node_id != expected_node or node_id not in nodes:
        localizable = False; reasons.append("anchor_node_mismatch")
    member = member_map(nodes[node_id]).get(member_id) if node_id in nodes else None
    text = str(member.get("text", "")) if member else ""
    if member is None:
        localizable = False; reasons.append("member_missing")
    if not (0 <= start < end <= len(text)):
        localizable = False; reasons.append("offset_out_of_bounds")
    elif text[start:end] != quote:
        localizable = False; reasons.append("quote_slice_mismatch")
    expected_hash = hashlib.sha256(text.encode()).hexdigest() if member else None
    if anchor.get("member_sha256") != expected_hash:
        localizable = False; reasons.append("member_hash_mismatch")
    kind = str(anchor.get("kind", "UNKNOWN"))
    granularity = "coarse_or_unknown" if kind == "ORIGINAL_TABLE_ROW" else "span_window"
    return {
        "anchor_id": f"{edge_id}:{side}:{index:03d}", "side": side,
        "node_id": node_id, "member_id": member_id, "char_start": start, "char_end": end,
        "quote": quote, "member_sha256": anchor.get("member_sha256"), "boxes": anchor.get("boxes", []),
        "kind": kind, "granularity": granularity, "localizable": localizable,
        "localization_reasons": reasons,
    }


def route_record(edge_id: str, graph_version: str, source: str, target: str, direction: str,
                 relation: str, source_anchors: list[dict], target_anchors: list[dict],
                 eligibility: str, eligibility_reason: str, provenance: list[dict],
                 relation_text: str = "", conditions: str = "", limitations: str = "",
                 semantic_support_claimed: bool = False) -> dict:
    return {
        "route_id": hashlib.sha256(f"{edge_id}\0{source}\0{target}".encode()).hexdigest()[:24],
        "canonical_pair_id": hashlib.sha256("\0".join(canonical(source, target)).encode()).hexdigest()[:24],
        "edge_id": edge_id, "graph_version": graph_version,
        "oriented_source_id": source, "oriented_target_id": target, "direction": direction,
        "relation_type": relation, "relation_text": relation_text,
        "conditions": conditions, "limitations": limitations,
        "semantic_support_claimed": semantic_support_claimed,
        "semantic_truth_verified": False,
        "relation_claim_present": bool(relation_text),
        "source_anchors": source_anchors, "target_anchors": target_anchors,
        "anchors_localizable": bool(source_anchors and target_anchors and
                                    all(x["localizable"] for x in source_anchors + target_anchors)),
        "eligibility": eligibility, "eligibility_reason": eligibility_reason,
        "inspection_only": eligibility == "unknown", "provenance": provenance,
        "scores": {"pair_score": None, "query_score": None, "model_space": None},
    }


def adapt(nodes: dict[str, dict], eligible_nodes: set[str]) -> tuple[list[dict], dict]:
    qwen_rows = rows(QWEN)
    semantic_ids = {row["task_id"] for row in rows(QWEN_ROLE)}
    noisy_by_pair = {canonical(row["source_id"], row["target_id"]): row
                     for row in rows(KG / "noisy_semantic_edges.jsonl")}
    review = {row["edge_id"]: row for row in rows(KG_REVIEW)}
    records = []
    qwen_pairs = set()
    for edge in qwen_rows:
        edge_id, source, target = edge["task_id"], edge["source"], edge["target"]
        if source not in eligible_nodes or target not in eligible_nodes:
            continue
        qwen_pairs.add(canonical(source, target))
        anchors = edge["model_result"].get("anchors", {})
        side_a = [normalize_anchor(x, edge_id, "A", i, source, nodes) for i, x in enumerate(anchors.get("A", []))]
        side_b = [normalize_anchor(x, edge_id, "B", i, target, nodes) for i, x in enumerate(anchors.get("B", []))]
        noisy = noisy_by_pair.get(canonical(source, target))
        provenance = [{"source": "qwen_original", "edge_id": edge_id,
                       "proposer": "Qwen", "verifier": "Qwen model result",
                       "review": "not_human_verified", "semantic_role_lane": edge_id in semantic_ids}]
        if noisy:
            provenance.append({"source": "kg_noisy_observation", "edge_id": noisy["edge_id"],
                               "ancestor_edge_id": edge_id, "deduplicated_provenance_only": True})
        common = dict(edge_id=edge_id, graph_version="vldocir-qwen-related-20261022",
                      relation="RELATED", eligibility="unknown",
                      eligibility_reason="model-proposed; navigation permission absent; isolated inspection only",
                      provenance=provenance, relation_text=edge["model_result"].get("matched_claim", ""),
                      conditions=json.dumps(edge["model_result"].get("shared_identity", {}), sort_keys=True),
                      limitations=edge["model_result"].get("limitation", ""))
        records.append(route_record(source=source, target=target, direction="A_TO_B",
                                    source_anchors=side_a, target_anchors=side_b, **common))
        records.append(route_record(source=target, target=source, direction="B_TO_A",
                                    source_anchors=side_b, target_anchors=side_a, **common))

    new_pairs = set()
    for edge in rows(KG_NEW):
        edge_id, source, target = edge["edge_id"], edge["source_id"], edge["target_id"]
        if source not in eligible_nodes or target not in eligible_nodes:
            continue
        new_pairs.add(canonical(source, target))
        side_a = [normalize_anchor(x, edge_id, "A", i, source, nodes)
                  for i, x in enumerate(edge["anchors"].get("A", []))]
        side_b = [normalize_anchor(x, edge_id, "B", i, target, nodes)
                  for i, x in enumerate(edge["anchors"].get("B", []))]
        audit = review.get(edge_id)
        allowed = audit and audit.get("allowed_for_navigation") is True
        eligibility = "allowed" if allowed else "denied"
        reason = ("independent review explicitly allowed navigation" if allowed else
                  "review overlay denied navigation: " + str((audit or {}).get("audit_status", "missing_review")))
        common = dict(edge_id=edge_id, graph_version=edge["edge_version"], relation="EVIDENCE_LINK",
                      eligibility=eligibility, eligibility_reason=reason,
                      provenance=[{"source": "kg_new", "proposer": edge.get("proposer_membership"),
                                   "verifier": edge.get("edge_source"), "model": edge.get("model"),
                                   "review": (audit or {}).get("audit_status"),
                                   "allowed_for_navigation": bool(allowed)}],
                      relation_text=edge.get("relation_description", ""),
                      conditions=edge.get("entity_condition_constraints", ""),
                      limitations=edge.get("limitations", ""))
        directions = [(source, target, "A_TO_B", side_a, side_b),
                      (target, source, "B_TO_A", side_b, side_a)]
        for left, right, direction, source_side, target_side in directions:
            records.append(route_record(source=left, target=right, direction=direction,
                                        source_anchors=source_side, target_anchors=target_side, **common))

    reading_rows = rows(KG / "validated_reading_edges.jsonl")
    reading_eligible = 0
    for edge in reading_rows:
        source, target = edge["source_id"], edge["target_id"]
        if source not in eligible_nodes or target not in eligible_nodes:
            continue
        reading_eligible += 1
        records.append(route_record(
            edge_id=edge["edge_id"], graph_version=edge["graph_version"], source=source, target=target,
            direction="A_TO_B", relation=edge["relation_id"], source_anchors=[], target_anchors=[],
            eligibility="allowed", eligibility_reason="validated structural reading artifact; semantic support not implied",
            provenance=[{"source": "kg_validated_reading", "verification_status": edge["verification_status"]}],
            semantic_support_claimed=False))
    inventory = {
        "qwen_edges": len(qwen_rows), "qwen_semantic_role_edges": len(semantic_ids),
        "kg_noisy_edges": len(noisy_by_pair), "qwen_kg_noisy_pair_overlap": len(qwen_pairs & set(noisy_by_pair)),
        "kg_new_edges": len(new_pairs), "qwen_kg_new_pair_overlap": len(qwen_pairs & new_pairs),
        "reading_records": len(reading_rows), "reading_eligible_records": reading_eligible,
        "oriented_route_records": len(records),
        "eligibility": dict(Counter(row["eligibility"] for row in records)),
        "localizable_route_records": sum(row["anchors_localizable"] for row in records),
    }
    return records, inventory


def dense_scores(eligible: set[str]) -> tuple[dict[str, dict[str, float]], dict]:
    queries, units, windows = rows(TRACE / "queries.jsonl"), rows(TRACE / "units.jsonl"), rows(TRACE / "windows.jsonl")
    cache = np.load(SOURCE / "search/query_window_scores.npy", mmap_mode="r", allow_pickle=False)
    encoding = json.loads((SOURCE / "search/encoding.json").read_text())
    if sha(SOURCE / "search/query_window_scores.npy") != encoding["score_sha256"]:
        raise ValueError("changed query score cache")
    result = {}
    for qi, query in enumerate(queries):
        scores = {}
        for wi, window in enumerate(windows):
            node = units[int(window["unit_input_line"]) - 1]["unit_id"]
            if node in eligible:
                scores[node] = max(scores.get(node, -float("inf")), float(cache[qi, wi]))
        result[query["question_id"]] = scores
    return result, {"shape": list(cache.shape), "model": encoding["model"], "sha256": encoding["score_sha256"]}


def feature_record(query: str, route: dict, query_target_score: float) -> dict:
    q = tokens(query)
    source = set().union(*(tokens(x["quote"]) for x in route["source_anchors"])) if route["source_anchors"] else set()
    target = set().union(*(tokens(x["quote"]) for x in route["target_anchors"])) if route["target_anchors"] else set()
    relation = tokens(route["relation_text"] + " " + route["conditions"])
    source_hit, target_hit, relation_hit = sorted(q & source), sorted(q & target), sorted(q & relation)
    source_anchor_precision_ok = bool(route["source_anchors"]) and all(
        anchor["granularity"] != "coarse_or_unknown" for anchor in route["source_anchors"])
    applicable = (route["anchors_localizable"] and source_anchor_precision_ok and
                  bool(source_hit) and bool(target_hit or relation_hit))
    return {
        "query_target_score": query_target_score,
        "query_source_anchor_terms": source_hit, "query_target_anchor_terms": target_hit,
        "query_relation_terms": relation_hit, "source_overlap": len(source_hit),
        "target_overlap": len(target_hit), "relation_overlap": len(relation_hit),
        "anchor_proxy_applicable": applicable,
        "source_anchor_precision_ok": source_anchor_precision_ok,
        "missing_feature": not route["anchors_localizable"],
    }


def order_key(arm: str, item: dict) -> tuple:
    route, feature = item["route"], item["features"]
    stable = (int(item["source_dense_rank"]), route["edge_id"], route["oriented_target_id"])
    if arm == "R1_static":
        return stable
    if arm == "R2_target_only":
        return (-feature["query_target_score"],) + stable
    if arm == "R2_anchor_proxy":
        return (not feature["anchor_proxy_applicable"], -feature["source_overlap"],
                -feature["target_overlap"], -feature["relation_overlap"],
                -feature["query_target_score"]) + stable
    raise ValueError(arm)


def select_arm(arm: str, candidates: list[dict], dense20: set[str]) -> tuple[list[dict], list[dict], dict]:
    ranked = sorted(candidates, key=lambda row: order_key(arm, row))
    selected, targets, decisions = [], set(), []
    anchors_read = 0
    for item in ranked:
        route, feature = item["route"], item["features"]
        if arm == "R2_anchor_proxy":
            anchors_read += len(route["source_anchors"]) + len(route["target_anchors"])
        if route["eligibility"] == "denied":
            action, reason = "reject", "eligibility_denied"
        elif route["eligibility"] not in {"allowed", "unknown"}:
            action, reason = "unknown", "unrecognized_eligibility"
        elif arm == "R2_anchor_proxy" and not feature["anchor_proxy_applicable"]:
            action, reason = "reject", "source_anchor_or_relation_not_query_applicable"
        elif len(selected) >= INSPECTION_BUDGET:
            action, reason = "reject", "inspection_budget_full"
        elif route["oriented_target_id"] in targets:
            action, reason = "reject", "duplicate_target_provenance_merged"
        elif len(targets) >= TARGET_BUDGET:
            action, reason = "reject", "unique_target_budget_full"
        else:
            targets.add(route["oriented_target_id"])
            action = "link_existing" if route["oriented_target_id"] in dense20 else "inspect"
            reason = ("target_already_in_dense20_composition_only" if action == "link_existing" else
                      "research_inspection_only_not_admitted")
            selected.append(item)
        decisions.append({**item, "arm": arm, "action": action, "reason": reason,
                          "expected_delta": None, "admitted": False})
    stop = "no_usable_route" if not selected else "inspection_or_link_candidates_selected"
    ledger = {"edges_scanned": len(candidates), "anchors_read": anchors_read,
              "routes_selected_for_inspection": len(selected), "unique_targets": len(targets),
              "new_targets_outside_dense20": sum(x["route"]["oriented_target_id"] not in dense20 for x in selected),
              "llm_calls": 0, "llm_input_tokens": 0, "llm_output_tokens": 0,
              "reranker_pairs": 0, "stop_reason": stop}
    return selected, decisions, ledger


def validate_evidence_state(state: dict) -> None:
    allowed = {"missing", "partial", "sufficient", "unknown"}
    for req in state.get("requirements", []):
        if req.get("status") not in allowed:
            raise ValueError("invalid requirement status")
        if req["status"] == "sufficient" and (req.get("missing_slots") or req.get("unresolved_constraints")):
            raise ValueError("sufficient requirement retains unresolved slots")
        if req["status"] in {"missing", "unknown"} and req.get("support_span_ids"):
            raise ValueError("missing/unknown requirement cannot claim support spans")


def state_conditioned_action(status: str, route_applicable: bool) -> str:
    if status == "sufficient": return "reject_redundant"
    if status in {"missing", "partial"} and route_applicable: return "inspect"
    if status == "unknown": return "unknown"
    return "reject_not_applicable"


def replay(route_records: list[dict], navigation_rows: list[dict], eligible: set[str],
           scores: dict[str, dict[str, float]]) -> tuple[list[dict], list[dict], dict, dict]:
    incident = defaultdict(list)
    for route in route_records:
        incident[route["oriented_source_id"]].append(route)
    all_decisions, ledgers, per_query = [], [], []
    count_by_source = defaultdict(lambda: {"queries": set(), "routes": 0, "novel": 0, "pages": set()})
    nodes = {row["id"]: row for row in rows(SOURCE / "nodes.jsonl")}
    raw_change = 0
    for context in navigation_rows:
        qid = context["question_id"]
        raw = context["node_ranking"]
        filtered = [node for node in raw if node in eligible]
        if len(filtered) != 6520 or len(set(filtered)) != 6520:
            raise ValueError("bad filtered universe: " + qid)
        if raw[:10] != filtered[:10]: raw_change += 1
        seeds, dense20 = filtered[:10], set(filtered[:20])
        seed_pages = {(nodes[x]["document"], int(nodes[x]["page"])) for x in seeds}
        candidates = []
        for rank, source in enumerate(seeds, 1):
            for route in incident.get(source, []):
                target = route["oriented_target_id"]
                feature = feature_record(context["question"], route, scores[qid][target])
                item = {"question_id": qid, "question": context["question"], "route": route,
                        "source_dense_rank": rank, "target_dense_rank": filtered.index(target) + 1,
                        "target_page": [nodes[target]["document"], int(nodes[target]["page"])],
                        "features": feature}
                candidates.append(item)
                source_name = route["provenance"][0]["source"]
                stats = count_by_source[source_name]; stats["queries"].add(qid); stats["routes"] += 1
                if target not in seeds: stats["novel"] += 1
                if (nodes[target]["document"], int(nodes[target]["page"])) not in seed_pages:
                    stats["pages"].add((qid, nodes[target]["document"], int(nodes[target]["page"])))
        query_summary = {"question_id": qid, "potential_routes": len(candidates), "arms": {}}
        for arm in ARMS:
            selected, decisions, ledger = select_arm(arm, candidates, dense20)
            all_decisions.extend(decisions); ledgers.append({"question_id": qid, "arm": arm, **ledger})
            query_summary["arms"][arm] = {"selected": len(selected), "stop_reason": ledger["stop_reason"],
                                               "targets": [x["route"]["oriented_target_id"] for x in selected]}
        per_query.append(query_summary)
    historical = {
        "raw_navigation_sizes": dict(Counter(len(x["node_ranking"]) for x in navigation_rows)),
        "filtered_size": 6520, "queries_top10_changed": raw_change,
        "route_counts": {name: {"queries": len(value["queries"]), "oriented_routes": value["routes"],
                                "novel_target_occurrences": value["novel"],
                                "novel_page_occurrences": len(value["pages"])}
                         for name, value in count_by_source.items()},
    }
    target_119397 = "f2ffcdc7-a320-41e0-b7e6-a5a843d468a4_3_HY_006"
    qid_119397 = "0c51adad-0445-4105-b846-ca6b5a9d3b82"
    context = next(x for x in navigation_rows if x["question_id"] == qid_119397)
    historical["job_119397_target_rank"] = {
        "target_id": target_119397, "raw_rank": context["node_ranking"].index(target_119397) + 1,
        "filtered_rank": [x for x in context["node_ranking"] if x in eligible].index(target_119397) + 1}
    return all_decisions, ledgers, {"queries": per_query}, historical


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: Iterable[dict]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        for value in values: stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def report(summary: dict) -> str:
    history, inventory = summary["historical_reproduction"], summary["inventory"]
    lines = ["# Query–Edge Utilization Phase-1 Replay", "", "## Result", "",
             "Tasks A/B and the CPU-only R1/R2 interface replay are complete. No Gold, LLM, GPU, verifier, reranker, or production navigation was used.", "",
             "The adapter preserves provenance, direction-specific anchors, three-state eligibility, and canonical deduplication. Qwen/KG noisy duplicates contribute provenance once, not two confidence votes. All eight KG-new edges are denied by the review overlay; old Qwen relations remain unknown and inspection-only.", "",
             "## Required reproduction checks", "",
             f"- Raw rankings: `{history['raw_navigation_sizes']}`; filtered universe: {history['filtered_size']} unique nodes.",
             f"- Top-10 changes after filtering: {history['queries_top10_changed']}/24 (expected 7/24).",
             f"- Job 119397 target rank: raw {history['job_119397_target_rank']['raw_rank']} → filtered {history['job_119397_target_rank']['filtered_rank']} (expected 211 → 206).",
             f"- Inventory: Qwen={inventory['qwen_edges']}, role-semantic={inventory['qwen_semantic_role_edges']}, KG-new={inventory['kg_new_edges']}, reading={inventory['reading_records']}.",
             f"- Qwen/KG-noisy overlap={inventory['qwen_kg_noisy_pair_overlap']}; Qwen/KG-new overlap={inventory['qwen_kg_new_pair_overlap']}.", "",
             "## CPU arms", "",
             "`R1_static` enumerates research-eligible adjacency only; `R2_target_only` uses the frozen query→target score; `R2_anchor_proxy` additionally requires lexical activation of the actual oriented source anchor and relation/target anchor. All arms may select zero routes, inspect at most six routes, and nominate at most three unique targets. Unknown never becomes admitted; denied always rejects.", ""]
    for arm, data in summary["arm_summary"].items():
        lines.append(f"- **{arm}:** selected {data['selected']} route occurrences; queries with selection {data['queries_with_selection']}/24; zero-selection queries {data['zero_selection_queries']}/24; new targets outside Dense20 {data['new_targets_outside_dense20']}.")
    case = summary["kmpg_case"]
    lines += ["", "## KPMG mixed-table acceptance case", "",
              f"- Edge `{case['edge_id']}` eligibility: `{case['eligibility']}`; anchor proxy applicable: `{case['anchor_proxy_applicable']}`.",
              f"- Final action: `{case['action']}` (`{case['reason']}`). Query terms overlap the mixed table window, but it is coarse/unknown rather than a precise auditor row and the auditor relation has no query-term match; the review overlay independently denies navigation.", "",
              "## Capability boundary", "",
              "There are currently no independently certified semantic positive routes. Therefore useful-edge precision, abstention accuracy, verified-edge recovery, reranked evidence, and final evidence recall remain unknown/not-run. The CPU proxy is an auditable screening mechanism, not a semantic validator.", "",
              "R3 is represented only by a validated EvidenceState contract and counterfactual component tests. It is not run over the 24 queries because no independent state labels exist and the review explicitly forbids presenting historical/model state as ground truth.", "",
              "## Recommendation", "",
              "Freeze at this phase boundary. Inspect the emitted route/action traces and, if proceeding, create the preregistered ≤12-route blind manual set. Do not run a reranker or migrate the adapter into production until at least one independently valid and query-useful route survives the source-anchor and opportunity-cost checks."]
    return "\n".join(lines) + "\n"


def run(output: Path) -> dict:
    output = output.resolve()
    if output.exists(): raise ValueError("fresh output required: " + str(output))
    inputs = {
        "nodes": SOURCE / "nodes.jsonl", "universe": KG / "candidate_universe.jsonl", "navigation": NAV,
        "qwen": QWEN, "qwen_role": QWEN_ROLE, "kg_noisy": KG / "noisy_semantic_edges.jsonl",
        "kg_new": KG_NEW, "kg_review": KG_REVIEW, "reading": KG / "validated_reading_edges.jsonl",
        "query_scores": SOURCE / "search/query_window_scores.npy", "score_encoding": SOURCE / "search/encoding.json",
        "queries": TRACE / "queries.jsonl", "units": TRACE / "units.jsonl", "windows": TRACE / "windows.jsonl",
    }
    started = time.perf_counter()
    nodes = {row["id"]: row for row in rows(inputs["nodes"])}
    eligible = {row["entity_id"] for row in rows(inputs["universe"]) if row.get("primary_eligible") is True}
    if len(eligible) != 6520: raise ValueError("universe changed")
    route_records, inventory = adapt(nodes, eligible)
    scores, score_meta = dense_scores(eligible)
    navigation = rows(inputs["navigation"])
    decisions, ledgers, per_query, history = replay(route_records, navigation, eligible, scores)
    if history["queries_top10_changed"] != 7 or history["job_119397_target_rank"] != {
            "target_id": "f2ffcdc7-a320-41e0-b7e6-a5a843d468a4_3_HY_006", "raw_rank": 211, "filtered_rank": 206}:
        raise ValueError("historical version reproduction failed")
    arm_summary = {}
    for arm in ARMS:
        arm_ledgers = [x for x in ledgers if x["arm"] == arm]
        arm_summary[arm] = {
            "selected": sum(x["routes_selected_for_inspection"] for x in arm_ledgers),
            "queries_with_selection": sum(x["routes_selected_for_inspection"] > 0 for x in arm_ledgers),
            "zero_selection_queries": sum(x["routes_selected_for_inspection"] == 0 for x in arm_ledgers),
            "new_targets_outside_dense20": sum(x["new_targets_outside_dense20"] for x in arm_ledgers),
            "anchors_read": sum(x["anchors_read"] for x in arm_ledgers),
        }
    kmpg = next(x for x in decisions if x["question_id"].startswith("0c51adad") and
                 x["route"]["edge_id"] == "MODEL_EDGE_eb8e8fb4464121433246" and
                 x["arm"] == "R2_anchor_proxy")
    kmpg_case = {"edge_id": kmpg["route"]["edge_id"], "eligibility": kmpg["route"]["eligibility"],
                  "anchor_proxy_applicable": kmpg["features"]["anchor_proxy_applicable"],
                  "action": kmpg["action"], "reason": kmpg["reason"]}
    git_status = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True,
                                capture_output=True, check=True).stdout.splitlines()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                            capture_output=True, check=True).stdout.strip()
    summary = {
        "version": VERSION, "status": "COMPLETE", "inventory": inventory,
        "historical_reproduction": history, "query_score_cache": score_meta,
        "arm_summary": arm_summary, "kmpg_case": kmpg_case,
        "execution_boundary": {"gold_read": False, "llm_calls": 0, "gpu_used": False,
                               "embeddings_generated": 0, "reranker_run": False,
                               "production_modified": False},
        "interpretation": {"unknown_is_negative": False, "selected_is_admitted": False,
                           "verified_edge_recovery": None, "final_evidence_recall": None},
        "git": {"branch": "feature/evidence-edges", "commit": commit,
                "dirty_or_untracked_at_start": git_status},
        "timing_seconds": time.perf_counter() - started,
    }
    output.mkdir(parents=True)
    write_jsonl(output / "route_records.jsonl", route_records)
    write_jsonl(output / "route_decisions.jsonl", decisions)
    write_jsonl(output / "budget_ledger.jsonl", ledgers)
    write_json(output / "per_query.json", per_query)
    write_json(output / "summary.json", summary)
    write_json(output / "status.json", {"state": "complete",
        "allowed_states": ["prepared", "running", "complete", "partial", "failed"],
        "version": VERSION, "gold_read": False, "production_modified": False})
    write_json(output / "evidence_state.schema.json", {
        "status_values": ["missing", "partial", "sufficient", "unknown"],
        "required_fields": ["requirement_id", "query_basis", "constraints", "status",
                            "support_span_ids", "missing_slots", "unresolved_constraints", "uncertainty"],
        "semantic_rules": ["sufficient forbids missing slots/unresolved constraints",
                           "missing/unknown forbids claimed support spans", "unknown is never auto-promoted"],
    })
    (output / "REPORT.md").write_text(report(summary), encoding="utf-8")
    config = {"version": VERSION, "seeds": 10, "hops": 1, "inspection_budget": INSPECTION_BUDGET,
              "unique_target_budget": TARGET_BUDGET, "arms": list(ARMS),
              "selector_inputs": list(inputs), "gold_input": None,
              "commands": [f"python {Path(__file__).relative_to(ROOT)} run --out {output.relative_to(ROOT)}",
                           f"python {Path(__file__).relative_to(ROOT)} check --out {output.relative_to(ROOT)}"]}
    write_json(output / "config.json", config)
    manifest = {"version": VERSION,
                "inputs": {name: {"path": str(path.resolve()), "sha256": sha(path)} for name, path in inputs.items()},
                "outputs": {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()},
                "code": {str(Path(__file__).resolve()): sha(Path(__file__).resolve()),
                         str((ROOT / "EvidenceNet/tests/test_query_edge_utilization_replay.py").resolve()):
                             sha(ROOT / "EvidenceNet/tests/test_query_edge_utilization_replay.py")}}
    write_json(output / "manifest.json", manifest)
    return summary


def check(output: Path) -> None:
    manifest = json.loads((output / "manifest.json").read_text())
    for item in manifest["inputs"].values():
        if sha(Path(item["path"])) != item["sha256"]: raise ValueError("changed input: " + item["path"])
    for name, expected in manifest["outputs"].items():
        if sha(output / name) != expected: raise ValueError("changed output: " + name)
    for raw, expected in manifest["code"].items():
        if sha(Path(raw)) != expected: raise ValueError("changed code: " + raw)
    print("QUERY_EDGE_UTILIZATION_REPLAY_OK")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run"); execute.add_argument("--out", type=Path, default=DEFAULT_OUT)
    verify = sub.add_parser("check"); verify.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(run(args.out), ensure_ascii=False, indent=2, sort_keys=True) if args.command == "run"
          else (check(args.out) or ""))


if __name__ == "__main__": main()
