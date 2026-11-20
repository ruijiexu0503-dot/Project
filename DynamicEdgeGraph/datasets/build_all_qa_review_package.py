#!/usr/bin/env python3
"""Assemble new- and legacy-corpus QA review candidates without mutating either."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NEW = ROOT / "real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/qa_review_drafts_v1/qa_drafts.jsonl"
OLD = ROOT / "node_vqa_reuse_v1_20261113/qa_review_drafts_v1/qa_drafts.jsonl"
EXPANSION = ROOT / "qa_expansion_candidates_v1/qa_expansion_candidates.jsonl"
DENSE = ROOT / "dense_magazine_candidates_v1/qa_dense_candidates.jsonl"
OUT = ROOT / "all_qa_review_drafts_v1"


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    new, old, expansion, dense = read(NEW), read(OLD), read(EXPANSION), read(DENSE)
    for row in new:
        row["corpus"] = "real_documents_v1_20261113"
        row["answer_status"] = "candidate_gold_requires_human_approval"
    for row in old:
        row["corpus"] = "node_vqa_reuse_v1_20261113"
        row["answer_status"] = "candidate_gold_requires_human_rewrite_and_approval"
    rows = new + old + expansion + dense
    assert len({r["draft_id"] for r in rows}) == len(rows)
    OUT.mkdir(exist_ok=True)
    (OUT / "all_qa_drafts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    summary = {
        "status": "combined_review_candidates_only",
        "total_queries": len(rows),
        "real_document_queries": len(new),
        "legacy_document_queries": len(old),
        "source_bound_expansion_queries": len(expansion),
        "dense_magazine_queries": len(dense),
        "real_document_multi_evidence": sum(r["question_type_actual"] == "multi_evidence" for r in new),
        "legacy_visual_only_not_annotated": ["nasa_cosmic_temperatures_image_only_pdf", "nasa_cosmic_temperatures_jpeg"],
        "note": "No candidate becomes a formal gold answer until human review. Legacy source PDFs are not uniformly verified; their evidence binds to preserved node/page assets.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
