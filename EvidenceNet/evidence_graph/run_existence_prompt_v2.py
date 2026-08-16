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


PROMPT_VERSION = "existence-multisignal-context-v2"
STATUSES = {"RELATED", "POSSIBLE_RELATION", "UNRELATED"}
SIGNALS = {
    "SAME_CLAIM_OR_RESULT", "EVIDENCE_OR_QUANTIFICATION", "EXPLANATION_OR_MECHANISM",
    "CONDITION_OR_SCOPE", "EXPLICIT_CONTRAST",
}


def _prompt(task: dict) -> str:
    return f'''Decide whether the two TARGET Evidence nodes have a meaningful semantic relationship. This is a
high-recall screening step: do not assign an edge type or direction, and do not reject a coherent relationship merely
because it is implicit or could later receive more than one semantic description.

Check each signal independently in BOTH directions:
- SAME_CLAIM_OR_RESULT: the targets state, repeat, summarize, or develop the same specific claim, result, or event.
- EVIDENCE_OR_QUANTIFICATION: one target supplies a measurement, observation, calculation, example, or quantitative
  detail that bears on a claim in the other.
- EXPLANATION_OR_MECHANISM: one target supplies a definition, mechanism, implementation detail, rationale, background,
  or interpretation that materially develops the other.
- CONDITION_OR_SCOPE: one target limits, qualifies, conditions, corrects, or narrows the other.
- EXPLICIT_CONTRAST: the targets express a specific comparison, difference, or conflict.

Use the optional neighboring CONTEXT only to resolve fragments, pronouns, or what a target is discussing. Context cannot
create an edge by itself: at least one concrete anchor must still appear in each TARGET.

Status policy:
- RELATED: at least one signal clearly holds between the targets.
- POSSIBLE_RELATION: a specific relationship hypothesis is plausible, but the target text remains insufficient or the
  apparent link may depend on omitted context. This status is retained for a second-stage verifier.
- UNRELATED: only shared topic/entities/proximity exist, or the real connection is only through a third node.

Before choosing UNRELATED, state the strongest plausible relationship and test the counterfactual: would information in
one target materially help interpret, justify, explain, qualify, or contrast the other? If yes, use RELATED or
POSSIBLE_RELATION. Do not require either target to be understandable only when the other is present.

relationship_probability means P(meaningful semantic relationship), not confidence in the chosen label.

Return exactly one JSON object:
{{
  "task_id": "{task['task_id']}",
  "status": "RELATED|POSSIBLE_RELATION|UNRELATED",
  "signals": ["one or more signal names, or empty for UNRELATED"],
  "best_relation_hypothesis": "specific sentence involving both targets, or null",
  "anchor_a": "short phrase copied from target A, or null",
  "anchor_b": "short phrase copied from target B, or null",
  "unrelated_reason": "specific reason, only for UNRELATED, otherwise null",
  "relationship_probability": 0.0
}}

For RELATED/POSSIBLE_RELATION, signals, hypothesis, and both anchors must be non-empty and unrelated_reason must be null.
For UNRELATED, signals must be empty, hypothesis and anchors must be null, and unrelated_reason must be non-empty.
JSON only.

INPUT:
{json.dumps(task, ensure_ascii=False)}'''


def _probability(value) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _anchor_in_target(anchor, target: dict) -> bool:
    if not _nonempty(anchor):
        return False
    target_text = str(target.get("text") or "")
    return _normalized_text(str(anchor)) in _normalized_text(target_text)


def _parse(parsed, task: dict) -> tuple[dict, bool]:
    if not isinstance(parsed, dict):
        return {}, False
    status = str(parsed.get("status") or "").upper()
    signals = parsed.get("signals")
    hypothesis = parsed.get("best_relation_hypothesis")
    anchor_a, anchor_b = parsed.get("anchor_a"), parsed.get("anchor_b")
    unrelated_reason = parsed.get("unrelated_reason")
    probability = _probability(parsed.get("relationship_probability"))
    signals_valid = (
        isinstance(signals, list) and len(signals) == len(set(signals))
        and all(signal in SIGNALS for signal in signals)
    )
    if status in {"RELATED", "POSSIBLE_RELATION"}:
        fields_valid = (
            signals_valid and bool(signals) and _nonempty(hypothesis)
            and _anchor_in_target(anchor_a, task["evidence_a"])
            and _anchor_in_target(anchor_b, task["evidence_b"])
            and unrelated_reason is None
        )
    elif status == "UNRELATED":
        fields_valid = (
            signals_valid and not signals and hypothesis is None and anchor_a is None
            and anchor_b is None and _nonempty(unrelated_reason)
        )
    else:
        fields_valid = False
    return {
        "status": status, "signals": signals if isinstance(signals, list) else [],
        "best_relation_hypothesis": hypothesis, "anchor_a": anchor_a, "anchor_b": anchor_b,
        "unrelated_reason": unrelated_reason, "relationship_probability": probability,
    }, status in STATUSES and fields_valid and probability is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run high-recall multi-signal edge-existence prompt v2")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=300)
    parser.add_argument("--maximum-runtime-minutes", type=float, default=8.0)
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
        "Screen a scientific Evidence pair for a meaningful semantic relationship with high recall. "
        "Check independent signals, use context only to resolve targets, and return exact JSON."
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
            "status_counts": {
                label: sum(row.get("status") == label for row in predictions) for label in sorted(STATUSES)
            },
            "complete": index + 1 == len(tasks),
        }
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
