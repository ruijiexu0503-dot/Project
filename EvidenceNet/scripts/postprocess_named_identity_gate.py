#!/usr/bin/env python3
"""Conservatively repair optional metadata in named-identity-gate outputs.

This pass never changes task_id, discovery_level, decision, basis, selected
evidence IDs, matched_claim, reason, or limitation.  It only removes optional
identity metadata when that metadata is both invalid and unnecessary for the
decision.  Every repaired payload is run through the original hard validator.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil

from evidence_graph.llm_client import extract_json
import run_named_identity_gate_verifier as gate
from run_node_context_edges import ROOT, jsonl, rows, write


SOURCE = ROOT / "EvidenceNet/output/named_identity_gate_verifier_v1_20261017"
OUT = ROOT / "EvidenceNet/output/named_identity_gate_verifier_v1_1_20261018"


def conflict_is_source_grounded(conflict: object, entry: dict) -> bool:
    keys = {"kind", "A_name", "A_evidence_id", "B_name", "B_evidence_id"}
    if not isinstance(conflict, dict) or set(conflict) != keys:
        return False
    try:
        for side in ("A", "B"):
            anchor = gate.original_anchor(entry, side, conflict[f"{side}_evidence_id"])
            if not gate.contains_surface(anchor, conflict[f"{side}_name"]):
                return False
    except (KeyError, ValueError):
        return False
    return True


def selected_has_original_on_both_sides(value: dict, entry: dict) -> bool:
    for side in ("A", "B"):
        evidence_ids = value.get(f"{side}_evidence_ids")
        if not isinstance(evidence_ids, list):
            return False
        if not any(
            entry["lookups"][side].get(evidence_id, {}).get("kind") in gate.ORIGINAL_KINDS
            for evidence_id in evidence_ids
        ):
            return False
    return True


def repair_optional_metadata(value: dict, entry: dict) -> tuple[dict, list[str]]:
    """Return a copied payload plus an audit trail of metadata-only repairs."""
    repaired = copy.deepcopy(value)
    changes: list[str] = []

    # Conflicts are explanatory metadata.  For rejected edges, an ungrounded
    # conflict must not turn a safe NO_LINK/UNCERTAIN decision into INVALID.
    if repaired.get("decision") in {"NO_LINK", "UNCERTAIN"}:
        conflicts = repaired.get("identity_conflicts")
        if isinstance(conflicts, list):
            grounded = [item for item in conflicts if conflict_is_source_grounded(item, entry)]
            if grounded != conflicts:
                repaired["identity_conflicts"] = grounded
                changes.append("dropped_ungrounded_conflict_metadata")

    # SAME_SPECIFIC_SUBJECT requires checked identity, so it is never repaired
    # this way.  Other evidence bases do not require shared_identity; remove an
    # invalid optional identity only when original selected evidence remains on
    # both endpoints.
    shared = repaired.get("shared_identity")
    if (
        shared is not None
        and repaired.get("decision") == "EVIDENCE_LINK"
        and repaired.get("basis") in {"CLAIM_CORRESPONDENCE", "DIRECT_COMPLEMENT"}
        and selected_has_original_on_both_sides(repaired, entry)
    ):
        probe = copy.deepcopy(repaired)
        probe["shared_identity"] = None
        try:
            gate.validate(probe, entry)
        except ValueError:
            pass
        else:
            try:
                gate.validate(repaired, entry)
            except ValueError as exc:
                if str(exc).startswith(("named identity", "shared identity")):
                    repaired = probe
                    changes.append("dropped_invalid_optional_shared_identity")

    return repaired, changes


def postprocess(source: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation").mkdir(exist_ok=True)
    entries = rows(source / "inputs.jsonl")
    predictions = rows(source / "predictions.jsonl")
    by_id = {entry["task"]["task_id"]: entry for entry in entries}
    repaired_predictions = []
    audit = []

    for prediction in predictions:
        updated = copy.deepcopy(prediction)
        if not prediction["valid"] and prediction.get("attempts"):
            raw = prediction["attempts"][-1].get("raw")
            changes: list[str] = []
            try:
                candidate = extract_json(raw)
                candidate, changes = repair_optional_metadata(candidate, by_id[prediction["task_id"]])
                result = gate.validate(candidate, by_id[prediction["task_id"]])
            except Exception as exc:
                audit.append({"task_id": prediction["task_id"], "repaired": False,
                              "changes": changes, "remaining_error": str(exc)})
            else:
                updated["valid"] = True
                updated["result"] = result
                updated["postprocess"] = {"source_attempt": len(prediction["attempts"]),
                                           "changes": changes}
                audit.append({"task_id": prediction["task_id"], "repaired": True,
                              "changes": changes})
        repaired_predictions.append(updated)

    for relative in ("inputs.jsonl", "protocol.json", "execution.json"):
        shutil.copy2(source / relative, out / relative)
    shutil.copy2(source / "evaluation/reference.jsonl", out / "evaluation/reference.jsonl")
    jsonl(out / "predictions.jsonl", repaired_predictions)
    jsonl(out / "postprocess_audit.jsonl", audit)
    write(out / "postprocess.json", {
        "source": str(source),
        "policy": [
            "never change the model's decision, basis, selected anchors, or explanation",
            "drop ungrounded optional conflict metadata only for NO_LINK/UNCERTAIN",
            "drop invalid optional shared identity only for non-identity evidence bases with original anchors on both sides",
            "rerun the original hard validator after every repair",
        ],
        "attempted": len(audit),
        "repaired": sum(item["repaired"] for item in audit),
    })
    return gate.report(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(postprocess(args.source.resolve(), args.output.resolve()), indent=2))
