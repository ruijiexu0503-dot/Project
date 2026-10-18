# Article reconstruction smoke 79721 — source review

2026-10-15. CPU job COMPLETED, 6m45s, exit 0. Output: `EvidenceNet/output/hybrid_article_clustering_smoke_v3_20261015/`. One rendered input is a two-page magazine spread (printed pages 10–11); this is not a full-magazine evaluation.

Both membership and reading requests passed their structural validators on the first attempt. All 38 node labels and 8 structural title labels are accounted for: four article groups containing 32 nodes and one page-context group containing six nodes. There are 23 within-page NEXT proposals, no cross-page links. Structural success does not establish correct source ownership or complete reading order.

## Original spread checked

Reviewed the original spread at `assets/pages/shard_1_CERNCourier2022NovDec-digitaledition_page_0006.jpg` and all cluster labels/flows against the prepared source text and geometry.

- Four independent stories correspond to the four visible headlines: Nobel recognition; CERN open science; Milky Way history; Microcosm closure/Science Gateway. Their main text and visuals are separated at article level.
- All eight supplied titles are retained. UV surprise, Mysterious and Further reading stay with the Milky Way story; EDUCATION AND OUTREACH stays with the Microcosm story. These are structural titles, not new evidence nodes.
- Previously omitted N011 (research integrity, open infrastructure, research assessment, training/outreach) is assigned to the open-science story. Its body sequence is N013 → N014 → N015 → N011 → N016 → N017, consistent with the columns and text continuation.
- Toolbar N037 and CERN footer logo N038 are page context, with no article ID or reading edges. N006/N007/N024/N030 unsupported annotation content is also retained as page context; its model-selected exclusion is a proposal, not parser correction.

## Remaining errors and limits

1. **Header contamination:** N019 NEWS ANALYSIS is the right running header, but is assigned to the Milky Way story and chained between N018 ASTROWATCH and N020 first paragraph. Page-context exclusion remains incomplete.
2. **Rubrics in body:** N001 QUANTUM INFORMATION, N012 OPEN SCIENCE and N018 ASTROWATCH are article-associated rubrics but currently become body-chain nodes. They should remain structural context, not ordinary body paragraphs.
3. **Upstream body/caption composition error:** N035 combines the Milky Way illustration with a long piece of right-column body text mislabeled as caption. Its article ownership is plausible, but the whole node is in a separate caption flow, so that body content is absent from the body chain. N026 also combines an actual figure caption with body text. Atomic-node reading order cannot fully represent the original page in this state.
4. Pure visuals N033 and N034 are represented as one-node caption flows. These produce no NEXT edges, but are not actual caption text and should not be interpreted as validated caption roles.
5. This is one spread using already generated hybrid nodes. It tests membership/reading decoupling and source coverage only. It does not test parsing-block-first segmentation, full-magazine continuation or independently scored segmentation accuracy.

## Consequence

The coverage failure and failure coupling are repaired in this smoke run; semantic role quality is not fully repaired. Next architecture experiment should use parsing text/visual/table blocks and their geometry/descriptions to establish article ownership before evidence-node assembly. Confirmed article boundaries should constrain node generation; uncertain ownership must remain explicit. Body/caption role errors need separate checking because article boundaries alone cannot prevent same-article body text being absorbed into visual nodes. Preserve this run as the node-first comparison, rather than relabeling it as evidence for the new order. No larger run or new pipeline order is launched by this status review.
