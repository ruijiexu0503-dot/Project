#!/usr/bin/env python3
"""Protocol v3: grounded support, non-support observations, and semantic routes."""
from __future__ import annotations

import copy
from query_evidence_policy_v2 import *  # query planning and graph traversal stay frozen

ASSESS = '''Evaluate this ONE original packet against every frozen requirement. Return JSON only:
{"requirements":[{"id":"R1","status":"missing|partial|sufficient","validation_state":"valid","exhaustive":false,"support_facts":[{"meaning":"what the cited original spans directly support","span_ids":["provided span ID"]}],"observations":[{"meaning":"background, scope mismatch, absence reason, or navigation clue","span_ids":["provided span ID"]}],"missing":["unresolved requested detail"]}]}.
support_facts are positive answer support. observations never create coverage gain. A missing requirement MUST have support_facts=[] but may have observations. Use status=missing, not partial, when there are observations but no positive support_facts. For partial, missing MUST name the unresolved detail; do not leave it empty. Each observation should use {"meaning":"...","span_ids":["provided span ID"]}; an absence note may use span_ids=[]. Preserve subject, time, unit, scope, negation, and the actual property bearer. Do not turn co-occurrence, a navigation date, a relation description, or external knowledge into support. A set is sufficient only when completeness is explicit and exhaustive=true. A stated total whose members are all enumerated, or an accounting of all four Grand Slam tournaments, can establish exhaustive=true.
'''
VERIFY = '''Audit ONLY the selected original packets jointly. Return JSON only:
{"requirements":[{"id":"R1","status":"missing|partial|sufficient","validation_state":"valid","exhaustive":false,"support_facts":[{"meaning":"joint or direct support","span_ids":["all necessary original span IDs"]}],"observations":[],"missing":["unresolved detail"]}]}.
Generated edge descriptions are not evidence. Joint support must cite every original span needed for subject/time/unit/property attribution. missing may contain observations but has no support_facts. Use observation objects with meaning and span_ids; absence notes may use an empty span_ids list. New irrelevant context cannot erase already grounded support; a real contradiction must be recorded in observations and may lower status. For a set, mark exhaustive=true when a stated total is fully enumerated or the source accounts for every possible member (for example, all four Grand Slam tournaments).
January-March is calendar Q1 only when the source is clearly using a calendar year; never apply that equivalence silently to a fiscal or otherwise shifted year.
'''
NAVIGATE = '''Judge every offered existing route against the unresolved requirements. The offline relation description is a fallible navigation hint, never evidence. A hidden or endpoint-only relation description does NOT make the supplied original anchors unavailable. Return:
{"routes":[{"id":"provided route ID","follow":true,"requirements":["R1"],"expected_gain":"direct_evidence|necessary_context|bridge","source_anchor_ids":["provided edge anchor ID"],"constraint_checks":["entity/time/unit/property check"],"reason":"specific grounded expectation","uncertainty":"remaining uncertainty"}]}.
source_anchor_ids must contain only exact provided anchor span_id values such as REL_x:A:S000, never member_id or node_id. For rejection use follow=false, requirements=[], expected_gain="none", but still provide reason, constraint_checks, and uncertainty. A bridge may be followed without answer coverage. Shared topic alone is insufficient. Do not invent an edge, target content, or answer.
'''


def configure_edges(edges, mode):
    """Freeze B/C ablation: identical graph, with generated descriptions hidden/shown."""
    if mode in {"fixed", "navigation", "navigation_semantic"}:
        return copy.deepcopy(edges)
    if mode != "navigation_endpoint":
        raise ValueError("unknown semantic-edge arm")
    output = copy.deepcopy(edges)
    for edge in output:
        original = edge["relation_description"]
        edge["relation_description"] = {
            "status": "ENDPOINT_ONLY_CONTROL", "text": "",
            "limitations": "Generated relation text is hidden for this arm; original anchors remain available.",
            "cited_span_ids": [], "provenance": original.get("provenance"),
        }
        edge["description_metadata"]["hidden_for_arm"] = True
    return output


def _facts(row):
    return row.get("support_facts")


def _validate_observations(values, spans, allowed_packet=None):
    if not isinstance(values, list):
        raise ValueError("observations must be a list")
    for item in values:
        exact_keys(item, {"meaning", "span_ids"})
        if not nonempty(item["meaning"]):
            raise ValueError("observation needs meaning")
        if not isinstance(item["span_ids"], list) or any(not isinstance(x, str) for x in item["span_ids"]):
            raise ValueError("observation span_ids must be a string list")
        if item["span_ids"]:
            cited_text(item["span_ids"], spans, allowed_packet)


def _normalize_requirement(row):
    """Conservative protocol repairs; raw model output remains in the call record."""
    row = copy.deepcopy(row)
    observations = row.get("observations")
    if isinstance(observations, list):
        row["observations"] = [
            {"meaning": value, "span_ids": []} if isinstance(value, str) else value
            for value in observations]
    if row.get("status") == "partial" and row.get("support_facts") == []:
        row["status"] = "missing"
    if (row.get("status") == "partial" and row.get("support_facts") and
            row.get("missing") == [] and row.get("observations")):
        # Preserve grounded positive evidence. The model already stated its
        # unresolved limitation in observations; copying that note into the
        # missing field is conservative and avoids a lossy semantic retry.
        row["missing"] = [item["meaning"] for item in row["observations"]
                          if isinstance(item, dict) and nonempty(item.get("meaning"))]
    return row


def validate_assessment(result, plan, pid, spans):
    expected = check_requirements(result, plan)
    result = copy.deepcopy(result)
    for row in result["requirements"]:
        normalized = _normalize_requirement(row)
        row.clear(); row.update(normalized)
        exact_keys(row, {"id", "status", "validation_state", "exhaustive", "support_facts", "observations", "missing"})
        if row["validation_state"] != "valid":
            raise ValueError("model assessment validation_state must be valid")
        conservative_state(row, expected[row["id"]])
        validate_state(row, expected[row["id"]])
        facts = _facts(row)
        if not isinstance(facts, list):
            raise ValueError("support_facts must be a list")
        if row["status"] == "missing" and facts:
            raise ValueError("missing cannot contain support_facts")
        if row["status"] != "missing" and not facts:
            raise ValueError("positive support requires support_facts")
        for fact in facts:
            exact_keys(fact, {"meaning", "span_ids"})
            if not nonempty(fact["meaning"]):
                raise ValueError("support fact needs meaning")
            cited_text(fact["span_ids"], spans, pid)
        _validate_observations(row["observations"], spans, pid)
    return result


def validate_verdict(result, plan, available_spans):
    expected = check_requirements(result, plan)
    result = copy.deepcopy(result)
    for row in result["requirements"]:
        normalized = _normalize_requirement(row)
        row.clear(); row.update(normalized)
        exact_keys(row, {"id", "status", "validation_state", "exhaustive", "support_facts", "observations", "missing"})
        if row["validation_state"] != "valid":
            raise ValueError("model verdict validation_state must be valid")
        conservative_state(row, expected[row["id"]])
        validate_state(row, expected[row["id"]])
        if row["status"] == "missing" and row["support_facts"]:
            raise ValueError("missing cannot contain support_facts")
        if row["status"] != "missing" and not row["support_facts"]:
            raise ValueError("positive support requires support_facts")
        for fact in row["support_facts"]:
            exact_keys(fact, {"meaning", "span_ids"})
            if not nonempty(fact["meaning"]):
                raise ValueError("support fact needs meaning")
            cited_text(fact["span_ids"], available_spans)
        _validate_observations(row["observations"], available_spans)
    return result


def partition_requirements(result, plan, validator, verdict=False):
    """Validate independently; protocol failures become unknown, never negative evidence."""
    expected = {r["id"]: r for r in plan["requirements"]}
    items = {rid: [] for rid in expected}; issues = []
    if isinstance(result, dict) and set(result) == {"requirements"} and isinstance(result["requirements"], list):
        for item in result["requirements"]:
            if isinstance(item, dict) and item.get("id") in items:
                items[item["id"]].append(item)
            else:
                issues.append({"requirement_id": None, "error": "unknown or malformed requirement entry"})
    else:
        issues.append({"requirement_id": None, "error": "expected requirements list"})
    validated, normalizations = [], []
    for rid, requirement in expected.items():
        try:
            if len(items[rid]) != 1:
                raise ValueError("requirement missing or duplicated")
            original = items[rid][0]
            one = validator({"requirements": [original]}, {"requirements": [requirement]})["requirements"][0]
            if one != original:
                reasons = []
                if original.get("status") == "partial" and not original.get("support_facts") and one.get("status") == "missing":
                    reasons.append("partial without positive support downgraded to missing; observations preserved")
                if any(isinstance(x, str) for x in original.get("observations", [])):
                    reasons.append("string observations normalized to non-support notes without citations")
                if (original.get("status") == "partial" and original.get("support_facts") and
                        original.get("missing") == [] and one.get("missing")):
                    reasons.append("partial unresolved details copied from observations; grounded support preserved")
                if original.get("status") == "sufficient" and one.get("status") == "partial":
                    reasons.append("unproven set completeness downgraded to partial")
                normalizations.append({"requirement_id": rid,
                    "reason": "; ".join(reasons) or "protocol output conservatively normalized"})
            validated.append(one)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            issues.append({"requirement_id": rid, "error": str(exc)})
            validated.append({"id": rid, "status": "unknown", "validation_state": "unknown",
                "exhaustive": False, "support_facts": [], "observations": [],
                "missing": ["Validation failed: " + str(exc)]})
    return {"requirements": validated, "validation_issues": issues, "normalizations": normalizations}


def empty_verdict(requirement, reason):
    return {"id": requirement["id"], "status": "missing", "validation_state": "valid",
            "exhaustive": False, "support_facts": [], "observations": [], "missing": [reason]}


def fact_key(requirement, fact, packet_id=""):
    return requirement, packet_id, tuple(sorted(fact["span_ids"]))


def pack(packets, assessments, budget, tok, render):
    selected, seen, remaining, dropped, chosen = [], set(), set(packets), [], []
    while remaining:
        ranked = []
        for pid in remaining:
            rr = assessments[pid]["requirements"]
            facts = {fact_key(r["id"], f, pid) for r in rr for f in r["support_facts"]}
            gain = facts - seen
            if not gain:
                continue
            sufficient = sum(r["status"] == "sufficient" and any(
                fact_key(r["id"], f, pid) in gain for f in r["support_facts"]) for r in rr)
            ranked.append(((sufficient, len(gain), packets[pid]["base_score"]), pid, gain))
        if not ranked:
            break
        _, pid, gain = max(ranked, key=lambda x: (x[0], x[1]))
        remaining.remove(pid); packet = packets[pid]
        if any(tuple(x["page"]) == tuple(packet["page"]) and x["member_sha256"] == packet["member_sha256"] for x in selected):
            dropped.append({"id": pid, "reason": "same_page_exact_duplicate"}); continue
        if len(tok.encode(render(selected + [packet]), add_special_tokens=False)) > budget:
            dropped.append({"id": pid, "reason": "whole_packet_over_budget"}); continue
        selected.append({**packet, "selection_id": pid}); chosen.append(pid); seen.update(gain)
    return {"packets": selected, "selected_ids": chosen, "dropped": dropped,
            "unselected_ids": sorted(set(packets) - set(chosen))}


def joint_group(verdict, spans, route):
    """Keep only genuinely multi-packet support from a route audit."""
    facts = []
    for requirement in verdict["requirements"]:
        for fact in requirement["support_facts"]:
            packet_ids = sorted({spans[sid]["packet_id"] for sid in fact["span_ids"]})
            if len(packet_ids) >= 2:
                facts.append({"requirement_id": requirement["id"], "status": requirement["status"],
                              "span_ids": fact["span_ids"], "packet_ids": packet_ids,
                              "meaning": fact["meaning"]})
    if not facts:
        return None
    return {"route_id": route["id"], "source_node": route["source_node"],
            "target_node": route["target_node"], "facts": facts,
            "packet_ids": sorted({pid for fact in facts for pid in fact["packet_ids"]})}


def pack_with_joint(packets, assessments, joint_groups, budget, tok, render):
    """Select an atomic multi-source group before ordinary packet-level facts."""
    selected, chosen, seen, dropped = [], [], set(), []
    ranked = []
    for group in joint_groups:
        gain = {(f["requirement_id"], tuple(sorted(f["span_ids"]))) for f in group["facts"]}
        sufficient = sum(f["status"] == "sufficient" for f in group["facts"])
        cost = len(tok.encode(render([packets[p] for p in group["packet_ids"]]), add_special_tokens=False))
        ranked.append(((sufficient, len(gain), -cost), group, gain))
    for _, group, gain in sorted(ranked, key=lambda x: x[0], reverse=True):
        if not gain - seen:
            continue
        addition_ids = [pid for pid in group["packet_ids"] if pid not in chosen]
        additions = [packets[pid] for pid in addition_ids]
        if len(tok.encode(render(selected + additions), add_special_tokens=False)) > budget:
            dropped.append({"id": group["route_id"], "reason": "joint_group_over_budget",
                            "packet_ids": group["packet_ids"]}); continue
        for pid, packet in zip(addition_ids, additions):
            selected.append({**packet, "selection_id": pid, "joint_route_id": group["route_id"]}); chosen.append(pid)
        seen.update(gain)

    # Add complementary direct facts without treating joint facts as independently supported.
    remaining = {pid: packet for pid, packet in packets.items() if pid not in chosen}
    while remaining:
        candidates = []
        for pid, packet in remaining.items():
            facts = {(r["id"], pid, tuple(sorted(f["span_ids"])))
                     for r in assessments[pid]["requirements"] for f in r["support_facts"]}
            if facts:
                sufficient = sum(1 for r in assessments[pid]["requirements"]
                                 if r["status"] == "sufficient" and r["support_facts"])
                candidates.append(((sufficient, len(facts), packet["base_score"]), pid))
        if not candidates:
            break
        _, pid = max(candidates, key=lambda x: (x[0], x[1])); packet = remaining.pop(pid)
        if any(tuple(x["page"]) == tuple(packet["page"]) and x["member_sha256"] == packet["member_sha256"] for x in selected):
            dropped.append({"id": pid, "reason": "same_page_exact_duplicate"}); continue
        if len(tok.encode(render(selected + [packet]), add_special_tokens=False)) > budget:
            dropped.append({"id": pid, "reason": "whole_packet_over_budget"}); continue
        selected.append({**packet, "selection_id": pid}); chosen.append(pid)
    return {"packets": selected, "selected_ids": chosen, "dropped": dropped,
            "unselected_ids": sorted(set(packets) - set(chosen)),
            "joint_groups_considered": joint_groups,
            "joint_route_ids_selected": sorted({p.get("joint_route_id") for p in selected if p.get("joint_route_id")})}


def actual_gain(before, after):
    def signatures(verdict):
        return {(r["id"], r["status"], tuple(sorted(s for f in r.get("support_facts", []) for s in f["span_ids"])))
                for r in verdict["requirements"] if r["status"] in {"partial", "sufficient"}}
    return {"support_before": sorted(signatures(before)), "support_after": sorted(signatures(after)),
            "new_or_changed_support": sorted(signatures(after) - signatures(before))}


def validate_routes(result, routes, missing):
    exact_keys(result, {"routes"})
    rows = result["routes"]; by_id = {r["id"]: r for r in routes}; req = {r["id"] for r in missing}
    if not isinstance(rows, list) or len(rows) != len(by_id) or {r.get("id") for r in rows} != set(by_id):
        raise ValueError("route IDs must match exactly")
    for row in rows:
        exact_keys(row, {"id", "follow", "requirements", "expected_gain", "source_anchor_ids",
                         "constraint_checks", "reason", "uncertainty"})
        if type(row["follow"]) is not bool or not nonempty(row["reason"]) or not isinstance(row["uncertainty"], str):
            raise ValueError("route needs boolean, reason, and uncertainty")
        if not isinstance(row["requirements"], list) or not set(row["requirements"]) <= req:
            raise ValueError("route must target unresolved requirements")
        if bool(row["requirements"]) != row["follow"]:
            raise ValueError("follow needs unresolved targets; rejection has none")
        allowed_gain = {"direct_evidence", "necessary_context", "bridge"} if row["follow"] else {"none"}
        if row["expected_gain"] not in allowed_gain:
            raise ValueError("invalid expected gain")
        if not isinstance(row["constraint_checks"], list) or any(not nonempty(x) for x in row["constraint_checks"]):
            raise ValueError("constraint checks must be nonempty text")
        anchors = {a["span_id"] for a in by_id[row["id"]].get("edge", {}).get("anchors", [])}
        if not isinstance(row["source_anchor_ids"], list) or not set(row["source_anchor_ids"]) <= anchors:
            raise ValueError("route source_anchor_ids must use exact provided span_id values; allowed=" + repr(sorted(anchors)))
        if row["follow"] and not row["source_anchor_ids"]:
            raise ValueError("followed route needs grounded source anchors")
    return result
