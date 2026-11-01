# VLDocIR Article Segmentation → Reading Order: Read-Only Pipeline Audit

Date: 2026-11-01
Status: **investigation plan only; do not repair, generate edges or run models yet**
Repository branch: `feature/evidence-edges`

## 0. Why this audit exists

The directional-relation opportunity audit reported only **9 final-node article/reading assignments among 7,291 nodes**, covering just **2 of 518 VLDocIR pages**, with **5 page-local NEXT edges**. All 9 assignments successfully mapped to final nodes. This does **not** imply that the main EvidenceNet parsing pipeline lacks reading order; it suggests some required upstream article/reading stages were never executed over the full VLDocIR pilot, or their outputs were not assembled/imported. **We have not yet established which.**

The user is also concerned that **article segmentation / article membership may never have run** for the 518-page dataset. Investigate that independently. Do not assume that `reading_order.order_blocks()` is equivalent to article segmentation or the final node-level NEXT graph.

**Objective:** establish the *actual executed* path from 518 raw pages through parsing, article segmentation, EvidenceNode generation/membership, reading flows and imported graph edges. Find the precise 518 → 2 coverage bottleneck, if any; distinguish missing execution from execution failure and from importer mismatch.

## 1. Strict execution rules

- First phase **read-only**: no Git changes except the final diagnostic report / optional standalone audit script and its tests; do not change production pipeline, manifests, frozen outputs, candidate graph, node IDs or evaluator.
- **No GPU, Qwen/LLM, parsing reruns, OCR, Slurm submission, or auto-repair** during diagnosis.
- Respect hashes and immutable evidence; do not flip `reading_ready` or `ready_for_downstream` just to pass a gate.
- Check **actual existing HoreKa files and job logs**, not only code paths or old design documents. If assets are missing, write `unknown` and list exact missing paths.
- **Do not assume all 518 pages belong to one article or one document.** Detect document boundaries, multi-article magazines, article continuations, one-page works, figures/tables and page-context content.
- Do not construct cross-page NEXT merely from page numbers or IDs; do not invent article identity.
- Do not use test-query gold or outcomes to determine article boundaries or graph edges.
- Source of truth for scope = exact input manifest and content hashes of the 24-query, 518-page VLDocIR run. Avoid mixing with other magazines, test corpora or an earlier two-page smoke.

## 2. Separate the stages explicitly

| Stage | Question to audit | Observable evidence |
| --- | --- | --- |
| Raw pages / parsing | Were all 518 page identities and parsed blocks available? | Source manifests, per-page output records and counts |
| Block reading order | Was block-level ordering performed for each page? | `final_order` / `reading_order`, block counts, order validation |
| Article segmentation | Were page-level article/article-continuation boundaries actually inferred? | segmentation artifacts, article IDs, cross-page decisions, accepted/rejected/unknown statuses |
| Article membership | Were all final EvidenceNodes assigned to correct article or page-context group? | `article_assignments.jsonl`, node ID mappings, unassigned reasons |
| Within-article reading flows | Were ordered flows generated for applicable nodes, including isolated nodes? | page decisions, flow files, NEXT proposals, audit status |
| Cross-page continuity | Were only evidenced cross-page article continuations joined? | positive decisions, source nodes, page evidence and unresolved list |
| Final graph import | Which NEXT/PREVIOUS were actually imported at query time? | backbone summary/manifest, imported edge IDs and route enumeration |

**Important:** successful block ordering and EvidenceNode generation do not establish that article segmentation, node membership or cross-page continuity were executed.

## 3. Code-entry audit: trace the *actual invocation chain*

Inspect at least these existing files (verify paths first):

- `EvidenceNet/evidence_graph/pipeline.py` → uses `reading_order.order_blocks()`; identify what it outputs and whether it writes article IDs or final NEXT relationships.
- `EvidenceNet/evidence_graph/reading_order.py` → block sorting, not automatically an article graph.
- `EvidenceNet/evidence_graph/document_article_graph.py` → article grouping and NEXT generation; identify its inputs, cross-page decision contract, output names and script/CLI invocation.
- `EvidenceNet/evidence_graph/magazine_article_reconstruction.py` and `hybrid_article_clustering.py` → check whether they are invoked on VLDocIR, or only on separate magazine experiments.
- `EvidenceNet/scripts/prepare_vldocir_nodes.py` and `prepare_vldocir_edge_adapter.py` → final node creation, source-member mapping and article fields carried forward.
- `EvidenceNet/scripts/repair_vldocir_single_work_reading.py` → optional `--page-id` filter, single-work scope, `smoke_only` marker, `reading_ready` validation. Determine whether *actual* two-page artifacts came from this path; don't assume.
- `EvidenceNet/scripts/vldocir_reading_backbone.py` → consumes only provided `article_roots`; validates `ready_for_downstream` and `reading_ready`, article/node ID coverage, adds PREVIOUS; single-document profile may only have page-local flows.
- `EvidenceNet/scripts/run_evidence_edge_pipeline.py` and query-side code → whether reading edges are loaded in the actual version used for VLDocIR experiments.
- Locate all calls/references to `document_article_graph`, `article_graph_manifest`, `article_assignments`, `reading_edges.jsonl`, `reading_ready`, `article_roots`, `--page-id`, `smoke_only`, and 518/2-page filters. Prefer `rg -n` and call-site trace rather than assuming file presence proves execution.

Produce an **executed DAG** (actual commands/job IDs/configs/hashes) and separately a **code-supported DAG**. Mark every stage as `executed_full`, `executed_partial`, `not_executed`, `failed`, or `unverifiable`.

## 4. Data/manifest provenance and 518 → 2 funnel

Locate exact datasets used by `directional_relation_v1_20261101` and `directional_relation_opportunity_audit_v1_20261101`. Follow manifest source references recursively, but do not mutate files.

For **every** article/reading artifact root found, record:
- path, document ID, source corpus hash, input/output version and creation/Slurm metadata;
- processed/expected pages and explicit selected page IDs;
- any `--page-id`, `--limit`, `--smoke`, subset/single-work flag;
- `ready_for_downstream`, `reading_ready`, failure lists, missing decisions, model validation problems;
- article IDs/groups, per-page assignment counts, assigned vs unassigned nodes, page-context nodes;
- NEXT, PREVIOUS and cross-page counts; number of unique pages actually covered;
- compatibility of output node IDs with the **same frozen 7,291-node set** used in query runs;
- whether full-scale article outputs exist in a different location but were not passed to importer.

Mandatory coverage funnel:

```text
518 source pages (verify identity and input hashes)
  → pages parsed/available
  → pages with block order
  → pages with article segmentation decisions
  → pages with node→article membership
  → pages with validated reading flows
  → pages with validated NEXT (+ explicit cross-page decisions)
  → imported pages/nodes/edges
  → pages/nodes actually visible in query navigation
```

If a stage drops coverage, trace *why*: data never submitted, smoke-only filter, unfinished jobs, invalid decision/JSON, missing image, incompatible schema, ID mismatch, missing merger/importer roots, or skipped special document modes. Give counts and a small set of concrete path/manifest examples for each reason.

## 5. Specifically test whether article segmentation exists

**Do not collapse these concepts:**

1. Sorting blocks on a page.
2. Splitting content into different articles/content items (including resumes and cross-page continuation).
3. Assigning final evidence nodes to an article.
4. Ordering nodes *inside* the article and linking NEXT.
5. Building hierarchical document/page/article access routes for a query.

For each VLDocIR document mode (single research article, multi-article magazine, other):
- Is the mode classified and recorded? Where?
- Is article segmentation invoked at all on the 518-page corpus?
- Is segmentation executed at page/block level, and is it mapped to final EvidenceNodes?
- Do identical article IDs persist correctly across pages? What grounds a continuation?
- Are singleton articles/nodes represented as membership without requiring a NEXT edge?
- Are mixed-content pages and figure/table captions assigned with provenance?
- Could the corpus have article IDs from document metadata but no actual model-based segmentation? Record this explicitly.
- Does a separate magazine reconstruction pipeline exist but not feed into VLDocIR? Do not mistake this for a completed VLDocIR segmentation stage.

Deliver verdicts for **article segmentation**, **membership**, **reading order**, and **import** independently:
`full / partial / absent / failed / unknown`, accompanied by file evidence and counts.

## 6. Cross-check the reported 9/7291 figure

The previous audit says two reading products contain nine assignments, all mapped, five page-local NEXT edges. Verify:
- Were two artifacts one page each, two pages in one document, or partial outputs?
- Were only 9 *audited* assignments while more raw assignments existed?
- Why 2/518 pages: intentional pilot/repair scope, failed preparation, or incomplete accumulation?
- Are the 9 assignment IDs from the correct frozen corpus and revision?
- Is `reading_ready=false` describing a prior incomplete graph while a later valid graph exists elsewhere?
- Does importer require full `set(assignments)==set(nodes)` and thereby reject a valid partial root for full 7,291-node import?
- Does query runner load `reading=off` explicitly even where artifacts are ready?

Explain exactly what 9/7291 measures; distinguish final node **assignment** coverage from NEXT endpoint coverage and from all block-order availability.

## 7. Outputs and completion criteria

Create a new isolated audit folder (no overwrite):
`EvidenceNet/output/vldocir_article_reading_audit_v1_20261101/`

Minimum deliverables:
- `RESULTS.md`: short executive verdict, stage-by-stage counts, precise first coverage loss, confirmed source files and flags, root cause vs remaining unknowns.
- `stage_funnel.json`: machine-readable counts with numerators/denominators and unknowns.
- `artifact_inventory.jsonl`: all discovered roots, manifest hashes and run scopes.
- `invocation_trace.md`: executed DAG and supported DAG with concrete file/functions and job/config evidence.
- `article_segmentation_verdict.md`: explicit split/membership/order/import conclusions, per document mode.
- `next_actions.md`: minimal non-destructive repair steps **only after** diagnosis, including which stages need running and whether full corpus reprocessing is necessary.
- Optionally one read-only audit script + CPU tests. Store code revisions and hashes; include limits of filesystem access.

Definition of done: an independent reviewer can tell whether VLDocIR's article segmentation was actually run, why the reading layer contained only two pages, whether the missing coverage is upstream execution, failed validation, postprocessing or graph import, and exactly what must happen next **without** guessing or quietly generating edges.

## 8. Direct instruction to Codex

> Perform a **read-only provenance and invocation audit** of VLDocIR article segmentation and reading order for the frozen 24-query/518-page corpus. Trace the executed pipeline rather than assuming that an existing function was called. Verify actual coverage at block order, article segmentation, final node membership, NEXT generation and query graph import, using real manifest hashes and run logs. Explain 9/7291 assignments and the 2-page scope and find the first 518→2 bottleneck. Do not start GPU/LLM/Slurm tasks, reparse pages, patch ready flags, fabricate cross-page edges or change the production pipeline. Produce the specified isolated reports and minimal proposed fix plan; distinguish confirmed facts from unknowns.
