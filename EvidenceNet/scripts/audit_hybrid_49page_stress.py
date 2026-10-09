#!/usr/bin/env python3
"""Aggregate 49-page shadow results and surface candidate semantic failures."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREPARED = ROOT / "EvidenceNet/output/hybrid_49page_stress_prepared_20261007"
RUN = ROOT / "EvidenceNet/output/hybrid_49page_stress_run_20261007"
REVIEW = ROOT / "EvidenceNet/config/reviews/node_generation/hybrid_49page_stress_review_20261007.json"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def text_of(atom):
    return "\n".join(f["text"] for f in atom["text_fragments"])


def inspect_page(source: dict, batch: int, run: Path, prepared: Path):
    task = source["task"]
    rep = read(prepared / task / "input_representation.json")
    atoms = {a["atom_id"]: a for a in rep["atoms"]}
    base = run / f"batch_{batch}" / "embedding_geometry" / task
    hybrid = run / f"batch_{batch}" / "hybrid" / task
    result = {"task": task, "batch": batch, "source": source,
              "status": "complete" if (hybrid / "run_summary.json").exists() else "incomplete"}
    if result["status"] != "complete":
        result["files_present"] = {"baseline_summary": (base / "run_summary.json").exists(),
                                   "candidates": (hybrid / "candidates.json").exists(),
                                   "decisions": (hybrid / "decisions.json").exists()}
        return result
    bsum, hsum = read(base / "run_summary.json"), read(hybrid / "run_summary.json")
    bnodes, hnodes = jsonl(base / "evidence_nodes.jsonl"), jsonl(hybrid / "evidence_nodes.jsonl")
    decision, candidate = read(hybrid / "decisions.json"), read(hybrid / "candidates.json")
    sidecar = read(hybrid / "structural_and_unresolved.json")
    owned = {aid for n in hnodes for aid in n["source_atom_ids"]}
    b_owned = {aid for n in bnodes for aid in n["source_atom_ids"]}
    table_ids = [a["atom_id"] for a in rep["atoms"] if a["atom_type"] == "table"]
    caption_ids = [a["atom_id"] for a in rep["atoms"] if a["atom_type"] == "caption"]
    pair_by_id = {p["pair_id"]: p for p in candidate["pairs"]}
    joins = []
    for choice in decision.get("pairs", []):
        if choice.get("decision") != "CONTINUATION":
            continue
        pair = pair_by_id.get(choice.get("pair_id"))
        if pair is None:
            continue
        left, right = atoms[pair["left_atom_id"]], atoms[pair["right_atom_id"]]
        left_text, right_text = text_of(left).strip(), text_of(right).strip()
        lo, hi = sorted((left.get("deepseek_order", 0), right.get("deepseek_order", 0)))
        between = [a["atom_id"] for a in rep["atoms"]
                   if lo < a.get("deepseek_order", -1) < hi
                   and a["atom_type"] in {"heading", "furniture", "table", "caption"}]
        flags = []
        if left_text.endswith(":") and right_text.startswith(("•", "- ", "1.", "(a)")):
            flags.append("colon_to_list")
        if left_text.endswith((".", "!", "?", ";")):
            flags.append("left_ends_sentence")
        if between:
            flags.append("crosses_non_body_atom")
            if any(atoms[aid]["atom_type"] == "table" for aid in between):
                flags.append("crosses_table_atom")
        if (left_text.endswith("$$") and right_text[:1].isupper()
                and re.search(r"\.(?:\\quad.*)?\$\$$", left_text[-100:])):
            flags.append("formula_period_to_new_sentence")
        joins.append({"left_atom_id": left["atom_id"], "right_atom_id": right["atom_id"],
                      "left_tail": left_text[-100:], "right_head": right_text[:100],
                      "intervening_atoms": between, "review_flags": flags,
                      "reason": choice.get("reason", "")})
    role_changes = [{"atom_id": r["atom_id"], "decision": r["decision"],
                     "text": text_of(atoms[r["atom_id"]])[:150]}
                    for r in decision.get("roles", []) if r["decision"] != "BODY"]
    result.update({"baseline_source_coverage": bsum["valid_coverage"],
                   "hybrid_source_coverage": hsum["valid_coverage"],
                   "qwen_decision_valid": decision["valid"],
                   "candidate_pairs": len(candidate["pairs"]),
                   "candidate_roles": len(candidate["roles"]),
                   "baseline_nodes": len(bnodes), "hybrid_nodes": len(hnodes),
                   "baseline_multi_atom_nodes": sum(len(n["source_atom_ids"]) > 1 for n in bnodes),
                   "hybrid_multi_atom_nodes": sum(len(n["source_atom_ids"]) > 1 for n in hnodes),
                   "hybrid_joins": joins, "hybrid_role_changes": role_changes,
                   "table_atom_ids": table_ids,
                   "table_atoms_outside_evidence": [aid for aid in table_ids if aid not in owned],
                   "caption_atom_ids": caption_ids,
                   "unassigned_caption_ids": sidecar["unassigned_caption_atom_ids"],
                   "caption_assignments": hsum["caption_assignments"],
                   "parser_structural_atoms_in_evidence": [aid for aid in owned
                                                           if atoms[aid]["atom_type"] in {"heading", "furniture", "foot", "header"}],
                   "text_atoms_newly_removed": sorted(b_owned - owned),
                   "visuals": len(rep["visual_bundles"]),
                   "visual_nodes": sum(bool(n["source_visual_bundle_ids"]) for n in hnodes),
                   "native_components": sum(len(v.get("native_components", []))
                                            for v in rep["visual_bundles"]),
                   "source_empty_text": not any(a["atom_type"] == "text" for a in rep["atoms"]),
                   "sidecar_structural_atoms": sidecar["structural_atom_ids"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=PREPARED)
    parser.add_argument("--run", type=Path, default=RUN)
    args = parser.parse_args()
    manifest = read(args.prepared / "manifest.json")
    batch_by_task = {task: i for i, batch in enumerate(manifest["batches"]) for task in batch}
    pages = [inspect_page(p, batch_by_task[p["task"]], args.run, args.prepared)
             for p in manifest["pages"]]
    complete = [p for p in pages if p["status"] == "complete"]
    flagged_joins = [{"task": p["task"], **j} for p in complete for j in p["hybrid_joins"]
                     if j["review_flags"]]
    totals = {"pages_expected": len(pages), "pages_complete": len(complete),
              "pages_incomplete": len(pages) - len(complete),
              "baseline_coverage_passed": sum(p["baseline_source_coverage"] for p in complete),
              "hybrid_coverage_passed": sum(p["hybrid_source_coverage"] for p in complete),
              "valid_qwen_decisions": sum(p["qwen_decision_valid"] for p in complete),
              "candidate_pairs": sum(p["candidate_pairs"] for p in complete),
              "candidate_roles": sum(p["candidate_roles"] for p in complete),
              "applied_joins": sum(len(p["hybrid_joins"]) for p in complete),
              "baseline_multi_atom_nodes": sum(p["baseline_multi_atom_nodes"] for p in complete),
              "hybrid_multi_atom_nodes": sum(p["hybrid_multi_atom_nodes"] for p in complete),
              "flagged_joins": len(flagged_joins),
              "table_atoms_outside_evidence": sum(len(p["table_atoms_outside_evidence"]) for p in complete),
              "table_atoms": sum(len(p["table_atom_ids"]) for p in complete),
              "unassigned_captions": sum(len(p["unassigned_caption_ids"]) for p in complete),
              "caption_atoms": sum(len(p["caption_atom_ids"]) for p in complete),
              "visual_nodes": sum(p["visual_nodes"] for p in complete),
              "visual_bundles": sum(p["visuals"] for p in complete),
              "native_components": sum(p["native_components"] for p in complete),
              "source_empty_text_pages": sum(p["source_empty_text"] for p in complete),
              "prior_relation_stage_failed_pages": sum(p["source"]["prior_relation_stage_failed"] for p in complete)}
    review_summary = None
    if len(complete) == len(pages) and REVIEW.exists():
        review = read(REVIEW)
        wrong = {tuple(row) for row in review["incorrect_joins"]}
        correct = {tuple(row) for row in review["correct_flagged_continuations"]}
        flagged = {(j["task"], j["left_atom_id"], j["right_atom_id"]) for j in flagged_joins}
        if wrong & correct or wrong | correct != flagged:
            raise ValueError("Manual review and heuristic-flagged join IDs disagree")
        review_summary = {"reviewed_flagged_joins": len(flagged),
                          "confirmed_incorrect_under_same_sentence_policy": len(wrong),
                          "confirmed_correct_despite_flag": len(correct),
                          "other_applied_joins_not_exhaustively_labeled": totals["applied_joins"] - len(flagged),
                          "independent_human_ground_truth": review["independent_human_ground_truth"]}
    output = {"totals": totals, "flagged_join_review": review_summary,
              "flagged_joins": flagged_joins,
              "pages": pages, "production_modified": False,
              "note": "Heuristic flags are review leads, not ground-truth precision estimates."}
    args.run.mkdir(parents=True, exist_ok=True)
    (args.run / "stress_audit.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"totals": totals, "flagged_join_review": review_summary},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
