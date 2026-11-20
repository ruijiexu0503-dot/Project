# Node-first QA v2 Pilot workflow

This directory is a non-destructive Pilot package. It does not replace any historical JSONL and exports no Gold record.

## Eligibility gate

1. Read the adjacent annotation eligibility manifest before sampling.
2. Only the 17 records marked ELIGIBLE_FOR_REVIEW_PENDING_NODE_MAPPING may supply new-periodical evidence units. They can reach at most CONTENT_PASS_MAPPING_PENDING.
3. real_015_batch_15_spinoff2008 is parked as an incomplete parse and cannot supply evidence.
4. The 25-document legacy corpus is PILOT_ONLY_BLOCKED. Its node IDs may test questions, ablation, and review behavior, but never export formal Gold until source PDFs and canonical status are independently verified.
5. Historical QA packages are used only for deduplication and failure analysis. Their questions and answers are not generation input.

## Pilot sequence

1. Freeze the eligibility manifest, corpus snapshot, and random seed.
2. Sample an evidence seed before writing a question.
3. Discover companions independently of the graph under evaluation, recording lexical, metadata, and curator relation checks.
4. Write atomic evidence claims and the planned relation before drafting the question.
5. Draft a standalone question and concise answer with claim-to-evidence links.
6. Run node deletion ablation. A multi-node label passes only if every removed node makes the complete answer impossible, not merely shorter.
7. Search for a single-node shortcut and alternative Gold sets.
8. Run an independent review across question, answer, sufficiency, necessity, source integrity, mapping, duplication, and leakage.
9. Keep mapping-pending and Pilot-only records in separate queues. Export only records that later satisfy all source and canonical mapping gates.

## Quota

The fixed Pilot has 50 drafts: 10 single-node, 15 cross-page, and 25 cross-document. Because 35% and 15% cannot both be represented exactly with 50 integers, cross-document is rounded to 17 two-document and 8 three-plus-document drafts (34% and 16% overall).

## Files

- source_inventory.json: eligibility-aware source and mapping inventory.
- sampled_seeds.jsonl: deterministic sampled seeds.
- evidence_group_candidates.jsonl: companion groups and discovery provenance.
- qa_drafts.jsonl: 50 immutable Pilot drafts.
- qa_independent_reviews.jsonl: separate review decisions.
- mapping_audit.jsonl and unresolved_evidence_mapping.jsonl: mapping status and action queue.
- qa_gold_verified.jsonl: intentionally empty until every Gold gate passes.
- validation_report.json: counts, reference checks, and content hashes.
