#!/usr/bin/env python3
"""Semantic-edge v2 policy: competitive joint packing and marginal support audits."""
from __future__ import annotations

from collections import defaultdict

from query_semantic_edge_policy import *  # noqa: F401,F403

POLICY_VERSION = "query-semantic-edge-policy-v2-20261031"

MARGINAL = '''Compare the candidate original packet(s) with the CURRENTLY SELECTED original packets.
Decide only whether adding the candidate changes necessary answer support. Generated edge text is never evidence.
Return JSON only:
{"requirements":[{"id":"R1","before_status":"missing|partial|sufficient|unknown","after_status":"missing|partial|sufficient|unknown","gain_kind":"missing_fact|constraint_completion|enumeration_completion|contradiction|independent_corroboration|replacement|repeated_support|no_support|unknown","necessary_span_ids":["provided original span ID"],"reason":"short source-grounded reason"}],"overall":"keep|skip|unknown"}.
Use repeated_support when the candidate restates support already sufficient in the selected set. A different packet or wording is not by itself new answer information. Preserve differences in subject, year, unit, scope, property, negation, and enumeration completeness. independent_corroboration is lower priority unless the question requires corroboration. contradiction must be kept for resolution. unknown must not be converted to skip merely to save tokens.
'''

REDUNDANCY = '''Audit whether removing the candidate packet(s) from the FULL selected original set preserves every necessary fact, identity attribution, time/unit/scope constraint, enumeration completeness, and contradiction. Generated edge text is never evidence.
Return the same marginal-decision JSON schema. Treat CURRENTLY SELECTED as the set after removal and CANDIDATE as the removed material. Set overall=skip only when the removed material is repeated support or no support and the remaining originals preserve the same necessary support. Use overall=keep for any regression and overall=unknown when uncertain.
'''

GAIN_KINDS = {
    "missing_fact", "constraint_completion", "enumeration_completion", "contradiction",
    "independent_corroboration", "replacement", "repeated_support", "no_support", "unknown",
}
STATUS_ORDER = {"unknown": -1, "missing": 0, "partial": 1, "sufficient": 2}


def validate_marginal(result, plan, available_spans, candidate_packet_ids):
    """Validate a set-conditional keep/skip decision against original span IDs."""
    exact_keys(result, {"requirements", "overall"})
    expected = {row["id"] for row in plan["requirements"]}
    rows = result["requirements"]
    if not isinstance(rows, list) or {row.get("id") for row in rows} != expected or len(rows) != len(expected):
        raise ValueError("marginal requirement IDs must match exactly")
    if result["overall"] not in {"keep", "skip", "unknown"}:
        raise ValueError("invalid marginal overall decision")
    candidate_packet_ids = set(candidate_packet_ids)
    for row in rows:
        exact_keys(row, {"id", "before_status", "after_status", "gain_kind",
                         "necessary_span_ids", "reason"})
        if row["before_status"] not in STATUS_ORDER or row["after_status"] not in STATUS_ORDER:
            raise ValueError("invalid marginal support status")
        if row["gain_kind"] not in GAIN_KINDS or not nonempty(row["reason"]):
            raise ValueError("invalid marginal gain kind or reason")
        if not isinstance(row["necessary_span_ids"], list):
            raise ValueError("necessary_span_ids must be a list")
        if row["necessary_span_ids"]:
            cited_text(row["necessary_span_ids"], available_spans)
        if row["gain_kind"] in {"missing_fact", "constraint_completion", "enumeration_completion",
                                "contradiction", "independent_corroboration", "replacement"}:
            if not row["necessary_span_ids"]:
                raise ValueError("positive or conflicting marginal change needs original spans")
            if not any(available_spans[sid]["packet_id"] in candidate_packet_ids
                       for sid in row["necessary_span_ids"]):
                raise ValueError("marginal change must cite at least one candidate packet span")
    kinds = {row["gain_kind"] for row in rows}
    positive = kinds & {"missing_fact", "constraint_completion", "enumeration_completion", "contradiction"}
    if result["overall"] == "skip" and (positive or "unknown" in kinds):
        raise ValueError("skip cannot discard a positive, conflicting, or unknown change")
    if result["overall"] == "keep" and not (positive or kinds & {"independent_corroboration", "replacement"}):
        raise ValueError("keep needs a stated marginal benefit")
    return result


def support_delta(before, after):
    """Separate support gains, regressions, citation changes, and unchanged requirements."""
    b = {row["id"]: row for row in before["requirements"]}
    a = {row["id"]: row for row in after["requirements"]}
    gains, regressions, citation_changes, unchanged = [], [], [], []
    for rid in sorted(set(b) | set(a)):
        old, new = b[rid], a[rid]
        old_status, new_status = old["status"], new["status"]
        item = {"requirement_id": rid, "before_status": old_status, "after_status": new_status}
        if STATUS_ORDER.get(new_status, -1) > STATUS_ORDER.get(old_status, -1):
            gains.append(item)
        elif STATUS_ORDER.get(new_status, -1) < STATUS_ORDER.get(old_status, -1):
            regressions.append(item)
        else:
            old_spans = {sid for fact in old.get("support_facts", []) for sid in fact["span_ids"]}
            new_spans = {sid for fact in new.get("support_facts", []) for sid in fact["span_ids"]}
            (citation_changes if old_spans != new_spans else unchanged).append(item)
    return {"gains": gains, "regressions": regressions,
            "citation_changes_without_status_gain": citation_changes, "unchanged": unchanged}


def actual_gain(before, after):
    return support_delta(before, after)


def _selection_units(packets, assessments, joint_groups):
    units = []
    for pid, packet in packets.items():
        rows = assessments[pid]["requirements"]
        facts = [(row["id"], row["status"], tuple(sorted(fact["span_ids"])))
                 for row in rows for fact in row.get("support_facts", [])]
        if facts:
            units.append({"id": "packet:" + pid, "packet_ids": [pid], "facts": facts,
                          "base_score": packet["base_score"], "route_id": None})
    for index, group in enumerate(joint_groups):
        facts = [(fact["requirement_id"], fact["status"], tuple(sorted(fact["span_ids"])))
                 for fact in group["facts"]]
        if facts:
            units.append({"id": "joint:" + group.get("route_id", str(index)),
                          "packet_ids": list(group["packet_ids"]), "facts": facts,
                          "base_score": max(packets[pid]["base_score"] for pid in group["packet_ids"]),
                          "route_id": group.get("route_id")})
    return units


def pack_with_joint(packets, assessments, joint_groups, budget, tok, render):
    """Compete direct packets and atomic joint groups under one marginal-cost budget."""
    selected, chosen, dropped, selected_units = [], [], [], []
    sufficient_requirements, seen_facts = set(), set()
    remaining = _selection_units(packets, assessments, joint_groups)
    while remaining:
        ranked = []
        for unit in remaining:
            uncovered = [fact for fact in unit["facts"]
                         if fact[0] not in sufficient_requirements and (fact[0], fact[2]) not in seen_facts]
            newly_sufficient = {rid for rid, status, _ in uncovered if status == "sufficient"}
            addition_ids = [pid for pid in unit["packet_ids"] if pid not in chosen]
            additions = [packets[pid] for pid in addition_ids]
            cost = len(tok.encode(render(selected + additions), add_special_tokens=False))
            incremental_cost = max(0, cost - len(tok.encode(render(selected), add_special_tokens=False)))
            ranked.append(((len(newly_sufficient), len(uncovered), -incremental_cost,
                            unit["base_score"], unit["id"]), unit, uncovered, addition_ids, cost))
        _, unit, uncovered, addition_ids, total_cost = max(ranked, key=lambda row: row[0])
        remaining.remove(unit)
        if not uncovered:
            dropped.append({"id": unit["id"], "reason": "no_new_requirement_support",
                            "packet_ids": unit["packet_ids"]})
            continue
        additions = [packets[pid] for pid in addition_ids]
        duplicate_ids = [pid for pid in addition_ids if any(
            tuple(old["page"]) == tuple(packets[pid]["page"]) and
            old["member_sha256"] == packets[pid]["member_sha256"] for old in selected)]
        if duplicate_ids:
            dropped.append({"id": unit["id"], "reason": "same_page_exact_duplicate",
                            "packet_ids": duplicate_ids})
            continue
        if total_cost > budget:
            dropped.append({"id": unit["id"], "reason": "joint_group_over_budget" if unit["route_id"] else "whole_packet_over_budget",
                            "packet_ids": unit["packet_ids"]})
            continue
        for pid, packet in zip(addition_ids, additions):
            value = {**packet, "selection_id": pid}
            if unit["route_id"]:
                value["joint_route_id"] = unit["route_id"]
            selected.append(value)
            chosen.append(pid)
        selected_units.append(unit["id"])
        for rid, status, spans in uncovered:
            seen_facts.add((rid, spans))
            if status == "sufficient":
                sufficient_requirements.add(rid)
    return {"packets": selected, "selected_ids": chosen, "dropped": dropped,
            "unselected_ids": sorted(set(packets) - set(chosen)),
            "joint_groups_considered": joint_groups, "selection_units_selected": selected_units,
            "joint_route_ids_selected": sorted({p.get("joint_route_id") for p in selected
                                                 if p.get("joint_route_id")})}


def pack(packets, assessments, budget, tok, render):
    """Use the same requirement-conditional competition when no route group exists."""
    result = pack_with_joint(packets, assessments, [], budget, tok, render)
    result.pop("joint_groups_considered", None)
    result.pop("joint_route_ids_selected", None)
    return result


def deduplicate_joint_groups(groups):
    """Merge path provenance for groups with the same original packet/span support."""
    merged = {}
    for group in groups:
        key = tuple(sorted((fact["requirement_id"], tuple(sorted(fact["span_ids"])))
                           for fact in group["facts"]))
        if key not in merged:
            merged[key] = {**group, "route_ids": [group["route_id"]]}
        elif group["route_id"] not in merged[key]["route_ids"]:
            merged[key]["route_ids"].append(group["route_id"])
    return list(merged.values())
