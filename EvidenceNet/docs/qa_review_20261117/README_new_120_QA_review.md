# New QA batch audit — start here

## Input and scope

- Input: `all_qa_review_decisions.json` (268 records).
- Compared against `all_qa_drafts.jsonl` (previous 148 records).
- All previous 148 records have unchanged `question`, `gold_answer_draft`, `gold_evidence_draft`, and `node_mapping_status`.
- New records: 120, exclusively from `real_016_batch_16_basic_version_07` (NASA Spinoff 2007).
- Recommendations for new records: 3 ACCEPT, 3 REVISE, 114 REJECT.
- **Review limitations:** extracted text only; original source PDFs, source_json file bodies, and canonical node mappings were not checked. All 120 new records say `PENDING_EVIDENCE_NODE_ASSEMBLY`.

## Package files

1. `new_120_qa_review_and_codex_repairs.md`: full human-readable QA-by-QA audit with concrete notes, evidence IDs, and repair instructions.
2. `new_120_qa_issue_manifest.jsonl`: 120 machine-readable issue rows with stable `draft_id`.
3. `new_120_qa_audit_index.csv`: sortable short index.
4. `all_qa_review_decisions_with_ai_audit.json`: 268 original records plus a new `ai_review` field; **original human-review fields are preserved**. Old 148 `ai_review` fields re-use the earlier AI audit (clearly tagged), rather than presenting them as newly source-verified.

## For Codex

Read the markdown audit and issue manifest first. Check each `draft_id` against the current dataset, then fix only the corresponding candidates; never treat REJECT as "delete graph node". Prioritize:

- `dense_magazine_v1`: 112 identical vague questions; every gold answer is an exact copy of its source evidence. Regenerate only from adequate, specific paragraphs.
- `auto_new_expansion`: 2 executive-summary / contents-like long snippets; reject the current QA, split into grounded topics or exclude from QA benchmark.
- `manual_qa_review_v1::059–064`: 3 retain with text-based acceptance (`060`, `061`, `063`), 3 revise (`059`, `062`, `064`); PDF and canonical node mapping still must be checked for all.
- `dense_magazine_v1::001` & `::112`: duplicate 9,359-character corrupted formula pages at page 2 and 172; investigate parsing artifact and prevent this type from entering QA generation.

## Required acceptance gates

1. Independently comprehensible question (avoid `selected passage` / `this article`).
2. Concise answer contains only claims entailed by verified evidence.
3. Source PDF reading order and OCR are sound; correct paragraph splits and multi-span ordering.
4. Gold Evidence maps to the intended canonical node ID(s) and page(s).
5. No exact duplicated questions; no entire evidence text copied as gold answer.
6. Log all before/after diffs and unresolved manual review cases.

`ai_review` is AI advice, **not** an automatic human approval. Keep `review.status`/`reviewer_decision` unchanged until manual signoff.
