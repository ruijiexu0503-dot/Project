# V2 comparison: bounded GPU smoke 80082

## Final review

Job 80082 ended **FAILED (exit 1)** after **4m46s**. All four conditions
passed membership and raw reading, then exhausted both composition attempts.
No final evidence-node or reading-edge artifacts were exported. This was not
a GPU memory failure or timeout; the model was fully resident on H100.

Source-image review and a stage-only audit (`page_2/stage_audit.json`) found
the same result in all four conditions:

| Stage | Article first, both presentations | Reading first, both presentations |
| --- | --- | --- |
| Article ownership of referenced sources | 11/11; pair TP27/FP0/FN0/TN28 | Same |
| Title ownership | 2/2 | Same |
| Reference BODY adjacencies | 7/7 | Same |
| Image credits excluded from article membership | 2/2 | Same |
| True continuation pairs surviving candidate filtering | 1/2 | Same |
| Final node composition | Failed | Failed |

The article and reading relations were identical between presentations and
arms on this page. These are partial development-reference stage checks,
not final-node accuracy or evidence of a general winning stage order.

Two remaining problems are concrete:

1. **Composition does not respect its bounded task.** There are no CAPTION
   candidates on this parsed page, yet every composition response invents
   figure rows. Several treat `N001`/`N011` (image credits, frozen PAGE_CONTEXT)
   as captions; some use visual nodes as captions or reverse the roles.
   One condition also invents P002–P009 although only P001 was supplied.
   Strict validation correctly rejects these responses. The composition
   prompt still exposes all source N labels and uses a nonempty figure JSON
   example without explicitly defining the empty-candidate behavior.
2. **The quote-start guard removes a true continuation before Qwen sees it.**
   A010 ends `the social gathering known as a`; A011 starts `"moussen" — an
   annual fair ...`. This is one sentence across columns, confirmed in the
   page image. The generic `new_quoted_paragraph` guard blocks A010→A011.
   A004→A005 survives and every response chooses CONTINUATION, but no valid
   final composition is available. Candidate recall is therefore 1/2, not
   final continuation recovery of 1/2.

Recommended next repair: separate body-pair and caption-scope decisions,
skip an empty task deterministically, expose an exact allowed-ID checklist
and give precise extra/missing IDs on retry. Do not delete invented output
rows silently. Replace the unconditional quote-start veto with a bounded
review of unfinished-sentence continuations, retaining the CERN A023→A024
new-paragraph negative regression. Keep all four existing outputs unchanged
and use a new experiment version for any repair. Re-run CLAD before expanding
to the other three materials. The present result cannot choose a pipeline order.

## Submission and startup record

2026-10-15. The user requested GPU execution. Job **80082** started on
`dev-gpu-h100`, node `hkn0901`, with one GPU and a one-hour wall-time limit.
CPU smoke **80079** was cancelled after GPU startup (CPU elapsed 5m28s);
its output remains available for provenance.

This smoke executes only CLAD page index 2: article-first and reading-first,
each with original and reversed input lists, for **four conditions**. All four
source snapshots are prepared, but pages 0, 1 and 3 are not submitted.
Completion and source review of the smoke are required before expanding it.

- Entry point: `EvidenceNet/scripts/run_article_order_gpu_smoke.py`.
- Launcher: `current/slurm/evidence_nodes/article_reading_v2_gpu_1h.sbatch`.
- Fresh output: `EvidenceNet/output/article_reading_order_comparison_v2_gpu_20261015/`.
- Logs: `EvidenceNet/logs/article-order-v2-gpu-80082.{out,err}`.

V2 prompts, validators, model and reference annotations are unchanged.
Only the frozen common role reviews and embeddings are reused from CPU
preprocessing; compared membership, reading and composition calls execute
in the fresh GPU output directory. CPU stage responses and summaries are
not reused as GPU results. The code/input manifest includes the GPU wrapper.

After model loading, `page_2/gpu_execution.json` records actual parameter
devices, device map, GPU model and CPU offload. This distinguishes GPU
allocation from actual model placement. The one-hour limit is a resource
ceiling, not a completion estimate; unfinished stage generation has no
checkpoint if Slurm terminates it.

Startup verified: the placement record identifies **NVIDIA H100** and all
35,107,181,936 model parameters on `cuda:0`, with `cpu_offload=false`.
Model loading completed successfully; no complete condition was available
at this startup check.

For this smoke, inspect `page_2/summary.json` and all four condition summaries.
The inherited top-level `comparison.json` still expects 16 conditions across
four pages, so its global `complete=false` alone does not imply smoke failure.
No winner or production pipeline change is established by job startup or
schema validation.
