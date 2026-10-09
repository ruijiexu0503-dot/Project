# ANN candidate pilot — 2026-09-16

Status: SHADOW. No production graph changes; no new semantic edges asserted.

## Completed real-data experiment

Input: 447 cached BGE-M3 embeddings, 1024 dimensions, grouped into 62 magazine
articles and three papers. CERN covers one issue; CLAD/DLR cover selected pages.
There are 2,080 possible unordered article/paper pairs, including distinct
articles within the same magazine. All units have article assignments.

Outputs: `EdgeGeneration/output/ann_candidate_real_v3/`.
Open `report.html` for candidate pairs and their source evidence.

HNSW preserved 100% of the exact baseline's cross-article top-10 evidence
neighbors. The three RRF candidate budgets also matched exact retrieval 100%.
This is ANN fidelity on 447 vectors, not semantic accuracy or a large-scale
performance claim. Single-pass timings are diagnostic only.

| Candidate policy | Unique unordered candidate pairs | Reduction vs all pairs | Provisional positive article pairs found, source-to-target |
|---|---:|---:|---:|
| RRF, 5 per article | 242 | 88.4% | 0/3 |
| RRF, 10 per article | 475 | 77.2% | 1/3 |
| RRF, 20 per article | 935 | 55.0% | 3/3 |
| Union of each route's top 3, at most 9 per article | 323 | 84.5% | 3/3 |
| Union of each route's top 5, at most 15 per article | 485 | 76.7% | 3/3 |

The RRF sweep fixes each route's depth at 20; budgets are nested and comparable.
Positive counts use the original directed retrieval queries; unordered candidate
counts measure deduplicated downstream verification workload. These are different
quantities, and reverse retrieval may also retrieve a pair.

Article-mean-only retrieval missed all three provisional positive article pairs
even at top 20. Local evidence and lexical routes must remain independent entry
points. Union-of-routes looks promising in this pilot; it is not selected as a
production default based on three examples.

There are only seven provisional evidence-pair labels: four positive rows map
to three article pairs, and three negative rows are not reliable negatives for
the entire article pair. One positive evidence pair is outside local top 10 even
though its article is recovered by other routes. Therefore article candidate
coverage does not imply recovery of the exact supporting evidence or a verified
semantic edge. No precision estimate is justified by this sample.

The report includes local evidence within union-3 candidate pairs for inspection.
Evidence is scored only inside these bounded article pairs. Similarity-ranked
passages still need semantic review.

## Incremental and implementation checks

- Built an index on 342 existing units and appended 105 units from held-out
  article groups; resulting top-10 retrieval matched exact search 100%.
- Saved/reloaded the index with identical results and persisted its row-ID map.
- Replayed candidate-cache inserts with zero duplicate additions.
- Six tests cover same-article overfetch, empty eligible sets, article dedup,
  invalid vectors, nested candidate budgets, and retrieval after insertion.

The cache stores retrieval candidates only. It conservatively invalidates the
dataset version on any input/policy change; fine-grained production invalidation,
deletions, and reverse-neighbor maintenance are future work.

## Large-scale run

Submitted Horeka job **5148688**, `dev_cpuonly`, 8 CPUs, 12 GB, 30 minutes, for
10,000/100,000 synthetic clustered vectors and 128 independent query vectors.
At report creation it is PENDING with `QOSMaxJobsPerUserLimit`; other user jobs
were not altered. The first normal-CPU submission 5148686 was cancelled before
execution because its estimated start was several days away.

The script writes scaling results to
`EdgeGeneration/output/ann_candidate_pilot_5148688/summary.json` and
`report.html`. Logs: `EdgeGeneration/logs/ann-pilot-5148688.out` and `.err`.
Synthetic data are explicitly marked and are not counted as real papers. Reported
RSS is a cumulative process peak including both indexes and input arrays;
serialized HNSW bytes are reported separately.

## Next interpretation step

Inspect union-3 candidates and judge concrete evidence-backed relations, then
expand independent article-pair labels across topics. Compare candidate recall
at the same verification budget before deciding whether union, RRF, or a quota
mixture should be promoted. The present result supports indexed retrieval and
preserving independent local retrieval, not automatic edge materialization.
