#!/usr/bin/env python3
"""Fixed-pair edge verification ablation for endpoint and neighbor context."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import copy
import json
import os
from pathlib import Path
from time import monotonic

import run_named_identity_gate_verifier as gate
from evidence_graph.llm_client import create_llm, extract_json
from run_node_context_edges import ROOT, jsonl, read, rows, sha, write


SOURCE = ROOT / "EvidenceNet/output/all_node_multimodal_relatedness_v1_20261017"
CORPUS = ROOT / "EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015"
FORMULAS = ROOT / "EvidenceNet/output/formula_retrieval_v1_20261016/formula_context/formula_bindings.jsonl"
REFERENCES = ROOT / "EvidenceNet/output/edge_candidate_allocation_repair_v2_20261017/reference_candidates.jsonl"
READING = [
    ROOT / "EvidenceNet/output/paper_relevance_urban_traffic_20261013/graph/reading_edges.jsonl",
    ROOT / "EvidenceNet/output/article_bridge_expanded_v5_20261012/reading_edges.jsonl",
]
ARMS = {"anchor", "bounded", "neighbors"}
MODEL = gate.MODEL
SYSTEM = "Judge endpoint relations with source-grounded supplemental context. Context cannot replace endpoint evidence. JSON only."


def verify(out: Path) -> None:
    for path, digest in read(out / "manifest.json")["files"].items():
        if sha(path) != digest:
            raise ValueError("Changed frozen input/code: " + path)


def atom_excerpt(node: dict, policies: dict, limit: int = 800) -> dict | None:
    allowed = {(m["member_id"], m["kind"]) for m in policies[node["id"]]["members"] if m["eligible"]}
    for member in node.get("members", []):
        if member["kind"] == "atom" and (member["id"], member["kind"]) in allowed and member.get("text", "").strip():
            return {"source_node_id": node["id"], "member_id": member["id"],
                    "kind": "CONTEXT_ORIGINAL_TEXT", "quote": member["text"][:limit]}
    return None


def reading_graph(nodes: dict) -> tuple[dict, dict]:
    forward, backward = defaultdict(list), defaultdict(list)
    for path in READING:
        for edge in rows(path):
            if edge["source"] not in nodes or edge["target"] not in nodes:
                continue
            a, b = nodes[edge["source"]], nodes[edge["target"]]
            if a.get("article_id") != b.get("article_id"):
                continue
            forward[a["id"]].append(b["id"]); backward[b["id"]].append(a["id"])
    return forward, backward


def immediate_context(node_id: str, nodes: dict, policies: dict, forward: dict, backward: dict) -> list[dict]:
    result = []
    for route, values in (("previous_reading_node", backward[node_id]), ("next_reading_node", forward[node_id])):
        for neighbor_id in sorted(values)[:1]:
            item = atom_excerpt(nodes[neighbor_id], policies)
            if item:
                item["route"] = route; result.append(item)
    return result


def generic_neighbors(node_id: str, nodes: dict, policies: dict, forward: dict, backward: dict) -> list[dict]:
    result, seen = [], {node_id}
    queue = deque((neighbor, 1, route) for route, values in
                  (("reading_previous", backward[node_id]), ("reading_next", forward[node_id]))
                  for neighbor in sorted(values))
    while queue and len(result) < 6:
        current, distance, route = queue.popleft()
        if current in seen or distance > 2:
            continue
        seen.add(current)
        item = atom_excerpt(nodes[current], policies)
        if item:
            item.update(route=route, distance=distance); result.append(item)
        if distance < 2:
            for neighbor in sorted(backward[current]): queue.append((neighbor, distance + 1, "reading_previous"))
            for neighbor in sorted(forward[current]): queue.append((neighbor, distance + 1, "reading_next"))
    return result


def context_indexes(nodes: dict) -> tuple[dict, dict]:
    formula_context = defaultdict(list)
    for binding in rows(FORMULAS):
        node_id = binding["formula"]["node_id"]
        for span in binding.get("context_spans", []):
            formula_context[node_id].append({"source_node_id": span["node_id"],
                "member_id": span["member_id"], "kind": "CONTEXT_ORIGINAL_TEXT",
                "quote": span["quote"], "route": "formula_" + span["route"]})
    figure_context = defaultdict(list)
    for pair in rows(REFERENCES):
        for anchor in pair["reference_anchors"]:
            referring = nodes.get(anchor["referring_node"])
            if referring:
                member = next((m for m in referring["members"] if m["id"] == anchor["member_id"]), None)
                if member:
                    figure_context[anchor["target_node"]].append({"source_node_id": referring["id"],
                        "member_id": member["id"], "kind": "CONTEXT_ORIGINAL_TEXT",
                        "quote": member["text"][:800], "route": "explicit_figure_reference"})
    return formula_context, figure_context


def dedup_context(items: list[dict], endpoint: str, maximum: int) -> list[dict]:
    result, seen = [], set()
    for item in items:
        signature = (item["source_node_id"], item["member_id"], item["quote"])
        if item["source_node_id"] == endpoint or signature in seen:
            continue
        seen.add(signature)
        item = copy.deepcopy(item); item["context_id"] = f"C{len(result):02d}"
        result.append(item)
        if len(result) == maximum:
            break
    return result


def supplemental_prompt(contexts: dict) -> str:
    return '''\nSUPPLEMENTAL CONTEXT POLICY:
The following records are source-grounded neighboring context, not endpoint evidence.
They may disambiguate an endpoint, but MUST NOT be returned in A_evidence_ids/B_evidence_ids,
MUST NOT anchor shared_identity, and MUST NOT create a link that the endpoint evidence itself
does not support. If removing the endpoint evidence would remove the claimed relation, choose
NO_LINK or connect the actual context nodes in a separate task. Treat A and B independently.
SUPPLEMENTAL_CONTEXT:\n''' + json.dumps(contexts, ensure_ascii=False)


def prepare(out: Path, arm: str) -> None:
    if arm not in ARMS:
        raise ValueError("unknown arm")
    if (out / "manifest.json").exists():
        verify(out); return
    if out.exists():
        raise ValueError("fresh_output_required")
    out.mkdir(parents=True); (out / "evaluation").mkdir()
    nodes = {node["id"]: node for node in rows(CORPUS / "corpus_nodes.jsonl")}
    policies = read(CORPUS / "corpus_policies.json")
    forward, backward = reading_graph(nodes)
    formula_context, figure_context = context_indexes(nodes)
    entries, stats = [], Counter()
    for source in rows(SOURCE / "inputs.jsonl"):
        entry = copy.deepcopy(source)
        contexts = {"A": [], "B": []}
        for side in ("A", "B"):
            node_id = entry["task"][side]["node_id"]
            if arm == "bounded":
                specialized = formula_context[node_id] + figure_context[node_id]
                items = specialized or immediate_context(node_id, nodes, policies, forward, backward)
                contexts[side] = dedup_context(items, node_id, 3)
            elif arm == "neighbors":
                contexts[side] = dedup_context(
                    generic_neighbors(node_id, nodes, policies, forward, backward), node_id, 6)
            stats[f"{side}_contexts"] += len(contexts[side])
            stats[f"{side}_endpoints_with_context"] += bool(contexts[side])
            for item in contexts[side]: stats["route_" + item["route"]] += 1
        entry["contexts"] = contexts
        entry["prompt"] = gate.prompt(entry["task"]) + supplemental_prompt(contexts)
        entries.append(entry)
    jsonl(out / "inputs.jsonl", entries)
    jsonl(out / "evaluation/reference.jsonl", rows(SOURCE / "evaluation/reference.jsonl"))
    write(out / "protocol.json", {"experiment": "edge_context_ablation_v1", "arm": arm,
        "tasks": len(entries), "context_stats": dict(stats),
        "endpoint_policy": "Only original endpoint evidence IDs may be selected or anchor identity.",
        "context_policy": "Source-grounded text context is supplemental; no context images; context-only relation must be rejected.",
        "inference": {"thinking": False, "sampling": False, "max_new_tokens": 700, "attempts": 2},
        "scope": "Fixed-pair development ablation; no production graph mutation."})
    files = [Path(__file__), Path(gate.__file__), SOURCE / "inputs.jsonl",
             SOURCE / "evaluation/reference.jsonl", CORPUS / "corpus_nodes.jsonl",
             CORPUS / "corpus_policies.json", FORMULAS, REFERENCES, *READING,
             out / "inputs.jsonl", out / "evaluation/reference.jsonl", out / "protocol.json",
             ROOT / "EvidenceNet/evidence_graph/llm_client.py", MODEL / "config.json",
             *sorted({Path(image) for entry in entries for image in entry["images"]})]
    write(out / "manifest.json", {"files": {str(path.resolve()): sha(path) for path in files}})
    print(json.dumps({"arm": arm, "tasks": len(entries), "context_stats": dict(stats)}), flush=True)


def run(out: Path, maximum_minutes: int = 56) -> None:
    verify(out)
    entries = rows(out / "inputs.jsonl")
    predictions = rows(out / "predictions.jsonl") if (out / "predictions.jsonl").exists() else []
    started = monotonic()
    model = create_llm({"provider": "transformers", "model": str(MODEL), "dtype": "bfloat16",
                        "device_map": "auto", "require_cuda": True, "enable_thinking": False})
    import torch
    write(out / "execution.json", {"job_id": os.environ.get("SLURM_JOB_ID"),
          "array_id": os.environ.get("SLURM_ARRAY_TASK_ID"), "gpu": torch.cuda.get_device_name()})
    for entry in entries[len(predictions):]:
        if monotonic() - started > maximum_minutes * 60:
            break
        attempts, result = [], None
        for _ in range(2):
            raw = None
            try:
                request = entry["prompt"] if not attempts else entry["prompt"] + "\nVALIDATION_ERROR:\n" + attempts[-1]["error"]
                raw = model.generate_raw_with_images(SYSTEM, request, entry["images"], 700).raw
                result = gate.validate(extract_json(raw), entry)
                attempts.append({"raw": raw, "valid": True}); break
            except Exception as exc:
                attempts.append({"raw": raw, "valid": False, "error": str(exc)})
        predictions.append({"task_id": entry["task"]["task_id"], "valid": result is not None,
                            "result": result, "attempts": attempts})
        jsonl(out / "predictions.jsonl", predictions)
        print(json.dumps({"processed": len(predictions), "valid": result is not None,
                          "decision": result and result["decision"]}), flush=True)
    print(json.dumps(gate.report(out)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "run", "report"))
    parser.add_argument("--arm", choices=sorted(ARMS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare": prepare(args.output.resolve(), args.arm)
    elif args.stage == "run": run(args.output.resolve())
    else: print(json.dumps(gate.report(args.output.resolve())))
