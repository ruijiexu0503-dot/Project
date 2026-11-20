#!/usr/bin/env python3
"""Merge prior eligible QA and new Snapshot-D drafts without duplicates."""

import json
import re
from collections import Counter
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]


def rows(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def norm(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def category(item):
    return item["qa_category"] if item["qa_category"] != "cross_document" else f"cross_document_{item['cross_document_subtype']}"


def main():
    prior = rows(OUT / "qa_prior_61_for_cumulative_review.jsonl")
    fresh = rows(OUT / "qa_candidates_snapshot_D_deterministic_pass.jsonl")
    merged = []
    rejected = []
    questions = set()
    groups = set()
    for item in prior + fresh:
        question = norm(item["question"])
        group = tuple(sorted(evidence["canonical_node_id"] for evidence in item["gold_evidence_draft"]))
        reasons = []
        if question in questions:
            reasons.append("CUMULATIVE_QUESTION_DUPLICATE")
        if group in groups:
            reasons.append("CUMULATIVE_EVIDENCE_GROUP_DUPLICATE")
        if reasons:
            rejected.append({"draft_id": item["draft_id"], "reasons": reasons})
            continue
        questions.add(question)
        groups.add(group)
        merged.append(item)
    (OUT / "qa_cumulative_candidates_for_independent_review.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in merged), encoding="utf-8"
    )
    (OUT / "qa_cumulative_duplicate_rejects.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rejected), encoding="utf-8"
    )
    summary = {
        "prior_input": len(prior),
        "fresh_input": len(fresh),
        "cumulative_review_pool": len(merged),
        "duplicate_rejects": len(rejected),
        "by_category": dict(Counter(category(item) for item in merged)),
    }
    (OUT / "qa_cumulative_review_pool_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
