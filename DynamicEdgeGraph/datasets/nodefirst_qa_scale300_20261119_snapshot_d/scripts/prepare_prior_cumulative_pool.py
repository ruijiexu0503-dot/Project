#!/usr/bin/env python3
"""Normalize prior r3 Gold and self-audited candidates for cumulative review."""

import json
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
PRIOR = OUT.parent / "nodefirst_qa_scale300_20261117"


def rows(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalized_category(item):
    subtype = item.get("cross_document_subtype")
    if subtype == "two_documents":
        item["cross_document_subtype"] = "two_doc"
    elif subtype == "three_plus_documents":
        item["cross_document_subtype"] = "three_plus_doc"
    return item


def main():
    output = []
    for item in rows(PRIOR / "qa_gold_r3_status_normalized.jsonl"):
        item = normalized_category(item)
        if not item.get("generation_node_necessity"):
            item["generation_node_necessity"] = [
                {
                    "evidence_index": result["removed_evidence_index"],
                    "canonical_node_id": item["gold_evidence_draft"][result["removed_evidence_index"]]["canonical_node_id"],
                    "missing_claim_ids": result.get("missing_claim_ids", []),
                    "why_answer_incomplete_without_node": "Prior automatic node-deletion test found the answer incomplete without this node.",
                }
                for result in item["necessity_test"]["node_deletion_results"]
            ]
        item["cumulative_origin"] = "r3_gold_auto_accepted"
        item["prior_source_mapping_gate"] = "PASS"
        item["prior_independent_review_gate"] = "PASS"
        item["review"] = {"status": "PENDING_QWEN36_CUMULATIVE_REVIEW"}
        output.append(item)

    self_audit = {item["draft_id"]: item for item in rows(PRIOR / "qa_primary_assistant_self_audit_v1.jsonl")}
    mapping = {item["draft_id"]: item for item in rows(PRIOR / "qa_revised_and_integrative_source_mapping_audit.jsonl")}
    drafts = rows(PRIOR / "qa_candidate_drafts_snapshot_B_short_revised_v2.jsonl") + rows(PRIOR / "qa_integrative_candidates_curated_v1.jsonl")
    for item in drafts:
        audit = self_audit.get(item["draft_id"])
        source = mapping.get(item["draft_id"])
        if not audit or audit.get("verdict") != "KEEP":
            continue
        if not source or source.get("source_mapping_gate") != "PASS" or source.get("deterministic_claim_grounding_gate") != "PASS":
            continue
        item = normalized_category(item)
        item["cumulative_origin"] = "snapshot_b_primary_audit_keep"
        item["prior_source_mapping_gate"] = "PASS"
        item["prior_independent_review_gate"] = "PENDING_QWEN36_CUMULATIVE_REVIEW"
        item["prior_primary_audit"] = audit
        item["review"] = {"status": "PENDING_QWEN36_CUMULATIVE_REVIEW"}
        output.append(item)

    ids = [item["draft_id"] for item in output]
    if len(ids) != len(set(ids)) or len(output) != 61:
        raise RuntimeError(f"Expected 61 unique prior candidates, got {len(output)}")
    (OUT / "qa_prior_61_for_cumulative_review.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in output), encoding="utf-8"
    )
    counts = Counter(
        item["qa_category"] if item["qa_category"] != "cross_document" else f"cross_document_{item['cross_document_subtype']}"
        for item in output
    )
    summary = {"prior_candidates": len(output), "by_category": dict(counts), "all_source_mapping_pass": True}
    (OUT / "qa_prior_61_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
