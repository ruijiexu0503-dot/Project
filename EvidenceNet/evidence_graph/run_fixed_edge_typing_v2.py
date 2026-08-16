from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


PROMPT_VERSION = "fixed-semantic-type-direction-v2"
RELATIONS = {"SUPPORTS", "EXPLAINS_OR_ELABORATES", "MODIFIES", "CONTRASTS_WITH", "REJECT_UNCERTAIN"}


def _prompt(task: dict) -> str:
    return f'''The two TARGET scientific Evidence nodes passed a separate high-recall relationship screen. Assign at most
one fixed semantic edge type and its semantic-role direction. Do not use reading order or A/B order to choose direction.

Choose exactly one:
- SUPPORTS: the source provides evidence, observation, data, a result, or quantitative grounding that makes the target
  claim more credible. Direction: evidence/result -> supported claim.
- EXPLAINS_OR_ELABORATES: the source supplies a definition, mechanism, implementation detail, rationale, interpretation,
  background, or substantive detail that develops the target. Direction: explanation/detail -> developed statement.
- MODIFIES: the source limits, qualifies, conditions, corrects, weakens, or narrows the target. Direction: modifier ->
  modified statement.
- CONTRASTS_WITH: the targets express a specific important comparison, difference, conflict, or opposition. Symmetric.
- REJECT_UNCERTAIN: the relationship screen appears to be a false positive, or the pair cannot reliably receive one of
  the four types from the targets.

SUPPORTS versus EXPLAINS_OR_ELABORATES:
- Prefer SUPPORTS when removing the source would remove empirical or quantitative grounds for believing the target.
- Prefer EXPLAINS_OR_ELABORATES when the source primarily improves understanding, detail, mechanism, or context.
- If both are plausible, select the dominant function and record the secondary function in secondary_relation.

Optional neighboring CONTEXT may resolve fragments or pronouns, but the edge must be between the two TARGET nodes.

Return exactly one JSON object:
{{
  "task_id": "{task['task_id']}",
  "relation": "SUPPORTS|EXPLAINS_OR_ELABORATES|MODIFIES|CONTRASTS_WITH|REJECT_UNCERTAIN",
  "secondary_relation": "SUPPORTS|EXPLAINS_OR_ELABORATES|null",
  "direction_status": "DIRECTED|SYMMETRIC|UNRESOLVED",
  "source_node_id": "target node ID or null",
  "target_node_id": "target node ID or null",
  "relation_description": "one specific sentence involving both targets",
  "confidence": 0.0
}}

For SUPPORTS, EXPLAINS_OR_ELABORATES, and MODIFIES, direction must be DIRECTED and endpoints must be the two target IDs.
For CONTRASTS_WITH, direction must be SYMMETRIC and endpoints null. For REJECT_UNCERTAIN, direction must be UNRESOLVED,
endpoints null, secondary_relation null, and the description must explain the rejection. secondary_relation is allowed
only as the other member of SUPPORTS/EXPLAINS_OR_ELABORATES and cannot equal the primary relation. JSON only.

INPUT:
{json.dumps(task, ensure_ascii=False)}'''


def _confidence(value) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _parse(parsed, task: dict) -> tuple[dict, bool]:
    if not isinstance(parsed, dict):
        return {}, False
    relation = str(parsed.get("relation") or "").upper()
    secondary = parsed.get("secondary_relation")
    if isinstance(secondary, str):
        secondary = secondary.upper()
    direction = str(parsed.get("direction_status") or "").upper()
    source, target = parsed.get("source_node_id"), parsed.get("target_node_id")
    description, confidence = parsed.get("relation_description"), _confidence(parsed.get("confidence"))
    endpoints = {task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]}
    secondary_valid = (
        secondary is None
        or (
            relation in {"SUPPORTS", "EXPLAINS_OR_ELABORATES"}
            and secondary in {"SUPPORTS", "EXPLAINS_OR_ELABORATES"}
            and secondary != relation
        )
    )
    if relation in {"SUPPORTS", "EXPLAINS_OR_ELABORATES", "MODIFIES"}:
        relation_valid = direction == "DIRECTED" and {source, target} == endpoints and source != target
    elif relation == "CONTRASTS_WITH":
        relation_valid = direction == "SYMMETRIC" and source is None and target is None
    elif relation == "REJECT_UNCERTAIN":
        relation_valid = direction == "UNRESOLVED" and source is None and target is None and secondary is None
    else:
        relation_valid = False
    valid = (
        relation in RELATIONS and secondary_valid and relation_valid
        and isinstance(description, str) and bool(description.strip()) and confidence is not None
    )
    return {
        "relation": relation, "secondary_relation": secondary,
        "direction_status": direction, "source_node_id": source, "target_node_id": target,
        "relation_description": description, "confidence": confidence,
    }, valid


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign an exclusive fixed semantic type and direction")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=230)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=5.8)
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
    system = "Assign one fixed semantic edge type and role-based direction to a screened pair. Return exact JSON only."
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    for index in range(start, len(tasks)):
        task, result, valid, raw, error = tasks[index], {}, False, "", ""
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
            "valid": valid, "raw_output": raw, "error": error,
            "model": str(Path(args.model).resolve()), "prompt_version": PROMPT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        write_jsonl(prediction_path, predictions)
        status = {
            "processed": index + 1, "total": len(tasks),
            "valid": sum(row["valid"] for row in predictions),
            "invalid": sum(not row["valid"] for row in predictions),
            "relation_counts": {
                label: sum(row.get("relation") == label for row in predictions) for label in sorted(RELATIONS)
            },
            "with_secondary_relation": sum(bool(row.get("secondary_relation")) for row in predictions),
            "complete": index + 1 == len(tasks),
        }
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
