# PR #3 audit provenance

All four files under EvidenceNet/docs/qa_r1_independent_audit_20261117 were read from pull request #3, head commit 30ba43476e4a250afd0716ea7f0cf1cffcc263f0.

- README_qa_r1_independent_audit.md, blob 5ce8c1c5128889c6e86eb90af483647ace3569c3
- qa_r1_independent_audit_index.csv, blob 9f1eb07ee91a9a30f970d015a54c699cf8ce8dea
- qa_r1_independent_audit_manifest.jsonl, blob 525d1450a5bf59e6e28662eb2565be72063af1b5
- qa_r1_independent_audit_report.md, blob adf6d1387520dc07401015c951fbe344416fc882

The local action manifest uses the complete draft_id as its only join key. No verdict is applied by row position or numeric suffix alone. PR #3 verdicts are repair inputs, not final Gold decisions; r2 receives a new independent model review and automated gates.
