# VLDocIR Article/Reading Fix — Existing Tests and Execution Evidence Audit

Date: 2026-11-02  
Branch: `feature/evidence-edges`  
Status: **audit instructions only; do not assume tests have not run**  
Purpose: verify the actual **already-executed** tests and recovery outputs after commits `Fix fresh VLDocIR article reading pipeline` and `bug_fix_reading_order`. Resolve what is fixed, what was tested, and what remains unverified **without automatically rerunning models, Slurm, or GPU jobs**.

## 1. Context

A previous audit found 518 pages / 32 documents / 7,291 nodes; first coverage loss 518→238 pages due to worker failure propagation; 47 membership-failed pages; 40 reading-flow unresolved pages; 3,329 assignments and 633 page-local NEXT proposals from attempted documents; 0/16 documents initially ready. Two later smoke pages produced 9 assignments; they were **not** evidence that only nine were ever generated.

After that audit, the user **has already run tests** and pushed two fixes. Do not interpret the absence of results committed to GitHub as absence of execution. Search the actual HoreKa output directories, job logs, script-produced manifests, and local repository history. The test suite may have passed without demonstrating an end-to-end full-corpus recovery: distinguish levels of evidence.

GitHub code-review observations, to check against the **latest local checkout**, not assume universally:
- `EvidenceNet/scripts/run_hybrid_article_clustering.py`: targeted `repair_instruction(error)`, three generation attempts, existing invalid checkpoint still returned by base `call()` unless isolated recovery handles it.
- `EvidenceNet/scripts/repair_vldocir_single_work_reading.py`: `--retry-invalid` and retry history.
- `EvidenceNet/scripts/vldocir_reading_backbone.py`: strict full-node coverage and strict readiness checks; intentionally fail-closed.
- In the original `single_article` path, a continuation call was gated to `document_mode != single_article`; check whether other new modules now supply independently validated cross-page links.

Do **not** treat these as proof of missing fixes. Trace actual execution.

## 2. Questions requiring definite answers

1. Which exact tests/jobs have already run **after** the two fix commits? Record `git SHA`, script/command, time, status, exit code, input/output hashes, test counts and log path.
2. Were changes limited to unit tests / CPU smoke, or did a complete 32-document/518-page article+reading recovery run finish? State separately.
3. Has the previous worker failure been fixed **in the launcher actually used**? Show that doc B is attempted even if doc A fails; locate exact worker script/line and cite test/log evidence.
4. How many of the **47 membership failures and 40 reading failures** were actually retried and validated? Give current exact remaining counts, overlap and per-error categories. Are `valid=false` snapshots still treated as completed caches in any executed path?
5. Were all 32 documents attempted? How many pages reached valid membership, valid reading flow, and accepted article assignments? What is the exact scope of results?
6. For `single_article`, was a cross-page continuity method executed? Report: pages with eligible candidate endpoints, positive/negative/unknown decisions, **validated cross-page NEXT edges**. Membership under one article ID alone does not establish reading adjacency.
7. Did an importer actually run? What is the status of `reading_ready`, `ready_for_downstream`, importer manifests, accepted NEXT/PREVIOUS, node/page/doc coverage, and source hashes?
8. Did query-time code actually use `reading=on` in a new trial? Verify loaded edge count and visited route traces; code switch availability is not enough.
9. Is `data/benchmarks/VL-DocIR/pilot_images/<document_id>/page_XXXX.png` present **locally** and excluded from GitHub? If present, audit exact document/page counts, file readability/dimensions, image-manifest IDs and page-numbering integrity. No need to push binary images to git for this audit.
10. Do tested inputs correspond to the same frozen 24-query/518-page corpus and 7,291-node identities, or another smoke/preflight dataset?

## 3. Evidence collection sequence (CPU and read-only)

### A. Repo history and tests
- `git status --short`, `git log -12 --oneline --decorate`, `git rev-parse HEAD`, `git diff origin/feature/evidence-edges...HEAD --stat`.
- Locate patch scope for both fix commits and inspect changed tests; inspect `EvidenceNet/scripts/audit_vldocir_article_codefix.py` and `EvidenceNet/tests/test_vldocir_article_codefix_audit.py`.
- Locate all test result logs (pytest/JUnit/status JSON), Slurm logs, run manifests and script execution summaries relevant to fixes. If one is absent, do not assume that run never happened: report filesystem evidence scope.
- Map each test to a *specific invariant*: failing first document doesn't block second; retry-invalid behavior; correct cache fingerprint; no fake readiness; cross-page decisions; strict importer; query structural route visibility.

### B. Actual artifact coverage
Build a status funnel with explicit denominators:
```text
32 documents / 518 source pages / 7291 nodes
  -> scheduled / attempted docs
  -> pages processed
  -> membership validated
  -> reading flow validated
  -> article ID assignments accepted
  -> accepted page-local NEXT
  -> accepted cross-page NEXT
  -> imported NEXT/PREVIOUS
  -> query-visible/visited routes
```
Do not equate proposed edges with accepted edges or singleton membership with being a NEXT endpoint.

### C. Targeted comparison of old/new
Compare frozen *before* manifests against newly versioned *after* manifests without writing to source roots. Build a per-document diff (old status/new status, reused count, retried count, unresolved cases, source hash). If after data isn't present, classify `code-only verified` rather than falsely declaring a failure.

### D. Images sanity check
If local images exist, calculate per-document page counts, gaps, duplicated file hashes, unreadable/0-size images, mismatched document IDs, unexpected dimensions / aspect ratios, and existence of images referenced by decisions. **Do not OCR or send images to a model**. A valid PNG inventory does not establish correct article segmentation.

## 4. Outcome classification: avoid binary “fixed/not fixed”

For EACH subsystem, classify `code_changed`, `unit_tested`, `integration_tested`, `full_corpus_verified`, `failed`, or `unknown` with a concrete file/line/log/hash:
- document scheduler isolation;
- checkpoint handling and targeted retries;
- membership correctness and coverage;
- page-local reading validity;
- single-article cross-page continuity;
- true multi-article segmentation (if any applicable documents);
- structural graph import;
- query navigation;
- local pilot image dataset.

A passing test suite (`886 passed` or higher) is **not** automatically full-corpus success; but do not dismiss it or rerun without checking the existing output.

## 5. Deliverables

Use a **new** output root:
`EvidenceNet/output/vldocir_article_reading_postfix_audit_v1_20261102/`

- `RESULTS.md`: executive evidence-based status, exact tested runs, verified improvements and remaining blockers, with file/line references.
- `test_run_inventory.jsonl`: existing test commands, commit versions, logs, status and coverage.
- `before_after_document_status.jsonl`: all 32 document entries, existing/missing attempts and validation outcomes.
- `coverage_funnel.json`: counts with denominator and source/version.
- `fix_verification_matrix.md`: code changed vs tests run vs full integration verified, separately.
- `pilot_images_inventory.json`: available image counts and integrity or explicit unavailable reason.
- `next_actions.md`: only remaining **demonstrated** gaps with minimal next work.

Create a small read-only script if necessary, with CPU tests. Do not overwrite frozen snapshots. Cite exact local paths and manifest hashes in reports.

## 6. Execution constraints and the requested first action

**Start by discovering existing evidence**, not by running the test suite again. Search current output folders including recent recovery roots, job logs, and the existing codefix audit. The user explicitly said tests have already run.

- Do not submit GPU/LLM/Slurm, do not regenerate page decisions, do not modify accepted graph or query baseline.
- Do not automatically change code based on old code-review limitations; confirm whether latest local flow routes around them and whether the test invoked that path.
- If an end-to-end failure is found, propose a *minimal* patch with a targeted regression test **after** establishing the current actual behavior.
- Keep the difference between `not present on GitHub`, `not found in inspected local roots`, and `not executed` explicit.

## 7. Direct Codex prompt

> The Reading Order and article recovery fixes have **already been implemented and tested** according to the user. Audit the **real completed test and job evidence first**; do not assume the old diagnostics remain current. Identify which exact commits, inputs, invocations and result artifacts were used. Compare pre/post coverage for all 32 documents and 518 pages; verify invalid checkpoint recovery, cross-page NEXT decisions, actual graph import, and query-time reading visibility independently. Also inventory local `data/benchmarks/VL-DocIR/pilot_images/<document_id>/page_XXXX.png` for image integrity. Output a versioned evidence matrix and only propose further fixes where an actual gap is demonstrated. **Do not rerun GPU/LLM/Slurm or overwrite frozen results.**
