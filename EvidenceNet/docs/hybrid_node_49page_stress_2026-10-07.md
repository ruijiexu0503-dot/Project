# 49-page hybrid node stress test (2026-10-07)

The opt-in embedding/geometry baseline and bounded-Qwen hybrid node branch were run on **all 49 pages from 25 documents** in the v7 relation-first shadow corpus. The selection includes 15 pages with a recorded failure in the earlier relation stage, 72 visual bundles, 28 parser-typed captions, three table atoms on two pages, slides, magazines, research papers, reports, and image-only sources. Those earlier relation failures were included as stress inputs; passing this node branch does not repair their relation outputs. The [prepared manifest](../output/hybrid_49page_stress_prepared_20261007/manifest.json) freezes exact source/image hashes and seven balanced batches. Preparation added only parser-order indices and empty native-component lists where needed by this branch; source fragments, layout atoms, visual bundles, and geometry were preserved. Neither production EvidenceNodes nor default Step-2A were modified.

The first attempt was canceled after a large page produced 39 adjacent-text candidates: one monolithic response could exceed the fixed 2,500-token generation allowance. The decision step now requests at most eight pairs per model call, stores every exact chunk prompt and hash, validates each chunk, then checks the combined IDs. Seven dev-GPU array tasks in job `55494` completed; the seven batch manifests also passed independent `--validate-only` runs.

| Check over 49 pages | Embedding + geometry | Bounded hybrid |
| --- | ---: | ---: |
| Complete source/member validation | 49/49 | 49/49 |
| Visual bundles retained | 72/72 | 72/72 |
| Native visual components retained | 10/10 | 10/10 |
| Pages with valid Qwen boundary decisions | n/a | 49/49 |
| Multi-atom text nodes | 0 | 48 |
| Added adjacent-atom joins | 0 | 71 from 466 candidates |
| Table atoms in retrievable evidence nodes | 0/3 | 0/3 |

Source validation means an atom is present in an evidence node **or** a structural/unresolved sidecar. It is therefore compatible with the important table failure: **all three parser `table` atoms remain outside retrievable EvidenceNodes**. One of 28 caption atoms, the caption for a table with no visual bundle, is also unassigned. Seventy-two visual bundles are retained, but retention alone does not establish that every visual description or attachment is semantically correct.

## Reviewed failures

The [stress audit](../output/hybrid_49page_stress_run_20261007/stress_audit.json) marks 16 of 71 added joins for source review. The [review ledger](../config/reviews/node_generation/hybrid_49page_stress_review_20261007.json) confirms **15 incorrect joins under the frozen same-grammatical-sentence policy**, and one correct continuation across an intervening figure/caption. The remaining 55 added joins were **not exhaustively labeled**. These are assistant-reviewed diagnostic examples, not independent human ground truth or a corpus precision estimate.

- Eleven incorrect joins attach a new sentence after a complete sentence ending in `.` or `?`. Example: CERN Courier's statement ending “their properties is extremely challenging.” was merged with a new sentence beginning “The only hypernucleus observed so far ...”. Similar cases occur across magazines and research papers.
- Two incorrect joins attach a new sentence after a displayed equation whose period is inside `$$...$$`; a simple `endswith('.')` check misses both. The next atoms begin “Thus, ...” and “The coefficient ...”.
- The NVIDIA annual-report introduction ending “from a Fiscal 2023 base year:” was merged with the following bullet list. The two pieces are related, but they are not the same grammatical sentence under this pilot's narrow node-boundary rule.
- On Shannon's *Entropy* page 6, a paragraph ending “associated probabilities:” was joined directly to “Suppose successive ‘words’ ...”, **skipping the intervening table atom** that should carry the probabilities. The table itself remained outside evidence nodes.
- The valid flagged case is Shannon page 10: “At the left we have three” continues as “possibilities ...” after a figure and caption. A blanket ban on every non-body atom between text candidates would lose this real continuation.

The [seven-page frozen review evaluated on this run](../output/hybrid_49page_stress_run_20261007/frozen7_evaluation.json) matches the earlier small pilot exactly: hybrid joins both required same-sentence continuations versus baseline 0/2, retains both clear image-caption bindings, but adds one colon-to-list wrong merge, leaves the table out of evidence, and does not resolve the slide headline/photo context. The seven inputs were checked for exact atom/visual content and source-image hash equality before reusing those labels.

The visual-description limitation also recurs: the 208-pixel stained-glass crop is described with specific designer/manufacturer names that are not supported by its source caption and cannot be verified confidently from the crop. This is separate from boundary assembly and makes the free-form description unsuitable as factual evidence without a visibility check.

## Decision and next changes

The 49-page run succeeded operationally, but **the hybrid is not ready to replace the default node builder**. Keep its outputs as shadow diagnostics. The next bounded revision should first prevent new-sentence and colon-to-list merges while preserving legitimate cross-figure continuations, materialize table atoms with their captions as retrievable table nodes, then handle slide headlines and visual context. Visual descriptions should avoid transcribing text below a legibility threshold. Re-evaluate on independent source review before any broad promotion.
