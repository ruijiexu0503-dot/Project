# Article segmentation vs raw reading order: paired comparison

2026-10-15. User requested both optimization and a direct comparison of which stage order works better and remains stable. CPU array **79854** runs four page workers (maximum two simultaneously); report job **79855** runs after all workers finish, including failed workers. Output: `EvidenceNet/output/article_reading_order_comparison_v1_20261015/`. The historical 79759 output/code is retained; this comparison uses a new opt-in driver and does not switch the production pipeline.

## Two orders, common inputs and policy

Both arms reuse frozen Dolphin parsing, source images, Qwen visual descriptions, Qwen3.5-35B-A3B and Qwen3-Embedding-0.6B. Each page gets one common role review **without article assignments or reading suggestions**, shared by both arms. This isolates the ordering comparison from role-extraction differences. Both later membership requests copy these same frozen roles exactly.

- **Article first:** roles → Qwen article membership → Qwen raw-block reading flows with membership proposal → evidence-node composition → node reading edges.
- **Reading first:** roles → Qwen raw-block reading flows without article proposal → Qwen article membership with reading proposal → evidence-node composition → node reading edges.

The reading proposal never defines article identity automatically. Each stage sees the original text, titles, geometry and page image; Qwen may itself use layout/story cues internally, so this compares implemented stage interfaces, not an assertion about hidden model reasoning. Prompts/schema/validators for each task, retry limit (two), token budget, model/backend, common roles and downstream composition are the same in both arms except the earlier stage's supplied proposal.

Reading output must explicitly account for every eligible raw block, either in a typed flow or unsequenced. It cannot substitute visuals/tables for body text or include known structural/page-context blocks in body chains. After membership, article ownership splits any crossing flow; **no shortcut is created around a foreign or unresolved intervening block**. Pre-filter cross-article adjacency counts remain visible as errors.

## Optimization tested in both arms

1. Body composition uses only consecutive raw blocks in same-article body flows, rather than parser-forward order. Correct source traversal is retained when composing text; merged atoms are not automatically re-sorted by parser ID. Paths must have one predecessor/successor and no cycles or branches.
2. Closed sentences and new quoted paragraphs are kept separate. The quote-start guard is conservative and may miss legitimate quotation continuations; the report must not assume that every blocked pair is a corrected error. Source text is preserved; no damaged OCR is silently reconstructed.
3. Caption ownership is reviewed jointly over all local same-article visual crops, with embedding/geometry hints. Multi-crop figures can be composed as a whole. PARTIAL/UNCERTAIN scope is explicit and remains uncombined instead of attaching a full caption to one known part. Qwen may still falsely declare complete scope; source-reviewed figure references check that separately.
4. Exact atom, fragment, visual and native-component accounting remains mandatory. Metadata exclusions retain original source IDs. Unknown content stays unresolved.

The observed A023→A018 continuation is now eligible despite reversed parser order; A023→A024's new quotation is blocked on the actual frozen source. These are candidate-rule regressions, **not new-model success claims**. Source-corrupted A008/A009 remains an uncertainty, not a positive composition reference.

## Materials and robustness conditions

Four source renders, including multi-page spreads:

| Page index | Source | Challenge |
| --- | --- | --- |
| 0 | CERN Courier 2022 Nov/Dec, source page_0006 (printed pp10–11) | Four articles, multi-column return, mixed caption/body types, split portrait figure; known development case. |
| 1 | DLR magazine 176, source page_0009 (printed pp16–17) | One feature with subsections, boxed explanations and overlapping/large visual crops. |
| 2 | CLADmag 2025 H2, source page_0063 | Two independent named stadium/project items, overlaid text and images. Item-level article units are declared explicitly for this list. |
| 3 | CERN Courier 2025 Jan/Feb, source page_0006 (printed pp10–11) | Three article items, repeated figure numbers, continuation text and pull quotes. |

Each arm runs with the original raw-node/title list and the same lists reversed, keeping labels, text, geometry and images unchanged. Thus **4 renders × 2 orders × 2 presentations = 16 conditions**. Arm execution order is counterbalanced across page and presentation. Generation is greedy (`do_sample=false`). This tests sensitivity to input list order given a common role review; it does **not** measure stochastic seed reproducibility, role-review stability, independent holdout quality or full-document cross-page identity. Additional materials have not been used to tune these new composition rules, but all belong to the previously used corpus.

## Evaluation fixed before inference

All four source images were inspected before preparing the run. Partial source-level development references (`page_*/reference.json`) and the source/code manifests are frozen before submission and never inserted into model prompts. References specify expected co-membership of selected source atoms/visuals, structural-title ownership, reading precedence, known continuations, forbidden joins, metadata exclusions and complete figure scope.

- Article co-membership TP/FP/FN/TN and reference-node assignment coverage; both under-splitting and over-splitting remain visible.
- Title ownership against source article anchors.
- Reading precedence recovered/reversed, measured by reachability over BODY flows; this is not exact adjacency accuracy. Missing links count as unrecovered. Raw cross-article adjacency counts are also retained.
- Known continuation recovery, the observed forbidden join, and full caption/figure scope.
- Metadata exclusion recovery, source accounting, unresolved nodes, invalid attempts and failed conditions.
- Stability between presentations using source IDs rather than arbitrary generated group labels: article-pair Jaccard, title-membership Jaccard, reading-adjacency Jaccard, node-composition Jaccard and assigned-source coverage. Two empty sets produce no Jaccard score rather than automatic perfect stability.
- Runtime and model calls; per-condition time excludes common model loading, embedding and role review. Common costs apply to both arms. Partial references are assistant-reviewed development annotations, not expert gold; unannotated errors need source inspection.

Choose based on quality **and coverage first**, then presentation robustness, then cost. A method cannot win by creating no links, assigning no article IDs, excluding substantive content, or merely passing schema validation. If there is no consistent winner across materials, report that rather than claiming superiority from a tiny average difference. Counts pooled over presentations reuse the same source references and are not independent document samples. Review the actual nodes and figures before promoting either order.

## Validation and execution

**170 tests passed**, including the tracked suite and new checks for backward parser traversal with preserved text order, no branch/cycle composition, immutable common roles, partial vs complete multi-crop figures, same downstream candidate policy across presentation orders, avoiding shortcuts across article boundaries, evaluation error accounting and incomplete-run reporting. Preparation validated all description crop hashes, source/code hashes and referenced source IDs. Slurm syntax and whitespace checks passed.

Each CPU worker requests 32 cores / 160 GB and at most three hours, reusing a loaded Qwen model for all four conditions on that page. This is a wall-time ceiling, not a completion estimate. Results are checkpointed per stage and condition. The automatic report writes `comparison.json` after the array ends; missing/failed conditions cannot be reported as a complete experiment. No semantic-edge or retrieval-quality claim is made by this comparison.

Implementation: `EvidenceNet/scripts/compare_article_reading_order.py`; shared guards: `EvidenceNet/evidence_graph/article_order.py`. Generated data, checkpoints and Slurm launchers follow the existing ignored output/slurm folders. Production integration remains pending result review.

## Failed V1 and bounded V2 repair

79854 ended with all 16 conditions incomplete before final evaluation. No order-quality or stability winner can be reported. See [failure review](ARTICLE_ORDER_79854_FAILURE_REVIEW.md). V2 separates content role from ownership uncertainty and normalizes already-excluded metadata explicitly; only CLAD smoke 80079 has been submitted, not the full comparison.

At the user's request, [GPU smoke 80082](ARTICLE_ORDER_GPU_80082.md) replaced
CPU 80079 after starting on H100 dev. It runs the same four CLAD conditions
in a separate output directory, with a one-hour resource limit.

80082 finished after 4m46s: all four CLAD conditions passed membership and
reading with identical source relations, then failed composition validation.
The [GPU review](ARTICLE_ORDER_GPU_80082.md) records invented caption/pair
outputs and one true continuation blocked by the quote-start candidate guard.
No final node results or overall order winner are available.
