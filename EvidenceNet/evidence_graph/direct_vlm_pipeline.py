from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm
from .relation_ontology import RELATIONS
from .relation_verifier import _recover_span

PROMPT_VERSION = "direct-vlm-page-graph-v1"
ACTIONS = {"CONTINUE_ACTIVE_ITEM", "START_NEW_ITEM", "STANDALONE_ITEM", "RESUME_ITEM"}


def _page_number(page_id):
    match = re.search(r"(\d+)$", page_id)
    return int(match.group(1)) if match else 0


def _node_view(node, limit=1200):
    return {"node_id": node["node_id"], "evidence_type": node.get("evidence_type"),
            "text": (node.get("original_markdown") or "")[:limit]}


def _image_path(aligned_root, doc_id, page_id):
    parsing_root = Path(aligned_root).parents[1]
    candidates = [
        parsing_root / "deepseekocr2_split_render" / doc_id / page_id / "page.png",
        Path("../parsing/output/deepseekocr2_split_render") / doc_id / page_id / "page.png",
    ]
    return next((p.resolve() for p in candidates if p.exists()), None)


def _validate_edges(result, current_ids, edges, by_id):
    accepted = []
    for row in result.get("semantic_edges", []) if isinstance(result, dict) else []:
        source, target = row.get("source"), row.get("target")
        relation = str(row.get("relation_type", "")).upper()
        confidence = float(row.get("confidence", 0))
        if source not in by_id or target not in by_id or source == target or relation not in RELATIONS or confidence < .8:
            continue
        if source not in current_ids and target not in current_ids: continue
        source_span = _recover_span(str(row.get("source_supporting_span", "")), by_id[source]["original_markdown"])
        target_span = _recover_span(str(row.get("target_supporting_span", "")), by_id[target]["original_markdown"])
        if not source_span or not target_span: continue
        edge = {"source": source, "target": target, "edge_layer": "semantic",
            "edge_type": relation, "directed": relation != "CONTRASTS_WITH", "confidence": confidence,
            "source_supporting_span": source_span, "target_supporting_span": target_span,
            "rationale": str(row.get("rationale", "")),
            "candidate_reasons": ["direct_vlm_page_reasoning"], "prompt_version": PROMPT_VERSION}
        key = (source, target, relation)
        if key not in {(e["source"], e["target"], e["edge_type"]) for e in edges + accepted}:
            accepted.append(edge)
    edges.extend(accepted)
    return accepted


def _apply_page_result(result, current_nodes, item_by_node, item_kind, active_item):
    current_ids = {n["node_id"] for n in current_nodes}
    known_items = set(item_by_node.values())
    next_number = 1 + max([int(x.rsplit("_", 1)[-1]) for x in known_items] or [0])
    rows = result.get("node_assignments", []) if isinstance(result, dict) else []
    returned = {r.get("node_id"): r for r in rows if isinstance(r, dict)}
    if set(returned) != current_ids:
        raise ValueError("VLM must assign every current-page Evidence node exactly once")
    assignments = []
    for node in current_nodes:
        row = returned[node["node_id"]]; action = str(row.get("action", "")).upper()
        if action not in ACTIONS: raise ValueError(f"invalid action {action}")
        requested = row.get("resume_item_id")
        if action == "CONTINUE_ACTIVE_ITEM" and active_item:
            item = active_item
        elif action == "RESUME_ITEM" and requested in known_items:
            item = requested
        else:
            item = f"ITEM_{next_number:04d}"; next_number += 1; known_items.add(item)
        kind = str(row.get("content_kind") or "other").lower()
        item_by_node[node["node_id"]] = item; item_kind.setdefault(item, kind); active_item = item
        assignments.append({"node_id": node["node_id"], "content_item_id": item,
                            "content_kind": item_kind[item], "action": action})
    return active_item, assignments


def main():
    parser = argparse.ArgumentParser(description="Direct page-wise VLM segmentation and semantic graph proposal")
    parser.add_argument("--doc-id", required=True); parser.add_argument("--config", required=True)
    parser.add_argument("--output-root", default="output/direct_vlm_runs")
    args = parser.parse_args(); config = load_config(args.config); llm = create_llm(config["enrichment"])
    source = Path(config["output"]["graph_root"]) / args.doc_id
    model_slug = Path(config["enrichment"]["model"]).name
    output = Path(args.output_root) / model_slug / args.doc_id; output.mkdir(parents=True, exist_ok=True)
    nodes = sorted(read_jsonl(source / "evidence_nodes.jsonl"), key=lambda n: n["document_order"])
    by_id = {n["node_id"]: n for n in nodes}; pages = defaultdict(list)
    for node in nodes: pages[(node.get("page_ids") or ["NO_PAGE"])[0]].append(node)
    page_ids = sorted(pages, key=_page_number)
    checkpoint_path = output / "page_checkpoint.jsonl"
    checkpoint = read_jsonl(checkpoint_path) if checkpoint_path.exists() else []
    completed = {r["page_id"]: r for r in checkpoint if r.get("status") in {"ok", "unresolved"}}
    item_by_node = {}; item_kind = {}; active_item = None; edges = []; assignments = []
    # Replay completed pages to reconstruct state deterministically.
    for page_id in page_ids:
        if page_id not in completed: break
        row = completed[page_id]
        for assignment in row.get("assignments", []):
            item_by_node[assignment["node_id"]] = assignment["content_item_id"]
            item_kind.setdefault(assignment["content_item_id"], assignment["content_kind"])
            active_item = assignment["content_item_id"]
        assignments.extend(row["assignments"]); edges.extend(row["accepted_edges"])
    system = ("You are directly constructing a document-internal evidence graph from page images and OCR Evidence. "
              "Decide content-item membership and semantic relations yourself. Return JSON only; use no external facts.")
    for page_index, page_id in enumerate(page_ids):
        if page_id in completed: continue
        current = pages[page_id]
        prior_by_item = defaultdict(list)
        for node in nodes:
            if node["node_id"] in item_by_node: prior_by_item[item_by_node[node["node_id"]]].append(node)
        item_context = []
        for item in list(dict.fromkeys(item_by_node.values()))[-6:]:
            members = prior_by_item[item]
            item_context.append({"content_item_id": item, "content_kind": item_kind.get(item, "other"),
                "evidence": [_node_view(n, 700) for n in (members[-80:] if item == active_item else members[-8:])]})
        payload = {"page_id": page_id, "active_item_id": active_item, "recent_items": item_context,
                   "current_page_evidence": [_node_view(n) for n in current], "allowed_relations": RELATIONS}
        assignment_prompt = f'''The supplied image is the current page. Assign every current_page_evidence node exactly once.
For each node return node_id, action (CONTINUE_ACTIVE_ITEM, START_NEW_ITEM, STANDALONE_ITEM, or RESUME_ITEM),
resume_item_id (only for RESUME_ITEM), and content_kind. Do not return a rationale per node. Multiple items may begin on one page.
Advertisements, covers, and visual inserts are valid standalone items; do not discard them. An interrupted article
may resume a prior item. Return one object with page_id, node_assignments, and a concise page_rationale.
INPUT:\n{json.dumps(payload, ensure_ascii=False)}'''
        image = _image_path(config["input"]["aligned_root"], args.doc_id, page_id)
        try:
            if not image: raise FileNotFoundError(f"page image missing for {page_id}")
            try:
                generation = llm.generate_json_with_images(
                    system, assignment_prompt, [str(image)], max_new_tokens=2200)
            except Exception:
                compact_retry = assignment_prompt + "\nRETRY: Return compact JSON only. Omit all explanations except page_rationale."
                generation = llm.generate_json_with_images(
                    system, compact_retry, [str(image)], max_new_tokens=3200)
            assignment_result = generation.parsed
            active_item, page_assignments = _apply_page_result(
                assignment_result, current, item_by_node, item_kind, active_item)
            relation_payload = {**payload, "current_assignments": page_assignments}
            relation_prompt = f'''The supplied image is the current page. Directly propose at most the 10 strongest
clearly grounded semantic relationships involving at least one current-page node and any supplied Evidence node.
For each edge return source, target, relation_type, confidence, exact source_supporting_span, exact
target_supporting_span, and a rationale of at most 25 words. Topic overlap alone is not a relation.
Return one object with page_id and semantic_edges.
INPUT:\n{json.dumps(relation_payload, ensure_ascii=False)}'''
            try:
                relation_generation = llm.generate_json_with_images(
                    system, relation_prompt, [str(image)], max_new_tokens=3000)
                relation_result = relation_generation.parsed
                accepted = _validate_edges(relation_result, {n["node_id"] for n in current}, edges, by_id)
                relation_status, relation_error = "ok", None
            except Exception as relation_exc:
                relation_result, accepted = {}, []
                relation_status, relation_error = "error", str(relation_exc)
            record = {"page_id": page_id, "status": "ok", "assignments": page_assignments,
                      "accepted_edges": accepted, "assignment_result": assignment_result,
                      "relation_result": relation_result, "relation_status": relation_status,
                      "relation_error": relation_error, "model": generation.model,
                      "timestamp": generation.timestamp, "prompt_version": PROMPT_VERSION}
            assignments.extend(page_assignments)
        except Exception as exc:
            record = {"page_id": page_id, "status": "unresolved", "error": str(exc),
                      "assignments": [], "accepted_edges": [], "relation_status": "skipped",
                      "prompt_version": PROMPT_VERSION}
            checkpoint = [r for r in checkpoint if r.get("page_id") != page_id] + [record]
            write_jsonl(checkpoint_path, checkpoint)
            print({"page": page_id, "status": "unresolved", "error": str(exc)}, flush=True)
            continue
        checkpoint = [r for r in checkpoint if r.get("page_id") != page_id] + [record]
        write_jsonl(checkpoint_path, checkpoint); write_jsonl(output / "content_item_assignments.jsonl", assignments)
        write_jsonl(output / "semantic_edges.jsonl", edges)
        print({"page": page_id, "nodes": len(current), "edges": len(accepted), "items": len(set(item_by_node.values()))}, flush=True)
    summary = {"doc_id": args.doc_id, "model": config["enrichment"]["model"], "pages": len(page_ids),
               "nodes": len(nodes), "content_items": len(set(item_by_node.values())), "semantic_edges": len(edges),
               "complete": len(assignments) == len(nodes)}
    write_json(output / "summary.json", summary); print(json.dumps(summary, indent=2))


if __name__ == "__main__": main()
