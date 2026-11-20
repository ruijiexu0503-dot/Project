# Article-first pilot 79759: completed, source-level review

2026-10-15. CPU job **79759 COMPLETED**, exit 0, **22m17s**. Frozen output: `EvidenceNet/output/article_first_smoke_v1_20261015/`. The source is the same CERN2022 printed pp10–11 spread as node-first **79721**. Raw output and result manifest are retained unchanged; this review does not rewrite its `source_review_complete=false` field or treat structural completion as an accuracy measurement.

## Execution and coverage

Qwen assigned 44 raw blocks and 8 titles to four articles plus page context, before evidence assembly. First membership response failed the consistency check for visual N043 (toolbar); the retry passed. Node-composition chunks and reading passed on their first attempts. Embedding+geometry produced 15 body-pair and four caption-link candidates; Qwen accepted six body joins and three caption links. Final output has **29 evidence nodes**, four explicitly unresolved annotation nodes, and 15 NEXT proposals. All original atoms, fragments, visual bundles and native components are accounted for exactly once in evidence or exclusions. No cross-page or semantic-edge evaluation occurred.

These counts cannot be interpreted as better/worse retrieval or compared as node accuracy percentages with the 38-node input to 79721: structural exclusions and newly composed nodes change the units.

## Source review against original spread

The original source image was inspected in the preceding comparison, and this review checked all raw article groups, corrected roles, source atom texts, six accepted body joins, all caption decisions and resulting reading chains.

| Predeclared check | Observed result |
| --- | --- |
| Four independent stories and eight structural titles | Preserved; subsection titles stay with their parent article. |
| A018 research-integrity paragraph belongs to open science | Correct article, retained as BODY. |
| A032 NEWS ANALYSIS absent from evidence/reading | Improved: marked STRUCTURAL and excluded; still associated with G3 in raw membership instead of PAGE_CONTEXT. Exact page-context role remains wrong. |
| A004/A019/A031 rubrics kept structural | Correctly excluded from evidence/body chains. |
| A040 full right-column narrative incorrectly parser-typed caption | Corrected to BODY; standalone TEXT evidence; enters the galaxy body chain after A042. No longer absorbed into the image node. |
| A044 actual figure caption vs A045 body | Separated: A044 becomes caption attached to V004; A045 stays body evidence. |
| V006/V007 navigation/logo | Page context, excluded from evidence and reading. |
| A014 Nobel caption describes all three portraits | Not solved: attached only to V002 (two portraits), while V001 (first portrait) remains a separate VISUAL. Caption scope is still incomplete. |
| Unsupported annotations A011/A013/A039/A055 | Retained as four unresolved nodes, with no confirmed article ID or reading chain. They are not silently dropped. |

## Accepted body composition review

- **A015 + A016:** appropriate source word/sentence continuation (`exper-` / `iments`).
- **A022 + A023:** appropriate column continuation (`which make all` / `research papers ...`).
- **A036 + A037:** appropriate telescope-name continuation (`...collected by the` / `Hubble Space Telescope...`).
- **A051 + A052:** appropriate source continuation (`EURO-` / `forum network`).
- **A023 + A024:** incorrect. A023 ends `open-source software and hardware,`; the real continuation is A018 (`research integrity, open infrastructure ...`). A024 starts a new quotation about publication of the policy. Qwen accepts this wrong same-sentence join, creating one A022/A023/A024 node. The reading stage cannot place A018 inside that immutable node, so it orders the quotation before the true continuation.
- **A008 + A009:** unreliable source. A008 contains corrupted OCR/address material and an invented-looking radiation phrase, so exact-source concatenation does not restore the printed `obtain-` / `ing measurements` continuation. Do not count this as a verified recovered sentence; parsing/OCR quality remains a separate issue.

Thus six accepted joins contain four clearly appropriate joins, one clearly wrong join and one source-corrupted uncertain join. This small development diagnosis is not a population precision estimate.

## Why the wrong join happened

The candidate generator still uses parser-forward order and a page-wide intervening-heading guard. A023→A018 is backwards in parser order, so it is never proposed; A023→A024 is proposed. The sentence guard permits comma endings, and Qwen accepts a new quoted paragraph as continuation despite an explicit same-sentence prompt. Article segmentation prevents cross-article composition, but does not establish the correct within-article column traversal. This is a residual candidate/assembly problem, not evidence that the four article boundaries are wrong.

## Next bounded corrections before scaling

Keep the article-first branch experimental. Retain the improvements in raw-block role review and boundary constraints, but fix composition before broad runs:

1. Discover continuation candidates in both parser directions within each article, using source geometry and unfinished sentence fragments; record actual source traversal instead of automatically sorting merged members by parser order. Prevent branches, cycles and crossing article/heading boundaries without treating unrelated parser-intervening headings as proof.
2. Block clearly new quotation starts after comma-ended unrelated prose unless source continuity is established. Use the observed A023/A024 error and true A023/A018 continuation as regression examples, alongside the other four valid joins; avoid indiscriminate comma bans.
3. Review shared-caption figure ownership as a complete multi-crop group; rejecting V001 while assigning the full three-person caption to V002 must remain visible as incomplete scope.
4. Keep damaged OCR explicitly reviewable rather than silently inferring missing source words.

The new run changes both stage order and role review, so these improvements cannot be attributed to order alone. One previously inspected magazine spread does not establish performance on other magazines or complete-document article continuation. No larger submission or production pipeline switch is made by this result review.
