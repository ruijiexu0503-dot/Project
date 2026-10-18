# Raw-block article-first diagnostic

2026-10-15, `feature/evidence-edges`. User-proposed order:

Parsing → multimodal description → article segmentation → evidence node generation → intra-article reading order → semantic edges.

CPU job **79759** implements the stages through reading order on the same CERN2022 spread used by **79721**. This is an opt-in diagnostic, not a replacement of the production entrypoint. New results go to `EvidenceNet/output/article_first_smoke_v1_20261015/`; legacy nodes, segmentation outputs and the frozen retrieval baseline remain unchanged. No new parsing or description inference is needed: existing Dolphin parsing and source-hashed Qwen descriptions are reused.

## Implementation

Entry: `EvidenceNet/scripts/run_article_first_pilot.py` (`prepare` or `run`). Inputs are the prepared `input_representation.json`, source page image and matching visual descriptions. It never reads assembled evidence nodes or old model article assignments. There are 54 parsing atoms (including 8 headings and 9 explicitly typed furniture atoms) plus 7 visual bundles; the model sees 44 raw non-title blocks and 8 structural titles. Every original atom, text fragment, visual and native component must be accounted for exactly once in evidence or explicit exclusions.

1. Assign raw blocks to independent articles, page context or unresolved ownership, with exact coverage of blocks and titles. At the same time, review block roles: BODY, CAPTION, TABLE, VISUAL, STRUCTURAL, PAGE_CONTEXT or UNRESOLVED. Original parser types/text are retained; corrections live in the model checkpoint. Parser-caption blocks may become BODY and parser paragraphs may become CAPTION or STRUCTURAL when supported by the page.
2. Compute Qwen3-Embedding-0.6B embeddings on CPU and use embedding/geometry ranks to propose body continuations and caption/visual links **only inside confirmed article groups**. Body candidate directions still use conservative parser-forward sentence guards; article-first segmentation alone does not solve all column-order problems. Candidate ranking is evidence discovery, not relation acceptance.
3. Qwen decides same-sentence composition and actual image-caption ownership, in bounded chunks. Caption links cannot absorb BODY content or cross article boundaries. Multiple image crops may share a caption and become one figure node; a visual may attach to at most one caption. Unknown ownership remains a separate unresolved node, never an automatically assigned neighbor. Failures stop assembly rather than accepting a fallback.
4. Build reading flows from newly generated nodes, inside the fixed article map. Titles/rubrics stay structural. Reading failure is reported separately; it does not undo valid article membership. No cross-page continuation or semantic edge inference is performed in this one-spread smoke test.

The 8192-character repeated-line annotation is shortened only in the model-facing prompt; its full source remains in the copied representation and source accounting. All substantive text blocks fit the prompt limit on this spread. Embedding input is tokenizer-truncated at 512 tokens; it is a candidate hint, while Qwen sees source text/page imagery.

## Predeclared source checks

Evaluate these against the original spread; do not feed them to the model:

- Four independent stories: Nobel recognition, open science, Milky Way history, Microcosm/Science Gateway.
- All eight titles retained with appropriate parent article; subsections do not create extra independent articles.
- A018 (previous N011) belongs to open science despite parser order placing it before that article's headline.
- A032 NEWS ANALYSIS is running page context, absent from evidence and reading chains.
- A004/A019/A031 are article rubrics, kept structurally rather than ordinary evidence paragraphs.
- A040 is a long narrative passage mislabeled caption by parsing: keep it as body evidence, not part of the galaxy image node.
- A044 is the actual Fermi-bubbles caption despite parser text typing; A045 is body. Do not merge them into one ordinary prose node.
- V_006/V_007 are toolbar/logo page chrome; verify against the actual image/crop rather than relying on IDs alone.
- Nobel portraits span V_001/V_002 with caption A014; inspect whether the model uses the caption's actual whole-figure scope.
- Image/table payloads and original descriptions remain available, with no source loss or duplicated ownership.

This smoke includes both a change of stage order and explicit block-role review. Any benefit cannot be attributed solely to order. It is development material already inspected during earlier experiments, not an independent holdout. After reviewing this spread, use additional magazines before promoting the order or submitting large tests.

## Validation and artifacts

**160 tests passed**: tracked regression suite plus article clustering and five new source-accounting/constraint tests. The new tests cover role correction without source mutation, exact fragment/visual/native coverage, multi-crop figure composition, blocking cross-article joins and BODY-to-visual attachment, article-scoped candidate retrieval, and retention of unresolved content. Source/crop preparation, Slurm syntax and whitespace checks passed before submission.

Outputs include `article_membership.json`, `candidates.json`, raw checkpointed `node_decisions/`, `evidence_nodes.jsonl`, `excluded_blocks.jsonl`, `title_assignments.json`, `reading.json`, `reading_edges.jsonl`, `summary.json`, and source/code/result manifests. New evidence IDs use an AF namespace; old node-level edge labels must not be copied to these nodes without a source-level mapping. `complete` means stage execution and source accounting, not expert-approved article quality; `reading_complete` is independent.

Submission: 32 CPU cores, 160 GB host memory, maximum 90 minutes. No GPU time is consumed. At submission, inference/source review has not completed.

## Result update

79759 completed in **22m17s**. Four articles/eight titles retained; raw-role review recovers A040 body text and excludes rubrics/header from evidence. One clear within-article continuation error remains (A023→A024 instead of A023→A018); Nobel caption scope is still incomplete. See [source review](ARTICLE_FIRST_79759_REVIEW.md). No production promotion or larger run yet.
