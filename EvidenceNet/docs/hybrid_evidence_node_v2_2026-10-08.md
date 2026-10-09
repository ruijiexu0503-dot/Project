# EvidenceNode v2 regression and paired experiment

This is an opt-in revision of the actual `evidence_nodes.jsonl` assembly branch.
It does not replace the component nodes used by document-graph job 59867, the
default Step-2A builder, or existing frozen results.

## Changes

- Text starts as individual parser atoms in both arms. Embedding similarity alone
  cannot merge text. Qwen proposes same-sentence continuations; source-boundary
  guards are enforced again during assembly.
- Block completed sentences, colon introductions, periods before closing math
  delimiters/equation numbers, and pairs crossing a table or heading. Captions
  and figures alone are not barriers, preserving genuine interrupted sentences.
- Materialize all parser table atoms as `TABLE` evidence. Retain unattached
  captions as `CAPTION` evidence with unresolved attachment; do not attach a
  Table-labelled caption to a visual when parser table atoms exist. Table-caption
  pairing is not solved by this revision.
- Mark existing crop descriptions as unverified retrieval hints. Both arms use
  identical frozen descriptions to isolate the embedding comparison. This does
  not repair hallucinated image descriptions.
- Validate atom/fragment/visual/native-component coverage, table inclusion,
  parser-recognized structural exclusion, input hashes and decision provenance.

## Local validation

Five boundary test methods pass, and fresh geometry-only candidate preparation
passes on all 49 pages. A 49-page replay uses frozen old Qwen decisions and new
geometry-only assembly; it is NOT fresh inference or an independent evaluation.

- Source and component checks: 49/49 pages.
- Known wrong joins retained: 0/15 (previously 15/15).
- Table atoms in evidence: 3/3 (previously 0/3).
- Frozen mixed-material required continuations: 2/2 retained.
- Flagged valid continuation across a figure/caption: 1/1 retained.
- Frozen mixed-material clear caption bindings: 2/2 retained.
- Known slide-headline structural leak: still present on ESS203 slide 4.

The rules were developed using these regression failures, so these counts must
not be presented as independent accuracy. Abbreviations ending in periods may
be conservatively split. Other previously unreviewed joins still need review.

Replay report:
`EvidenceNet/output/hybrid_node_v2_guard_replay_20261008/regression_evaluation.json`.

## Submitted experiment

Status update 2026-10-09: GPU job 61078 and CPU evaluation 61079 completed.
Both arms have 49/49 valid pages, all 3 tables and no retained known wrong joins
among the 15 reviewed negatives. The embedding arm produces 550 nodes / 34 joins
and retains 2/2 specified mixed-material continuations; geometry produces
566 nodes / 18 joins and retains 0/2. Both lose the reviewed cross-figure
continuation and retain the slide-headline leak. Unlike the frozen replay above,
these are fresh Qwen decisions; neither run is an independent holdout.
Per-arm `regression_evaluation.json` and batch `run_summary.json` files are the
sources for these counts. The submission details below are historical.

GPU array **61078**: 14 tasks, two arms of the same 49 pages, seven batches per
arm, at most two tasks concurrently, two H100 GPUs per task, 14m30s limit.
Submission was confirmed PENDING (Priority).

1. Embedding + geometry + bounded Qwen.
2. Geometry + bounded Qwen (no embedding calls).

The node boundaries, structural policies, descriptions, Qwen model and guards
are otherwise shared. This compares embedding's effect on caption ranking and
boundary-score hints, not description generation. Fresh Qwen decisions use the
v2 prompt and policy-specific candidate caches.

CPU evaluation **61079** depends on successful completion of 61078 and evaluates
both arms. Outputs: `EvidenceNet/output/hybrid_node_v2_61078/{embedding_geometry,geometry}`.
Entrypoints: `current/slurm/hybrid_nodes/run_hybrid_node_v2_dev.sbatch` and
`current/slurm/hybrid_nodes/evaluate_hybrid_node_v2.sbatch`.

## Promotion remains pending

The separate nine-page new-document sample has not undergone node inference.
The VL-DocIR retrieval workflow has been submitted, but is not an independently
annotated node-quality benchmark. Resolve the slide-role and description problems,
then review held-out node boundaries, caption/table
attachments, source coverage and structural exclusions. Neither operational
success nor the known-error replay automatically promotes the branch.

Only after that gate should article membership, NEXT and semantic edges be
adapted to the selected EvidenceNode IDs; the existing component-based graph
must not be described as already using these EvidenceNodes.
