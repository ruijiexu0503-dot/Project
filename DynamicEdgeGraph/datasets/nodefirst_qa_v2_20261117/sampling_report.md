# Node-first QA v2 — 50-item Pilot report

Date: 2026-11-17. Seed: 20261117. This Pilot is not a Gold benchmark.

## Eligibility inventory

- New periodicals: 17 documents are eligible for review but all remain pending canonical node mapping. real_015_batch_15_spinoff2008 is excluded/parked because only 194 of 217 page directories exist and only 193 pages have successful summaries.
- Legacy corpus: 25 documents, 49 pages, 550 unique non-null node IDs. All 550 nodes are HYBRID_SHADOW_CANDIDATE and the original PDFs are not uniformly verified, so the entire corpus remains PILOT_ONLY_BLOCKED.
- Legacy node types: 474 TEXT, 27 COMPOSITE, 45 VISUAL, 3 TABLE, and 1 CAPTION. A minimal text/type gate retains 451 heuristic candidates; this is not a semantic quality acceptance count.
- Existing 268 QA records: 64 REVIEW_REQUIRED, 60 PILOT_ONLY_BLOCKED, and 144 EXCLUDE_OR_PARK. They were not rewritten or used as question/answer generation input.

## Pilot sampling

- Target and actual category counts: 10 Single-node (20%), 15 Cross-page (30%), and 25 Cross-document (50%).
- Cross-document rounding: 17 two-document (34% overall) and 8 three-plus-document (16% overall). Exact 35%/15% counts are impossible with 50 integer records.
- Seed corpus: 10 new-periodical evidence units and 40 legacy-node seeds.
- Coverage: 30 distinct documents; 99 evidence references total.
- Evidence types in this Pilot: 10 provisional PARA units and 89 legacy TEXT nodes. TABLE, IMAGE/VISUAL, CAPTION, and COMPOSITE evidence are not represented and remain a coverage gap.
- Cross-page distance: 4 near (1–2 pages), 6 medium (3–10 pages), and 5 far (>10 pages), matching the intended 5%/10%/15% overall split after integer rounding.
- Reasoning types: 15 bridge, 15 comparison, 10 complementary, 3 constraint, and 7 fact.
- Draft-answer length: 5–19 whitespace-delimited words, mean 12.22.
- Cross-corpus Cross-document groups: 0. All 25 Cross-document stress tests use legacy Pilot-only nodes because the eligible new periodicals have no canonical node mapping.

## Independent review

- Overall: 9 CONTENT_PASS_MAPPING_PENDING, 24 PILOT_ONLY_BLOCKED_CONTENT_PASS, and 17 REVISE.
- Single-node: 9 content-pass/mapping-pending and 1 revise.
- Cross-page: 12 Pilot-only content-pass and 3 revise.
- Cross-document: 12 Pilot-only content-pass and 13 revise.

Only 12 of 25 Cross-document drafts passed semantic multi-document necessity: 48%. Thirteen failed. Drafts 026, 028, 032, and 040 have a direct single-document shortcut. Other failures are primarily loose analogy, generic governance transfer, or an author-imposed parallel list rather than a genuine joint inference.

This is the main Pilot finding: meeting the numerical Cross-document quota is easy, but more than half of the proposed Evidence Groups do not survive independent necessity review. Scaling is blocked until companion discovery and question generation reject these patterns before drafting.

## Mapping and source-integrity status

- Ten new-periodical evidence units are PENDING_MAPPING and appear in unresolved_evidence_mapping.jsonl.
- Eighty-nine legacy evidence references have an ID and valid local reference, but are explicitly PILOT_ONLY_ID_PRESENT_SOURCE_PDF_UNVERIFIED.
- No record is FINAL_ACCEPT. qa_gold_verified.jsonl is intentionally empty.
- Page-image/PDF pixel checks and exhaustive alternative-evidence/semantic-duplicate search are not complete.

## Required repairs before any scale-up

1. Build a frozen canonical node assembly for the 17 complete new periodicals and verify evidence-unit-to-node mappings.
2. Verify original PDFs and canonical status for any legacy material that might be promoted beyond Pilot-only use.
3. Add a pre-generation relation gate that rejects parallel-list questions, cross-domain analogy without a shared measured relation, and generic governance overlays.
4. Run corpus-level single-node shortcut and alternative-Gold retrieval before accepting every multi-node group.
5. Add TABLE and image-pixel-reviewed examples; current Pilot is text-only.
6. Perform exhaustive lexical and semantic deduplication against the 268 historical candidates and record nearest matches.
7. Re-run an independent review after repair. Do not scale while Cross-document necessity pass rate remains 48%.
