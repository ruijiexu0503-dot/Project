# v7 flow and anchor recovery: isolated shadow experiment

Date: 2026-10-04. Source: frozen `relation_first_corpus_shadow_v7_cpu` output.
Parser route: Dolphin-v2, with the existing DLR native visual override where applicable.
Original model: Qwen3.5-35B-A3B on CPU. This experiment does not change that output,
the parser, or the production graph.

Archival note (2026-10-04): the standalone exploratory scripts used below are
now under `_archive/2026-10-04-superseded-scripts/`. Their integrated successors
remain active. To reproduce these historical commands, first preview/restore
with `python3 current/restore_superseded_scripts.py [--apply]`; see
[`current/GIT_CLEANUP.md`](../../current/GIT_CLEANUP.md). Frozen results stay at
the original output paths.

## Frozen-output replay

Run:

```bash
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/experiment_flow_anchor_recovery.py \
  --source EvidenceNet/output/relation_first_corpus_shadow_v7_cpu \
  --output EvidenceNet/output/flow_anchor_recovery_shadow_NEW
```

Retained result: `EvidenceNet/output/flow_anchor_recovery_shadow_v4_20261004/`.
The 15 failed flow pages contain 14 parseable model replies. ID deduplication,
removal of nonexistent IDs/invalid continuations, and an explicit quarantine for
unassigned source members yield 15/15 **bookkeeping-valid** flows. Three of the
pages have zero parser text atoms; these take a visual-only fallback. Visible text
on such pages still needs independent OCR recovery. The one unparseable reply is
among these three pages.

This is **not** 15/15 article, reading-order, or semantic accuracy. The quarantine
is a source-preserving disposition, not a page-furniture judgment. The output
records unresolved IDs and uses `semantic_validated: false`. A downstream consumer
must not treat a bookkeeping-valid flow with unresolved members as completed
reconstruction.

Seven local image/text proposals were rejected for anchor mismatch. Two have a
valid primary source anchor and invalid extra `supporting_anchors`; the replay
stores their validated primary-anchor versions as unverified review candidates.
The other five still fail and are not salvaged. The original rejected proposals
remain unchanged.

## Bounded dev GPU adjudication

Jobs 44577 and 44578 used `dev-gpu-h100`, two GPUs, Qwen3.5-35B-A3B and one
bounded model call per page. The Slurm wall limits were 14m30s; actual wall times
were 2m08s and 1m14s. Outputs are in `duplicate_assignment_dev_44577/` and
`duplicate_assignment_dev_44578/`. Job 44577 reviewed 2 pages/6 duplicate IDs;
job 44578 reviewed 4 pages/11 duplicate IDs.

The prompt offered only the occurrences already present in the frozen invalid
flow. It did not ask the model to rebuild entire pages. The model selected a
unique occurrence for every duplicate. One reply omitted the requested outer
`choices` wrapper but was otherwise an exact ID-to-choice map. The replay
normalizes that wrapper without changing any choices:

```bash
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/replay_duplicate_assignment_gpu.py \
  --run EvidenceNet/output/duplicate_assignment_dev_44577 \
  --run EvidenceNet/output/duplicate_assignment_dev_44578 \
  --output EvidenceNet/output/duplicate_assignment_replay_NEW
```

Retained replay: `EvidenceNet/output/duplicate_assignment_replay_20261004/`.
After this schema normalization, 5/6 pages pass flow coverage directly. The
sixth, CERN Courier 2025 p6, still omits four source fragments; its repaired
flow passes bookkeeping validation only because those four remain explicitly
unresolved. Thus 6/6 are structurally addressable and **0/6 have independent
semantic validation**.

The model moved the title and section heading on Hallmarks of Aging p18 into
structural entries. On CLAD contents p6 it assigned four photos to the page
context instead of the content item containing photo-credit text; this agrees
with a manual view of the source page. The remaining choices are available in
the replay's `summary.json` for review. These observations do not establish
corpus-level accuracy or validate article ownership and reading order.

## Follow-up decision gate

Review a balanced sample of corrected and previously successful pages for
article ownership, order, missing evidence, caption association, and source
anchors. Keep denominator 49 pages, report unresolved members separately,
and compare against the frozen v7 baseline before integrating any repair into
the active pipeline. The two salvaged caption candidates also need source-page
semantic review before acceptance.

Verification: 14 existing relation-first tests passed; the replayed 15 flows
were independently revalidated against their frozen source inventories. Both
GPU jobs exited successfully. No production graph or baseline artifact changed.

## Matched v7 dense candidate diagnostic

Jobs 44581 and 44582 completed on one H100 in 14s and 10s respectively, using
the local Qwen3-Embedding-0.6B checkpoint. Both used exact cosine retrieval,
last-token pooling, no query instruction, and top 5 outgoing candidates per
unit/scope before symmetric deduplication. Inputs remain the frozen v7 adapter
snapshot; repaired flows above were not mixed into this comparison.

| Input | Eligible units | Lexical pairs | Dense pairs | Overlap |
|---|---:|---:|---:|---:|
| Text plus attributed visual text proxies | 296 | 2,403 | 2,870 | 1,135 |
| Text-only ablation | 271 | 2,174 | 2,596 | 1,054 |

The cross-document subset is more different: 1,249 lexical versus 1,251 dense
pairs overlap on 191 pairs. Removing visual endpoints still gives only 180
overlapping pairs out of 1,125 lexical and 1,141 dense cross-document pairs.
Thus the candidate-set difference persists without visual text proxies.
Neither comparison measures semantic precision or recall. The final unique
candidate budgets differ, and no independent relation labels have been added.
In the text-only arm, lexical pairs were filtered from the existing ranked
snapshot while dense pairs were reranked on text-only units; this arm is a
candidate diagnostic rather than a fully matched retriever benchmark.

Three text units exceed the 512-token encoding limit (maximum 5,209 tokens).
Both runs record truncation; longer-context/windowed retrieval remains a
separate experiment. No visual pixels are encoded by these text embeddings.

Outputs: `EdgeGeneration/output/v7_dense_candidate_dev_44581/` and
`EdgeGeneration/output/v7_dense_text_only_dev_44582/`. Each contains 108
deterministically sampled pairs covering lexical-only, dense-only and shared
routes across three scopes. All review labels are null. The first run also
has `review_sample_with_provenance.jsonl`, which adds explicit text/proxy source
and page-status fields. Pair IDs, deduplication, exclusion of known local
relations and absence of visual endpoints in the text-only output were checked.

Next useful comparison: independently review these samples, then compare
lexical/dense/combined policies at a fixed verification budget with per-scope
precision and a separately annotated recall set. Candidate-count growth alone
is not evidence of better edge generation.
