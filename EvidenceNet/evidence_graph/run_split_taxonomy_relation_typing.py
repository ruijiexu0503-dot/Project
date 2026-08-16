from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .evaluate_split_taxonomy import REJECT, SEMANTIC_RELATIONS
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


PROMPT_VERSION = "oracle-split-semantic-reference-v1"

SEMANTIC_DEFINITIONS = {
    "SUPPORTS": (
        "The source supplies evidence, an observation, data, or a result that makes the target statement more credible."
    ),
    "EXPLAINS_OR_ELABORATES": (
        "The source explains, develops, adds details, mechanism, background, or context to the target."
    ),
    "MODIFIES": (
        "The source qualifies, corrects, conditions, weakens, narrows, or constrains the target statement."
    ),
    "CONTRASTS_WITH": (
        "The nodes express an explicit important difference, opposition, conflict, or comparison. This is symmetric."
    ),
}


def prompt(task: dict) -> str:
    return f'''The supplied scientific Evidence-node pair is known to be related. Perform TWO INDEPENDENT tasks.

TASK A — SEMANTIC FUNCTION
Choose one semantic label:
{json.dumps(SEMANTIC_DEFINITIONS, ensure_ascii=False, indent=2)}
Use REJECT_UNCERTAIN only when none of the four semantic functions can be assigned reliably.

Semantic direction is determined by ROLE, never by Evidence A/B order or reading order:
- SUPPORTS: evidence/result -> supported statement.
- EXPLAINS_OR_ELABORATES: explanation/detail/context -> explained/developed statement.
- MODIFIES: modifier/condition/limitation -> modified statement.
- CONTRASTS_WITH is symmetric; either endpoint order is accepted.
Explicit reference wording does NOT replace the semantic label. A pair may have both a semantic relation and a reference.

TASK B — EXPLICIT REFERENCE
Independently decide whether one supplied node explicitly cites, points to, or refers back to the other supplied node.
REFERENCES=true requires a localizable cue such as "see Figure 2", "as discussed above", "shown previously", or a clear
anaphor whose antecedent is the other supplied node. Mere topic similarity is false. A figure/citation mention pointing to
some third node is false for this pair.
Reference direction is: node containing the cue -> node being referenced. Determine it separately from semantic direction;
the two directions may be opposite. If REFERENCES=false, its endpoints and cue must be null.

Return exactly one JSON object with this shape:
{{
  "task_id": "{task['task_id']}",
  "semantic": {{
    "relation": "SUPPORTS|EXPLAINS_OR_ELABORATES|MODIFIES|CONTRASTS_WITH|REJECT_UNCERTAIN",
    "source_node_id": "supplied ID or null",
    "target_node_id": "supplied ID or null",
    "confidence": 0.0
  }},
  "references": {{
    "exists": false,
    "source_node_id": null,
    "target_node_id": null,
    "cue": null,
    "confidence": 0.0
  }}
}}
For a non-rejected semantic label, semantic endpoints must be the two supplied IDs. For REJECT_UNCERTAIN they must be null.
For REFERENCES=true, reference endpoints must be the two supplied IDs and cue must quote a short phrase from the referring
node. Confidence values are JSON numbers from 0 to 1. JSON only.

PAIR:
{json.dumps(task, ensure_ascii=False)}'''


def confidence(value) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def parse(parsed, task: dict) -> tuple[dict, bool]:
    if not isinstance(parsed, dict):
        return {}, False
    endpoints = {task["evidence_a"]["node_id"], task["evidence_b"]["node_id"]}
    semantic_raw = parsed.get("semantic")
    reference_raw = parsed.get("references")
    if not isinstance(semantic_raw, dict) or not isinstance(reference_raw, dict):
        return {}, False

    relation = str(semantic_raw.get("relation") or "").upper()
    semantic_source = semantic_raw.get("source_node_id")
    semantic_target = semantic_raw.get("target_node_id")
    semantic_confidence = confidence(semantic_raw.get("confidence"))
    if relation == REJECT:
        semantic_valid = semantic_source is None and semantic_target is None and semantic_confidence is not None
    else:
        semantic_valid = (
            relation in SEMANTIC_RELATIONS
            and {semantic_source, semantic_target} == endpoints
            and semantic_source != semantic_target
            and semantic_confidence is not None
        )

    reference_exists = reference_raw.get("exists")
    reference_source = reference_raw.get("source_node_id")
    reference_target = reference_raw.get("target_node_id")
    reference_cue = reference_raw.get("cue")
    reference_confidence = confidence(reference_raw.get("confidence"))
    if reference_exists is True:
        reference_valid = (
            {reference_source, reference_target} == endpoints
            and reference_source != reference_target
            and isinstance(reference_cue, str)
            and bool(reference_cue.strip())
            and reference_confidence is not None
        )
    elif reference_exists is False:
        reference_valid = (
            reference_source is None
            and reference_target is None
            and reference_cue is None
            and reference_confidence is not None
        )
    else:
        reference_valid = False

    result = {
        "semantic": {
            "relation": relation,
            "source_node_id": semantic_source,
            "target_node_id": semantic_target,
            "confidence": semantic_confidence,
        },
        "references": {
            "exists": reference_exists,
            "source_node_id": reference_source,
            "target_node_id": reference_target,
            "cue": reference_cue,
            "confidence": reference_confidence,
        },
    }
    return result, semantic_valid and reference_valid


def main() -> None:
    parser = argparse.ArgumentParser(description="Run independent semantic and reference oracle-pair tasks")
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--tasks",
        default="evaluation/ground_truth/gw150914_detection/split_taxonomy_oracle_pairs.jsonl",
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=220)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=6.0)
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
        model=str(Path(args.model).resolve()),
        require_cuda=True,
        enable_thinking=False,
    )
    llm = create_llm(config["enrichment"])
    system = (
        "Classify semantic function and explicit reference independently for a known-related scientific pair. "
        "Follow role-based direction rules and return exact JSON only."
    )
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
            "task_id": task["task_id"],
            "pair_id": task["pair_id"],
            **result,
            "valid": valid,
            "error": error,
            "raw_output": raw,
            "model": str(Path(args.model).resolve()),
            "prompt_version": PROMPT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        write_jsonl(prediction_path, predictions)
        status = {
            "processed": index + 1,
            "total": len(tasks),
            "valid": sum(row["valid"] for row in predictions),
            "invalid": sum(not row["valid"] for row in predictions),
            "semantic_reject_uncertain": sum(
                (row.get("semantic") or {}).get("relation") == REJECT for row in predictions
            ),
            "reference_true": sum(
                (row.get("references") or {}).get("exists") is True for row in predictions
            ),
            "complete": index + 1 == len(tasks),
        }
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
