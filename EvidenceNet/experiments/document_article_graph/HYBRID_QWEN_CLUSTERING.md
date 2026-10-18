# Hybrid EvidenceNode article reconstruction

2026-10-15, branch `feature/evidence-edges`. This closes the missing document-reconstruction stage in the hybrid pipeline entrypoint. It follows the earlier Qwen page-grouping approach, rather than classifying adjacent pairs as if parser order were already a single article. Initial CPU pilot **79582** failed coverage and was stopped; V3 one-page repair verification is job **79721**, with model/source review pending.

Update: 79582 was stopped after about 45 minutes. All six checkpointed pages failed coverage after two attempts; this was not six successful article reconstructions. CPU accounting indicated roughly 31 of 32 cores active. Inspection found many omitted footer/navigation/logo nodes, some unsupported annotation OCR, and at least one omitted substantive paragraph (CERN2022 page6 N011). The initial schema forced all of these into article groups and retry errors did not list missing IDs. This is both an input-role/protocol issue and a coverage failure, not just CPU speed.

V2 explicitly supports page-context groups and retained unassigned nodes. Page-context nodes have no article ID or NEXT edges, are exported in `excluded_non_evidence_units.jsonl`, and carry model-role review provenance. Truly unresolved content remains visible and unassigned rather than being silently discarded. Coverage errors enumerate missing/duplicate IDs. Raw V1 attempts are preserved unchanged. A new single-page smoke test uses the same problematic CERN2022 page6 before any further 11-page rerun; 151 tests pass after this correction. No speedup or corrected ownership accuracy has yet been measured.

## V3: separate membership from reading (2026-10-15)

V2 smoke **79683** failed after 13m01s. Its first response placed N011 in G2's sidebar flow without including N011 in G2's members; its retry removed that flow but omitted N011 entirely. No valid articles were exported. Both raw attempts remain unchanged in the V2 output directory.

V3 changes the protocol rather than automatically filling missing ownership:

- The first Qwen request assigns article members and structural titles only (`flows=[]`). Exact node/title coverage remains mandatory. Nodes may be explicitly unresolved; the validator never assigns a missing paragraph to the nearest article or silently demotes it to page context.
- The second request builds reading flows inside the **fixed** validated groups. It cannot alter membership or titles. Bad flows are checkpointed independently and create `reading_issues.jsonl`; they do not invalidate a valid article map or create guessed NEXT edges.
- Retry input includes the preceding full response and the exact validation error, including missing node labels. Both model attempts remain recorded.
- `article_membership_complete` and `reading_complete` are separate summary fields; `article_graph_manifest.json` exposes `ready_for_downstream` for article membership and `reading_ready` for reading edges. These flags measure structural completion, not independently verified ownership accuracy.

Verification: **16 related tests passed**, including regressions for dropped substantive nodes, cross-article flows, immutable membership during reading, retry context, partial reading failure, source-preserving materialization, cross-page continuation constraints and document entrypoint integration. The full tracked regression suite plus the updated article tests also passed: **155 tests**. Source preparation/audit and Slurm syntax checks passed.

CPU job **79721** re-runs exactly the problematic CERN2022 page6 into `hybrid_article_clustering_smoke_v3_20261015`. It has 38 input nodes and 8 structural titles. Review must check N011 belongs to the open-science story, distinct headlines form separate articles, subsections remain with their parent story, and toolbar/logo/running-header content is excluded. No corrected model ownership accuracy is claimed before this run and source review. Do not expand to the 11-page pilot yet.

## Actual stage order

`run_vldocir_nodes.py document` runs describe → embedding/geometry candidates → Qwen node decisions → assemble/source audit for every batch, then runs document-wide article reconstruction. Existing four batch commands remain compatible, and still build nodes only. Article reconstruction waits for all selected source pages; it cannot be invoked with `--batch`.

Already assembled nodes can be reused without regenerating them:

```bash
PYTHONPATH=EvidenceNet python EvidenceNet/scripts/run_vldocir_nodes.py articles \
  --source EvidenceNet/output/hybrid_49page_stress_prepared_20261007 \
  --output EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry \
  --article-output EvidenceNet/output/hybrid_article_clustering_magazines_20261015 \
  --article-device cpu \
  --include-document CERNCourier2022NovDec-digitaledition \
  --include-document CERNCourier2025JanFeb-digitaledition \
  --include-document CERNCourier2026MayJun-digitaledition \
  --include-document DLRmagazine_176_EN \
  --include-document detr --single-document detr
```

On GPU-equipped runs, the integrated `document` command accepts the same source/output and article options, omitting `--include-document` to reconstruct all documents. Node-generation stages retain their existing GPU requirements; `--article-device cpu` controls only article reconstruction. The current CPU trial reuses audited nodes and does not rerun parsing or node generation.

## Clustering and boundaries

- Page-level Qwen input contains current immutable node IDs behind short selectable labels, original text/captions/tables, per-visual Qwen descriptions, geometry, every structural title and the source page image. It does not reuse legacy segmentation suggestions or fuzzy text mappings.
- The page output partitions every eligible node exactly once. Each title must belong to a group or be explicitly retained as page context. Titles remain structural records, never new evidence endpoints. Empty/metadata-only nodes retain explicit exclusion status.
- Independent top-level stories stay separate, even when sharing topics or institutions. Section headings do not automatically start articles. Body, caption, footnote and sidebar reading flows stay separate; visual/table/caption-only nodes cannot silently become body continuations. Conflicted immutable nodes stay unresolved instead of being split or assigned arbitrarily.
- Cross-page Qwen review uses current page clusters and the most recent original evidence of earlier article candidates within three source-page indices in the same document. It requires an owned original supplied node/quote at each endpoint to merge identity. A shared subject alone is insufficient. Different current-page clusters cannot both be merged into the same prior article, avoiding a transitive bridge that would undo page boundaries.
- Article identity and reading adjacency are distinct. The current input adapter cannot establish authoritative physical-page adjacency from all legacy `existing_render_page` labels, so cross-page NEXT proposals are disabled (`reading_adjacency_verified=false`). Same-article identity can still be linked when grounded. Within-page NEXT remains a Qwen reading-flow proposal. This stage does not assert SAME_SENTENCE or semantic relations.
- Known single-work profiles are explicit `--single-document` arguments; they are not inferred from topical similarity or filename heuristics. They preserve one document-level article without automatically claiming cross-page reading adjacency. Other inputs default to multi-item clustering.

## Outputs and downstream contract

`units.jsonl` preserves node IDs and members, adding article metadata. `article_assignments.jsonl`, `article_clusters.jsonl` and `articles.jsonl` contain exact membership and cluster evidence. `title_assignments.jsonl` has globally namespaced title IDs plus original per-page title IDs. `reading_edges.jsonl` is separate from semantic edges; `reading_issues.jsonl` reports independent flow failures. `eligibility.json`, `issues.jsonl`, page inputs, raw model attempts and source/code hashes are retained.

`summary.json` and `article_graph_manifest.json` report whether the structural stage completed. Failures preserve partial exports, return a nonzero exit and mark `ready_for_downstream=false`; downstream edge work must not treat such an output as an accepted full article map. `PAGE_LOCAL_ONLY` remains provisional; `QWEN_CROSS_PAGE_LINKED` means a model-grounded continuation, not expert-verified segmentation. Checkpoint hashes prevent reuse with changed prompts, images or node inputs.

The pilot covers 11 pages from three CERN issues, DLR magazine and DETR: 208 eligible evidence nodes and 39 structural titles. Sampling is sparse and cannot measure complete-document continuation recall. The earlier `hybrid_article_clustering_pilot_v1_20261015` directory is preparation-only and has no model results; the active run writes to `hybrid_article_clustering_magazines_20261015`.

## Validation and promotion

150 tests pass: the 145 tracked tests plus five focused tests covering full title/node ownership, cannot-link constraints, endpoint-owned continuation quotes, source-page adjacency guards, immutable node preservation, globally unique title IDs, and the integrated entrypoint running reconstruction after all node batches. The actual 11-page preparation and all selected source audits passed; Slurm syntax and whitespace checks passed.

These checks establish integration and structural/source accounting, not semantic ownership accuracy. Inspect each page's clusters against the original spread, particularly independent headlines, captions attached to the wrong story and any continuation decisions. The frozen VL-DocIR no-edge baseline is not rewritten. No claim of solved full-magazine segmentation is made before model output review.

V3 smoke result: **79721 completed in 6m45s**. Four article groups, eight assigned titles, no omitted nodes; N011 recovered. Original-spread review still found a running header in the Milky Way body chain and upstream body/caption composition errors. See [source review](ARTICLE_SMOKE_79721_REVIEW.md). This is not a validation of parsing-block-first article segmentation.
