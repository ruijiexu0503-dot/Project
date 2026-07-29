from __future__ import annotations

import json
import re
from typing import Any

ROLES = {"abstract", "background", "motivation", "method", "definition", "observation", "result",
         "evidence", "comparison", "limitation", "discussion", "conclusion", "other"}
PROMPT_VERSION = "node-enrichment-v1"
FORMULA_PROMPT_VERSION = "formula-context-enrichment-v1"


def enrich_formula_nodes(nodes: list[dict[str, Any]], selected_ids: set[str], llm,
                         generation_tokens: int = 1200):
    """Enrich display formulas from their immediate document context.

    This does not alter node boundaries, IDs, or source text. Context is used only
    to resolve the scientific meaning of symbols that cannot be recovered from an
    equation in isolation.
    """
    updated = [dict(n) for n in nodes]
    ordered = sorted(updated, key=lambda n: n.get("document_order", 0))
    failures = []
    system = ("Interpret a displayed formula using only the formula and supplied adjacent "
              "document evidence. Return valid JSON only; do not add external facts.")
    for index, node in enumerate(ordered):
        if node["node_id"] not in selected_ids or node.get("evidence_type") != "formula":
            continue
        before = ordered[index - 1] if index else None
        after = ordered[index + 1] if index + 1 < len(ordered) else None
        payload = {
            "node_id": node["node_id"],
            "formula": node["original_markdown"],
            "preceding_evidence": before["original_markdown"] if before else None,
            "following_evidence": after["original_markdown"] if after else None,
        }
        prompt = f'''Contextually enrich this formula Evidence node. Preserve node_id.
Distinguish scientific concepts from mathematical symbols. The central output must explain
what the equation means in the argument of the document, not merely list its parameters.
Return one JSON object containing: node_id; formula_name; base_summary (at most 35 words);
concept_definition (what scientific quantity/relationship the formula defines);
physical_interpretation (what phenomenon it characterizes); observational_role (how it
connects observed data to an inference); inference_chain (2–4 short grounded steps from
preceding observation through formula to following conclusion); concepts (at most 8 named
scientific concepts); key_points (at most 4 conceptual statements); keywords (at most 8
scientific concepts, not bare symbols); entities (at most 8 named events, objects, physical
quantities, instruments, or methods explicitly present; never include entries formatted as
"symbol - definition" and never include units); symbol_definitions (a separate object mapping
each formula symbol to its meaning stated in the supplied context);
discourse_role (definition, method, evidence, result, or other); and contextual_links,
an array with entries containing context_position (preceding or following), relation_type
(ELABORATES or DEPENDS_ON), direction (formula_to_context or context_to_formula), and rationale.
The formula normally ELABORATES preceding prose that introduces the defined quantity.
Following prose that substitutes measurements or derives a value DEPENDS_ON the formula.
INPUT:\n{json.dumps(payload, ensure_ascii=False)}'''
        try:
            generation = llm.generate_json(system, prompt, max_new_tokens=generation_tokens)
            row = generation.parsed
            if isinstance(row, dict) and isinstance(row.get("formula"), dict):
                row = row["formula"]
            if not isinstance(row, dict) or row.get("node_id") != node["node_id"]:
                raise ValueError("formula enrichment returned the wrong node_id")
            node.update(
                base_summary=str(row.get("base_summary") or node.get("base_summary") or ""),
                key_points=[str(x) for x in row.get("key_points", [])],
                keywords=[str(x) for x in row.get("keywords", [])],
                entities=[str(x) for x in row.get("entities", [])],
                discourse_role=(row.get("discourse_role") if row.get("discourse_role") in ROLES else "definition"),
            )
            node["metadata"] = {**node.get("metadata", {}), "formula_semantics": {
                "formula_name": str(row.get("formula_name") or ""),
                "concept_definition": str(row.get("concept_definition") or ""),
                "physical_interpretation": str(row.get("physical_interpretation") or ""),
                "observational_role": str(row.get("observational_role") or ""),
                "inference_chain": [str(x) for x in row.get("inference_chain", [])],
                "concepts": [str(x) for x in row.get("concepts", [])],
                "symbol_definitions": row.get("symbol_definitions") if isinstance(row.get("symbol_definitions"), dict) else {},
                "contextual_links": row.get("contextual_links") if isinstance(row.get("contextual_links"), list) else [],
                "context_node_ids": {"preceding": before["node_id"] if before else None,
                                     "following": after["node_id"] if after else None},
                "model": generation.model, "prompt_version": FORMULA_PROMPT_VERSION,
                "timestamp": generation.timestamp, "parsing_status": "ok",
            }}
        except Exception as exc:
            failures.append({"node_ids": [node["node_id"]], "error": str(exc)})
    return updated, failures


def enrich_evidence_nodes(nodes: list[dict[str, Any]], selected_ids: set[str], llm, batch_size: int = 3,
                          generation_tokens: int = 1000, retry_generation_tokens: int = 1400):
    updated = [dict(n) for n in nodes]; by_id = {n["node_id"]: n for n in updated}; failures = []
    selected = [n for n in updated if n["node_id"] in selected_ids]
    system = "You extract only information explicitly present in supplied evidence. Return valid JSON only. Never add external facts."
    def process(batch, token_limit):
        payload = [{"node_id": n["node_id"], "original_text": n["original_markdown"]} for n in batch]
        prompt = f'''Enrich each independent Evidence node. Do not use one node to enrich another.
        Return a compact JSON array with exactly one object per input, preserving node_id. Each object must contain:
        base_summary (at most 25 words), key_points (at most 3 short grounded statements), keywords (at most 6),
        entities (at most 5 important named entities explicitly present), discourse_role (one of {sorted(ROLES)}).
INPUT:\n{json.dumps(payload, ensure_ascii=False)}'''
        generation = llm.generate_json(system, prompt, max_new_tokens=token_limit)
        rows = generation.parsed if isinstance(generation.parsed, list) else generation.parsed.get("nodes", [])
        returned = {r.get("node_id"): r for r in rows if isinstance(r, dict)}
        missing = [node for node in batch if node["node_id"] not in returned]
        if missing:
            raise ValueError(f"Missing enrichment for {[n['node_id'] for n in missing]}")
        for node in batch:
            row = returned[node["node_id"]]
            role = row.get("discourse_role") if row.get("discourse_role") in ROLES else "other"
            node.update(base_summary=str(row.get("base_summary") or ""),
                        key_points=[str(x) for x in row.get("key_points", [])],
                        keywords=[str(x) for x in row.get("keywords", [])],
                        entities=[str(x) for x in row.get("entities", [])], discourse_role=role)
            # Very short headers/placeholders provide too little evidence for an
            # abstractive summary. Keep these extractive and remove entities or
            # keywords that are not literally grounded in the node itself.
            source = node.get("plain_text", "").strip()
            if len(re.findall(r"\b\w+\b", source)) <= 12:
                node["base_summary"] = " ".join(source.split())
                node["key_points"] = [" ".join(source.split())] if source else []
                folded = source.casefold()
                node["entities"] = [x for x in node["entities"] if x.casefold() in folded]
                node["keywords"] = [x for x in node["keywords"] if x.casefold() in folded]
                node["metadata"] = {**node.get("metadata", {}), "short_node_extractively_grounded": True}
            node["metadata"] = {**node.get("metadata", {}), "enrichment": {
                "model": generation.model, "prompt_version": PROMPT_VERSION,
                "timestamp": generation.timestamp, "parsing_status": "ok"}}

    for offset in range(0, len(selected), batch_size):
        batch = selected[offset:offset+batch_size]
        try:
            process(batch, generation_tokens)
        except Exception as batch_exc:
            # A truncated batch is retried node-by-node with more output room. This keeps
            # one malformed response from discarding otherwise valid pilot enrichment.
            for node in batch:
                try:
                    process([node], retry_generation_tokens)
                except Exception as retry_exc:
                    failures.append({"node_ids": [node["node_id"]], "error": str(retry_exc),
                                     "initial_batch_error": str(batch_exc)})
    # Ordinary nodes remain independent; only formulas receive adjacent context.
    updated, formula_failures = enrich_formula_nodes(updated, selected_ids, llm, retry_generation_tokens)
    failures.extend(formula_failures)
    return updated, failures
