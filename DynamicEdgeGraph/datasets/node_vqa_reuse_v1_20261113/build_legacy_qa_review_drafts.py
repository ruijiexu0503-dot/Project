#!/usr/bin/env python3
"""Create conservative, source-node-bound review candidates for legacy assets.

This never edits the frozen corpus.  It intentionally emits only one candidate
per legacy document with preserved text; image-only documents are reported,
not guessed.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "qa_review_drafts_v1"


def score(node):
    text = node.get("content_text", "").strip()
    words = re.findall(r"[A-Za-z]{3,}", text.lower())
    # Favour a self-contained paragraph but avoid boilerplate-sized pages.
    return min(len(words), 300) + len(set(words)) * 0.45 - abs(len(text) - 950) * 0.04


def main():
    docs = [json.loads(x) for x in (HERE / "documents.jsonl").read_text().splitlines() if x]
    nodes = [json.loads(x) for x in (HERE / "nodes.jsonl").read_text().splitlines() if x]
    pages = [json.loads(x) for x in (HERE / "pages.jsonl").read_text().splitlines() if x]
    page_image = {(p["doc_id"], p["page_id"]): p.get("image_path") for p in pages}
    by_doc = defaultdict(list)
    for node in nodes:
        if len(node.get("content_text", "").strip()) >= 120:
            by_doc[node["doc_id"]].append(node)

    records, skipped = [], []
    for doc in docs:
        candidates = by_doc[doc["doc_id"]]
        if not candidates:
            skipped.append({"doc_id": doc["doc_id"], "reason": "no_preserved_text_node; visual-only QA requires image review"})
            continue
        node = max(candidates, key=score)
        text = " ".join(node["content_text"].split())
        records.append({
            "draft_id": f"legacy_qa_review_v1::{len(records)+1:03d}",
            "review_status": "NEEDS_HUMAN_REVIEW",
            "document_id": doc["doc_id"], "document_title": doc["title"],
            "question": f"What substantive claim, mechanism, or result does the selected passage establish about {doc['title']}? Include any condition that limits the claim.",
            "gold_answer_draft": text,
            "gold_evidence_draft": [{
                "evidence_unit_id": node["node_id"], "document_id": node["doc_id"], "page_id": node["page_id"],
                "element_type": node["node_type"], "bbox": node["bbox"], "text": text,
                "source_page_image": page_image.get((node["doc_id"], node["page_id"])),
                "source_node_file": node["source_file"], "source_atom_ids": node["source_atom_ids"],
                "future_node_mapping": "already_bound_to_legacy_node",
            }],
            "difficulty": "review_candidate", "question_type_actual": "single_evidence",
            "uses_gold_annotations": False, "node_mapping_status": "BOUND_TO_EXISTING_LEGACY_NODE",
            "provenance_warning": "Legacy original PDFs were not uniformly verified; review against preserved page image and node text.",
            "reviewer_decision": None, "reviewer_notes": None,
        })
    OUT.mkdir(exist_ok=True)
    (OUT / "qa_drafts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    (OUT / "skipped_visual_only.json").write_text(json.dumps(skipped, ensure_ascii=False, indent=2) + "\n")
    (OUT / "summary.json").write_text(json.dumps({"status": "legacy_review_candidates_only", "draft_count": len(records), "document_count": len(docs), "skipped": skipped, "note": "Candidate answers are source-node text and require human rewrite/approval before gold use."}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
