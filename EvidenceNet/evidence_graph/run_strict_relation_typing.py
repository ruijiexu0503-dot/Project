from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm
from .prepare_strict_relation_typing import PROMPT_VERSION, RELATIONS


DEFINITIONS = {
    "ELABORATES": "The source adds material detail or specificity to the same proposition in the target.",
    "SUPPORTS": "The source provides evidence that increases the credibility of a claim in the target.",
    "EXPLAINS": "The source supplies why/how, a mechanism, or an explanation for content in the target.",
    "QUALIFIES": "The source limits, conditions, narrows, or adds an important caveat to the target.",
    "DEPENDS_ON": "The source uses or requires a method, equation, definition, assumption, resource, or result in the target.",
    "CONTRASTS_WITH": "The two nodes express a meaningful contrast. This relation is symmetric.",
}


def prompt(task: dict) -> str:
    return f'''The two supplied scientific Evidence nodes are known to have exactly one meaningful semantic relation.
Do not decide whether a relation exists and do not answer NONE. Select the single best relation type and its semantic
direction from this fixed ontology:
{json.dumps(DEFINITIONS, ensure_ascii=False, indent=2)}

Direction conventions:
- ELABORATES: added detail -> proposition being developed.
- SUPPORTS: evidence -> claim.
- EXPLAINS: explanation/mechanism -> content being explained.
- QUALIFIES: limitation/caveat -> statement being qualified.
- DEPENDS_ON: dependent content -> required method/equation/definition/resource/result.
- CONTRASTS_WITH is symmetric; return the two endpoint IDs in either order.

Test both orientations independently. Text order and Evidence A are not default sources. Distinguish elaboration from
explanation: extra detail about the same proposition is ELABORATES; why/how or mechanism is EXPLAINS. Distinguish
support from elaboration: SUPPORTS requires evidence for a claim, not merely more detail.

Return one JSON object with exactly: task_id, relation_type, source_node_id, target_node_id, confidence.
relation_type must be one of {json.dumps(RELATIONS)}. source_node_id and target_node_id must be the supplied IDs.
confidence must be a JSON number from 0 to 1. JSON only.

TASK:
{json.dumps(task, ensure_ascii=False)}'''


def parse(parsed, task: dict) -> tuple[dict, bool]:
    endpoints = {task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]}
    if not isinstance(parsed, dict):
        return {}, False
    relation = str(parsed.get("relation_type") or "").upper()
    source, target = parsed.get("source_node_id"), parsed.get("target_node_id")
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence"))))
    except (TypeError, ValueError):
        confidence = None
    valid = (relation in RELATIONS and {source, target} == endpoints and source != target
             and confidence is not None)
    return {"relation_type": relation, "source_node_id": source,
            "target_node_id": target, "confidence": confidence}, valid


def main() -> None:
    parser = argparse.ArgumentParser(description="Run known-related strict type+direction evaluation")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", default="output/strict_relation_typing/shared/blind_tasks.jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=180)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=20)
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
    config["enrichment"].update(model=str(Path(args.model).resolve()), require_cuda=True,
                                enable_thinking=False)
    llm = create_llm(config["enrichment"])
    system = "You classify a known scientific relation and its direction. Follow the JSON schema exactly."
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    for index in range(start, len(tasks)):
        task = tasks[index]
        error, raw, result, valid = "", "", {}, False
        for attempt in range(2):
            try:
                generation = llm.generate_json(system, prompt(task), args.generation_tokens)
                raw = generation.raw
                result, valid = parse(generation.parsed, task)
                if valid:
                    break
            except Exception as exc:
                error = str(exc)
        predictions.append({
            "task_id": task["task_id"], "pair_id": task["pair_id"],
            **result, "valid": valid, "error": error, "raw_output": raw,
            "model": str(Path(args.model).resolve()), "prompt_version": PROMPT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        write_jsonl(prediction_path, predictions)
        status = {"processed": index + 1, "total": len(tasks),
                  "valid": sum(row["valid"] for row in predictions),
                  "invalid": sum(not row["valid"] for row in predictions),
                  "complete": index + 1 == len(tasks)}
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
