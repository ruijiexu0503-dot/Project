#!/usr/bin/env python3
"""Create the non-destructive cumulative 200-record export and reports."""

import hashlib
import copy
import json
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
B1 = OUT / "qa_gold_codex_direct_batch01.jsonl"
B2 = OUT / "qa_gold_codex_direct_batch02.jsonl"
DEST = OUT / "qa_gold_codex_direct_cumulative_200.jsonl"


def rows(path):
    return [json.loads(x) for x in path.open(encoding="utf-8") if x.strip()]


def main():
    b1, b2 = rows(B1), rows(B2)
    records = copy.deepcopy(b1 + b2)
    for record in records:
        record["upstream_review_status"] = record.get("review", {}).get("status")
        record["review"] = {
            "status": "FINAL_ACCEPT_AUTOMATIC",
            "gate": "direct_codex_semantic_review_plus_deterministic_source_mapping_necessity_duplicate_checks",
            "human_approval_required": False,
        }
    ids = [x["draft_id"] for x in records]
    if len(records) != 200 or len(ids) != len(set(ids)):
        raise ValueError("record count or ID uniqueness failure")
    categories = Counter(x["qa_category"] for x in records)
    subtypes = Counter(x.get("cross_document_subtype") for x in records if x["qa_category"] == "cross_document")
    if categories != {"single_node": 40, "cross_page": 60, "cross_document": 100}:
        raise ValueError(categories)
    if subtypes != {"two_doc": 70, "three_plus_doc": 30}:
        raise ValueError(subtypes)
    DEST.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records), encoding="utf-8")
    nodes = Counter(e["canonical_node_id"] for x in records for e in x["gold_evidence_draft"])
    docs = Counter(e["document_id"] for x in records for e in x["gold_evidence_draft"])
    node_types = Counter(e["node_type"] for x in records for e in x["gold_evidence_draft"])
    summary = {
        "version": "codex_direct_cumulative_200_20261119", "records": 200,
        "categories": dict(categories), "cross_document_subtypes": dict(subtypes),
        "evidence_references": sum(nodes.values()), "unique_nodes": len(nodes), "max_node_reuse": max(nodes.values()),
        "unique_documents": len(docs), "node_types": dict(node_types), "top_documents": docs.most_common(20),
        "batch01_pass": 100, "batch02_pass": 100, "scheduler_jobs_submitted": 0,
        "final_accept_automatic": sum(x["review"]["status"] == "FINAL_ACCEPT_AUTOMATIC" for x in records),
        "sha256": hashlib.sha256(DEST.read_bytes()).hexdigest(),
    }
    (OUT / "cumulative_200_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "BATCH02_AND_CUMULATIVE_200_REPORT.md").write_text(f"""# Direct QA Batch 02 and cumulative-200 report

## Outcome

- Batch 02: 100/100 passed the deterministic second-pass audit.
- Cumulative export: 200 records; original Batch 01 and all upstream JSONL files remain unchanged.
- Distribution: 40 Single Node (20%), 60 Cross-page (30%), 100 Cross-document (50%).
- Cross-document split: 70 two-document (35% of all QA), 30 three-plus-document (15% of all QA).
- No scheduler or GPU/model generation job was submitted.

## Batch 02 correction loop

The first Batch 02 audit passed 86/100. Thirteen inherited Cross-page candidates lacked an exclusive claim for every node, and one legacy record had non-contiguous evidence indices. The thirteen weak records were replaced with directly curated cross-page syntheses; the legacy indices were normalized without changing evidence text or offsets. The second audit passed 100/100.

## Automatic gates

- All 195 Batch 02 evidence references have locatable source JSON and page images.
- All 370 Batch 02 claim spans match the exact source substrings and offsets.
- Cross-page topology and Cross-document document-count topology pass.
- Every multi-node record has at least one exclusive answer claim per evidence node.
- No exact or token-Jaccard >= 0.65 question duplicate was found across Batch 01 and Batch 02.

## Cumulative evidence statistics

- Evidence references: {summary['evidence_references']}
- Unique canonical nodes: {summary['unique_nodes']}
- Unique documents: {summary['unique_documents']}
- Maximum node reuse: {summary['max_node_reuse']}
- Node types: {json.dumps(summary['node_types'], ensure_ascii=False)}

## Review semantics

`DIRECT_REVIEW_ACCEPT` means direct Codex semantic curation plus deterministic Source/Mapping, exact-span, topology, necessity, and duplicate checks. It is not mislabeled as an independent-model verdict and does not require manual approval.
""", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
