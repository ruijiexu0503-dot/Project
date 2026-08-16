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


PROMPT_VERSION = "strict-direct-edge-existence-v1"
DIRECTNESS = {
    "DIRECT", "SHARED_CENTER", "MEDIATED", "TOPIC_ONLY",
    "REFERENCE_ONLY", "CONTEXT_ONLY", "REDUNDANT", "INSUFFICIENT",
}
VERDICTS = {"KEEP_EDGE", "REJECT_EDGE"}


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _nonempty(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _anchor_in_target(anchor, target: dict) -> bool:
    return _nonempty(anchor) and _normalized(str(anchor)) in _normalized(str(target.get("text") or ""))


def _nullable_text(value):
    return value if _nonempty(value) else None


def _confidence(value) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _prompt(task: dict) -> str:
    return f'''Audit whether the two TARGET scientific Evidence nodes deserve a DIRECT semantic graph edge. A previous
high-recall screen accepted the pair, so rejection is expected whenever its apparent relationship is only topical,
mediated, redundant, reference-only, or created by neighboring context. Do not assign an edge type or direction.

A semantic edge requires BOTH:
1. A specific atomic subject, claim, result, measurement, method, condition, or comparison grounded by an exact phrase
   in each TARGET.
2. A direct, non-redundant information contribution: information in one TARGET materially changes the credibility,
   interpretation, specificity, scope, or contrastive meaning of the other TARGET.

Reject these common false positives:
- both targets concern the same document, section, event, entity, figure, or central claim but do not inform each other;
- A relates to a third node C and B relates to C, but A and B are not directly related;
- the relationship needs a third node or neighboring CONTEXT to exist;
- one target merely mentions an entity and the other gives unrelated details about that entity;
- both targets are broadly useful background for the same topic;
- they repeat the same information without a material addition;
- an explicit Figure/Table/Equation/Section pointer exists but there is no additional semantic contribution. This is
  REFERENCE_ONLY; the discourse reference may be kept elsewhere while the semantic edge is rejected.

Optional CONTEXT can resolve a fragment or pronoun, but cannot supply either exact anchor and cannot create the bridge.
Test the shared-center counterfactual: if the common central claim/event/third node were removed, can the direct
contribution still be stated using only the two TARGET texts? If not, reject.

directness labels:
- DIRECT: the two targets themselves support a direct, non-redundant semantic contribution or explicit contrast.
- SHARED_CENTER: both connect to the same central claim/event but not directly to each other.
- MEDIATED: the proposed relationship requires a third node.
- TOPIC_ONLY: only topic/entity similarity exists.
- REFERENCE_ONLY: only an explicit discourse pointer exists.
- CONTEXT_ONLY: neighboring context creates the bridge; the targets do not.
- REDUNDANT: substantially repeated information with no useful addition.
- INSUFFICIENT: target evidence is too incomplete to prove a direct edge.

Return exactly one JSON object:
{{
  "task_id": "{task['task_id']}",
  "anchor_a": "exact substring from TARGET A or null",
  "anchor_b": "exact substring from TARGET B or null",
  "shared_atomic_subject": "specific common proposition or null",
  "contribution_a_to_b": "specific non-redundant contribution or null",
  "contribution_b_to_a": "specific non-redundant contribution or null",
  "directness": "DIRECT|SHARED_CENTER|MEDIATED|TOPIC_ONLY|REFERENCE_ONLY|CONTEXT_ONLY|REDUNDANT|INSUFFICIENT",
  "third_node_required": false,
  "verdict": "KEEP_EDGE|REJECT_EDGE",
  "rejection_reason": "specific reason or null",
  "confidence": 0.0
}}

KEEP_EDGE is valid only with DIRECT, third_node_required=false, two exact TARGET anchors, a specific shared subject, at
least one non-empty contribution, and rejection_reason=null. Every other case must be REJECT_EDGE with a non-DIRECT
label and a specific rejection_reason. For MEDIATED, third_node_required must be true; otherwise it must be false.
JSON only.

INPUT:
{json.dumps(task, ensure_ascii=False)}'''


def _parse(parsed, task: dict) -> tuple[dict, bool]:
    if not isinstance(parsed, dict):
        return {}, False
    verdict = str(parsed.get("verdict") or "").upper()
    directness = str(parsed.get("directness") or "").upper()
    anchor_a, anchor_b = parsed.get("anchor_a"), parsed.get("anchor_b")
    subject = _nullable_text(parsed.get("shared_atomic_subject"))
    a_to_b = _nullable_text(parsed.get("contribution_a_to_b"))
    b_to_a = _nullable_text(parsed.get("contribution_b_to_a"))
    third = parsed.get("third_node_required")
    reason = _nullable_text(parsed.get("rejection_reason"))
    confidence = _confidence(parsed.get("confidence"))
    if verdict == "KEEP_EDGE":
        fields_valid = (
            directness == "DIRECT" and third is False
            and _anchor_in_target(anchor_a, task["evidence_a"])
            and _anchor_in_target(anchor_b, task["evidence_b"])
            and subject is not None and (a_to_b is not None or b_to_a is not None)
            and reason is None
        )
    elif verdict == "REJECT_EDGE":
        fields_valid = (
            directness in DIRECTNESS - {"DIRECT"} and reason is not None
            and isinstance(third, bool) and (third is True) == (directness == "MEDIATED")
        )
    else:
        fields_valid = False
    result = {
        "anchor_a": anchor_a if _nonempty(anchor_a) else None,
        "anchor_b": anchor_b if _nonempty(anchor_b) else None,
        "shared_atomic_subject": subject,
        "contribution_a_to_b": a_to_b,
        "contribution_b_to_a": b_to_a,
        "directness": directness,
        "third_node_required": third,
        "verdict": verdict,
        "rejection_reason": reason,
        "confidence": confidence,
    }
    return result, (
        verdict in VERDICTS and directness in DIRECTNESS and fields_valid and confidence is not None
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Strictly validate direct type-free semantic edges")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/evidence_graph.yaml")
    parser.add_argument("--generation-tokens", type=int, default=330)
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
    system = (
        "Adversarially audit a screened scientific pair for a direct semantic edge. "
        "Reject shared-center, mediated, topical, reference-only, context-only, and redundant links. JSON only."
    )
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
            "keep": sum(row.get("verdict") == "KEEP_EDGE" and row["valid"] for row in predictions),
            "reject": sum(row.get("verdict") == "REJECT_EDGE" and row["valid"] for row in predictions),
            "directness_counts": {
                label: sum(row.get("directness") == label for row in predictions)
                for label in sorted(DIRECTNESS)
            },
            "complete": index + 1 == len(tasks),
        }
        write_json(status_path, status)
        print(json.dumps(status), flush=True)
        if monotonic() >= deadline:
            break


if __name__ == "__main__":
    main()
