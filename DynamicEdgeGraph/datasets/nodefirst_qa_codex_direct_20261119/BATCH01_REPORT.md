# Codex Direct Node-first QA — Batch 01

Date: 2026-11-19  
Status: first 100-record batch complete; cumulative 300-record target not yet complete.

## Output

- Gold QA: `qa_gold_codex_direct_batch01.jsonl`
- Per-record second-pass audit: `batch01_direct_audit.jsonl`
- Audit summary: `batch01_audit_summary.json`
- Build summary: `batch01_summary.json`
- Reproducible local scripts: `scripts/build_batch01.py` and `scripts/audit_batch01.py`

No scheduler, GPU job, or external generation service was used. No r1, r2, r3,
Snapshot-B, or Snapshot-D source file was overwritten.

## Distribution

| Category | Records |
|---|---:|
| Single Node | 20 |
| Cross-page | 30 |
| Cross-document, two documents | 35 |
| Cross-document, three or more documents | 15 |
| Total | 100 |

This is exactly the requested 20% / 30% / 50% distribution, including 35% two-document
and 15% three-plus-document QA.

## Construction difference from the previous 299-record review pool

- 83 source records were retained only after direct semantic re-review.
- 11 of those retained records had their question or answer rewritten to remove internal
  document IDs, unsupported implications, misleading spatial wording, or ambiguity.
- 17 records were newly authored directly from canonical evidence groups.
- Repetitive Twitter/X comparisons, redundant NIH-logo variants, single-document
  shortcuts, and answers containing unsupported words such as `implied` were not used.
- Three weak or repetitive Cross-page records were replaced with previously audited
  integrative questions.

The old 299-record file remains a candidate pool; it is not renamed or treated as Gold.

## Second-pass audit results

| Check | Result |
|---|---:|
| Records passed | 100/100 |
| Evidence references locatable | 196/196 |
| Page images locatable | 196/196 |
| Exact claim spans | 362/362 |
| Exact normalized question duplicates | 0 |
| Question pairs with token Jaccard >= 0.65 | 0 |
| Multi-node evidence without an exclusive answer contribution | 0 |
| Questions exposing internal `real_*` / `short_*` IDs | 0 |
| Scheduler jobs submitted | 0 |

There are 176 different Gold nodes. The most reused node appears four times. Evidence
modalities are 117 TEXT, 47 IMAGE, 14 PARA, 11 COMPOSITE, and 7 TABLE references.

## Mapping note

156 evidence references belong to the Snapshot-D formal canonical pool. Another 40
references come from the earlier frozen canonical corpus used by the reviewed r3 and
integrative records. All 40 legacy references retain existing source JSON and page-image
provenance, but they still need to be included in the retrieval node-union manifest before
training; they must not be looked up in Snapshot-D alone.

## Review scope

The semantic review in this batch was performed directly by Codex as requested, followed
by deterministic source, mapping, exact-span, category, node-contribution, internal-ID,
and duplicate checks. It is intentionally labelled `direct_codex_semantic_review`, not
misrepresented as an independent external-model review.

## Remaining work

Two additional 100-record batches are still required to reach 300 records while preserving
the same distribution. New Cross-document questions remain the limiting category; later
batches must continue to prefer textual, table, temporal, method-to-result, and controlled
comparison evidence rather than filling the quota with repetitive logo/color questions.
