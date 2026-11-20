# Previous schemes on the current regression suite

2026-10-15. User requested comparison with job 76411 or preceding schemes to identify the strongest current approach. Retrieval and relation verification are assessed separately; neither candidate count nor model acceptance count is a semantic accuracy score.

## Immediate reuse of original six-paper outputs

The frozen 58-case suite contains 39 cases whose endpoints exist in the original six-paper corpus: 19 positive, 17 negative and 3 uncertain. The other 19 cases are unavailable in that corpus and are not scored as misses.

| Original policy | Candidates | Positive cases retrieved | Negative cases entering candidates |
| --- | ---: | ---: | ---: |
| 76411 hierarchical V1 | 174 | 8/19 | 2/17 |
| Previous whole-node dense | 432 | 4/19 | 3/17 |

These are candidate-stage results on expanded development annotations, not verified-edge precision or retrieval-query quality. They supersede no old artifacts. The earlier three-positive diagnostic had 1/3 coverage for both policies; the expanded case set gives a different picture. This set also includes within-paper explanation/visual cases, and relation-specific details should be inspected before assigning a general winner.

## New full-corpus retrieval replay

Output: `EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/`.

The corpus is the complete union of the six-paper graph (763 nodes) and the earlier expanded material graph (550 nodes), totaling 1,313 immutable nodes across 31 documents. This avoids retrieving only against the 413 suite-packaged candidate endpoints. Cases and annotations are used only for reporting, never selection. The resulting member views number 2,223.

The original 76411 algorithm and defaults are reused unchanged: per-member windows/table rows, Qwen3-Embedding-0.6B, BM25 and identifier channels, reciprocal-rank fusion, article routing plus global escape, and original per-bucket budgets. The earlier whole-node cosine policy is rebuilt on the same corpus with its original 24 pairs per different-document pair, 12 per document and degree caps. Because those policies produce different total candidate counts, a global-cosine top-K control at the hierarchical final count is also reported separately. It is not mislabeled as the old policy.

169 expanded-material nodes have no confirmed article identity. Their search grouping uses explicitly marked document/page buckets, never a shared null article, and never claims to solve magazine segmentation. Same-PDF different-page buckets are eligible for routing. The baseline groups by PDF document, as its original policy did. These grouping differences and budget differences are part of the overall policy comparison.

Outputs include initial pool, final candidates, article search buckets, vectors, per-case coverage, and `retrieval_summary.json`. The original six-paper policies are also rescored with unavailable endpoints excluded. Candidate-negative inclusion is reporting of search burden, not a false accepted edge.

## Previous concrete-correspondence verifier

45 current cases fall within its existing taxonomy: METHOD_CORRESPONDENCE, DATASET_CORRESPONDENCE, MEASUREMENT_COMPARISON (17 positive, 25 negative, 3 uncertain). The other 13 explanation/definition/project-navigation cases are outside its supported scope and are not silently counted as failures.

Replay reuses the exact 75115 prompt literal, source catalog, endpoint anchor validator, two-attempt protocol, 1,800-token generation budget and original raw visual crops / parsed table input. Model remains Qwen3.5-35B-A3B, CPU bfloat16, thinking disabled, deterministic generation. All 45 pairs are forced into the verifier to isolate its decision from candidate omission. Presentation order is deterministically swapped by opaque case ID, matching the current suite protocol. Labels, source-review reasons and requested relation are not supplied to the model.

The original suite and four-function annotations have different semantics. Only 37 cases have resolved, agreeing binary reference judgments under both protocols. On those cases, report existence TP/FP/FN/TN separately from native type accuracy; exclude invalid/uncertain from valid-only metrics and report their count. Jointly processed cases are reported separately while either run is incomplete. Do not compare raw aggregate accuracy across the 45-case and 58-case scopes.

This is an overall scheme comparison, not a prompt-only ablation: taxonomy, output schema, evidence representation and token budget differ. Model ACCEPT is not proof that its local content, shared mechanism and qualifications are source-correct; source review remains necessary. The 14-case non-text representation experiment is a separate controlled comparison.

## Execution and checks

```bash
.venv-magazine-exp1/bin/python EvidenceNet/scripts/compare_previous_edge_schemes.py prepare
sbatch current/slurm/traffic_relevance/previous_schemes_retrieval_cpu.sbatch
sbatch --dependency=afterok:78100 current/slurm/traffic_relevance/previous_schemes_verifier_cpu.sbatch
```

Retrieval job: **78100**. Verifier job: **78102**, runs after retrieval to serialize writes to the shared report. Output/code/source hashes were frozen before submission. Existing experiments and production pipelines are preserved. Four focused tests passed for exact prompt reuse, unavailable endpoint accounting, original candidate budgets/degree caps and invalid/missing/uncertain handling.

Files to inspect: `REPORT.md`, `retrieval_summary.json`, `retrieval_cases.json`, `verification_comparison.json`, `verifier/predictions.jsonl` (raw outputs and anchored local claims). The common-scope comparison reads the current 58-case run as it progresses; regenerate report after both finish.
