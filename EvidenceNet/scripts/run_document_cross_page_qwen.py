#!/usr/bin/env python3
"""Classify document-graph cross-page candidates with a conservative Qwen judge."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

EVIDENCENET_ROOT = Path(__file__).resolve().parents[1]
if str(EVIDENCENET_ROOT) not in sys.path:
    sys.path.insert(0, str(EVIDENCENET_ROOT))

from evidence_graph.llm_client import TransformersLLM


LABELS = {
    "SAME_SENTENCE", "SAME_ARTICLE_NEW_NODE", "SAME_ARTICLE_NO_EDGE",
    "NEW_CONTENT", "UNCERTAIN",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def boundary_prompt(row: dict[str, Any]) -> str:
    payload = {key: row.get(key) for key in (
        "document_id", "source_page", "source_flow_kind", "source_node_id", "source_text_tail",
    )}
    return """Judge only whether the SOURCE ends at a syntactically complete boundary. Do not infer from any target.

Use SYNTACTICALLY_INCOMPLETE when the visible tail ends inside a sentence, clause, word sequence, list item, or other grammatical construction that requires continuation. Use COMPLETE when it ends a complete sentence or self-contained unit. Use UNCERTAIN only when truncation or OCR damage prevents a reliable judgment.

Return exactly one JSON object:
{"source_boundary_status":"SYNTACTICALLY_INCOMPLETE|COMPLETE|UNCERTAIN","confidence":0.0,"reason":"..."}

SOURCE:
""" + json.dumps(payload, ensure_ascii=False, indent=2)


def prompt(row: dict[str, Any], source_boundary_status: str) -> str:
    payload = {key: row.get(key) for key in (
        "document_id", "document_mode", "source_page", "target_page", "source_flow_kind", "target_flow_kind",
        "source_node_id", "target_node_id", "source_text_tail", "target_text_head",
    )}
    payload["source_boundary_status"] = source_boundary_status
    return """Judge one proposed cross-page pair along two separate axes: article membership and direct reading adjacency.

Decision order:
1. Read document_mode first. For single_article, all supplied non-page-context flows, including figures and captions, already belong to the same article; do not relitigate membership. For multi_article, decide membership conservatively and do not use topical similarity alone.
2. If they are in the same article, decide whether this exact TARGET is the direct next reading unit after this exact SOURCE.
3. source_boundary_status was decided independently from SOURCE alone. Treat it as fixed. Use SAME_SENTENCE only when it is SYNTACTICALLY_INCOMPLETE and TARGET directly completes its grammar.
4. Use SAME_ARTICLE_NEW_NODE when the exact pair is directly adjacent but starts a new sentence/paragraph/node.
5. Use SAME_ARTICLE_NO_EDGE when they belong to the same article but another flow or unit intervenes, so this pair must not receive NEXT.
6. Use NEW_CONTENT for another article, advertisement, or page furniture in multi_article mode. A caption or figure is not NEW_CONTENT merely because it uses a separate flow. Use UNCERTAIN when evidence is insufficient.

Flow kinds matter. Do not connect every source flow to every target flow merely because one main-flow pair continues. Captions, sidebars, footnotes, and main text may share an article while requiring separate reading chains.

Return exactly one JSON object with these keys:
{"same_article":true,"direct_reading_successor":false,"source_boundary_status":"SYNTACTICALLY_INCOMPLETE|COMPLETE|UNCERTAIN","label":"SAME_SENTENCE|SAME_ARTICLE_NEW_NODE|SAME_ARTICLE_NO_EDGE|NEW_CONTENT|UNCERTAIN","confidence":0.0,"reason":"..."}

PAIR:
""" + json.dumps(payload, ensure_ascii=False, indent=2)


def normalise_boundary(value: Any) -> dict[str, Any]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict):
        return {"source_boundary_status": "UNCERTAIN", "confidence": 0.0, "reason": "response_not_object"}
    status = str(value.get("source_boundary_status", "UNCERTAIN")).upper()
    if status not in {"SYNTACTICALLY_INCOMPLETE", "COMPLETE", "UNCERTAIN"}:
        status = "UNCERTAIN"
    try:
        confidence = max(0.0, min(1.0, float(value.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return {**value, "source_boundary_status": status, "confidence": confidence}


def normalise(value: Any, source_boundary_status: str) -> dict[str, Any]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict):
        return {"label": "UNCERTAIN", "confidence": 0.0, "reason": "response_not_object"}
    label = str(value.get("label", "UNCERTAIN")).upper()
    value["label"] = label if label in LABELS else "UNCERTAIN"
    try:
        value["confidence"] = max(0.0, min(1.0, float(value.get("confidence", 0.0))))
    except (TypeError, ValueError):
        value["confidence"] = 0.0
    value["source_boundary_status"] = source_boundary_status
    if value["label"] == "SAME_SENTENCE" and source_boundary_status != "SYNTACTICALLY_INCOMPLETE":
        value["label"] = "UNCERTAIN"
        value["confidence"] = 0.0
        value["reason"] = "same_sentence_rejected_by_independent_source_boundary"
    if value["label"] == "SAME_SENTENCE":
        value["same_article"] = True
        value["direct_reading_successor"] = True
    elif value["label"] == "SAME_ARTICLE_NEW_NODE":
        value["same_article"] = True
        value["direct_reading_successor"] = True
    elif value["label"] == "SAME_ARTICLE_NO_EDGE":
        value["same_article"] = True
        value["direct_reading_successor"] = False
    elif value["label"] == "NEW_CONTENT":
        value["same_article"] = False
        value["direct_reading_successor"] = False
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=320)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output / "predictions.jsonl"
    existing = {row["candidate_id"]: row for row in read_jsonl(checkpoint)} if args.resume and checkpoint.exists() else {}
    llm = TransformersLLM(str(args.model.resolve()), dtype="bfloat16", max_new_tokens=args.max_new_tokens,
                          require_cuda=True, enable_thinking=False)
    candidates = read_jsonl(args.candidates)
    boundary_path = args.output / "boundary_decisions.json"
    boundary_existing: dict[str, Any] = {}
    if args.resume and boundary_path.exists():
        boundary_existing = {
            row["source_flow_id"]: row
            for row in json.loads(boundary_path.read_text()).get("decisions", [])
        }
    boundary_decisions: dict[str, dict[str, Any]] = dict(boundary_existing)
    for candidate in candidates:
        source_flow_id = candidate["source_flow_id"]
        if source_flow_id in boundary_decisions:
            continue
        generation = llm.generate_json(
            "Judge the grammatical boundary of the supplied source only. Return JSON only.",
            boundary_prompt(candidate), args.max_new_tokens,
        )
        boundary = normalise_boundary(generation.parsed)
        boundary_decisions[source_flow_id] = {
            "source_flow_id": source_flow_id,
            "source_node_id": candidate.get("source_node_id"),
            **boundary,
            "raw_response": generation.raw,
            "model": generation.model,
        }
        boundary_path.write_text(json.dumps({
            "version": "source-boundary-independent-v1",
            "decisions": list(boundary_decisions.values()),
        }, ensure_ascii=False, indent=2))

    results = []
    for index, candidate in enumerate(candidates, 1):
        if candidate["candidate_id"] in existing:
            results.append(existing[candidate["candidate_id"]])
            continue
        boundary = boundary_decisions[candidate["source_flow_id"]]
        generation = llm.generate_json(
            "Conservative document article and reading-order judge. Return JSON only.",
            prompt(candidate, boundary["source_boundary_status"]), args.max_new_tokens,
        )
        prediction = normalise(generation.parsed, boundary["source_boundary_status"])
        result = {
            **candidate, "decision_id": candidate["candidate_id"],
            "label": prediction["label"], "confidence": prediction["confidence"],
            "prediction": prediction, "source_boundary_decision": boundary,
            "raw_response": generation.raw,
            "model": generation.model, "prompt_version": "article-reading-two-stage-v2",
        }
        results.append(result)
        write_jsonl(checkpoint, results)
        print(json.dumps({"index": index, "candidate_id": candidate["candidate_id"],
                          "label": prediction["label"], "confidence": prediction["confidence"]}), flush=True)
    decisions = {"version": "article-reading-two-stage-v2", "model": str(args.model.resolve()),
                 "decisions": results}
    (args.output / "decisions.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2))
    print(json.dumps({"candidates": len(results), "labels": {label: sum(r["label"] == label for r in results)
                                                               for label in sorted(LABELS)},
                      "output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
