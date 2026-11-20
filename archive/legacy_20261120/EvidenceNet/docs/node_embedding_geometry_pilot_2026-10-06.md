# Node ownership: visual/table embedding and geometry pilot (2026-10-06)

This is a frozen **candidate-ranking** experiment, not a node-generation change or an edge-acceptance evaluation. It reads existing parsed nodes and does not alter production output. Review labels are assistant source review from the previous prompt comparison, not independent human ground truth. The 12 visual cases were purposively chosen (seven supported links, five known unsupported links), and only one candidate per case is labeled here; other candidates may also be valid or invalid.

## Method

- For each target visual, Qwen3.5-35B-A3B receives **only that visual's crop** and produces a visible-content description. The full page and candidate text are withheld from description generation. Each crop SHA-256, prompt, raw description, and model is recorded in `output/node_embedding_geometry_pilot_20261006/descriptions.jsonl`.
- The existing Qwen3-Embedding-0.6B text model embeds the description as a query and the unchanged same-page text candidates. The geometry arm uses the existing `candidate_ledger.json` score. An equal-rank fusion arm sorts by the sum of the two ranks, breaking ties with geometry. All arms see the same candidate pool.
- The separate table check uses three parsed tables. It compares raw HTML against a deterministic row-by-row cell serialization; both are embedded against the same-page text atoms. This serialization preserves the parser's cell order and values, but does not infer missing header relationships or repair parser errors. Geometry uses the existing `pair_hint` formula.

## Visual ranking results

| Arm | Supported reviewed link at Top-1 | Supported at Top-3 | Known unsupported link at Top-1 |
| --- | ---: | ---: | ---: |
| Geometry | 5/7 | 6/7 | 4/5 |
| Description embedding | 4/7 | 6/7 | 1/5 |
| Equal-rank fusion | 6/7 | 6/7 | 4/5 |

Embedding strongly demoted the wrong link from the left spring-mass illustration to the right block-diagram prose (`case_00`: rank 1 to 9). It also demoted the wrong river-vehicle/rescue-caption link (`case_05`: rank 3 to 4). However, fusion promoted the latter **to rank 1**, while the supported block-diagram prose in `case_01` fell from geometry rank 2 to embedding rank 6. The photo-credit false link in `case_04` remained rank 1 under embedding. The crop included visible credit text and the generated description repeated it despite the instruction to ignore photo credits. There is no clean cosine threshold: reviewed supported scores range 0.243–0.727 and unsupported scores 0.245–0.531.

These are retrieval ranks, not accepted-edge precision. No production change should follow from the aggregate alone, especially because the chosen error controls and valid links are not a representative sample.

## Table ranking results

Each tuple is the preselected source-supported introducing paragraph/caption's rank among all eligible same-page text atoms.

| Table | Geometry | Raw HTML embedding | Row-description embedding | Raw + geometry | Row + geometry |
| --- | ---: | ---: | ---: | ---: | ---: |
| `entropy/page_0006/A_006` | 2 | 3 | 3 | 1 | 1 |
| `entropy/page_0006/A_011` | 1 | 6 | 8 | 2 | 2 |
| `gNtSaU-1511.05999v3/page_0006/A_006` | 2 | 1 | 1 | 1 | 1 |

The second entropy table illustrates a concrete failure: embedding ranks a later example message first because it repeats table words (`BEBE`, `DEED`, etc.), although the introducing paragraph immediately before the table explains its role. Three tables are insufficient to establish a general result. For table nodes, preserve exact cells and row structure as the source; attach a description only as derived, auditable metadata.

## Decision and next controlled step

Keep node boundaries and source text/HTML unchanged. Description embedding is useful for surfacing a target-specific semantic mismatch, but should be a *candidate feature*, not an automatic ownership or edge-acceptance rule. The next test should use a larger, independently reviewed set with positive and negative links for **every candidate**, plus cases with multiple figures, photo credits, nearby captions, diagrams with equations, and tables containing repeated values. Compare geometry-only, crop-description embedding, direct image embedding if available, and calibrated fusion under the same candidate budget. Explicit caption/figure references and verified table structure should remain separate evidence features. Do not tune a cosine cutoff on these 12 development cases.

Run commands:

```bash
sbatch _archive/2026-10-09-launchers/current/run_node_embedding_geometry_pilot_dev.sbatch
sbatch _archive/2026-10-09-launchers/current/run_table_embedding_geometry_pilot_dev.sbatch
```

Machine-readable results: `EvidenceNet/output/node_embedding_geometry_pilot_20261006/ranking_report.json` and `table_ranking_report.json`. The image job `53052` and table job `53058` completed successfully on dev H100. No broad test was submitted.
