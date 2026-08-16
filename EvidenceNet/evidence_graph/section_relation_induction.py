from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm
from .relation_verifier import _confidence, _recover_span
from .verify_scientific_body_coarse import FAMILIES, SUBTYPES


PROMPT_VERSION = "section-graph-induction-v1"


def pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def build_groups(nodes: list[dict], boundary_context: int = 2) -> list[dict]:
    ordered = sorted(nodes, key=lambda row: row["document_order"])
    by_section: dict[str | None, list[dict]] = defaultdict(list)
    section_order: list[str | None] = []
    for node in ordered:
        section = node.get("section_id")
        if section not in by_section:
            section_order.append(section)
        by_section[section].append(node)
    anchors = [node for node in ordered
               if not node.get("section_path") or node.get("discourse_role") == "abstract"]
    groups = []
    for index, section in enumerate(section_order):
        core = by_section[section]
        context = list(anchors)
        if index:
            context.extend(by_section[section_order[index - 1]][-boundary_context:])
        if index + 1 < len(section_order):
            context.extend(by_section[section_order[index + 1]][:boundary_context])
        seen = set()
        members = []
        for node in sorted(core + context, key=lambda row: row["document_order"]):
            if node["node_id"] not in seen:
                members.append(node); seen.add(node["node_id"])
        groups.append({
            "group_id": f"SECTION_GROUP_{index + 1:03d}",
            "section_id": section,
            "section_path": core[0].get("section_path") or ["Front matter / abstract"],
            "core_node_ids": [node["node_id"] for node in core],
            "node_ids": [node["node_id"] for node in members],
        })
    return groups


def _node_view(node: dict, core: set[str]) -> dict:
    return {
        "node_id": node["node_id"], "document_order": node["document_order"],
        "role_in_group": "CORE" if node["node_id"] in core else "CONTEXT",
        "evidence_type": node.get("evidence_type"),
        "discourse_role": node.get("discourse_role"),
        "section_path": node.get("section_path") or [],
        "text": node.get("original_markdown") or node.get("plain_text") or "",
    }


def _prompt(group: dict, nodes: list[dict], maximum_relations: int) -> str:
    core = set(group["core_node_ids"])
    payload = [_node_view(node, core) for node in nodes]
    return f'''Induce a sparse scientific evidence graph for one paper section.
Nodes marked CORE belong to the target section. CONTEXT nodes are the abstract or neighboring boundary context.
Return only meaningful document-internal semantic relationships where at least one endpoint is CORE.

Broad families: {json.dumps(FAMILIES)}
Optional subtypes: {json.dumps(SUBTYPES)}

Prefer high-value scientific links: evidence-to-claim, method-to-result, equation-to-use, explanation-to-observation,
qualification/contrast, and a detailed statement developing a broader claim. Do not connect nodes merely because
they are adjacent, in the same section, or mention the same topic. Test both directions. Preserve uncertainty as
UNCERTAIN rather than inventing a precise label. Return at most {maximum_relations} strongest relationships.

Return one JSON object with a `relations` array. Every relation has exactly:
source; target; status (RELATED or UNCERTAIN); relation_family; relation_subtype;
source_supporting_span; target_supporting_span; rationale; existence_confidence;
family_confidence; direction_confidence.
Confidence values are JSON numbers 0..1. Spans are short exact substrings from the corresponding text;
for display math use __FULL_FORMULA__. Return {{"relations": []}} when no relation is warranted. JSON only.

GROUP: {json.dumps({"group_id": group["group_id"], "section_path": group["section_path"], "nodes": payload}, ensure_ascii=False)}'''


def _parse_relations(parsed) -> list[dict]:
    if isinstance(parsed, dict) and isinstance(parsed.get("relations"), list):
        return [row for row in parsed["relations"] if isinstance(row, dict)]
    if isinstance(parsed, list):
        return [row for row in parsed if isinstance(row, dict)]
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Induce sparse relations with one LLM call per paper section")
    parser.add_argument("--source", default="output/scientific_body_semantics/shared_candidates/gw150914_detection")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--boundary-context", type=int, default=2)
    parser.add_argument("--maximum-relations-per-group", type=int, default=16)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=45)
    args = parser.parse_args()

    source, target = Path(args.source), Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    nodes = read_jsonl(source / "evidence_nodes.jsonl")
    by_id = {node["node_id"]: node for node in nodes}
    order = {node["node_id"]: node["document_order"] for node in nodes}
    groups = build_groups(nodes, args.boundary_context)
    write_jsonl(target / "section_groups.jsonl", groups)

    checkpoint_path = target / "group_status.json"
    checkpoint = (json.loads(checkpoint_path.read_text()) if checkpoint_path.exists()
                  else {"processed_groups": 0})
    processed = int(checkpoint.get("processed_groups", 0))
    raw_rows = read_jsonl(target / "group_relations.jsonl") if (target / "group_relations.jsonl").exists() else []
    malformed = read_jsonl(target / "malformed_groups.jsonl") if (target / "malformed_groups.jsonl").exists() else []
    if processed >= len(groups):
        print(json.dumps(checkpoint, indent=2)); return

    config = load_config(args.config)
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True,
                                enable_thinking=False)
    llm = create_llm(config["enrichment"])
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    system = "You induce sparse, text-grounded scientific evidence graphs. Return JSON only."
    for index in range(processed, len(groups)):
        group = groups[index]
        members = [by_id[node_id] for node_id in group["node_ids"]]
        try:
            generation = llm.generate_json(
                system, _prompt(group, members, args.maximum_relations_per_group), 1800)
            rows = _parse_relations(generation.parsed)
            for row in rows:
                row.update({"group_id": group["group_id"], "model": generation.model,
                            "prompt_version": PROMPT_VERSION,
                            "verification_timestamp": generation.timestamp})
            raw_rows.extend(rows)
        except Exception as exc:
            malformed.append({"group_id": group["group_id"], "error": str(exc),
                              "timestamp": datetime.now(timezone.utc).isoformat()})
        write_jsonl(target / "group_relations.jsonl", raw_rows)
        write_jsonl(target / "malformed_groups.jsonl", malformed)
        checkpoint = {"processed_groups": index + 1, "total_groups": len(groups),
                      "raw_relations": len(raw_rows), "malformed_groups": len(malformed),
                      "complete": index + 1 == len(groups)}
        write_json(checkpoint_path, checkpoint)
        print(json.dumps(checkpoint), flush=True)
        if monotonic() >= deadline:
            break

    # Deduplicate overlapping section/context proposals and validate annotations.
    best: dict[tuple[str, str], dict] = {}
    for row in raw_rows:
        source, target_id = row.get("source"), row.get("target")
        if source not in by_id or target_id not in by_id or source == target_id:
            continue
        key = pair(source, target_id)
        existence, _ = _confidence(row.get("existence_confidence", 0))
        if key not in best or existence > _confidence(best[key].get("existence_confidence", 0))[0]:
            best[key] = row
    related, verified, ambiguous = [], [], []
    for key, row in sorted(best.items()):
        source, target_id = row["source"], row["target"]
        existence, _ = _confidence(row.get("existence_confidence", 0))
        family_conf, _ = _confidence(row.get("family_confidence", 0))
        direction_conf, _ = _confidence(row.get("direction_confidence", 0))
        family = str(row.get("relation_family") or "NONE").upper()
        subtype = str(row.get("relation_subtype") or "AMBIGUOUS").upper()
        source_span = _recover_span(str(row.get("source_supporting_span") or ""),
                                    by_id[source]["original_markdown"])
        target_span = _recover_span(str(row.get("target_supporting_span") or ""),
                                    by_id[target_id]["original_markdown"])
        common = {"node_a": key[0], "node_b": key[1], "source": source, "target": target_id,
                  "relation_family": family, "relation_subtype": subtype,
                  "existence_confidence": existence, "family_confidence": family_conf,
                  "direction_confidence": direction_conf, "source_supporting_span": source_span or "",
                  "target_supporting_span": target_span or "", "rationale": row.get("rationale", ""),
                  "group_id": row["group_id"], "model": row["model"],
                  "prompt_version": PROMPT_VERSION,
                  "reading_order_distance": abs(order[source] - order[target_id])}
        if str(row.get("status") or "").upper() in {"RELATED", "UNCERTAIN"} and existence >= .55:
            related.append(common)
            if (str(row.get("status") or "").upper() == "RELATED" and existence >= .80
                    and family in FAMILIES and family_conf >= .55 and direction_conf >= .55
                    and source_span and target_span):
                verified.append({**common, "edge_layer": "semantic", "edge_type": family,
                                 "directed": subtype != "CONTRASTS_WITH", "confidence": existence})
            else:
                ambiguous.append(common)
    write_jsonl(target / "related_edges.jsonl", related)
    write_jsonl(target / "accepted_edges.jsonl", verified)
    write_jsonl(target / "ambiguous_edges.jsonl", ambiguous)
    write_json(target / "summary.json", {**checkpoint, "unique_related": len(related),
               "fully_verified": len(verified), "ambiguous": len(ambiguous),
               "llm_calls": checkpoint["processed_groups"]})


if __name__ == "__main__":
    main()
