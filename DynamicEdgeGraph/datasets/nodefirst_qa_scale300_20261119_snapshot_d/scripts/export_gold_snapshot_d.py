#!/usr/bin/env python3
"""Apply final automatic gates and export a diverse 60/90/105/45 Gold set."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


OUT = Path(__file__).resolve().parents[1]
TARGETS = {
    "single_node": 60,
    "cross_page": 90,
    "cross_document_two_doc": 105,
    "cross_document_three_plus_doc": 45,
}


def rows(path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def category(item):
    if item["qa_category"] != "cross_document":
        return item["qa_category"]
    return f"cross_document_{item['cross_document_subtype']}"


def norm(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def main():
    candidates = rows(OUT / "qa_cumulative_candidates_for_independent_review.jsonl")
    review_paths = sorted(OUT.glob("qa_independent_reviews_snapshot_D_shard_*.jsonl"))
    reviews = {item["draft_id"]: item for path in review_paths for item in rows(path)}
    canonical = {item["canonical_node_id"]: item for item in rows(OUT / "snapshot_D_formal_canonical_nodes.jsonl")}
    eligible = []
    rejected = []
    for draft in candidates:
        failures = []
        review = reviews.get(draft["draft_id"])
        if review is None:
            failures.append("INDEPENDENT_REVIEW_MISSING")
        elif not review.get("valid_review"):
            failures.append("INDEPENDENT_REVIEW_INVALID")
        elif not review.get("semantic_pass"):
            failures.append("INDEPENDENT_REVIEW_NOT_KEEP")
        for evidence in draft["gold_evidence_draft"]:
            node = canonical.get(evidence["canonical_node_id"])
            if node is None and draft.get("prior_source_mapping_gate") == "PASS":
                continue
            if node is None:
                failures.append("GOLD_NODE_ID_NOT_LOCATABLE")
                continue
            if node["document_id"] != evidence["document_id"] or node["page_id"] != evidence["page_id"]:
                failures.append("NODE_DOCUMENT_PAGE_MISMATCH")
            if node.get("source_integrity_status") != "SOURCE_INTEGRITY_PASS":
                failures.append("SOURCE_INTEGRITY_FAIL")
            if node.get("mapping_status") != "MAPPED_VERIFIED_AUTOMATIC":
                failures.append("CANONICAL_MAPPING_FAIL")
            if not Path(node["page_image"]).is_file() or not Path(node["source_json"]).is_file():
                failures.append("SOURCE_TRACE_NOT_LOCATABLE")
        result = {
            **draft,
            "independent_review": review,
            "final_automatic_gate": {"pass": not failures, "failures": sorted(set(failures))},
        }
        (eligible if not failures else rejected).append(result)

    # Deterministic diversity-first ranking. Prefer multimodal evidence, then
    # underused documents, and keep ordering stable by content hash.
    selected = []
    selected_ids = set()
    doc_use = Counter()
    group_use = Counter()
    seen_questions = set()
    for target_category, target in TARGETS.items():
        pool = [item for item in eligible if category(item) == target_category]
        while len([item for item in selected if category(item) == target_category]) < target:
            choices = []
            for item in pool:
                if item["draft_id"] in selected_ids or norm(item["question"]) in seen_questions:
                    continue
                documents = tuple(sorted({evidence["document_id"] for evidence in item["gold_evidence_draft"]}))
                if any(doc_use[document] >= 30 for document in documents):
                    continue
                if target_category.startswith("cross_document") and group_use[documents] >= 8:
                    continue
                multimodal = sum(evidence["node_type"] in {"TABLE", "IMAGE", "COMPOSITE", "CAPTION"} for evidence in item["gold_evidence_draft"])
                score = (
                    multimodal,
                    -max((doc_use[document] for document in documents), default=0),
                    -sum(doc_use[document] for document in documents),
                    hashlib.sha256(item["draft_id"].encode()).hexdigest(),
                )
                choices.append((score, item, documents))
            if not choices:
                break
            _, chosen, documents = max(choices, key=lambda value: value[0])
            selected.append(chosen)
            selected_ids.add(chosen["draft_id"])
            seen_questions.add(norm(chosen["question"]))
            for document in documents:
                doc_use[document] += 1
            if target_category.startswith("cross_document"):
                group_use[documents] += 1

    selected_counts = Counter(category(item) for item in selected)
    complete = all(selected_counts[key] == value for key, value in TARGETS.items())
    accepted_path = OUT / "qa_gold_snapshot_D_auto_accepted_pool.jsonl"
    accepted_path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in eligible), encoding="utf-8")
    (OUT / "qa_gold_snapshot_D_final_300.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in selected) if complete else "", encoding="utf-8"
    )
    (OUT / "qa_gold_snapshot_D_final_gate_rejects.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in rejected), encoding="utf-8"
    )
    summary = {
        "target": TARGETS,
        "independent_review_files": len(review_paths),
        "candidates": len(candidates),
        "automatic_gate_pass": len(eligible),
        "automatic_gate_reject": len(rejected),
        "selected": len(selected),
        "selected_by_category": dict(selected_counts),
        "shortfall": {key: TARGETS[key] - selected_counts[key] for key in TARGETS if selected_counts[key] < TARGETS[key]},
        "gold_export_complete": complete,
        "gold_export_policy": "EXPORT_ONLY_IF_EXACT_60_90_105_45_QUOTAS_MET",
        "documents_used": len(doc_use),
        "max_document_use": max(doc_use.values(), default=0),
        "multimodal_qa": sum(any(evidence["node_type"] in {"TABLE", "IMAGE", "COMPOSITE", "CAPTION"} for evidence in item["gold_evidence_draft"]) for item in selected),
    }
    (OUT / "qa_gold_snapshot_D_export_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
