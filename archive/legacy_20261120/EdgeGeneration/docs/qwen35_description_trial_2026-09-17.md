# Qwen3.5 evidence-description retrieval trial

Prepared 1,158 matched evidence nodes: CERN 2022 Nov/Dec 333, CERN 2025 Jan/Feb
379, CERN 2026 May/Jun 399, GW150914 detection 47. Only successful explicitly
Qwen3.5-35B-A3B comparison records are used. Canonical source snapshots must match
the comparison's original baseline fields, order and type, not merely node IDs.
The historical descriptions do not include original-text hashes; that remaining
provenance limitation is recorded in the input manifest.

Exclusions: 1,225 nodes under 25 words, 28 unsuccessful descriptions, 24 snapshot
mismatches, two non-text/formula nodes, 25 reference/acknowledgment-section nodes.
These define a controlled experiment, not a production deletion policy.

Matched arms use BGE-M3 normalized CLS embeddings with a 512-token maximum:
original evidence text; Qwen3.5 summary plus key points; RRF fusion at top 10;
and union of both top-10 lists (a larger budget, reported separately). Same-document
pairs are excluded because validated article ownership has not yet been joined to
these historical snapshots. No claim is made about same-magazine retrieval.

Qwen3.5 reviews eight deterministic pairs in each of three strata: shared,
original-only, description-only. The reviewer sees originals and descriptions
but not retrieval scores or stratum. Direct relations require nonempty exact
source spans; invalid output remains invalid. The same model produced the
descriptions and reviews them, so these are exploratory model judgments, not an
independent precision estimate. There is no cross-document gold recall metric.

Prepared files: `EdgeGeneration/output/qwen35_description_trial_v1/`.
The job writes vectors, candidate lists, review sample, reviews, summary and HTML
report there. No production graph is written.

Slurm job **5149993** submitted to `dev_accelerated,accelerated`, 2 GPUs, 192 GB,
45 minutes; pending for priority at submission. Job 5149992 was cancelled before
execution because its H100 nodes were unavailable. Logs:
`EdgeGeneration/logs/q35-description-5149993.out` and `.err`.

Entry points: `scripts/run_qwen35_description_trial.py prepare|run --output PATH`
and `slurm/run_qwen35_description_trial.sbatch`. Twelve tests passed, including
the three snapshot-join tests. Input manifest hashes identify exact input files.
# Completed run findings

Job 5149993 completed with exit code 0:0 in 7m35s (Slurm accounting).
All 24 sampled judgments passed the implemented output validation.

| Candidate stratum | Reviewed | Direct relation | Topical only | Unrelated |
|---|---:|---:|---:|---:|
| Shared by original and description | 8 | 0 | 8 | 0 |
| Original only | 8 | 0 | 7 | 1 |
| Description only | 8 | 0 | 8 | 0 |

Unique candidate pairs: original 9,151; description 9,161; RRF 9,249;
union 14,003. Original/description intersection is 4,309, with 4,842 original-only
and 4,852 description-only pairs. Candidate novelty is not evidence of quality.

The review establishes no advantage for either representation on these small,
stratified samples. It does not estimate independent precision or corpus recall,
and it does not show that the corpus has no direct evidence relationships.
RRF-only candidates were not separately sampled for review.

Inspection shows clear false neighbors (e.g. Milky Way central-black-hole X-ray
measurements versus GW150914 binary-merger detection). Some rejections also merit
human calibration: a specific LHCb performance result paired with a broad CERN
performance statement, or collider plans paired with physics motivation, might
be useful under a broader contribution relation. The prompt's requirement for
a specific shared event/result/method/claim is stricter than general usefulness.
These examples are hypotheses for review, not relabeled positive edges.

Before another broad model run, establish a small independent evaluation set
with accepted relation scope and negative controls. Inspect subject loss in
descriptions and preserve exact entities from source context. Do not lower the
acceptance threshold merely to produce nonzero edges. Same-magazine article
connections remain outside this experiment.
