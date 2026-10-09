# Matched node-generation pilot: Qwen models vs embedding + geometry

Date: 2026-10-06. This is a three-page **node-generation** comparison, not the earlier visual-to-text candidate ranking experiment. It is a shadow run; no production node or edge output was changed.

## Fixed input and arms

Pages: `DLRmagazine_176_EN/page_0009`, `gw150914_detection/page_0004`, and `DLRmagazine_176_EN/page_0017`. They cover two-caption magazine layout, a scientific diagram/caption and cross-block sentence continuation, and a full-page photograph with overlay article text. Qwen3.5-9B and Qwen3.6-35B-A3B were run against the *exact prepared Qwen3.5-35B-A3B input files*: same prompt bytes, annotated page and native PDF component sheets; input hashes are saved per page. Older Qwen3.5-35B-A3B and Qwen3.5-122B-A10B results use identical atoms/geometry/image bytes, and their prompts match after normalizing model-specific image paths.

The embedding+geometry arm is a **Qwen-assisted deterministic baseline**: parser atoms are initial text nodes; conservative rules preserve structural atoms and keep source fragments addressable; Qwen3.5-35B-A3B describes only each visual crop; Qwen3-Embedding-0.6B and source-member geometry score candidate caption attachment and possible adjacent text merges. It does **not** ask Qwen to assemble nodes. It sees crop-only descriptions rather than the full native component sheets, so modality evidence and computation cost are not identical to Qwen assembly. This arm passed its source coverage check, while the Qwen arms were checked against the stricter Qwen assembly schema. These checks must not be treated as equivalent semantic scores.

The [source review labels](../config/reviews/node_generation/matched_node_benchmark_review_20261006.json) cover all source atoms on these pages: structural vs body vs caption, three explicit visual-caption pairs, and two required across-block sentence continuations. The reviewer is the assistant, not independent human ground truth. Four body paragraphs in the full-page-photo article are reviewed as separable evidence spans, except the middle pair that completes one sentence. Article ownership, paragraph-internal boundaries, visual description truthfulness, and table nodes are **not** scored.

## Results

| Arm | Validation passed | Reviewed structural atoms put in nodes | Wrong body-pair merges | Required continuations missed | Correct caption pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3.5-9B | 0/3 | 9 | 9 | 1/2 | 2/3 |
| Qwen3.5-35B-A3B | 3/3 | 6 | 5 | 1/2 | 3/3 |
| Qwen3.5-122B-A10B | 2/3 | 1 | 5 | 1/2 | 3/3 |
| Qwen3.6-35B-A3B | 2/3 | 5 | 5 | 0/2 | 3/3 |
| Parser + embedding + geometry | 3/3 source coverage | 1 | 0 | 2/2 | 3/3 |

All arms materialized each reviewed body atom exactly once. The structural, merge and continuation counts are source-review diagnostics, not a general precision estimate. The Qwen validation column reflects each model's assembly-schema validation. The deterministic arm's validation is **source coverage only**.

Concrete examples:

- On DLR page 9, 9B put the title, deck, byline, body paragraphs, footer and a photo into one composite node. It also missed the correct `V008`–`D007` caption binding; the other arms bound both captions correctly. Qwen3.5-122B had no reviewed role or boundary error on this particular page. Qwen3.5-35B and Qwen3.6-35B both turned section headings into evidence nodes; 35B also merged an internal `DLR` label into prose. The embedding+geometry arm treated the deck `D001` as prose.
- On GW page 4, `D006` ends with “their” and `D007` continues “suspensions: …”. Qwen3.6-35B joined them correctly. The other Qwen models and the conservative baseline split the sentence across nodes.
- On DLR page 17, all four Qwen models combined four article text blocks with the full-page photograph into one composite node. `PDFTEXT_002` and `PDFTEXT_003` belong together because one sentence crosses the block boundary, but `PDFTEXT_001` and `PDFTEXT_004` carry separate claims. The baseline kept the photo and text separate, avoiding the broad composite, yet incorrectly split the `002`–`003` continuation. Whether a narrower image/text relation should be added is not labeled here.

The three correct visual-caption bindings in the deterministic arm are **not evidence of embedding gain**: geometry alone picks the same three captions, and the arm made no embedding-triggered text merge in this sample. The prior [visual/table ranking pilot](node_embedding_geometry_pilot_2026-10-06.md) showed mixed effects from embedding on harder candidate sets; it did not test node boundaries.

## Decision

Keep the parser/source-atom and geometry scaffold as the safe starting point. Qwen3.5-35B-A3B is the most reliable **Qwen assembly reference** in this matched sample because it passed the schema on all three pages, but its output still needs a semantic gate for headings, source labels, sentence continuations, and overlarge composites. The 122B is not a clear upgrade: it handled DLR page 9 particularly well but failed one of these three pages, and its earlier four-page run had an out-of-memory failure on the larger GW figure. 9B is too unreliable for unsupervised node assembly here. Qwen3.6 caught both continuations but failed the DLR page 9 contract and still overmerged the photo article; keep it as a challenger, not a default.

Next iteration: add a source-addressed continuation detector before node assembly; use Qwen only for ambiguous article/reading-flow and multimodal grouping decisions; validate every source fragment and structural role after assembly. A larger independent review must include tables and ambiguous multi-image spreads before choosing a production default. The current three pages do not show whether text embedding improves node generation over geometry alone.

Machine-readable [evaluation](../output/matched_node_benchmark_20261006/evaluation.json), Qwen [runner](../scripts/run_matched_qwen_node_benchmark.py), deterministic [runner](../scripts/run_embedding_geometry_node_baseline.py), and [review labels](../config/reviews/node_generation/matched_node_benchmark_review_20261006.json). New dev jobs: 9B `53083`, Qwen3.6 `53084` (timed out after page 9) and `53226` (finished remaining pages), deterministic baseline `53087` and corrected reassembly `53227`. Dependent job `53271` found the final page complete and ran no additional inference.
