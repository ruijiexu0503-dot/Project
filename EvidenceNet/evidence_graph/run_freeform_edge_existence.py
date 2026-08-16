from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


PROMPT_VERSION = "freeform-grounded-existence-v1"
STATUSES = {"RELATED_STRONG", "AMBIGUOUS", "UNRELATED"}


def _prompt(task: dict) -> str:
    return f'''Decide whether these two scientific Evidence nodes have a DIRECT, SUBSTANTIVE semantic relationship.

Do not assign a relation type or taxonomy label. Do not decide a graph direction.

Use RELATED_STRONG only when you can state a specific factual relationship that genuinely requires BOTH nodes and quote a
supporting span from each. Shared topic, shared entities, document proximity, or generic relevance are not enough. A
description such as "both discuss gravitational waves" is not a relationship.

Use UNRELATED when:
- the nodes are merely topically similar;
- a citation or figure mention points to a third node rather than the supplied partner;
- the only connection is reading order, section membership, or layout;
- the text fragments merely continue one physical sentence (that belongs to CONTINUES, not a semantic edge);
- no precise relationship can be stated from the supplied text alone.

Use AMBIGUOUS only when a plausible direct relationship exists but the supplied spans are insufficient to establish it
confidently. AMBIGUOUS will not become a production edge.

Return exactly one JSON object:
{{
  "task_id": "{task['task_id']}",
  "status": "RELATED_STRONG|AMBIGUOUS|UNRELATED",
  "relation_description": "one concrete sentence describing how the two nodes are related, or null",
  "supporting_span_a": "short exact quote from Evidence A, or null",
  "supporting_span_b": "short exact quote from Evidence B, or null",
  "confidence": 0.0
}}

For RELATED_STRONG and AMBIGUOUS, description and both spans must be non-empty. For UNRELATED they must all be null.
Confidence must be a JSON number from 0 to 1. JSON only.

PAIR:
{json.dumps(task, ensure_ascii=False)}'''


def _confidence(value) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _parse(parsed) -> tuple[dict, bool]:
    if not isinstance(parsed, dict):
        return {}, False
    status = str(parsed.get("status") or "").upper()
    description = parsed.get("relation_description")
    span_a, span_b = parsed.get("supporting_span_a"), parsed.get("supporting_span_b")
    confidence = _confidence(parsed.get("confidence"))
    if status in {"RELATED_STRONG", "AMBIGUOUS"}:
        fields_valid = all(isinstance(value, str) and value.strip()
                           for value in (description, span_a, span_b))
    elif status == "UNRELATED":
        fields_valid = description is None and span_a is None and span_b is None
    else:
        fields_valid = False
    result = {
        "status": status,
        "relation_description": description,
        "supporting_span_a": span_a,
        "supporting_span_b": span_b,
        "confidence": confidence,
    }
    return result, status in STATUSES and fields_valid and confidence is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run taxonomy-free grounded edge-existence decisions")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=190)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=20.0)
    args = parser.parse_args()

    tasks, output = read_jsonl(Path(args.tasks)), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    prediction_path, status_path = output / "predictions.jsonl", output / "status.json"
    predictions = read_jsonl(prediction_path) if prediction_path.exists() else []
    start = len(predictions)
    if start >= len(tasks):
        print(json.dumps({"complete": True, "processed": start, "total": len(tasks)}, indent=2))
        return

    config = load_config(args.config)
    config["enrichment"].update(
        model=str(Path(args.model).resolve()), require_cuda=True, enable_thinking=False,
    )
    llm = create_llm(config["enrichment"])
    system = (
        "Judge only whether a direct substantive semantic relationship is grounded. "
        "Use no relation taxonomy. Return exact JSON only."
    )
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    for index in range(start, len(tasks)):
        task, error, raw, result, valid = tasks[index], "", "", {}, False
        for _attempt in range(2):
            try:
                generation = llm.generate_json(system, _prompt(task), args.generation_tokens)
                raw = generation.raw
                result, valid = _parse(generation.parsed)
                if valid:
                    break
            except Exception as exc:
                error = str(exc)
        predictions.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"], **result,
            "valid": valid, "error": error, "raw_output": raw,
            "model": str(Path(args.model).resolve()), "prompt_version": PROMPT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        write_jsonl(prediction_path, predictions)
        status = {
            "processed": index + 1, "total": len(tasks),
            "valid": sum(row["valid"] for row in predictions),
            "invalid": sum(not row["valid"] for row in predictions),
            "related_strong": sum(row.get("status") == "RELATED_STRONG" for row in predictions),
            "ambiguous": sum(row.get("status") == "AMBIGUOUS" for row in predictions),
            "unrelated": sum(row.get("status") == "UNRELATED" for row in predictions),
            "complete": index + 1 == len(tasks),
        }
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
