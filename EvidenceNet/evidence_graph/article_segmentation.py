from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io_utils import read_jsonl, write_jsonl


PROMPT_VERSION = "unified-adjacent-relationship-v1"
SEMANTIC_RELATIONS = {"PROVIDES_BACKGROUND_FOR", "EXPLAINS", "ELABORATES", "SUPPORTS",
                      "QUALIFIES", "CONTRASTS_WITH", "DEPENDS_ON", "RESULTS_IN",
                      "NONE", "UNSUPPORTED_RELATION"}


def segment_articles(nodes: list[dict[str, Any]], llm, batch_size: int = 10,
                     generation_tokens: int = 1400, checkpoint_path: str | Path | None = None):
    """Classify every adjacent Evidence pair without changing either node."""
    ordered = sorted(nodes, key=lambda n: n.get("document_order", 0))
    pairs = []
    for left, right in zip(ordered, ordered[1:]):
        pairs.append({
            "left_id": left["node_id"],
            "right_id": right["node_id"],
            "left_section": left.get("section_path", []),
            "right_section": right.get("section_path", []),
            "left_text": left.get("plain_text", "")[-900:],
            "right_text": right.get("plain_text", "")[:900],
        })
    checkpoint = Path(checkpoint_path) if checkpoint_path else None
    existing = read_jsonl(checkpoint) if checkpoint and checkpoint.exists() else []
    decision_by_pair = {(r.get("left_id"), r.get("right_id")): r for r in existing
                        if r.get("prompt_version") == PROMPT_VERSION}
    failures = []
    system = ("You build grounded relationships between adjacent Evidence nodes using only supplied "
              "text. Return valid JSON only. Decide content continuity and semantic relation together.")

    def process(batch):
        prompt = f'''For every adjacent Evidence pair jointly decide (1) whether the right node continues the
same independent content unit as the left node and (2) their semantic relation. A new title/byline, a clearly different topic,
contents entry, masthead, or new standalone item can start a new content unit.
Page or section changes alone are not sufficient. Pronouns, continued sentences, shared argument,
shared experiment, and a title followed by its body indicate the same article.
Return a JSON array with exactly one object per pair containing left_id, right_id, decision
(SAME_CONTENT_UNIT or STARTS_NEW_CONTENT_UNIT), confidence (0 to 1), supporting_span_left,
supporting_span_right, and rationale; plus semantic_relation (PROVIDES_BACKGROUND_FOR, EXPLAINS,
ELABORATES, SUPPORTS, QUALIFIES, CONTRASTS_WITH, DEPENDS_ON, RESULTS_IN, NONE, or
UNSUPPORTED_RELATION), direction (LEFT_TO_RIGHT or RIGHT_TO_LEFT), relation_confidence (0 to 1),
semantic_supporting_span_left, semantic_supporting_span_right, and semantic_rationale.
Choose NONE when no allowed semantic relation is directly supported. A SAME_CONTENT_UNIT decision
does not by itself justify a semantic edge. Supporting spans must be exact substrings of the input.
INPUT:\n{json.dumps(batch, ensure_ascii=False)}'''
        generation = llm.generate_json(system, prompt, max_new_tokens=generation_tokens)
        rows = generation.parsed if isinstance(generation.parsed, list) else generation.parsed.get("pairs", [])
        keyed = {(r.get("left_id"), r.get("right_id")): r for r in rows if isinstance(r, dict)}
        normalized = []
        for item in batch:
            key = (item["left_id"], item["right_id"])
            row = keyed.get(key)
            if not row or row.get("decision") not in {"SAME_CONTENT_UNIT", "STARTS_NEW_CONTENT_UNIT"}:
                raise ValueError(f"missing article-boundary decision for {key}")
            semantic_relation = row.get("semantic_relation", "NONE")
            if semantic_relation not in SEMANTIC_RELATIONS:
                semantic_relation = "UNSUPPORTED_RELATION"
            normalized.append({
                "left_id": key[0], "right_id": key[1], "decision": row["decision"],
                "confidence": float(row.get("confidence", 0)),
                "supporting_span_left": str(row.get("supporting_span_left", "")),
                "supporting_span_right": str(row.get("supporting_span_right", "")),
                "rationale": str(row.get("rationale", "")), "model": generation.model,
                "semantic_relation": semantic_relation,
                "direction": row.get("direction") if row.get("direction") in {"LEFT_TO_RIGHT", "RIGHT_TO_LEFT"} else "LEFT_TO_RIGHT",
                "relation_confidence": float(row.get("relation_confidence", 0)),
                "semantic_supporting_span_left": str(row.get("semantic_supporting_span_left", "")),
                "semantic_supporting_span_right": str(row.get("semantic_supporting_span_right", "")),
                "semantic_rationale": str(row.get("semantic_rationale", "")),
                "prompt_version": PROMPT_VERSION, "timestamp": generation.timestamp,
            })
        for row in normalized:
            decision_by_pair[(row["left_id"], row["right_id"])] = row
        if checkpoint:
            ordered_rows = [decision_by_pair[(p["left_id"], p["right_id"])] for p in pairs
                            if (p["left_id"], p["right_id"]) in decision_by_pair]
            write_jsonl(checkpoint, ordered_rows)

    pending = [p for p in pairs if (p["left_id"], p["right_id"]) not in decision_by_pair]
    for offset in range(0, len(pending), batch_size):
        batch = pending[offset:offset + batch_size]
        try:
            process(batch)
        except Exception as exc:
            # Retrying each pair prevents one malformed batch from losing many boundaries.
            for item in batch:
                try:
                    process([item])
                except Exception as retry_exc:
                    failures.append({"left_id": item["left_id"], "right_id": item["right_id"],
                                     "error": str(retry_exc), "batch_error": str(exc)})
    decisions = [decision_by_pair[(p["left_id"], p["right_id"])] for p in pairs
                 if (p["left_id"], p["right_id"]) in decision_by_pair]
    if failures or len(decisions) != len(pairs):
        return [], decisions, failures or [{"error": "incomplete segmentation checkpoint"}]

    article_number = 1
    assignments = []
    if ordered:
        assignments.append({"node_id": ordered[0]["node_id"], "content_unit_id": f"UNIT_{article_number:04d}"})
    for decision in decisions:
        if decision["decision"] == "STARTS_NEW_CONTENT_UNIT":
            article_number += 1
        assignments.append({"node_id": decision["right_id"], "content_unit_id": f"UNIT_{article_number:04d}"})
    return assignments, decisions, []


def select_article_pilot(nodes: list[dict[str, Any]], assignments: list[dict[str, str]], maximum: int = 25):
    by_article: dict[str, list[dict[str, Any]]] = {}
    article_by_node = {row["node_id"]: row["content_unit_id"] for row in assignments}
    for node in sorted(nodes, key=lambda n: n.get("document_order", 0)):
        by_article.setdefault(article_by_node[node["node_id"]], []).append(node)
    eligible = [(len(values), -values[0].get("document_order", 0), article_id, values)
                for article_id, values in by_article.items() if len(values) >= 20]
    if not eligible:
        raise ValueError("No independently segmented article contains the 20 nodes required for a pilot")
    _, _, article_id, selected = max(eligible)
    return [n["node_id"] for n in selected[:maximum]], article_id
