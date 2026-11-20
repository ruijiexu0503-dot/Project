# Completed comparisons and natural-edge retry

2026-10-15. Completed: description 78065 (35m35s), modality comparison 78086 (30m49s), full-corpus retrieval 78100 (10m56s), previous verifier 78102 (1h01m06s). All exited zero. Natural-candidate graph pilot 78114 failed before model inference on `slide_0020`; it did not generate any evidence edges. The page parser was repaired and the 48 actual inputs prepared successfully before retry **79541**. Failed V1 artifacts/logs are retained; retry uses separate V2 output.

## Retrieval, complete 1,313-node corpus

| Scheme | Candidate pairs | Core positives included / 26 | Hard-negative cases included / 27 |
| --- | ---: | ---: | ---: |
| 76411 hierarchical replay | 1,301 | 10 | 2 |
| Previous whole-node dense policy | 10,152 | 7 | 3 |
| Global cosine at matched 1,301-pair budget | 1,301 | 6 | 0 |
| Initial multichannel pool, before selection | 41,186 | 24 | 14 |

Two project-navigation positives are separate: hierarchical 2/2, dense 0/2, equal-budget global cosine 0/2. The 27 negatives include the navigation negative; do not merge navigation positives into the 26 semantic positives without stating this change.

Hierarchical retrieval is the stronger candidate policy on this development set. It still discards 14 positive cases present in the initial pool: P01/P02/P04/P05/P07/P08/P17/P18/P19/P20/P22/P23/P24/P26. Two core positives were absent from the initial pool. The largest measured retrieval loss is final fusion/routing/degree/budget selection; these counts do not individually isolate each selection mechanism. Candidate-negative inclusion is search burden, not verified-edge false positive rate. The initial pool is not an operational semantic graph.

## Fixed-pair verification

There are 37 cases with resolved, agreeing binary reference judgments under both protocols: 14 positives and 23 negatives. This is the appropriate limited scope for an existence comparison; taxonomy, prompt, schema, representation and generation limits still differ.

| Verifier | TP | FN | FP | TN | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Previous concrete-correspondence protocol | 10 | 4 | 1 | 22 | 90.9% | 71.4% |
| Current four-function description protocol | 6 | 8 | 0 | 23 | 100% | 42.9% |

The previous protocol has better recall and F1 on this scope, while the four-function protocol is more conservative. This is not a conclusion that previous generated edge prose is correct, or that either graph improves retrieval.

On its native requested-relation reference set, previous verifier processed 45 cases, accepting 17, rejecting 27 and returning uncertain once. On 42 positive/negative cases it had 12 TP, 5 FN, 3 FP and 22 TN (80% precision, 70.6% recall). The remaining three source-uncertain cases were not silently scored as negatives; U01 and U02 were accepted and require review.

The four-function run processed all 58 cases with no invalid outputs. On 51 provisionally resolved semantic cases: 16 TP, 10 FN, 0 FP and 25 TN. Label plus direction matched an allowed frozen reading in 35/51 cases, including correctly rejected negatives. References: 5 TP, 1 FP, 0 FN, 52 TN. Seven semantic cases remain unresolved. These references are assistant source-review annotations, not independently adjudicated expert gold.

## Source review of concerning old-verifier accepts

The following are direct checks of generated claims against supplied source content; this is a targeted audit, not a precision estimate over all proposed prose.

| Case | Observed problem | Consequence |
| --- | --- | --- |
| N04 | Claims the FUSU results figure uses EuroSAT because its scenes resemble EuroSAT classes. Supplied figure/text does not establish that dataset identity. | Unsupported dataset edge; the only false accepted negative in the 37-case common scope. |
| N05 | Uses overlapping RF/SVM/Naive Bayes names in a generic method list as proof of the old strict method-mechanism correspondence. | Violates the old no-bare-list mechanism requirement. Under broad explanation/context semantics this case has a different legitimate reading and is excluded from the common comparison. |
| N06 | Accepts DATASET_CORRESPONDENCE for PeMSD7(M), 228 sensors, versus PeMSD7, 883 sensors, although the case asks whether measurements are comparable. | Dataset-family navigation cannot establish comparable measurement populations; its accepted relation also differs from the requested relation. |
| U01 | Calls both endpoints an L1 loss, although one endpoint only says loss between predictions and labels. | Imports L1 identity from the other endpoint; insufficient source evidence. |
| U02 | Says STTN processes remote-sensing imagery when its source is road-traffic forecasting. | Cross-endpoint/domain contamination; broad temporal modules do not establish that application identity. |
| P01/P04 | `source_content` contains explicit descriptions of both endpoints, rather than remaining local to the source endpoint. | Pair existence can be correct while the intended local-content protocol is not followed. |
| P13 | Acknowledges May31 versus June30 end-date disagreement, yet summarizes a shared six-month interval. | Keep identity/navigation separate from scope-compatible measurement comparison; disputed dates must not be normalized away. |

## Controlled non-text representations, complete

All three arms processed the same 14 cases without invalid outputs. One case is semantically unresolved. Of the remaining 13, there are nine positives and four negatives.

| Representation | Semantic positives found / 9 | Semantic FP / 4 negatives | Allowed label + direction matches / 13 | Reference FP |
| --- | ---: | ---: | ---: | ---: |
| Qwen descriptions | 7 | 0 | 10 | 0 |
| Original crops | 7 | 0 | 9 | 2 |
| Mixed | 9 | 0 | 10 | 2 |

Mixed finds relations in the two table cases P14/P15 that description/raw arms reject, but does not improve the total exact label/direction score over descriptions. P14 is classified SUPPORTS instead of the frozen explanation reading; P15's explanation direction differs from the frozen reading. P21's raw arm puts SUPPORTS from result prose to plot; mixed puts plot to claim, consistent with the evidence role. P16/P23 have spurious reference edges in raw and mixed arms. All three arms choose the same explanation direction on P23 contrary to the provisional reference, so that direction should receive independent adjudication before being treated as an established model error; frozen scores are not changed retrospectively.

These few repeated assets cannot establish a universal winning modality. Existing eight descriptions were reused, and one new 180-token table description was truncated and omitted row detail. Better table-description coverage is a separate future intervention, not silently repaired in these runs.

## Current interpretation

Preserve the hierarchical candidate policy as the strongest measured retrieval option here, but prioritize fixing final selection losses rather than changing the embedding model. Previous concrete-correspondence judgment is a stronger recall-oriented starting point within its supported relation scope; add stricter endpoint-local fact checks and dataset-scope checks before trusting prose. Broad semantic functions and explicit references remain separate. Mixed visual input is promising for recovering connections, with no current exact-score advantage over descriptions and additional reference errors.

The natural 48-pair pilot still needs to finish and undergo source review. It uses four functions, description representation and explicit owned quotes; this differs from the fixed-pair 400-token classification run and does not automatically inherit its accuracy. No production pipeline or retrieval baseline has been replaced.

Raw results: `EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/`, `EvidenceNet/output/split_taxonomy_modality_comparison_v1_20261015/`, `EvidenceNet/output/split_taxonomy_current_suite_qwen_descriptions_v2_20261015/`. Retry graph output: `EvidenceNet/output/retrieved_evidence_edges_pilot_v2_20261015/`.
