# Article / Reading fixes — focused verification of five code-review concerns

Date: 2026-11-02  
Scope: **verify the five concerns raised in the previous GitHub code review against the latest actual execution path and tests already run**. This is NOT a new pipeline audit or recovery assignment.

## Important context

The user has **already implemented changes and run tests**. Start from current local code (including new wrappers, tests, recovered artifacts and logs) rather than presuming an older function is still the invoked one. A legacy function containing an old condition does not establish that the currently executed pipeline has that defect.

**DO NOT** run pytest again, GPU, LLM, Slurm, OCR or benchmarks; do not regenerate outputs, modify code, submit jobs or create new experiments. Do not re-audit 32 documents / 518 pages comprehensively. Read existing test logs/results and the smallest relevant source snippets only.

## Five questions to verify

| # | Concern from earlier review | Precise verification |
| --- | --- | --- |
| 1 | Worker isolation | When document A has invalid reading or membership, does the **actual launcher/worker** continue to document B? Find the real entrypoint and an existing test or completed-run trace, not just the old `materialize()` exception. |
| 2 | Invalid checkpoints | Does any **actively invoked** path reuse a `valid=false` checkpoint without an explicit retry mechanism? Check original `run_hybrid_article_clustering.py::call()` against the actual recovery path, `--retry-invalid`, cache/version rules, and already run tests. |
| 3 | Single-article cross-page NEXT | Does the **current executed** single-work path have validated cross-page continuation/reading links, possibly implemented in a new module? Distinguish document-wide `article_id` from confirmed cross-page NEXT and do not infer links merely from adjacent page numbers. |
| 4 | Readiness coupling | Do current stage/status gates distinguish membership, page-local reading and cross-page continuity appropriately? Does one unresolved page unnecessarily block unrelated work? Distinguish deliberate strict full import from an unwanted scheduler abort. |
| 5 | Reading graph import/query | Does the existing tested integration correctly import validated NEXT/PREVIOUS and allow query navigation? If only a unit test exists, say so; do not infer that a full query run occurred. |

## Files and evidence to consult minimally

- Latest checked-out source: `EvidenceNet/scripts/run_hybrid_article_clustering.py`, `repair_vldocir_single_work_reading.py`, `vldocir_reading_backbone.py`, `EvidenceNet/evidence_graph/hybrid_article_clustering.py`; actual worker launcher and any *new* integration modules referenced by current scripts.
- Existing tests, especially `EvidenceNet/tests/test_hybrid_article_clustering.py`, `test_vldocir_article_codefix_audit.py`, and worker/reading/import tests actually present.
- Existing output/log artifacts from recovery and smoke runs, only insofar as each of the five questions requires evidence.
- Previous findings: `ARTICLE_READING_CODE_LEVEL_FIX_HANDOFF_20261102.md` were based partly on pre-fix code. Treat them as **hypotheses to verify**, not accepted current failures.

## Required compact output

Provide **one concise Markdown answer** with exactly five rows:

| Concern | Verdict | Actual code path and lines | Existing test/log evidence | Any real remaining gap |
| --- | --- | --- | --- | --- |
| ... | fixed / still present / old path unused / unverified | ... | ... | ... |

For `unverified`, state what evidence is missing; do **not** propose broad reruns. Explain any difference between what GitHub shows and newer HoreKa local code. Only suggest a small targeted follow-up when a genuine defect remains. **Do not generate a new multi-file report bundle.**

## Direct instruction to Codex

> Only validate the five previously raised concerns against current executed code and tests **already completed**. Do not assume testing is pending. Do not run new tests, GPU, LLM, Slurm, or change source/output files. Produce the five-row evidence matrix with exact references and correct earlier claims where tests prove them obsolete.
