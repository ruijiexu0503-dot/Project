from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


PROMPT_VERSION = "contribution-profile-typing-v1"
RELATIONS = {"CONTRIBUTES_TO", "MODIFIES", "CONTRASTS_WITH", "RELATED"}
MODES = {"EVIDENTIAL", "EXPLANATORY"}
DIRECTIONS = {"DIRECTED", "SYMMETRIC", "UNRESOLVED"}


def _prompt(task: dict) -> str:
    return f'''The supplied scientific Evidence pair is already known to have a semantic relationship. Do not decide
whether an edge exists. Describe its semantic profile without forcing evidence and explanation to be mutually exclusive.

Choose one primary_relation:
- CONTRIBUTES_TO: one node contributes evidence, explanation, mechanism, background, definition, or specific detail to
  the other node. For this relation, contribution_modes must contain EVIDENTIAL, EXPLANATORY, or both.
- MODIFIES: one node limits, qualifies, conditions, corrects, weakens, or narrows the other.
- CONTRASTS_WITH: the nodes explicitly express an important contrast or conflict. This is symmetric.
- RELATED: a direct relationship exists, but the supplied text does not support a stable type or direction.

Contribution modes are independent:
- EVIDENTIAL: the source provides observation, measurement, result, data, or a factual instance that makes the target
  claim more credible or establishes it.
- EXPLANATORY: the source provides a mechanism, definition, derivation, background, context, or detail that helps explain
  or develop the target.
A contribution may be BOTH evidential and explanatory. Do not choose EVIDENTIAL merely because a sentence is factual.

Direction is a separate decision:
- CONTRIBUTES_TO: contributor -> focal statement.
- MODIFIES: modifier/condition -> modified statement.
- CONTRASTS_WITH: direction_status is SYMMETRIC and source/target are null.
- If a CONTRIBUTES_TO direction genuinely cannot be resolved, use UNRESOLVED and null endpoints.

Return exactly one JSON object:
{{
  "task_id": "{task['task_id']}",
  "primary_relation": "CONTRIBUTES_TO|MODIFIES|CONTRASTS_WITH|RELATED",
  "contribution_modes": ["EVIDENTIAL", "EXPLANATORY"],
  "direction_status": "DIRECTED|SYMMETRIC|UNRESOLVED",
  "source_node_id": "node ID or null",
  "target_node_id": "node ID or null",
  "relation_description": "one specific sentence requiring both nodes",
  "confidence": 0.0
}}

For MODIFIES, CONTRASTS_WITH, and RELATED, contribution_modes must be empty. JSON only.

PAIR:
{json.dumps(task, ensure_ascii=False)}'''


def _confidence(value) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _parse(parsed, task: dict) -> tuple[dict, bool]:
    if not isinstance(parsed, dict):
        return {}, False
    relation = str(parsed.get("primary_relation") or "").upper()
    modes = parsed.get("contribution_modes")
    direction = str(parsed.get("direction_status") or "").upper()
    source, target = parsed.get("source_node_id"), parsed.get("target_node_id")
    description = parsed.get("relation_description")
    confidence = _confidence(parsed.get("confidence"))
    endpoints = {task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]}
    modes_valid = (
        isinstance(modes, list) and len(modes) == len(set(modes))
        and all(value in MODES for value in modes)
    )
    if relation == "CONTRIBUTES_TO":
        modes_valid = modes_valid and bool(modes)
        direction_valid = (
            direction == "DIRECTED" and {source, target} == endpoints and source != target
        ) or (direction == "UNRESOLVED" and source is None and target is None)
    elif relation == "MODIFIES":
        modes_valid = modes_valid and not modes
        direction_valid = direction == "DIRECTED" and {source, target} == endpoints and source != target
    elif relation == "CONTRASTS_WITH":
        modes_valid = modes_valid and not modes
        direction_valid = direction == "SYMMETRIC" and source is None and target is None
    elif relation == "RELATED":
        modes_valid = modes_valid and not modes
        direction_valid = direction == "UNRESOLVED" and source is None and target is None
    else:
        direction_valid = False
    valid = (
        relation in RELATIONS and direction in DIRECTIONS and modes_valid and direction_valid
        and isinstance(description, str) and bool(description.strip()) and confidence is not None
    )
    return {
        "primary_relation": relation,
        "contribution_modes": modes if isinstance(modes, list) else [],
        "direction_status": direction,
        "source_node_id": source,
        "target_node_id": target,
        "relation_description": description,
        "confidence": confidence,
    }, valid


def main() -> None:
    parser = argparse.ArgumentParser(description="Type accepted edges with non-exclusive contribution modes")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=280)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=10.0)
    args = parser.parse_args()

    tasks, output = read_jsonl(args.tasks), Path(args.output)
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
        "Type a known scientific semantic edge. Evidence and explanation are independent modes. "
        "Judge direction separately. Return exact JSON only."
    )
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    for index in range(start, len(tasks)):
        task, error, raw, result, valid = tasks[index], "", "", {}, False
        for _attempt in range(2):
            try:
                generation = llm.generate_json(system, _prompt(task), args.generation_tokens)
                raw = generation.raw
                result, valid = _parse(generation.parsed, task)
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
            "primary_relation_counts": {
                relation: sum(row.get("primary_relation") == relation for row in predictions if row["valid"])
                for relation in sorted(RELATIONS)
            },
            "both_contribution_modes": sum(
                set(row.get("contribution_modes") or []) == MODES for row in predictions if row["valid"]
            ),
            "complete": index + 1 == len(tasks),
        }
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
