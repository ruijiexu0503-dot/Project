from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm
from .relation_verifier import _confidence


PROMPT_VERSION = "high-recall-binary-screen-v1"
VALID_CLASSES = {"RELATED", "POSSIBLE", "NONE"}


def pair_id(candidate: dict) -> str:
    return f'{candidate["node_a"]}||{candidate["node_b"]}'


def build_payload(candidates: list[dict], by_id: dict[str, dict]) -> dict:
    node_ids = sorted({node_id for row in candidates for node_id in (row["node_a"], row["node_b"])},
                      key=lambda node_id: by_id[node_id]["document_order"])
    nodes = []
    for node_id in node_ids:
        node = by_id[node_id]
        nodes.append({
            "node_id": node_id, "document_order": node["document_order"],
            "section_path": node.get("section_path") or [],
            "evidence_type": node.get("evidence_type"),
            "discourse_role": node.get("discourse_role"),
            "summary": node.get("base_summary") or "",
            "text": node.get("original_markdown") or node.get("plain_text") or "",
        })
    pairs = [{"pair_id": pair_id(row), "node_a": row["node_a"], "node_b": row["node_b"],
              "retrieval_signals": row.get("candidate_reasons") or []}
             for row in candidates]
    return {"nodes": nodes, "pairs": pairs}


def prompt(payload: dict) -> str:
    return f'''Screen every listed pair for high-recall scientific semantic verification.
This stage decides relationship existence only. Do not determine direction, relation type, supporting spans, or rationale.

For each pair choose exactly one classification:
- RELATED: a meaningful document-internal scientific relationship clearly exists.
- POSSIBLE: a relationship may exist, including implicit method/result, evidence/claim, formula/application,
  explanation/observation, qualification, contrast, anaphora, figure/text, or broad-claim/specific-detail links.
- NONE: the pair is clearly unrelated or has only incidental topic/entity overlap.

Optimize recall. When uncertain, use POSSIBLE. Adjacency alone is not sufficient, but do not reject a relation merely
because it is implicit, long-distance, or its direction/type is unclear. Evaluate every supplied pair.
Return one JSON object: {{"decisions": [...]}}. The array must contain exactly one row per supplied pair, with only:
pair_id; classification; confidence_any_relation. Confidence must be a JSON number from 0 to 1. JSON only.

INPUT: {json.dumps(payload, ensure_ascii=False)}'''


def parse_decisions(parsed, candidates: list[dict], model: str, timestamp: str) -> list[dict]:
    rows = parsed.get("decisions", []) if isinstance(parsed, dict) else parsed if isinstance(parsed, list) else []
    returned = {row.get("pair_id"): row for row in rows if isinstance(row, dict)}
    output = []
    for candidate in candidates:
        pid = pair_id(candidate)
        row = returned.get(pid, {})
        classification = str(row.get("classification") or "POSSIBLE").upper()
        fallback = classification not in VALID_CLASSES or pid not in returned
        if fallback:
            classification = "POSSIBLE"
        confidence, _ = _confidence(row.get("confidence_any_relation", .5 if fallback else 0))
        output.append({
            "pair_id": pid, "classification": classification,
            "confidence_any_relation": confidence, "fallback_possible": fallback,
            "candidate": candidate, "model": model, "prompt_version": PROMPT_VERSION,
            "timestamp": timestamp,
        })
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Batched high-recall scientific-pair screening")
    parser.add_argument("--source", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=40)
    parser.add_argument("--generation-tokens", type=int, default=900)
    args = parser.parse_args()

    source, target = Path(args.source), Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    nodes = read_jsonl(source / "evidence_nodes.jsonl")
    candidates = read_jsonl(source / "candidates.jsonl")
    by_id = {node["node_id"]: node for node in nodes}
    decision_path, status_path = target / "screening_decisions.jsonl", target / "status.json"
    decisions = read_jsonl(decision_path) if decision_path.exists() else []
    status = json.loads(status_path.read_text()) if status_path.exists() else {"processed": 0}
    start = int(status.get("processed", 0))
    if start >= len(candidates):
        print(json.dumps(status, indent=2)); return

    config = load_config(args.config)
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True,
                                enable_thinking=False)
    llm = create_llm(config["enrichment"])
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    system = "You are a high-recall scientific relation screener. Return JSON only."

    def screen_batch(batch: list[dict]) -> list[dict]:
        try:
            generation = llm.generate_json(system, prompt(build_payload(batch, by_id)),
                                           args.generation_tokens)
            rows = parse_decisions(generation.parsed, batch, generation.model, generation.timestamp)
            missing = [candidate for candidate, row in zip(batch, rows) if row["fallback_possible"]]
            resolved = [row for row in rows if not row["fallback_possible"]]
            if missing and len(batch) > 1:
                return resolved + screen_batch(missing)
            return rows
        except Exception as exc:
            if len(batch) > 1:
                middle = len(batch) // 2
                return screen_batch(batch[:middle]) + screen_batch(batch[middle:])
            timestamp = datetime.now(timezone.utc).isoformat()
            rows = parse_decisions({}, batch, str(Path(args.model).resolve()), timestamp)
            rows[0]["batch_error"] = str(exc)
            return rows

    for offset in range(start, len(candidates), args.batch_size):
        batch = candidates[offset:offset + args.batch_size]
        batch_rows = screen_batch(batch)
        decisions.extend(batch_rows)
        write_jsonl(decision_path, decisions)
        processed = min(offset + len(batch), len(candidates))
        counts = {label: sum(row["classification"] == label for row in decisions)
                  for label in sorted(VALID_CLASSES)}
        status = {"processed": processed, "total": len(candidates), **counts,
                  "fallback_possible": sum(row["fallback_possible"] for row in decisions),
                  "complete": processed == len(candidates)}
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break

    forwarded = [row["candidate"] for row in decisions
                 if row["classification"] in {"RELATED", "POSSIBLE"}]
    write_jsonl(target / "evidence_nodes.jsonl", nodes)
    write_jsonl(target / "candidates.jsonl", forwarded)
    write_jsonl(target / "forwarded_candidates.jsonl", forwarded)


if __name__ == "__main__":
    main()
