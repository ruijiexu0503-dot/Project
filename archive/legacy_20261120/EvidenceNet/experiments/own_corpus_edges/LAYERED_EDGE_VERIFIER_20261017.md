# Layered edge verifier: shadow result and source review (2026-10-17)

## Scope

This is a development, fixed-pair shadow experiment over the 103 frozen
relatedness tasks. It measures verifier behavior after a pair has already been
retrieved. It is not an end-to-end retrieval score and is not a held-out estimate
of production accuracy.

The verifier separates:

- `EVIDENCE_LINK`: a claim-level or same-specific-subject edge that may enter
  semantic aggregation.
- `NAVIGATION_LINK`: shared named method/component only; useful for discovery,
  but excluded from evidence propagation.
- `NO_LINK`: topical, visual, institutional, or otherwise insufficient overlap.

Every positive decision must cite owned evidence anchors from both endpoints.

## Run

- Slurm job: `82626`
- Status: completed, exit code 0
- Runtime: 26m42s on H100
- Processed: 103 / 103
- Invalid outputs: 0

Exports:

- `output/layered_edge_verifier_v1_20261016/predictions.jsonl`
- `output/layered_edge_verifier_v1_20261016/evidence_edges.jsonl`
- `output/layered_edge_verifier_v1_20261016/navigation_edges.jsonl`
- `output/layered_edge_verifier_v1_20261016/reference_edges.jsonl`

## Aggregate result

| Decision | Count |
|---|---:|
| Evidence link | 49 |
| Navigation link | 11 |
| No link | 43 |

On the 58 provisional, source-reviewed ordinal cases, treating evidence and
navigation links as accepted relatedness:

| Verifier | TP | FN | TN | FP | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Previous binary relatedness | 29 | 2 | 19 | 6 | 0.829 | 0.936 |
| Layered verifier | 28 | 3 | 25 | 0 | 1.000 | 0.903 |

The layered decision removes all six observed false positives, at the cost of
one additional false negative. These numbers are development diagnostics, not
an unbiased benchmark.

## Failure-case review

- `N04`, `N21`, and `N22`: now `NO_LINK`. Visual similarity and broad
  remote-sensing/topic overlap no longer become semantic edges.
- `P01`: recovered as `EVIDENCE_LINK / CLAIM_CORRESPONDENCE`, with owned quotes
  containing “fixed once trained” and “fixed after training”. Edge existence is
  correct, but `CONTRASTS_WITH` is wrong: the passages agree on the same Graph
  WaveNet limitation. The ontology needs a symmetric
  `CLAIM_CORRESPONDENCE`/`AGREES_WITH` relation instead of forcing this case into
  `CONTRASTS_WITH`.
- `P02`: `NAVIGATION_LINK`, not evidence. Both mention temporal
  transformer/attention, but one is a concrete implementation and the other a
  broad survey description.
- `P11`: `NO_LINK`. “Multi-head attention/Transformer” is too generic across
  DETR and traffic forecasting. If broad exploration is desired, this can be a
  weak component-navigation edge, never an evidence edge.
- `P12`: `NO_LINK`. Two unrelated tasks both use an L1-style loss; shared generic
  mathematics is insufficient for evidence. A formula-navigation lane may keep
  it discoverable without polluting the semantic graph.
- `P26`: `NO_LINK`. A specific stroke-AI project and a generic NIST definition
  share only the broad concept “AI system”.
- Linden Hall (`REL_282b01cff6d8ce3c`): correctly changed from `SUPPORTS` to
  symmetric `SAME_SUBJECT`; however, the explicit-reference direction is wrong.
  The narrative endpoint contains “(fig. 7)” and therefore refers to the caption,
  not vice versa.

## Reference-direction audit

The model emitted six explicit-reference edges, all as `A_TO_B`. Direct source
inspection shows that at least five have the pointer (`Fig. 1`, `Fig. 4`, or
`Fig. 5`) on endpoint B and should be `B_TO_A`; only the traffic STTN prose-to-
caption case is clearly `A_TO_B`.

Therefore explicit-reference direction should not be accepted directly from the
LLM. Resolve it deterministically:

1. Extract normalized pointer keys such as `(document_id, figure|table|equation,
   number, subfigure)` from prose and captions.
2. The endpoint containing “Fig./Table/Eq. N” is the referring side; the endpoint
   whose caption identity is N is the referred-to side.
3. Emit direction only when keys match uniquely; otherwise use `NONE` or
   `UNCERTAIN` and require review.
4. Keep this explicit-reference edge separate from the semantic relation edge.

## Retrieval findings

Verifier changes cannot recover pairs that never enter the candidate pool.
Earlier shadow tests showed:

- Current selector: 10 / 26 positive cases in the final 1,301 candidates, with
  2 / 27 hard negatives.
- Generic BGE reranking: 4 / 26 and 0 / 27; retrieval-plus-reranker RRF: 9 / 26
  and 2 / 27. Generic web relevance is too conservative for this task.
- Node-level view deduplication expands the unique initial pool from 41,186 to
  50,872 but leaves final recall unchanged at 10 / 26.
- Expanding the per-article budget to 512 creates about 6,596 candidates but
  reaches only 16 / 26.
- An exploratory identifier-conditioned lane reaches 13 / 26 at the same 1,301
  budget, but was tuned while inspecting this development suite and requires a
  held-out test.

The most promising end-to-end design is therefore two-stage and typed:

1. Retrieve with separate lanes for exact named model/entity, claim phrase,
   formula/component, and current dense similarity; deduplicate node pairs before
   quota allocation.
2. Verify into evidence/navigation/no-link layers using the strict gates tested
   here.
3. Resolve explicit citation directions deterministically.
4. Calibrate lane quotas and thresholds on a held-out article split, reporting
   end-to-end recall and false-edge rate separately for each edge type.
