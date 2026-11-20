# VLDocIR Article Membership & Reading Order — Recovery Implementation Plan

Date: 2026-11-01  
Status: **implementation handoff (not implemented by this commit)**  
Target branch: `feature/evidence-edges`  
Input audit: `EvidenceNet/output/vldocir_article_reading_audit_v1_20261101/RESULTS.md` and associated `stage_funnel.json`, `artifact_inventory.jsonl`, `invocation_trace.md`, `next_actions.md` (read these local HoreKa outputs first).

## 0. Objective and confirmed diagnosis

Restore a trustworthy article-membership and reading-order layer for the **frozen VLDocIR development corpus: 518 pages, 32 documents, 7,291 EvidenceNodes**. Make the resulting NEXT/PREVIOUS usable as a **separate structural layer** at query time. Do not confuse block sorting, article segmentation, assignment, page-local reading flow and cross-page continuation.

The audit reported:
- First coverage loss **518 → 238 pages**: 16 workers each assigned two documents, but a `reading_ready=false` result on the first document aborts the worker, leaving its second document untouched.
- 16 first documents processed; **3,329 article assignments and 633 page-local NEXT proposals**.
- **47 membership-failed pages, 40 unresolved reading-flow pages, 0/16 documents reading_ready**.
- **No cross-page NEXT** in those outputs, no aggregate/import stage, query currently `reading=off`.
- `9/7291` came from two explicit repair smoke pages (job 5215323), not entire initial production.
- The current `single_article` profile maps nodes into a *preknown document-level work*; this is **not** verification that genuine multi-article segmentation ran. The block-level `order_blocks()` execution in this specific run remains unproven.

These are user-supplied audited facts, **not** new code execution or new measurements here. Verify artifact hashes before using them. Do not mark a document ready solely because some assignments or edges exist.

## 1. Guardrails (non-negotiable)

1. Keep all frozen nodes, old graph, old queries, qrels, earlier run output and experiment manifests **read-only**. Use a **new versioned root** for retries, reconciliations, accepted reading edges and retrieval.
2. **Reuse already valid per-page membership/reading decisions** only after re-validating against the exact immutable node/page payload, image, prompt/schema and model-record provenance. Do not trust matching filenames alone; record hashes and reasons for invalidation.
3. Never silently convert failed/unknown pages to successful ones, modify `reading_ready` / `ready_for_downstream` by hand, or synthesize cross-page NEXT by sequential page numbers.
4. Model/Slurm jobs are **conditional**: execute CPU validation and reuse first. Submit only missing/invalid scoped page decisions after reporting exact pending count and resources; preserve deterministic resume state. Do not perform a blind all-518-page re-run.
5. Query-phase graph must not infer answer evidence from generated relation text, NEXT or membership; validate original source anchors, article boundaries and modality.
6. Do not use evaluation questions/gold labels/known retrieval failures to create article links, repair segmentation or choose edge coverage.
7. Keep `single_article` and true multi-article segmentation **separate by document-mode classifier**; unsupported modes should remain explicit `unknown`, not forced to single article.
8. An import-ready **partial** graph may be supported only via explicit policy and provenance (valid subgraph, page/document coverage and unavailable parts published); never falsely label it corpus-complete.

## 2. Start by inspecting the *actual* code / manifests

Trace end-to-end, with exact source file/function/line and job submission command:
- worker scheduler and per-document loop that treats first document `reading_ready=false` as worker-fatal;
- `EvidenceNet/scripts/repair_vldocir_single_work_reading.py` (`--page-id`, reuse, validation);
- article membership/reading worker, status validator and aggregator; locate by `rg -n 'reading_ready|single_article|article_graph_manifest|article_roots|reading_decisions|page_decisions' EvidenceNet`;
- `EvidenceNet/evidence_graph/document_article_graph.py` (article-local NEXT and explicitly verified cross-page links);
- `EvidenceNet/evidence_graph/reading_order.py` and `EvidenceNet/evidence_graph/pipeline.py` (block ordering versus node-level flow);
- `EvidenceNet/scripts/vldocir_reading_backbone.py` (needs valid roots and emits reverse PREVIOUS);
- `EvidenceNet/scripts/prepare_vldocir_nodes.py` and query runners (node identity, import and `reading=off` gate);
- `EvidenceNet/output/vldocir_article_reading_audit_v1_20261101/` results / artifact inventory, actual job scripts, work logs and source manifest.

**Do not create a second pipeline.** Refactor and fix the real entrypoints with minimal isolated changes and backward-compatible CLI where practical. Preserve existing semantic graph pipeline and all historical scripts.

## 3. P0 — fix document isolation, resume and job status

Failure at document A must not suppress assigned document B.

- Make **each document an independent, resumable unit** with its own status `pending | running | complete | partial | failed | blocked`, exact error, accepted membership/reading counts, input hashes, output root and timestamp.
- Worker processes every assigned document, catching per-document stage errors and continuing to the next; worker reports all outcomes. Scheduler retries **only** missing/failed docs/pages. If an external fatal resource error stops a process, queued second docs stay `pending` and are picked up by another worker/run.
- Page statuses are independent from document readiness. Use explicit `membership_valid`, `reading_valid`, `cross_page_validated`; status aggregation is deterministic. `reading_ready` means every *required* item for that document has met the existing contract; do not weaken it.
- Output writes atomic (temp→rename), collision-safe, idempotent and lock/resume aware. Crash mid-write must not yield success markers. Canonical `document_id` and `page_id` keys; no file-name-only matching.
- Test: first doc has `reading_ready=false` yet second is processed; malformed single page does not destroy other page results; restart reuses valid decisions and retries only invalid/missing decisions; duplicate worker scheduling cannot overwrite valid output; status reflects partially complete docs.

**Exit criterion:** scheduler can enumerate all 32 documents, and a failed first document does not prevent the remaining 16 from being attempted. This is not a request to falsify readiness.

## 4. P1 — recover and validate existing 238-page work

- Verify the 16 existing document roots by exact input/content hashes.
- Build a per-page triage table for 47 membership failures, 40 reading-flow unresolved, their overlap, error type, source spans/images, missing vs invalid JSON, schema mismatch, response truncation, inconsistent node coverage, wrong scope.
- Distinguish old valid content from failure. Materialize a new, provenance-linked recovery root and retain every validated assignment / flow. Recheck all accepted original anchor/node IDs and article IDs.
- Retry failed page stages **with the same contract first** (unless contract itself provably impossible); track `old_status`, `retry_reason`, `new_status`, `attempt_count`, model/config/prompt/version/hashes.
- For page-level retry, perform membership before reading. A reading decision is invalid if based on obsolete membership; reuse only if membership payload hash and output are identical.
- Preserve unresolved pages as `partial` and publish exact coverage. No global success from simply producing a JSON file.
- Test original untouched, replay idempotent, invalid caches rejected, partial import has strict opt-in policy.

## 5. P2 — process the unattempted 16 documents, not 280 blind pages

- Generate missing-work inventory from the **32-document frozen input**, matching immutable page/node manifests. The prior 238 pages correspond to 16 first documents; the other pages must be enumerated from actual document page counts rather than guessed.
- First CPU-check parser/source payloads and document-mode classification.
- Run article membership/reading for the **16 unattempted documents**, using the corrected per-document worker. Reuse any discovered valid historical/alternate root by strict hash and schema validation.
- Reconcile all 32 doc outcomes, preserve failures, run targeted resume on unresolved pages.
- Estimate compute and write an execution plan before GPU/LLM submission. Run a small, non-gold smoke for retry/resume and status semantics. Use queue resources only for unresolved model-dependent work.
- Report coverage as page/node/doc numerators and denominator, with separate membership and reading statuses.

**Exit criterion:** all 32 docs are attempted or explicitly blocked for a recorded reason, not necessarily all marked ready. Any remaining invalid pages are enumerated individually.

## 6. P3 — article segmentation and document modes: do not overclaim

Before cross-page edges:
- Create a **document-mode inventory** for all 32 inputs: known single-article research document, multi-article magazine/collection, uncertain. Ground in content/source metadata, not query qrels.
- In true `single_article` docs, assigning the document as an article is **membership by premise**, not article segmentation. Preserve this distinction in reports and manuscript.
- For multi-article/uncertain documents, locate existing article-segmentation/reconstruction implementation (e.g. `document_article_graph.py` and magazine/segment logic) and determine compatibility. If not executed or not supported, create a *separate, staged implementation plan* and block cross-page stitching there; do not force all pages to one article.
- Validate article continuity at page breaks using explicit original source evidence, consistent subject and IDs, not merely adjacency in page index. Content resume may be nonconsecutive; page headers/chrome/ads must not be treated as article passages.
- Unit tests with multiple articles on one page, continuation after interruption, singleton pages, table/figure-only pages, title without following content, different papers sharing generic formulas.

**Exit criterion:** counts of real inferred article splits vs preknown single-article assignments; no claim that the VLDocIR experiment verified multi-article segmentation unless a corresponding branch actually ran and its results were checked.

## 7. P4 — validate and import the structural graph

**Start with safely validated page-local edges.** Build exact document/page/node membership checks, no duplicate NEXT pairs, in/out degree ≤1 for linear reading paths as appropriate, no cycles, all endpoints existing and article-compatible. For every NEXT verify original support and track source hashes. PREVIOUS is reverse navigation for the same accepted NEXT, not new factual evidence.

- Cross-page NEXT only when explicit validated positive continuity exists; do not infer from page order. Keep `cross_page_missing` visible. Distinguish page-local completeness from cross-page completeness.
- Adapt readiness/import contracts **without bypassing validation**: strict full-doc import requires full-doc readiness; optional `partial_validated` imports must be intentionally selected, bounded to all-valid components/pages, exclusion audited, and marked non-complete.
- Produce `article_assignments.jsonl`, `reading_edges.jsonl`, a merged provenance/validation manifest and a fail/skip manifest; pass the *correct full set* of accepted article roots to `vldocir_reading_backbone.build()`.
- Verify actual distinct pages/nodes/documents with membership; valid NEXT/PREVIOUS count and cross-page count separately. **Do not use total assignments as proxy for graph-connected endpoints**.
- Keep semantic `RELATED` and structural `NEXT/PREVIOUS` separate; no semantic inference or unconditional ranking bonus from reading neighbors.
- Acceptance: repeatable SHA/content audit, imported edge IDs match accepted edges and query can enumerate those routes, no new nodes without source provenance.

## 8. P5 — controlled query integration and evaluation

Only after accepted import artifacts exist:
1. Add explicit reading switch with default **off** to the query-runner adapter; changing the switch must not change the frozen semantic graph or no-edge baseline.
2. Verify query trace includes actually loaded NEXT/PREVIOUS route IDs from all accepted docs and missing-coverage counts. Fail loudly if `reading=on` but import absent/empty.
3. Compare `R0 no graph`, `reading only`, `semantic only`, `reading + semantic` using same seeds, extra target slots, original-node access, reranker, target/source token accounting, and fixed query set.
4. Report target novelty, original evidence gains, number of seed neighbors, page metrics, reranker retention, modality context, latency and full online cost. Provide per-query output not just aggregate. Keep relation representation R1–R5 frozen until this coverage problem is solved.
5. No post-hoc gold-derived graph construction. 24 queries remain an often-inspected **development** set; no generalization claim.

## 9. Suggested implementation sequence and milestones

**Milestone A — CPU only**: source code/job trace; independent document scheduler, resume/status tests; inventory 16 existing + 16 unattempted; coverage/readiness report. Deliver test pass and exact changed paths. **No model run yet**.

**Milestone B — scoped recovery**: hash-verified reuse and isolated retries for 47/40 failure categories and other blocked work; request/submit resources only as necessary and account retries. Preserve all per-page decisions.

**Milestone C — full-scope execution**: run remaining 16 documents with correct scheduler; collect 32-document report and explicit missing pages.

**Milestone D — graph validation/import**: validate accepted page-local and any explicitly confirmed cross-page NEXT, produce versioned import, review provenance and node/reading coverage.

**Milestone E — query integration**: enable reading switch only for new experiments, smoke trace, matched 4-arm comparison; report negative results honestly.

If resource limits or persistent validation failures block an entire stage, **stop that stage with a documented blocker and preserve partial results** rather than reporting completion or silently skipping.

## 10. Required artifacts and acceptance criteria

Versioned new root suggested:
`EvidenceNet/output/vldocir_article_reading_recovery_v1_20261101/`

Write:
- `execution_plan.md` (entrypoints, exact job scope, resource estimate);
- `document_status.jsonl`, `page_status.jsonl` with immutable IDs/hashes/errors;
- `reuse_manifest.json`, `retry_manifest.jsonl`, `failure_triage.jsonl`;
- `article_mode_inventory.jsonl` with source justification;
- `coverage_funnel.json` (518/32/7291 denominator verified);
- `accepted_reading_edges.jsonl`, `rejected_reading_edges.jsonl`, `reading_import_manifest.json`;
- `query_reading_smoke.jsonl` and four-arm eval artifacts once P5 runs;
- `RESULTS.md`: what truly ran, success/failure, counts, checksums, observed difference vs historic sparse graph, and follow-up issues.

**Acceptance criteria:**
- The full 32-document workload is reachable by scheduler, with **no document dropped due to previous failure**.
- Existing validated per-page decisions are reused without mutating frozen snapshots; retries are bounded and reproducible.
- Membership, page-local reading, cross-page continuity, graph import and query visibility have **independent completion/coverage statuses**.
- A structural edge is imported iff it passed original-source/provenance validation and import policy; no fabricated links.
- For eligible documents, query can navigate validated NEXT/PREVIOUS; disabled control is unchanged.
- Report reflects partial coverage honestly if any document is not complete.
- All existing tests + new regression tests pass; no hardcoded claims about total accepted edge counts or retrieval improvement.

## 11. Immediate instruction for Codex

> Implement this recovery **incrementally** on `feature/evidence-edges`. First inspect real code and read the prior audit results. **Start with Milestone A only**: fix per-document failure isolation, reliable resumable statuses and CPU regression tests; produce a 32-document missing/failed work inventory and execution plan. Avoid changing the graph or submitting Slurm/LLM jobs until Milestone A tests and provenance review are complete. Then reuse existing validated decisions and perform only scoped recovery; never blindly rerun 518 pages or fake `reading_ready`. Treat article segmentation/mode as a separate correctness gate and validate accepted NEXT before import. For each milestone, report exact code changes, tests, artifacts and unattempted/invalid pages.
