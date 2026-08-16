from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from .config import load_config
from .io_utils import read_jsonl, write_json, write_jsonl
from .llm_client import create_llm


PROMPT_VERSION = "sequential-long-range-ranking-v1"
NODE_SUFFIX = re.compile(r"^(.*?_EV_)0*(\d+)$")


def _prompt(task: dict) -> str:
    return f'''A document is being processed in reading order. Rank the EARLIER candidate Evidence nodes by whether they
have a direct, high-information long-range semantic relationship with the CURRENT node.

These candidates are deliberately far away or in another section. Same document, shared topic, shared entity, and broad
background relevance are expected and are NOT enough for an edge. A valuable long-range edge should connect evidence,
explanation, limitation, contrast, a specific repeated quantitative fact, or an explicit cross-reference that cannot be
recovered merely from reading order or section hierarchy.

Do not assign an edge type or direction. Rank every supplied candidate from strongest to weakest. Then place one cutoff:
all candidates before the cutoff deserve an edge; all candidates at or after it do not. The cutoff may be zero, one,
several, or all candidates. There is no quota. Most long-range candidates should normally remain below the cutoff.

Return exactly one JSON object:
{{
  "current_node_id": "{task['current_node']['node_id']}",
  "ranked_candidate_ids": ["every supplied candidate ID exactly once"],
  "edge_cutoff": 0
}}

`edge_cutoff` is an integer from 0 through the number of candidates. JSON only.

INPUT:
{json.dumps(task, ensure_ascii=False)}'''


def _parse(parsed, task: dict) -> tuple[list[str], int, bool]:
    expected = [node["node_id"] for node in task["earlier_candidates"]]
    if not isinstance(parsed, dict) or not isinstance(parsed.get("ranked_candidate_ids"), list):
        return expected, 0, False
    ranked = parsed["ranked_candidate_ids"]
    # Some otherwise valid outputs omit padding zeroes (EV_00059 vs EV_000059).
    # Resolve only an unambiguous numeric-suffix match; this repairs formatting,
    # never candidate membership or semantic ordering.
    canonical = {}
    for value in expected:
        match = NODE_SUFFIX.match(value)
        key = (match.group(1), int(match.group(2))) if match else None
        if key is not None:
            canonical.setdefault(key, []).append(value)
    repaired = []
    for value in ranked:
        if value in expected:
            repaired.append(value)
            continue
        match = NODE_SUFFIX.match(value) if isinstance(value, str) else None
        matches = canonical.get((match.group(1), int(match.group(2))), []) if match else []
        repaired.append(matches[0] if len(matches) == 1 else value)
    ranked = repaired
    cutoff = parsed.get("edge_cutoff")
    valid_ranking = (
        len(ranked) == len(expected) and len(set(ranked)) == len(expected)
        and set(ranked) == set(expected) and all(isinstance(value, str) for value in ranked)
    )
    valid_cutoff = isinstance(cutoff, int) and not isinstance(cutoff, bool) and 0 <= cutoff <= len(expected)
    return (ranked if valid_ranking else expected), (cutoff if valid_cutoff else 0), valid_ranking and valid_cutoff


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sequential long-range comparative ranking")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=420)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=12.0)
    args = parser.parse_args()

    tasks, output = read_jsonl(Path(args.tasks)), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    prediction_path, status_path = output / "rankings.jsonl", output / "status.json"
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
        "Rank earlier nodes for sparse, high-information long-range graph edges. "
        "Shared topic is not an edge. Use no taxonomy. Return exact JSON only."
    )
    deadline = monotonic() + args.maximum_runtime_minutes * 60
    for index in range(start, len(tasks)):
        task, error, raw, ranked, cutoff, valid = tasks[index], "", "", [], 0, False
        for _attempt in range(2):
            try:
                generation = llm.generate_json(system, _prompt(task), args.generation_tokens)
                raw = generation.raw
                ranked, cutoff, valid = _parse(generation.parsed, task)
                if valid:
                    break
            except Exception as exc:
                error = str(exc)
        predictions.append({
            "task_id": task["task_id"], "current_node_id": task["current_node"]["node_id"],
            "ranked_candidate_ids": ranked, "edge_cutoff": cutoff,
            "valid": valid, "error": error, "raw_output": raw,
            "model": str(Path(args.model).resolve()), "prompt_version": PROMPT_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        write_jsonl(prediction_path, predictions)
        status = {
            "processed": index + 1, "total": len(tasks),
            "valid": sum(row["valid"] for row in predictions),
            "invalid": sum(not row["valid"] for row in predictions),
            "cutoff_edges": sum(row.get("edge_cutoff", 0) for row in predictions if row["valid"]),
            "zero_cutoff_centers": sum(row.get("edge_cutoff") == 0 for row in predictions if row["valid"]),
            "complete": index + 1 == len(tasks),
        }
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
