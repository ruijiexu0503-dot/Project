# VLDocIR Article / Reading Order — Code-Level Root-Cause Fix Handoff

Date: 2026-11-02  
Branch: `feature/evidence-edges`  
Status: **detailed implementation specification, not a completed repair**  
Audience: Codex / implementer. Start with CPU-only patches; do **not** automatically submit GPU, LLM or Slurm jobs.

## 0. Objective and observed evidence

Fix the actual Article Membership → Reading Flow → Document Readiness → Worker Scheduling → Graph Import → Query Integration path for the frozen VLDocIR pilot; **do not implement yet another parallel article pipeline**.

User-provided, audited execution observations:
- 518 pages, 32 documents, 7,291 EvidenceNodes; first coverage loss 518 → 238 pages.
- 16 workers with two documents each; first document ends incomplete and its second document never starts.
- On 16 attempted documents: 3,329 article assignments, 633 NEXT proposals, 47 page-membership failures, 40 unresolved reading flows; 0/16 `reading_ready=true`.
- Existing NEXT proposals were all within-page. Later `9 / 7291` assignments came from **two intentionally selected repair smoke pages** and should not be mistaken for initial pipeline coverage.
- No full collector/importer ran; query `reading=off`.
- Exact block-level `order_blocks()` execution in this VLDocIR job is unverified.
- Current experiments ran `single_article` on all documents. This signifies document-level membership by prior, not independently evaluated multi-article segmentation.

These observations must be checked against the **actual HoreKa diagnostics**, not regenerated from memory:
`EvidenceNet/output/vldocir_article_reading_audit_v1_20261101/{RESULTS.md,stage_funnel.json,artifact_inventory.jsonl,invocation_trace.md,next_actions.md}`.

## 1. What code review actually confirms (specific file/line references)

### 1.1 Two-step membership and reading, and readiness coupling

`EvidenceNet/scripts/run_hybrid_article_clustering.py`:
- `prepare()` ~lines 47–117: consumes frozen hybrid nodes, sets document mode using `--single-document`; supplies separate membership input.
- `materialize()` ~lines 164–260: for each page, calls `validate_membership` first, then `validate_reading` if it has groups.
- ~lines 182–188: an invalid reading result appends `PAGE_READING_UNRESOLVED` while leaving membership available.
- ~lines 198–199: invalid membership adds `PAGE_CLUSTER_FAILED`.
- ~lines 293–314: `ready_for_downstream = not issues`; `reading_ready = not issues and not reading_issues`; **only `issues` causes `RuntimeError` at line ~312**, whereas a reading-only failure can return with `reading_ready=false`. Separate these two exit paths when inspecting the outer worker.
- An incomplete document does not imply zero valid page assignments or zero candidate NEXT edges.

### 1.2 Failed checkpoint persists unless explicit retry logic handles it

`run_hybrid_article_clustering.py::call()` ~lines 133–155:

```python
if path.exists():
    record = read(path)
    if record['input_sha256'] != fingerprint:
        raise ValueError('Stale article checkpoint: ' + str(path))
    return record
```

**It returns existing `valid=false` checkpoints without retry.** This is important: rerunning the same output path does *not* automatically repair invalid decisions. Keep historical invalid cache immutable; introduce explicit, narrow, versioned recovery with audit provenance, not automatic deletion or overwriting. Positive cache requires independent revalidation (fingerprint alone is not full validation if contracts change). An invalid cache is a recorded failure, **not** a success or a fresh model call.

### 1.3 Single-article profile intentionally bypasses cross-page decision generation

`run_hybrid_article_clustering.py` ~lines 200–231:
- `if ... page['document_mode'] != 'single_article':` gates continuation Qwen call.
- Single mode directly assigns `page['document'] + '::DOCUMENT_ARTICLE'`.
- Page-local `NEXT` is derived from adjacent nodes **inside one flow** (~lines 240–244). Cross-page `NEXT` is added only via explicit `reading_link` in continuation decisions (~lines 229–231), which single mode never calls.

Therefore all nodes can have identical article IDs yet remain disconnected across pages. **Do not equate same article with directly successive nodes**; cross-page join requires evidence and explicit validated decision. A separate `document_article_graph.py` has an explicit-decision path for cross-page NEXT; inspect whether it can be reused without creating duplicate conflicting graph contracts.

### 1.4 Strict importer is currently all-or-nothing

`EvidenceNet/scripts/vldocir_reading_backbone.py` ~lines 32–46:
- rejects any imported root lacking `ready_for_downstream` and `reading_ready`;
- validates hashed outputs;
- rejects duplicate node assignments;
- requires `set(assignments) == set(nodes)` for all 7,291 nodes;
- later validates article-boundary and edge structure, and generates PREVIOUS from validated NEXT.

Keep **strict-full** semantics intact for final corpus-complete artifacts. If partial import is needed for debugging, add explicitly named, fail-closed **`partial_validated`** mode that records assigned/unassigned coverage and only imports edges from accepted components. Do not simply remove readiness or set equality checks.

### 1.5 Critical worker-level evidence still needs direct tracing

Repository review confirms the document-level `RuntimeError` and readiness gates, **but has not independently inspected the exact script submitting 16 workers and grouping two documents per worker**, nor all raw exceptions behind the 47/40 failures. Locate and cite that code/job script before editing it. Do not treat a hypothesized outer `assert reading_ready` as confirmed until located.

## 2. Mandatory investigation before code changes (Milestone 0, CPU only)

1. Identify exact commit/hash of job inputs and the worker `sbatch` script, job arrays, wrappers, log paths and grouping logic. Compare GitHub state with **local uncommitted code**; do not assume remote branch is identical to executed job.
2. Construct exception trace `worker → run() → materialize() → report/readiness-check → next document`. Show which function and condition prevented document two from running.
3. Inspect failures by class, not just counts: membership 47, reading 40, overlap, invalid response JSON, node/title coverage, group identity mismatch, hallucinated labels, failed validation of type/body/caption, prompt truncation/token cap, image issue, stale invalid cache and infrastructure interruption.
4. For every existing cache, record `page_id, stage, valid, fingerprint, code/schema/prompt hash, attempt_count, error summary`. Distinguish validator errors from model transport failures.
5. Verify 16 attempted document page counts total 238, and the missing 16 documents' exact page counts sum 280; record mode rationale and original document identifiers.
6. Confirm what `run_hybrid_article_clustering.prepare()` did or did not invoke from `evidence_graph/reading_order.py`. It carries parser order fields but that alone is not proof that `order_blocks()` ran.
7. Capture all preliminary evidence in `execution_root_cause.md` and `failure_taxonomy.jsonl`, with explicit proven/likely/unknown labels.

**Gate:** no actual retry/Slurm until missing-work inventory, failure taxonomy and CPU tests exist.

## 3. Milestone A — make failures isolated and resumable

Implement on **the real scheduler or wrapper** rather than burying catch-all exceptions in `materialize()`.

### Contract

- A task is a frozen `document_id` and ordered page IDs; workers may process multiple tasks, but a recoverable failure in A **never skips** B.
- Each document gets durable independent state: `pending, running, partial, complete, failed, blocked` plus `membership_state`, `reading_state`, input/protocol hashes, output roots, error detail, retry count and last attempt.
- Use `try/except` per document with explicit `finally`/status recording; do not absorb true process-fatal conditions (OOM, node eviction) without a restartable scheduler. On process crash, unfinished tasks remain retryable and visible.
- Make writes atomic and idempotent with collision protection. A repeated run with the same immutable inputs reuses successful checkpoints; changing input/model/prompt/schema requires a new cache namespace or explicit invalidation policy.
- `reading_ready=false` is a per-document failure/partial state, **not a reason to abort the entire array worker**.
- Preserve the old fail-closed semantic-edge gate unless there is a rigorously specified, separately tested partial import mode.

### Regression tests

- First of two docs has invalid membership: second attempted.
- First doc has valid membership but invalid reading: second attempted.
- First doc raises an unexpected but document-scoped error: status persisted and second attempted.
- Worker crashes mid-document: following run enumerates missing work; no fake success.
- Same good page is reused without a model call; bad page remains invalid until explicitly scheduled for recovery.
- Two concurrent workers do not corrupt a checkpoint.

**Acceptance:** scheduler enumerates all 32 document IDs, with none silently skipped by earlier document errors.

## 4. Milestone B — minimal, provenance-preserving checkpoint recovery

Do **not** fix this by deleting failed JSON files or lowering validator strictness globally.

- Reuse the existing `repair_vldocir_single_work_reading.py` when compatible. It supports isolated recovery and a `--page-id` smoke path; ensure smoke outputs cannot be accidentally treated as full documents.
- Inventory valid and invalid checkpoints. For each positive checkpoint, revalidate against **the same source payload and current explicit schema version**; record whether reuse is byte-identical vs canonicalized. Preserve original model attempts/raw outputs.
- Retry only failed page/stage pairs, membership before reading. A changed membership result invalidates dependent reading-cache input; do not reuse it.
- Fix clearly demonstrated deterministic failures in prompts/schema/validation only with targeted unit tests and a new protocol version. Distinguish actual unsupported multimodal evidence from JSON/format mistakes.
- On a second-stage failure, keep the first-stage **validated** membership; do not relabel it complete reading.
- Emit one versioned `reuse_manifest.json`, `retry_manifest.jsonl`, `invalid_decisions.jsonl` and per-page status table.
- Any GPU/LLM rerun must be scoped, counted and separately approved/triggered per existing operational workflow; a code handoff alone is not a running job.

**Acceptance:** 238 attempted pages produce individually classified reusable/invalid/missing stage results; only unresolved work is queued, without overwriting original snapshots.

## 5. Milestone C — finish all 32 documents and separate readiness layers

- Run the remaining 16 never-attempted documents with corrected isolation. Do not assume 238 existing pages are valid just because they were attempted.
- Per-page statuses: `membership_valid`, `reading_valid`, `article_id_valid`, `original_anchor_valid`, `failure_reason`.
- Per-document aggregate statuses: `membership_complete`, `page_local_reading_complete`, `cross_page_continuity_status`, `strict_full_ready`.
- Keep `ready_for_downstream` and `reading_ready` backward-compatible and correctly fail closed; do **not** rewrite frozen old manifests.
- Record `article_assigned_nodes` separately from `nodes_with_next`; singleton flow nodes may be successfully assigned without having any NEXT edge.
- Report denominators 32 docs / 518 pages / 7291 nodes at each stage; counts by document and error category, not only global percentage.

**Acceptance:** all documents attempted or explicitly blocked; all acceptable outputs are hash-verified, and unresolved cases are visible instead of dropped.

## 6. Milestone D — actually resolve the cross-page design gap

**This is a correctness problem distinct from worker robustness.**

### Mode-aware behavior

- A scientifically known one-article PDF can legitimately use `single_article` membership. That mode **does not** mean every successive page node is adjacent in reading order.
- For genuine multi-article PDFs, run/validate article segmentation and continuation identification separately. Do not assign every node to the document article by fiat.
- For `single_article`, add a distinct **cross-page continuity candidate/decision stage**, using original source context, layout, page identity, paragraph break, title/section boundaries and flow endpoints. Only accepted positive decisions create a cross-page NEXT.
- Consider missing or reordered pages, front matter, references, table-only pages, figures, appendices and layout inconsistencies. Permit `NO_LINK` / `UNKNOWN`; never require a link at every page break.
- Reuse the already implemented explicit decision validation machinery in `document_article_graph.py` where compatible, rather than producing unvalidated sequential edges.
- For `multi_article`, existing continuation logic has `max_lookback_pages=3`; this is a policy limitation, not complete magazine reconstruction. Distinguish nonconsecutive resumed articles and label unresolved continuations.

### Tests

- Same article across consecutive pages with supported continuity → validated NEXT.
- Same article but separate section with no confirmed direct successor → **no NEXT**.
- Two articles on one page, page-context headers/ads, split figures and captions → no accidental cross-article NEXT.
- Nonconsecutive article resumption, missing pages and page renumbering → no synthetic numeric adjacency.
- All generated NEXT endpoints match original EvidenceNode IDs, same article, expected flow type; reverse PREVIOUS is purely an inverse navigation view.
- No branching/cycles or incompatible multiple predecessor/successor relationships for linear flows; different flow kinds remain distinct when necessary.

**Acceptance:** cross-page confirmed count can be >0 when source warrants it, but **0 is valid** if no tested candidate passes. The key is that the stage actually executes, explains omissions and rejects wrong links.

## 7. Milestone E — validated graph import and query integration

- Inspect current `vldocir_reading_backbone.build()` before modifying; keep strict-full import as standard.
- If partial diagnostics are necessary, implement a separately named `partial_validated` import with an explicit accepted-page set and manifest that lists all excluded pages/nodes; never call it full.
- Validate graph source hash, node IDs, article IDs, edge sources, degree/cycle constraints and absence of fabricated cross-page paths.
- Store `NEXT` and generated inverse `PREVIOUS` as **structural navigation** only. Do not let them propagate answer evidence or increase relevance unconditionally.
- Enable a new query flag `reading=on` only after actual graph artifact validation; log route traversal, original source target, overlap with dense search and fallback. A flag alone is not proof of import.
- Compare no graph / reading only / semantic only / both under the **same Top10 seed nodes, target exposure budget and BGE/source selector**; record route novelty, page-level Recall/AP/nDCG, original evidence coverage and costs. Do not claim improvements from imported-edge count alone.

## 8. Files and design components to inspect

| File | Purpose |
| --- | --- |
| `EvidenceNet/scripts/run_hybrid_article_clustering.py` | Primary hybrid page prepare, caches, membership, reading, document materialization and readiness |
| `EvidenceNet/evidence_graph/hybrid_article_clustering.py` | Validation and membership/reading/continuation prompts |
| `EvidenceNet/scripts/repair_vldocir_single_work_reading.py` | Existing isolated recovery with per-page smoke option |
| `EvidenceNet/evidence_graph/document_article_graph.py` | Explicit cross-page decision, article assignment and local NEXT machinery (different pipeline contract) |
| `EvidenceNet/scripts/vldocir_reading_backbone.py` | Strict graph importer and PREVIOUS generation |
| `EvidenceNet/evidence_graph/reading_order.py` | Block ordering; separate from article graph |
| `EvidenceNet/evidence_graph/pipeline.py` | Main EvidenceNet block-order invocation |
| Existing audited job launcher | **Locate actual file/script before editing**; not independently located during GitHub review |

## 9. Deliverables, staged report and test plan

Recommended output root:
`EvidenceNet/output/vldocir_article_reading_codefix_v1_20261102/`

**Required after Milestone 0/A (CPU):**
- `execution_root_cause.md`: actual worker exception chain, line references, raw error categories;
- `document_inventory.jsonl`: 32-document scheduling and statuses;
- `failure_taxonomy.jsonl`: 47/40 class breakdown, cached `valid=false`, overlaps;
- `scheduler_resume_tests.md` and unit tests;
- `RESULTS.md`: what is **implemented/tested** vs planned, precise changed files.

**Required after full implementation/execution:**
- `retry_manifest.jsonl`, `reuse_manifest.json`, `page_status.jsonl`, `document_status.jsonl`;
- `cross_page_decisions.jsonl` (includes explicit `NO_LINK` and `UNKNOWN` outcomes);
- `article_mode_inventory.jsonl`;
- `validated_reading_edges.jsonl`, `reading_import_manifest.json`, `query_trace.jsonl`;
- 4-arm matched retrieval report and cost accounting, if query experiment actually ran.

Regression suite must include: cached invalid checkpoint behavior, first-doc-fails/second-runs, restart after crash, successful cache reuse, stage-wise readiness, cross-page no-link cases, partial vs strict import, multiple articles, source-ID integrity, cycles, reversed PREVIOUS, query switch loading.

**Do not report the work complete because 886 historical tests pass.** Add targeted tests proving the previously observed failures are fixed. Model-generated reading flow accuracy and evidence usefulness require separate validation.

## 10. Recommended immediate Codex task (one milestone, not all at once)

> Read this handoff and the real HoreKa audit artifacts. Locate the actual 16-worker launcher and prove exactly why document B was skipped after document A was incomplete. Independently inspect all `valid=false` checkpoints and categorize the 47 membership / 40 reading errors, including overlap. Then implement **only Milestone A**: per-document failure isolation, resumable durable statuses, safe checkpoint handling and CPU regression tests. Preserve all frozen files; do not launch models or graph import. Report exact changed files and failed tests before/after. Once Milestone A is verified, propose the smallest scoped recovery run. Do **not** start Milestones B–E without explicitly separating their results.
