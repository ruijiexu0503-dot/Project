# Node-first QA r1 → r2 difference report

Date: 2026-11-17  
PR #3 join key: complete `nodefirst_v2_r1::NNN` `draft_id`  
Manual approval required: no

## Inputs and non-destructive scope

- Applied all 38 PR #3 manifest decisions: 22 KEEP, 13 REVISE, 3 REMOVE.
- Preserved the original Pilot and all r1 files. All new artifacts are under this r2 directory.
- Reused the existing automated Source Integrity and Canonical Node Mapping audits as separate gates.
- For frozen legacy nodes with no separate Evidence Unit ID, the stable canonical Node ID is the Evidence Unit ID; document/page/source checks remain required.

## Repair disposition

- 22 KEEP records were rebuilt with explicit answer claims and literal evidence spans.
- 8/13 REVISE records were repaired and resubmitted: `011`, `012`, `013`, `020`, `025`, `030`, `041`, `045`.
- 5/13 REVISE records were excluded for resampling because the supplied evidence could not support a genuine bridge: `019`, `031`, `038`, `043`, `044`.
- PR #3 REMOVE records excluded: `024`, `039`, `050`.
- Questions changed in 11 records; answers changed in 12 records. Exact old/new values are in `r1_to_r2_diff.jsonl`.

## Fresh independent review

- Reviewed: 30 candidates.
- Strict pass: 28; fail: 2.
- All 10 Cross-document candidates passed node-deletion, claim grounding, duplicate, and shortcut review.
- `nodefirst_v2_r1::020` failed because it is a parallel two-entry glossary, not an integrative cross-page inference.
- `nodefirst_v2_r1::021` failed because it lists two intervention families without a shared condition, comparison criterion, or interaction.
- No exact historical duplicate and no resolved single-node shortcut was found.

## Automated Gold Gate

- Automatic Gold eligible: 28 = 21 PR #3 KEEP + 7 repaired REVISE.
- Eligible pool distribution: 9 Single Node, 9 Cross-page, 10 Cross-document.
- Exact target export: 20 records = 4 Single Node (20%), 6 Cross-page (30%), 10 Cross-document (50%).
- Source Integrity, Canonical Mapping, semantic review, evidence necessity, claim grounding, duplicate, and shortcut checks all pass for every exported record.
- The two semantic failures remain blocked; they are not silently converted to Single Node or exported.

## Output map

- `qa_gold_auto_accepted_pool_r2.jsonl`: all 28 automatically eligible Gold records.
- `qa_gold_balanced_20_30_50_r2.jsonl`: exact 20/30/50 release subset (20 records).
- `qa_independent_reviews_r2.jsonl`: fresh independent model decisions.
- `deterministic_validation_r2.jsonl`: per-ID deterministic gate results.
- `r1_to_r2_diff.jsonl`: complete 38-ID before/after diff and disposition.
- `gold_export_summary_r2.json`: export counts and distribution check.

