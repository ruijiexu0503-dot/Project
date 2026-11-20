#!/usr/bin/env python3
"""Deterministic audit of direct Batch 02, including cross-batch duplicates."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve()
OUT = HERE.parents[1]
SNAPSHOT = OUT.parent / "nodefirst_qa_scale300_20261119_snapshot_d"
DATA = OUT / "qa_gold_codex_direct_batch02.jsonl"
PRIOR = OUT / "qa_gold_codex_direct_batch01.jsonl"
NODES = SNAPSHOT / "snapshot_D_formal_canonical_nodes.jsonl"

STOP = set("the a an in on of and to is are how what which between does do from with their for according".split())


def rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOP


def main() -> None:
    records, prior = rows(DATA), rows(PRIOR)
    node_map = {item["canonical_node_id"]: item for item in rows(NODES)}
    audits, failures_all = [], []
    counters = Counter()
    node_reuse, document_use = Counter(), Counter()
    for record in records:
        failures = []
        evidence, claims = record.get("gold_evidence_draft", []), record.get("answer_claims", [])
        docs = {item.get("document_id") for item in evidence}
        pages = {(item.get("document_id"), item.get("page_number")) for item in evidence}
        category = record.get("qa_category")
        subtype = record.get("cross_document_subtype")
        if category == "single_node" and len(evidence) != 1:
            failures.append("SINGLE_NODE_CARDINALITY")
        if category == "cross_page" and (len(docs) != 1 or len(pages) < 2):
            failures.append("CROSS_PAGE_TOPOLOGY")
        if category == "cross_document":
            expected = 2 if subtype == "two_doc" else 3
            if len(docs) < expected:
                failures.append("CROSS_DOCUMENT_TOPOLOGY")
        exclusive = set()
        for i, item in enumerate(evidence):
            if item.get("evidence_index") != i:
                failures.append("EVIDENCE_INDEX_NONCONTIGUOUS")
            node_id = item.get("canonical_node_id")
            node_reuse[node_id] += 1
            document_use[item.get("document_id")] += 1
            node = node_map.get(node_id)
            if node is None:
                counters["legacy_refs"] += 1
            else:
                counters["snapshot_refs"] += 1
                if (node["document_id"], node["page_number"], node["content_text"].strip()) != (
                    item.get("document_id"), item.get("page_number"), (item.get("evidence_text") or "").strip()
                ):
                    failures.append("SNAPSHOT_NODE_MISMATCH")
            if item.get("source_json") and os.path.isfile(item["source_json"]):
                counters["source_json_exists"] += 1
            else:
                failures.append("SOURCE_JSON_MISSING")
            if item.get("page_image") and os.path.isfile(item["page_image"]):
                counters["page_image_exists"] += 1
            else:
                failures.append("PAGE_IMAGE_MISSING")
        for claim in claims:
            support = set(claim.get("supporting_evidence_indices", []))
            if len(support) == 1:
                exclusive.update(support)
            if not support or not claim.get("claim_text"):
                failures.append("EMPTY_CLAIM_SUPPORT")
            for span in claim.get("evidence_spans", []):
                idx = span.get("evidence_index")
                if not isinstance(idx, int) or not 0 <= idx < len(evidence):
                    failures.append("SPAN_INDEX_INVALID")
                    continue
                source = evidence[idx].get("evidence_text", "")
                start, end = span.get("char_start"), span.get("char_end")
                if not isinstance(start, int) or not isinstance(end, int) or source[start:end] != span.get("text"):
                    failures.append("SPAN_OFFSET_INVALID")
                else:
                    counters["exact_claim_spans"] += 1
        if len(evidence) > 1 and exclusive != set(range(len(evidence))):
            failures.append("NODE_WITHOUT_EXCLUSIVE_CLAIM")
        if re.search(r"\b(?:real|short)_\d+", record.get("question", ""), re.I):
            failures.append("INTERNAL_DOCUMENT_ID_IN_QUESTION")
        if record.get("direct_codex_review", {}).get("status") != "DIRECT_REVIEW_ACCEPT":
            failures.append("DIRECT_REVIEW_STATUS_MISSING")
        audit = {
            "draft_id": record["draft_id"], "category": category, "subtype": subtype,
            "document_count": len(docs), "page_count": len(pages),
            "failures": sorted(set(failures)), "audit_status": "PASS" if not failures else "FAIL",
        }
        audits.append(audit)
        failures_all.extend((record["draft_id"], item) for item in audit["failures"])

    if Counter(item["qa_category"] for item in records) != {"single_node": 20, "cross_page": 30, "cross_document": 50}:
        failures_all.append(("BATCH", "CATEGORY_QUOTA"))
    if Counter(item.get("cross_document_subtype") for item in records if item["qa_category"] == "cross_document") != {"two_doc": 35, "three_plus_doc": 15}:
        failures_all.append(("BATCH", "SUBTYPE_QUOTA"))
    exact = Counter(normalized(item["question"]) for item in prior + records)
    exact_dup = {key: value for key, value in exact.items() if value > 1}
    near = []
    for left, right in itertools.combinations(prior + records, 2):
        if left in prior and right in prior:
            continue
        a, b = tokens(left["question"]), tokens(right["question"])
        score = len(a & b) / max(1, len(a | b))
        if score >= 0.65:
            near.append((left["draft_id"], right["draft_id"], round(score, 4)))
    if exact_dup:
        failures_all.append(("BATCH", f"EXACT_DUPLICATES:{len(exact_dup)}"))
    if near:
        failures_all.append(("BATCH", f"NEAR_DUPLICATES:{len(near)}"))

    summary = {
        "audit_version": "codex_direct_batch02_second_pass_20261119",
        "audit_mode": "direct_semantic_curation_plus_deterministic_checks",
        "records": len(records), "passed": sum(x["audit_status"] == "PASS" for x in audits),
        "failed": sum(x["audit_status"] != "PASS" for x in audits),
        "batch_failures": failures_all,
        "categories": dict(Counter(x["qa_category"] for x in records)),
        "cross_document_subtypes": dict(Counter(x.get("cross_document_subtype") for x in records if x["qa_category"] == "cross_document")),
        "evidence_references": sum(len(x["gold_evidence_draft"]) for x in records),
        "unique_nodes": len(node_reuse), "max_node_reuse": max(node_reuse.values()),
        "snapshot_d_references": counters["snapshot_refs"], "frozen_legacy_references": counters["legacy_refs"],
        "source_json_exists": counters["source_json_exists"], "page_image_exists": counters["page_image_exists"],
        "exact_claim_spans": counters["exact_claim_spans"],
        "exact_question_duplicates_across_batches": len(exact_dup),
        "near_duplicate_pairs_across_batches_jaccard_ge_0_65": near,
        "top_documents": document_use.most_common(15), "scheduler_jobs_submitted": 0,
        "data_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
    }
    (OUT / "batch02_direct_audit.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in audits), encoding="utf-8")
    (OUT / "batch02_audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures_all:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
