#!/usr/bin/env python3
"""Deterministic second-pass audit for the direct Codex batch."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import statistics
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve()
OUT = HERE.parents[1]
SNAPSHOT = OUT.parent / "nodefirst_qa_scale300_20261119_snapshot_d"
DATA = OUT / "qa_gold_codex_direct_batch01.jsonl"
NODES = SNAPSHOT / "snapshot_D_formal_canonical_nodes.jsonl"


def rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


STOP = set("the a an in on of and to is are how what which between does do from with their for according".split())


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOP


def main() -> None:
    records = rows(DATA)
    node_map = {item["canonical_node_id"]: item for item in rows(NODES)}
    audits = []
    all_failures = []
    source_json_exists = page_image_exists = snapshot_refs = legacy_refs = exact_spans = 0
    for record in records:
        failures = []
        evidence = record.get("gold_evidence_draft", [])
        claims = record.get("answer_claims", [])
        exclusive = set()
        for item in evidence:
            node_id = item.get("canonical_node_id")
            node = node_map.get(node_id)
            if node is None:
                legacy_refs += 1
                if not item.get("source_json"):
                    failures.append("LEGACY_SOURCE_UNLOCATABLE")
            else:
                snapshot_refs += 1
                if (node["document_id"], node["page_number"], node["content_text"].strip()) != (
                    item.get("document_id"), item.get("page_number"), (item.get("evidence_text") or "").strip()
                ):
                    failures.append("SNAPSHOT_NODE_MISMATCH")
            if item.get("source_json") and os.path.isfile(item["source_json"]):
                source_json_exists += 1
            else:
                failures.append("SOURCE_JSON_MISSING")
            if item.get("page_image") and os.path.isfile(item["page_image"]):
                page_image_exists += 1
            else:
                failures.append("PAGE_IMAGE_MISSING")
        for claim in claims:
            support = set(claim.get("supporting_evidence_indices", []))
            if len(support) == 1:
                exclusive.update(support)
            if not support or not claim.get("claim_text"):
                failures.append("EMPTY_CLAIM_SUPPORT")
            for span in claim.get("evidence_spans", []):
                index = span.get("evidence_index")
                if not isinstance(index, int) or not 0 <= index < len(evidence):
                    failures.append("SPAN_INDEX_INVALID")
                    continue
                source = evidence[index].get("evidence_text", "")
                start, end = span.get("char_start"), span.get("char_end")
                if not isinstance(start, int) or not isinstance(end, int) or source[start:end] != span.get("text"):
                    failures.append("SPAN_OFFSET_INVALID")
                else:
                    exact_spans += 1
        if len(evidence) > 1 and exclusive != set(range(len(evidence))):
            failures.append("NODE_WITHOUT_EXCLUSIVE_CLAIM")
        if re.search(r"\b(?:real|short)_\d+", record.get("question", ""), re.I):
            failures.append("INTERNAL_DOCUMENT_ID_IN_QUESTION")
        if re.search(r"\b(?:implied|not specified|appears to)\b", record.get("gold_answer_draft", ""), re.I):
            failures.append("SPECULATIVE_ANSWER_WORDING")
        if record.get("direct_codex_review", {}).get("status") != "DIRECT_REVIEW_ACCEPT":
            failures.append("DIRECT_REVIEW_STATUS_MISSING")
        audit = {
            "draft_id": record["draft_id"],
            "category": record["qa_category"],
            "subtype": record.get("cross_document_subtype"),
            "source_mapping_pass": not any("SOURCE" in item or "NODE_MISMATCH" in item for item in failures),
            "claim_span_pass": not any("SPAN" in item or "CLAIM" in item for item in failures),
            "exclusive_node_contribution_pass": "NODE_WITHOUT_EXCLUSIVE_CLAIM" not in failures,
            "question_form_pass": "INTERNAL_DOCUMENT_ID_IN_QUESTION" not in failures,
            "answer_wording_pass": "SPECULATIVE_ANSWER_WORDING" not in failures,
            "direct_semantic_review_pass": record.get("direct_codex_review", {}).get("status") == "DIRECT_REVIEW_ACCEPT",
            "failures": sorted(set(failures)),
            "audit_status": "PASS" if not failures else "FAIL",
        }
        audits.append(audit)
        all_failures.extend((record["draft_id"], item) for item in audit["failures"])

    exact_questions = Counter(normalized(item["question"]) for item in records)
    exact_duplicates = {key: count for key, count in exact_questions.items() if count > 1}
    near = []
    for left, right in itertools.combinations(records, 2):
        a, b = tokens(left["question"]), tokens(right["question"])
        similarity = len(a & b) / max(1, len(a | b))
        if similarity >= 0.65:
            near.append({
                "left": left["draft_id"], "right": right["draft_id"],
                "token_jaccard": round(similarity, 4),
            })
    if exact_duplicates or near:
        raise ValueError(f"duplicate audit failed: exact={exact_duplicates}, near={near}")
    if all_failures:
        raise ValueError(f"record audit failed: {all_failures}")

    evidence_refs = sum(len(item["gold_evidence_draft"]) for item in records)
    unique_nodes = {item["canonical_node_id"] for record in records for item in record["gold_evidence_draft"]}
    node_reuse = Counter(item["canonical_node_id"] for record in records for item in record["gold_evidence_draft"])
    document_use = Counter(item["document_id"] for record in records for item in record["gold_evidence_draft"])
    answer_lengths = [len(item["gold_answer_draft"].split()) for item in records]
    summary = {
        "audit_version": "codex_direct_batch01_second_pass_20261119",
        "audit_mode": "direct_codex_semantic_review_plus_deterministic_checks",
        "records": len(records),
        "passed": sum(item["audit_status"] == "PASS" for item in audits),
        "failed": sum(item["audit_status"] != "PASS" for item in audits),
        "categories": dict(Counter(item["qa_category"] for item in records)),
        "cross_document_subtypes": dict(Counter(
            item.get("cross_document_subtype") for item in records if item["qa_category"] == "cross_document"
        )),
        "evidence_references": evidence_refs,
        "unique_nodes": len(unique_nodes),
        "snapshot_d_references": snapshot_refs,
        "frozen_legacy_references": legacy_refs,
        "source_json_exists": source_json_exists,
        "page_image_exists": page_image_exists,
        "exact_claim_spans": exact_spans,
        "node_types": dict(Counter(
            item["node_type"] for record in records for item in record["gold_evidence_draft"]
        )),
        "max_node_reuse": max(node_reuse.values()),
        "top_documents": document_use.most_common(15),
        "answer_words": {
            "min": min(answer_lengths),
            "median": statistics.median(answer_lengths),
            "max": max(answer_lengths),
        },
        "exact_question_duplicates": 0,
        "near_duplicate_pairs_jaccard_ge_0_65": 0,
        "scheduler_jobs_submitted": 0,
        "data_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
    }
    (OUT / "batch01_direct_audit.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in audits), encoding="utf-8"
    )
    (OUT / "batch01_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
