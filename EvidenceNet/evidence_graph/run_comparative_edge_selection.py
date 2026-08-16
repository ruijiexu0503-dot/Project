from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


PROMPT_VERSION = "comparative-freeform-edge-selection-v1"


def _prompt(task: dict) -> str:
    return f'''Build a SPARSE evidence graph around one SOURCE node by comparing all supplied CANDIDATE nodes.

Select zero, one, or at most three candidates that have the most direct, substantive, graph-worthy relationship with the
SOURCE. Return an empty selection when none deserves an edge. The nodes are from the same scientific paper, so broad
relatedness is expected and is NOT sufficient.

Do not assign an edge type or direction. Apply all of these tests:
1. The relationship must be expressible as one precise factual sentence that genuinely requires content from both nodes.
2. Reject a candidate when the sentence reduces to "both mention X", "both concern the same event/entity/detector", or
   "one shows another aspect of X".
3. Reject proximity, reading order, section membership, and generic background relevance.
4. Reject a figure/citation cue that actually points to a third node rather than the supplied candidate.
5. Prefer the strongest direct relationship over several weaker topical associations. Do not fill the quota.

For every selected candidate, quote a short exact supporting span from SOURCE and from that candidate. Do not select it
if both spans cannot ground the stated relationship.

Return exactly one JSON object:
{{
  "source_id": "{task['source']['node_id']}",
  "selected": [
    {{
      "target_id": "candidate node ID",
      "relation_description": "one precise factual sentence",
      "source_span": "short exact quote from SOURCE",
      "target_span": "short exact quote from candidate"
    }}
  ]
}}

`selected` must contain 0 to 3 unique supplied candidate IDs, strongest first. JSON only.

INPUT:
{json.dumps(task, ensure_ascii=False)}'''


def _parse(parsed, task: dict) -> tuple[list[dict], bool]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("selected"), list):
        return [], False
    allowed = {candidate["node_id"] for candidate in task["candidates"]}
    selected, seen = [], set()
    for row in parsed["selected"]:
        if not isinstance(row, dict):
            return [], False
        target = row.get("target_id")
        fields = (row.get("relation_description"), row.get("source_span"), row.get("target_span"))
        if target not in allowed or target in seen or not all(isinstance(value, str) and value.strip() for value in fields):
            return [], False
        seen.add(target)
        selected.append({
            "target_id": target,
            "relation_description": fields[0].strip(),
            "source_span": fields[1].strip(),
            "target_span": fields[2].strip(),
        })
    return selected, len(selected) <= 3


def main() -> None:
    parser = argparse.ArgumentParser(description="Run taxonomy-free comparative edge selection")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=720)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=12.0)
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
        "Select only the strongest graph-worthy relations around a source node. "
        "Broad same-document relatedness is not an edge. Use no taxonomy. Return exact JSON only."
    )
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    for index in range(start, len(tasks)):
        task, error, raw, selected, valid = tasks[index], "", "", [], False
        for _attempt in range(2):
            try:
                generation = llm.generate_json(system, _prompt(task), args.generation_tokens)
                raw = generation.raw
                selected, valid = _parse(generation.parsed, task)
                if valid:
                    break
            except Exception as exc:
                error = str(exc)
        predictions.append({
            "task_id": task["task_id"], "source_id": task["source"]["node_id"],
            "selected": selected, "valid": valid, "error": error, "raw_output": raw,
            "model": str(Path(args.model).resolve()), "prompt_version": PROMPT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        write_jsonl(prediction_path, predictions)
        status = {
            "processed": index + 1, "total": len(tasks),
            "valid": sum(row["valid"] for row in predictions),
            "invalid": sum(not row["valid"] for row in predictions),
            "selected_directed": sum(len(row.get("selected") or []) for row in predictions),
            "selected_none": sum(not row.get("selected") for row in predictions if row["valid"]),
            "complete": index + 1 == len(tasks),
        }
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
