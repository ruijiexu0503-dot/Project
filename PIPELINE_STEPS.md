# Pipeline steps

## 1. Parsing

Run the parser with checkpoint/resume enabled. A document enters the canonical
pool only when its expected pages have complete summaries and traceable page
images. Partial documents are parked, not counted as complete.

## 2. Canonical EvidenceNodes

Prepare parser output with `EvidenceNet/scripts/prepare_vldocir_nodes.py`, then
run `EvidenceNet/scripts/run_vldocir_nodes.py` in four resumable stages:

```text
describe -> candidates -> decide -> assemble
```

Canonical Node IDs are immutable within a corpus snapshot. Node generation may
run on CUDA or CPU, but the large Qwen model makes CPU execution a fallback.

## 3. QA generation and automatic review

Candidate discovery samples from canonical node pools. QA generation must not
invent unresolved Evidence Unit IDs. Automatic review checks question quality,
answer claims, evidence sufficiency and necessity, duplicates, and single-node
shortcuts. Cross-document QA additionally requires evidence from each stated
document to be necessary.

The target release distribution is 20% single-node, 30% cross-page, and 50%
cross-document. The eventual 300-example release additionally targets 35%
two-document and 15% three-or-more-document questions.

## 4. Gold export

Export only records with resolvable Gold Node IDs, passing source/mapping gates,
passing claim grounding and necessity, no known shortcut, and no severe source
anomaly. Preserve every prior draft and Gold version; exports are append-only or
written to a new versioned directory.

## 5. Training and evaluation

`prepare_gold200_split.py` creates a document-component-disjoint split.
`train_gold_frozen_ranker.py` embeds queries/evidence with the frozen Qwen3
embedding model and trains `DynamicEdgeRanker`. New-document validation must be
reported separately from the current 19-example held-out component split.
