#!/usr/bin/env python3
"""Combine Snapshot-D generation shards and apply deterministic grounding gates."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]


def rows(path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def normalized(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def validate(draft, node_ids):
    failures = []
    evidence = draft.get("gold_evidence_draft", [])
    claims = draft.get("answer_claims", [])
    necessity = draft.get("generation_node_necessity", [])
    if not draft.get("question") or not draft.get("gold_answer_draft"):
        failures.append("EMPTY_QUESTION_OR_ANSWER")
    ids = [item.get("canonical_node_id") for item in evidence]
    if not ids or len(ids) != len(set(ids)) or any(node_id not in node_ids for node_id in ids):
        failures.append("CANONICAL_NODE_MAPPING_FAIL")
    documents = {item.get("document_id") for item in evidence}
    pages = {(item.get("document_id"), item.get("page_id")) for item in evidence}
    category = draft.get("qa_category")
    subtype = draft.get("cross_document_subtype")
    if category == "single_node" and len(evidence) != 1:
        failures.append("CATEGORY_MISMATCH")
    elif category == "cross_page" and not (len(documents) == 1 and len(pages) >= 2):
        failures.append("CATEGORY_MISMATCH")
    elif category == "cross_document":
        if subtype == "two_doc" and len(documents) != 2:
            failures.append("CATEGORY_MISMATCH")
        elif subtype == "three_plus_doc" and len(documents) < 3:
            failures.append("CATEGORY_MISMATCH")
    covered = set()
    claim_ids = set()
    for claim in claims:
        claim_id = claim.get("claim_id")
        claim_ids.add(claim_id)
        support = set(claim.get("supporting_evidence_indices", []))
        spans = claim.get("evidence_spans", [])
        span_support = set()
        if not claim.get("claim_text") or not support or not spans:
            failures.append("EMPTY_CLAIM_OR_SUPPORT")
            continue
        for span in spans:
            index = span.get("evidence_index")
            if not isinstance(index, int) or not 0 <= index < len(evidence):
                failures.append("SPAN_INDEX_INVALID")
                continue
            text = span.get("text", "")
            source = evidence[index].get("evidence_text", "")
            start = span.get("char_start")
            end = span.get("char_end")
            if not text or source.find(text) != start or end != start + len(text):
                failures.append("NON_LITERAL_OR_OFFSET_SPAN")
            span_support.add(index)
            covered.add(index)
        if not support <= span_support:
            failures.append("CLAIM_SUPPORT_WITHOUT_SPAN")
    if covered != set(range(len(evidence))):
        failures.append("NOT_ALL_NODES_CLAIM_GROUNDED")
    necessity_indices = {item.get("evidence_index") for item in necessity}
    if necessity_indices != set(range(len(evidence))):
        failures.append("NODE_NECESSITY_COVERAGE_FAIL")
    for item in necessity:
        if not set(item.get("missing_claim_ids", [])) <= claim_ids or not item.get("why_answer_incomplete_without_node"):
            failures.append("NODE_NECESSITY_CONTENT_FAIL")
    return sorted(set(failures))


def main():
    node_ids = {item["canonical_node_id"] for item in rows(OUT / "snapshot_D_formal_canonical_nodes.jsonl")}
    shard_paths = sorted(OUT.glob("qa_candidate_drafts_snapshot_D_shard_*.jsonl"))
    if not shard_paths:
        raise RuntimeError("No Snapshot-D generation shards found")
    candidates = [item for path in shard_paths for item in rows(path)]
    seen_drafts = set()
    seen_questions = set()
    seen_groups = set()
    accepted = []
    rejected = []
    for draft in candidates:
        failures = validate(draft, node_ids)
        question_key = normalized(draft.get("question", ""))
        group_key = tuple(sorted(item["canonical_node_id"] for item in draft.get("gold_evidence_draft", [])))
        if draft.get("draft_id") in seen_drafts:
            failures.append("DUPLICATE_DRAFT_ID")
        if question_key in seen_questions:
            failures.append("EXACT_NORMALIZED_QUESTION_DUPLICATE")
        if group_key in seen_groups:
            failures.append("DUPLICATE_EVIDENCE_GROUP")
        seen_drafts.add(draft.get("draft_id"))
        seen_questions.add(question_key)
        seen_groups.add(group_key)
        record = {**draft, "deterministic_generation_gate": {"pass": not failures, "failures": sorted(set(failures))}}
        (accepted if not failures else rejected).append(record)
    (OUT / "qa_candidates_snapshot_D_deterministic_pass.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in accepted), encoding="utf-8"
    )
    (OUT / "qa_candidates_snapshot_D_deterministic_reject.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rejected), encoding="utf-8"
    )
    failures = [failure for item in rejected for failure in item["deterministic_generation_gate"]["failures"]]
    summary = {
        "shards": len(shard_paths),
        "generated_candidates": len(candidates),
        "deterministic_pass": len(accepted),
        "deterministic_reject": len(rejected),
        "pass_by_category": dict(Counter(
            item["qa_category"] if item["qa_category"] != "cross_document" else f"cross_document_{item['cross_document_subtype']}"
            for item in accepted
        )),
        "reject_reasons": dict(Counter(failures)),
    }
    (OUT / "generation_snapshot_D_combined_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
