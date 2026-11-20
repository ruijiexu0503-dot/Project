# RELATED ordinal pilot, one GPU hour

2026-10-15. User authorized a one-hour GPU trial replacing forced directional semantic types with undirected RELATED plus a relatedness level. Submitted job **79705**, partition `gpu-h200`, one GPU, 16 CPUs, 160 GB host memory, wall limit 01:00:00. Initial pending reason is Priority, not a reported quota reason; remaining project GPU minutes are not established by the available user-level `sshare` output. `gpu-b100` was not a valid partition name in the scheduler query. No duplicate GPU job or CPU fallback was submitted.

Scheduling update: initial H200 start estimate was 2026-10-16 03:33:57 Europe/Berlin, an unguaranteed scheduler estimate. The developer H100 queue was empty at inspection, and its maximum wall time is one hour. The same pending job 79705 was updated to allow `dev-gpu-h100,gpu-h200,gpu-h200-8`, retaining one GPU and one hour. Local checkpoint metadata reports 71,903,655,008 weight bytes (about 67 GiB), so a single 80 GiB H100 is a plausible alternative for these bounded prompts; actual placement/device and any runtime failure are recorded rather than assumed. The launcher now reflects the allowed partition list.

After the update, `sacct` reports **79705 RUNNING on gpu-h200-8**. Logs show weight loading in progress. This is one running GPU allocation, not simultaneous jobs across those partitions.

## Fixed inputs and scoring

58 reusable cases plus all 48 naturally retrieved pairs from 79541, deduplicated by unordered immutable node IDs, give **103 pairs**. Three natural pairs overlap the reusable suite. Tasks are hash-ordered independently of reference labels; A/B presentation is also deterministic. There are 42 image-bearing pairs. The prior experiment need not finish to reuse its already frozen candidate inputs.

Qwen3.5-35B-A3B receives ordinary source text, source-mapped original HTML table rows, existing visual descriptions and original visual/table crops. No extra lossy table description is generated. Each source text window/table row/visual gets a short endpoint-owned evidence ID. Model selects IDs instead of regenerating quotations, addressing the previous quote-length, line-wrap and HTML representation failures without waiving endpoint ownership.

Levels are fixed before inference:

| Level | Intended meaning |
| --- | --- |
| 0 | No supported substantive content connection |
| 1 | Broad theme/task/institution only; generic terms or visual style are insufficient |
| 2 | Specific content connection, preserving differences in dataset population, method components or conditions |
| 3 | Direct complementary evidence: actual text/figure pairing, explanation or specific definition/application |

Exported candidate cutoff is level >= 2. `related_score = level / 3` is only an ordinal graph weight, not a calibrated probability or model confidence. RELATED is symmetric and does not assert support, causality, numerical comparability, identical algorithms or an explicit reference. Reading and reference layers remain independent. A short reason and limitation accompany each decision; levels >= 2 require evidence IDs at both endpoints. A node without eligible evidence forces level zero.

## Evaluation scope

The original requested-relation binary labels are not copied into the RELATED evaluator. New provisional source-reviewed readings are frozen before inference. N05's concrete method names/application, N06's PeMS subset-family connection and U03's shared optimizer components can be related without satisfying the earlier strict full-mechanism or measurement-comparability claim. N06's 228 versus 883 sensors must remain a limitation. U01 and U02 straddle the candidate cutoff and are excluded from cutoff precision/recall.

Reference distribution: 23 cases at level2, eight at level3, 19 at level1, three at level0, three with allowed levels0/1, and two unresolved between1/2. Cutoff evaluation therefore has 31 provisional positives and 25 negatives; this differs from previous taxonomy references and cannot be used to claim improved precision/recall by directly comparing headline numbers. Ordinal agreement and cutoff confusion are reported separately. These are assistant-reviewed development annotations, not expert blind-test gold. The natural cohort has no complete independent labels and requires source review of accepted and rejected cases.

## Execution and artifacts

```bash
.venv-magazine-exp1/bin/python EvidenceNet/scripts/run_relatedness_pilot.py prepare
sbatch current/slurm/traffic_relevance/relatedness_h200_1h.sbatch
```

Output: `EvidenceNet/output/relatedness_ordinal_mixed_v1_20261015/`.

`inputs.jsonl` freezes exact prompts, evidence-ID lookup maps and image associations. `evaluation/reference.jsonl`, `protocol.json` and `manifest.json` freeze readings, settings, code and asset hashes. `execution.json` records GPU/device placement and Slurm job ID. `predictions.jsonl` preserves all raw attempts and checkpointed decisions. `related_edges.jsonl` exports model proposals at the fixed cutoff with owned source anchors. `summary.json` reports completion, invalid outputs, levels and reference metrics; `evaluation/review.jsonl` joins predictions to provisional readings.

The runner requires CUDA, uses deterministic decoding with thinking disabled and a 360-token response cap, and allows two attempts with explicit error feedback. It checks an internal 52-minute budget between pairs, leaving time for checkpoint/report writes within the one-hour allocation. A partial run remains explicitly incomplete; it is not reported as a completed experiment. Original pipeline, frozen baseline and 79541 outputs are unchanged.

Four focused tests pass for endpoint ownership, required evidence, empty-node rejection, ordinal integer validation, exact native-table row mapping, text-window coverage, deduplication and the difference between RELATED and prior reference semantics. Preparation passed for all 103 pairs; largest prompt is 16,396 characters. Shell syntax and whitespace checks passed.
