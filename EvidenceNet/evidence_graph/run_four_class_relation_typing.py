from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .four_class_relation_typing import ABSTAIN, PROMPT_VERSION, RELATIONS
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


DEFINITIONS = {
    "CONTRIBUTES_TO": (
        "The source provides substantive additional information, explanation, evidence, background, "
        "or development for the target."
    ),
    "MODIFIES": (
        "The source qualifies, corrects, conditions, restricts, or changes the scope or applicability "
        "of the target."
    ),
    "CONTRASTS_WITH": "The nodes express an explicit contrast, conflict, or important difference. It is symmetric.",
    "REFERENCES": (
        "The source explicitly cites, points to, or refers back to the target. An explicit referential "
        "cue in the source is required, such as 'shown in Fig. 1', 'see Fig. 3', or a clear anaphoric cue."
    ),
}


def prompt(task: dict) -> str:
    return f'''The two supplied scientific Evidence nodes are guaranteed to have a meaningful relation.
Do not decide whether an edge exists and do not answer NONE. Choose the single best relation from this ontology:
{json.dumps(DEFINITIONS, ensure_ascii=False, indent=2)}

Decision policy:
- REFERENCES requires an explicit cue in the source that points to the other supplied node. A citation or figure
  mention that points somewhere else does not qualify.
- If an explicit reference also expresses a substantive contrast, choose CONTRASTS_WITH when contrast is the main relation.
- MODIFIES requires a real change of condition, limitation, correction, scope, or applicability.
- Otherwise, substantive elaboration, explanation, support, or background is CONTRIBUTES_TO.

Direction conventions:
- CONTRIBUTES_TO: contributing information -> content receiving the contribution.
- MODIFIES: qualifier/condition/correction -> content being modified.
- REFERENCES: referring node containing the explicit cue -> node being referenced.
- CONTRASTS_WITH is symmetric; return the endpoint IDs in either order.

Test both orientations independently. Text order and Evidence A are not default sources. If the class or direction
cannot be selected reliably even though an edge is known to exist, return REJECT_UNCERTAIN rather than inventing a label.

Return one JSON object with exactly: task_id, relation_type, source_node_id, target_node_id, confidence.
relation_type must be one of {json.dumps(RELATIONS + (ABSTAIN,))}. For the four relation classes, source_node_id and
target_node_id must be the supplied IDs. For REJECT_UNCERTAIN, both endpoint fields must be null. confidence must be a
JSON number from 0 to 1. JSON only.

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
    if relation == ABSTAIN and confidence is not None:
        return {"relation_type": relation, "source_node_id": None,
                "target_node_id": None, "confidence": confidence}, True
    valid = (relation in RELATIONS and {source, target} == endpoints and source != target
             and confidence is not None)
    return {"relation_type": relation, "source_node_id": source,
            "target_node_id": target, "confidence": confidence}, valid


def main() -> None:
    parser = argparse.ArgumentParser(description="Run known-related four-class type+direction evaluation")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", default="output/strict_relation_typing/shared/blind_tasks.jsonl")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=120)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=4.5)
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
    system = "Classify a known scientific relation and its direction using the fixed four-class ontology. Return exact JSON."
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    for index in range(start, len(tasks)):
        task = tasks[index]
        error, raw, result, valid = "", "", {}, False
        for _attempt in range(2):
            try:
                generation = llm.generate_json(system, prompt(task), args.generation_tokens)
                raw = generation.raw
                result, valid = parse(generation.parsed, task)
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
        status = {"processed": index + 1, "total": len(tasks),
                  "valid": sum(row["valid"] for row in predictions),
                  "invalid": sum(not row["valid"] for row in predictions),
                  "reject_uncertain": sum(row.get("relation_type") == ABSTAIN for row in predictions),
                  "complete": index + 1 == len(tasks)}
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
