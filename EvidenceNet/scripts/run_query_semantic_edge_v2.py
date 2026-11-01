#!/usr/bin/env python3
"""Query-semantic-edge v2: isolated P0/P1 execution, diagnostics, and accounting."""
from __future__ import annotations

import argparse
import fcntl
import json
import time
from contextlib import contextmanager
from pathlib import Path

import query_semantic_edge_core as core
import query_semantic_edge_policy_v2 as policy
import run_query_adaptive_evidence_v2 as engine
import run_query_semantic_edge_v1 as v1
from build_reader_anchor_ablation import MODEL, ROOT, sha

DEFAULT_OUT = ROOT / "EvidenceNet/output/query_semantic_edge_v2_20261031"
DECODE_CONFIG = {"enable_thinking": False, "max_new_tokens": 8192,
                 "dtype": "bfloat16", "device_map": "balanced", "temperature": None}
CACHE_SCHEMA = "semantic-edge-call-cache-v2"
RUN_VERSION = "query-semantic-edge-v2r1-20261031"
MAX_MARGINAL_AUDITS = 2
MAX_REDUNDANCY_AUDITS = 2


@contextmanager
def semantic_protocol():
    previous = engine.policy
    previous_pack = engine.pack_and_verify
    engine.policy = policy
    engine.pack_and_verify = pack_and_verify
    try:
        yield
    finally:
        engine.policy = previous
        engine.pack_and_verify = previous_pack


def _audit_selected(task, selected_ids, plan, broker, phase="selected_set_audit"):
    if not selected_ids:
        return {"requirements": [policy.empty_verdict(row, "No evidence selected within this budget")
                                 for row in plan["requirements"]],
                "validation_issues": [], "normalizations": []}
    available = {sid: span for sid, span in task["source_spans"].items()
                 if span["packet_id"] in selected_ids}
    return engine.isolated_requirements(task, phase, policy.VERIFY,
        {"question": task["question"], "requirements": plan["requirements"],
         "packets": [engine.packet_payload(task, pid) for pid in selected_ids]},
        plan, broker, lambda raw, subplan: policy.validate_verdict(raw, subplan, available), True, 4096)


def _removal_preserves_support(full, reduced):
    """Conservatively allow deletion only after a stable source-set re-audit."""
    if full.get("validation_issues") or reduced.get("validation_issues"):
        return False, "validation is unresolved"
    before = {row["id"]: row for row in full["requirements"]}
    after = {row["id"]: row for row in reduced["requirements"]}
    for rid, old in before.items():
        new = after.get(rid)
        if not new or old["status"] in {"partial", "unknown"} or new["status"] == "unknown":
            return False, f"{rid} is partial, unknown, or absent"
        if policy.STATUS_ORDER[new["status"]] < policy.STATUS_ORDER[old["status"]]:
            return False, f"{rid} support regresses"
        if old.get("exhaustive") and not new.get("exhaustive"):
            return False, f"{rid} loses enumeration completeness"
        if old.get("observations"):
            return False, f"{rid} has conflict/context observations that must be retained conservatively"
    return True, "remaining originals preserve every stable support state and completeness flag"


def pack_and_verify(task, pids, assessments, plan, broker, budget, mode, joint_groups=None):
    """Bounded set-conditional addition and deletion audits over original packets."""
    packets = {pid: dict(task["packets"][pid]) for pid in pids}
    if mode == "fixed":
        for pid, packet in packets.items():
            packet["base_score"] = task["fixed_base_scores"][pid]
    groups = policy.deduplicate_joint_groups(joint_groups or [])
    packed = (policy.pack_with_joint(packets, assessments, groups, budget, broker.tok, engine.render)
              if groups else policy.pack(packets, assessments, budget, broker.tok, engine.render))
    selected_ids = list(packed["selected_ids"])
    decisions = []

    units = {unit["id"]: unit for unit in policy._selection_units(packets, assessments, groups)}
    audit_count = 0
    for dropped in list(packed["dropped"]):
        if dropped["reason"] != "no_new_requirement_support" or audit_count >= MAX_MARGINAL_AUDITS:
            continue
        unit = units.get(dropped["id"])
        if not unit:
            continue
        addition_ids = [pid for pid in unit["packet_ids"] if pid not in selected_ids]
        if not addition_ids:
            continue
        proposed = selected_ids + addition_ids
        proposed_packets = [{**packets[pid], "selection_id": pid} for pid in proposed]
        if len(broker.tok.encode(engine.render(proposed_packets), add_special_tokens=False)) > budget:
            decisions.append({"unit_id": unit["id"], "decision": "skip",
                              "reason": "candidate addition exceeds whole-packet budget"})
            continue
        available = {sid: span for sid, span in task["source_spans"].items()
                     if span["packet_id"] in set(proposed)}
        payload = {"question": task["question"], "requirements": plan["requirements"],
            "currently_selected": [engine.packet_payload(task, pid) for pid in selected_ids],
            "candidate": [engine.packet_payload(task, pid) for pid in addition_ids]}
        decision = broker.call(task["question_id"], "marginal_support", policy.MARGINAL, payload,
            lambda raw: policy.validate_marginal(raw, plan, available, addition_ids), 4096)
        audit_count += 1
        decisions.append({"unit_id": unit["id"], "candidate_packet_ids": addition_ids, **decision})
        if decision["overall"] in {"keep", "unknown"}:
            selected_ids.extend(addition_ids)

    verdict = _audit_selected(task, selected_ids, plan, broker)
    redundancy_count = 0
    for pid in list(reversed(selected_ids)):
        if len(selected_ids) <= 1 or redundancy_count >= MAX_REDUNDANCY_AUDITS:
            break
        remaining = [other for other in selected_ids if other != pid]
        reduced = _audit_selected(task, remaining, plan, broker, "redundancy_set_audit")
        removable, reason = _removal_preserves_support(verdict, reduced)
        decision = {"overall": "skip" if removable else "keep", "reason": reason,
                    "support_delta": policy.support_delta(reduced, verdict)}
        redundancy_count += 1
        decisions.append({"unit_id": "removal:" + pid, "candidate_packet_ids": [pid], **decision})
        if removable:
            selected_ids = remaining
            verdict = reduced

    selected = []
    active_route_ids = set()
    for pid in selected_ids:
        value = {**packets[pid], "selection_id": pid}
        route_ids = sorted({group["route_id"] for group in groups if pid in group["packet_ids"] and
                            set(group["packet_ids"]) <= set(selected_ids)})
        if route_ids:
            value["joint_route_ids"] = route_ids
            active_route_ids.update(route_ids)
        selected.append(value)
    text = engine.render(selected)
    return {**packed, "packets": selected, "selected_ids": selected_ids,
            "unselected_ids": sorted(set(packets) - set(selected_ids)),
            "joint_route_ids_selected": sorted(active_route_ids),
            "marginal_decisions": decisions, "marginal_audit_count": audit_count,
            "redundancy_audit_count": redundancy_count, "budget": budget,
            "evidence_text": text,
            "evidence_tokens": len(broker.tok.encode(text, add_special_tokens=False)),
            "sufficiency": verdict, "sufficiency_is_model_estimate": True}


class Broker(engine.Broker):
    """Versioned cache identity plus cold-logical and actual-cache accounting."""
    def __init__(self, out, model, minutes, tok, llm=None):
        super().__init__(out, model, minutes, tok, llm)
        self.events = []

    def call(self, qid, phase, instruction, payload, validator, max_tokens=8192):
        prompt = instruction + "\nSOURCE DATA:\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        identity = {"cache_schema": CACHE_SCHEMA, "policy_version": policy.POLICY_VERSION,
                    "model": str(self.model), "decode": {**DECODE_CONFIG, "max_new_tokens": max_tokens},
                    "system": policy.SYSTEM, "instruction": instruction, "payload": payload}
        key = sha(json.dumps(identity, ensure_ascii=False, sort_keys=True))
        directory = self.directory / qid
        directory.mkdir(exist_ok=True)
        path = directory / (key + ".json")
        record = {"request_sha256": key, "cache_identity": identity, "phase": phase,
                  "question_id": qid, "model": str(self.model), "instruction": instruction,
                  "request": payload, "system": policy.SYSTEM, "valid": False,
                  "result": None, "attempts": []}
        cache_hit = False
        if path.exists():
            record = json.loads(path.read_text())
            if record["request_sha256"] != key or record.get("cache_identity") != identity:
                raise ValueError("stale or incomplete v2 call cache identity")
            if record["valid"]:
                cache_hit = True
                result = validator(record.get("parsed_result", record["result"]))
                self._event(qid, phase, record, cache_hit, 0)
                return result
        attempts_before = len(record["attempts"])
        for _ in range(2):
            if time.monotonic() >= self.deadline:
                raise engine.Deadline()
            current = prompt
            if record["attempts"]:
                current += "\nValidation error: " + record["attempts"][-1]["error"] + "\nReturn complete corrected JSON."
            n = core.chat_prompt_token_count(self.tok, [
                {"role": "system", "content": policy.SYSTEM}, {"role": "user", "content": current}],
                enable_thinking=False)
            if n > 24576:
                raise engine.InvalidOutput("prompt over limit; no truncation")
            if self.llm is None:
                from evidence_graph.llm_client import create_llm
                self.llm = create_llm({"provider": "transformers", "model": str(self.model),
                    "dtype": "bfloat16", "require_cuda": True, "enable_thinking": False,
                    "max_new_tokens": 8192, "device_map": "balanced",
                    "max_memory": {i: "26GiB" for i in range(4)}})
            start = time.monotonic()
            raw = core.generate_raw_text(self.llm, policy.SYSTEM, current, max_tokens)
            attempt = {"input_tokens": n,
                       "output_tokens": len(self.tok.encode(raw, add_special_tokens=False)),
                       "seconds": time.monotonic() - start, "raw": raw, "error": None}
            try:
                from evidence_graph.llm_client import extract_json
                parsed = extract_json(raw)
                result = validator(parsed)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
                attempt["error"] = str(exc)
                record["attempts"].append(attempt)
                engine.base.save(path, record)
                continue
            record.update(valid=True, result=result, parsed_result=parsed,
                          validation_complete=not result.get("validation_issues"))
            record["attempts"].append(attempt)
            engine.base.save(path, record)
            self._event(qid, phase, record, cache_hit, len(record["attempts"]) - attempts_before)
            return result
        self._event(qid, phase, record, cache_hit, len(record["attempts"]) - attempts_before)
        raise engine.InvalidOutput(f"{phase}: " + record["attempts"][-1]["error"])

    def _event(self, qid, phase, record, cache_hit, actual_attempts):
        attempts = record.get("attempts", [])
        self.events.append({"question_id": qid, "phase": phase, "request_sha256": record["request_sha256"],
            "cache_hit": cache_hit, "cold_attempts": len(attempts),
            "cold_input_tokens": sum(a["input_tokens"] for a in attempts),
            "cold_output_tokens": sum(a["output_tokens"] for a in attempts),
            "cold_generation_seconds": sum(a["seconds"] for a in attempts),
            "actual_attempts": actual_attempts,
            "actual_input_tokens": sum(a["input_tokens"] for a in attempts[-actual_attempts:]) if actual_attempts else 0,
            "actual_output_tokens": sum(a["output_tokens"] for a in attempts[-actual_attempts:]) if actual_attempts else 0,
            "actual_generation_seconds": sum(a["seconds"] for a in attempts[-actual_attempts:]) if actual_attempts else 0})

    def accounting(self, qid):
        rows = [row for row in self.events if row["question_id"] == qid]
        return {"logical_requests": len(rows), "cache_hits": sum(row["cache_hit"] for row in rows),
                "cold_attempts": sum(row["cold_attempts"] for row in rows),
                "cold_input_tokens": sum(row["cold_input_tokens"] for row in rows),
                "cold_output_tokens": sum(row["cold_output_tokens"] for row in rows),
                "cold_generation_seconds": sum(row["cold_generation_seconds"] for row in rows),
                "actual_attempts": sum(row["actual_attempts"] for row in rows),
                "actual_input_tokens": sum(row["actual_input_tokens"] for row in rows),
                "actual_output_tokens": sum(row["actual_output_tokens"] for row in rows),
                "actual_generation_seconds": sum(row["actual_generation_seconds"] for row in rows),
                "phase_logical_requests": {phase: sum(row["phase"] == phase for row in rows)
                    for phase in sorted({row["phase"] for row in rows})}}


def execution_stats(result, task, edges, mode):
    seed_record = next((row for row in result["records"]
                        if row["arm"] == "seed10" and row["budget"] == 1024), None)
    seed_rows = seed_record["sufficiency"]["requirements"] if seed_record else []
    counts = {state: sum(row["status"] == state for row in seed_rows)
              for state in ("sufficient", "partial", "missing", "unknown")}
    route_steps = [row for row in result["trace"] if "routes" in row]
    frontier_count = sum(len(row["routes"]) for row in route_steps)
    decisions = [decision for row in route_steps for decision in row.get("decisions", [])]
    followed = [route for row in route_steps for route in row.get("followed", [])]
    edge_map = {edge["edge_id"]: edge for edge in edges}
    visible = sum(bool(edge_map[route["edge_id"]]["relation_description"].get("text", "").strip())
                  for row in route_steps for route in row["routes"])
    summaries = [row for row in result["trace"] if "visited_nodes" in row]
    visited = set(summaries[-1]["visited_nodes"]) if summaries else set(task["seed_nodes"])
    joint_audits = [audit for row in route_steps for audit in row.get("route_joint_audits", [])]
    stop_rows = [row for row in result["trace"] if row.get("stop")]
    if stop_rows:
        stop_reason = stop_rows[-1]["stop"]
    elif route_steps and not route_steps[-1].get("followed"):
        stop_reason = "no_routes_followed"
    elif len(route_steps) >= 2:
        stop_reason = "hop_limit"
    else:
        stop_reason = "not_exercised" if not route_steps else "completed_navigation_round"
    seed_issues = [issue for issue in result.get("validation_issues", []) if issue.get("arm") == "seed10"]
    return {"seed_assessment_complete": bool(seed_record and not seed_issues and
                                               not seed_record["sufficiency"].get("validation_issues")),
            "seed_sufficient": counts["sufficient"], "seed_unresolved": counts["partial"] + counts["missing"],
            "seed_unknown": counts["unknown"], "frontier_count": frontier_count,
            "eligible_route_count": sum(bool(row["follow"]) for row in decisions),
            "navigation_call_count": sum((len(row["routes"]) + 5) // 6 for row in route_steps),
            "description_visible_route_count": visible, "followed_route_count": len(followed),
            "visited_new_node_count": len(visited - set(task["seed_nodes"])),
            "joint_audit_count": len(joint_audits),
            "valid_joint_group_count": sum(audit.get("joint_group") is not None for audit in joint_audits),
            "navigation_state": "not_exercised" if not route_steps else "exercised",
            "stop_reason": stop_reason, "exception": None,
            "validation_issues": result.get("validation_issues", [])}


def reachability(task, edges, stats=None):
    seed = set(task["seed_nodes"])
    one_routes = policy.frontier(edges, seed, seed, 1)
    one = {row["target_node"] for row in one_routes}
    seen = seed | one
    two_routes = policy.frontier(edges, one, seen, 2)
    two = {row["target_node"] for row in two_routes}
    labels = []
    if stats:
        required = {"seed_unknown", "seed_unresolved", "seed_sufficient",
                    "visited_new_node_count", "stop_reason"}
        if not required <= set(stats):
            labels.append("F_engine_incomplete")
        elif stats["seed_unknown"]:
            labels.append("F_validation_unknown")
        if required <= set(stats) and stats["seed_unresolved"]:
            labels.append("B_seed_missing_reachable" if one or two else "C_seed_missing_unreachable")
        elif required <= set(stats) and stats["seed_sufficient"] and not stats["seed_unknown"]:
            labels.append("A_seed_sufficient")
        if (required <= set(stats) and stats["visited_new_node_count"] and
                stats["stop_reason"] != "selected_sources_sufficient"):
            labels.append("D_visited_but_not_sufficient")
    return {"question_id": task["question_id"], "question": task["question"],
            "seed_node_count": len(seed), "seed_packet_count": len({p for n in seed for p in task["by_node"].get(n, [])}),
            "one_hop_route_count": len(one_routes), "one_hop_new_node_count": len(one),
            "two_hop_route_count": len(two_routes), "two_hop_new_node_count": len(two),
            "reachable_node_count": len(seen | two), "online_labels": labels,
            "gold_used": False, "stats": stats}


def run_task(task, edges, mode, broker):
    with semantic_protocol():
        result = engine.run_task(task, edges, mode, broker)
    result["execution_stats"] = execution_stats(result, task, edges, mode)
    result["selection_policy"] = policy.POLICY_VERSION
    return result


def prepare(out: Path, model: Path, max_candidates: int = 40):
    v1.prepare(out, model, max_candidates)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest.update({"version": "query-semantic-edge-v2", "parent_protocol": "query-semantic-edge-v1",
        "policy_version": policy.POLICY_VERSION, "run_version": RUN_VERSION,
        "selection": "requirement-conditional competitive direct/joint units; larger budgets need not be filled",
        "execution_reporting": "per-query seed/frontier/navigation/joint/stop statistics plus no-gold reachability",
        "cache_identity": "full payload+model+decode+prompt+schema+policy version",
        "cost_reporting": "cold logical and actual cache-aware accounting",
        "source_sha256": {**manifest["source_sha256"], str(Path(__file__)): engine.digest(Path(__file__)),
                          str(Path(policy.__file__)): engine.digest(Path(policy.__file__))}})
    engine.base.save(out / "manifest.json", manifest)
    check(out, model)
    print(json.dumps({"output": str(out), "queries": manifest["queries"], "version": manifest["version"]}))


def check(out: Path, model: Path):
    engine.check(out, model)
    manifest = json.loads((out / "manifest.json").read_text())
    if manifest.get("version") != "query-semantic-edge-v2" or manifest.get("policy_version") != policy.POLICY_VERSION:
        raise ValueError("wrong semantic-edge v2 identity")
    edges = engine.rows(out / "edges.jsonl")
    coverage = manifest.get("description_coverage", {})
    if len(edges) != coverage.get("total") or coverage.get("described", 0) < 1:
        raise ValueError("semantic description coverage mismatch")
    if any(edge["relation_description"]["status"] == "PENDING" for edge in edges):
        raise ValueError("PENDING description reached v2 preflight")


def infer(out, model, mode, minutes, limit=None, query_ids=None):
    check(out, model)
    tasks = engine.rows(out / "tasks.jsonl")
    edges = policy.configure_edges(engine.rows(out / "edges.jsonl"), mode)
    manifest = json.loads((out / "manifest.json").read_text())
    identity = sha(json.dumps({"manifest": manifest, "model": str(model), "mode": mode,
                               "decode": DECODE_CONFIG, "policy": policy.POLICY_VERSION}, sort_keys=True))
    if query_ids:
        if not set(query_ids) <= {task["question_id"] for task in tasks}:
            raise ValueError("unknown query ID")
        tasks = [task for task in tasks if task["question_id"] in query_ids]
    if limit is not None:
        tasks = tasks[:limit]
    run = out / mode
    run.mkdir(exist_ok=True)
    pred = run / "predictions"
    pred.mkdir(exist_ok=True)
    with (run / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        broker = Broker(run, model, minutes, engine.base.tokenizer(model))
        tasks.sort(key=lambda task: (len(list((run / "calls" / task["question_id"]).glob("*.json"))),
                                     task["question_id"]))
        for task in tasks:
            path = pred / (task["question_id"] + ".json")
            if path.exists():
                previous = json.loads(path.read_text())
                if previous.get("run_identity") != identity:
                    superseded = run / "superseded_predictions" / task["question_id"]
                    superseded.mkdir(parents=True, exist_ok=True)
                    old_identity = previous.get("run_identity", "missing_identity")
                    path.replace(superseded / (old_identity + ".json"))
                if previous.get("complete"):
                    if path.exists():
                        continue
            if time.monotonic() >= broker.deadline:
                break
            try:
                result = run_task(task, edges, mode, broker)
                result["run_identity"] = identity
                result["call_accounting"] = broker.accounting(task["question_id"])
                engine.base.save(path, result)
                print(task["question_id"], "complete" if result["complete"] else "partial_validation", flush=True)
            except engine.Deadline:
                engine.base.save(path, {"question_id": task["question_id"], "complete": False,
                    "checkpoint_reason": "time_budget", "run_identity": identity,
                    "execution_stats": {"stop_reason": "time_budget", "exception": None}})
                break
            except engine.InvalidOutput as exc:
                engine.base.save(path, {"question_id": task["question_id"], "complete": False,
                    "error": str(exc), "run_identity": identity,
                    "execution_stats": {"stop_reason": "protocol_failure", "exception": str(exc)}})
                print(task["question_id"], str(exc), flush=True)
    report(out, mode)


def report(out, mode):
    run = out / mode
    run.mkdir(exist_ok=True)
    (run / "predictions").mkdir(exist_ok=True)
    engine.report(out, mode)
    tasks = engine.rows(out / "tasks.jsonl")
    edges = policy.configure_edges(engine.rows(out / "edges.jsonl"), mode)
    diagnostics = []
    accounting = {}
    for task in tasks:
        path = run / "predictions" / (task["question_id"] + ".json")
        result = json.loads(path.read_text()) if path.exists() else None
        if result and result.get("call_accounting"):
            accounting[task["question_id"]] = result["call_accounting"]
        diagnostics.append(reachability(task, edges, result.get("execution_stats") if result else None))
    engine.jsonl(run / "diagnostics.jsonl", diagnostics)
    cost_path = run / "costs.jsonl"
    costs = engine.rows(cost_path)
    engine.jsonl(cost_path, [{**row, "cache_accounting": accounting.get(row["question_id"])}
                             for row in costs])
    status_path = run / "status.json"
    status = json.loads(status_path.read_text())
    status.update({"policy_version": policy.POLICY_VERSION,
        "navigation_exercised_queries": sum(bool(row["stats"] and row["stats"].get("navigation_state") == "exercised") for row in diagnostics),
        "navigation_not_exercised_queries": sum(bool(row["stats"] and row["stats"].get("navigation_state") == "not_exercised") for row in diagnostics),
        "diagnostics": "diagnostics.jsonl", "gold_used_for_diagnostics": False,
        "cost_scope": "costs.jsonl reports persisted generation totals and per-query cold-logical/cache-aware accounting"})
    engine.base.save(status_path, status)
    print(json.dumps(status))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "check", "infer", "report"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", type=Path, default=MODEL)
    parser.add_argument("--edge-mode", choices=["endpoint", "semantic"], default="semantic")
    parser.add_argument("--minutes", type=float, default=40)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--query-id", action="append", dest="query_ids")
    args = parser.parse_args()
    mode = "navigation_" + args.edge_mode
    if args.stage == "prepare":
        prepare(args.out, args.model)
    elif args.stage == "check":
        check(args.out, args.model)
        print("QUERY_SEMANTIC_EDGE_V2_PREFLIGHT_OK")
    elif args.stage == "infer":
        infer(args.out, args.model, mode, args.minutes, args.limit, args.query_ids)
    else:
        report(args.out, mode)


if __name__ == "__main__":
    main()
