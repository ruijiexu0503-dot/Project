# Relation-policy ablation

Slurm job 5150318 uses Qwen3.5-35B-A3B on two GPUs. It was RUNNING when this
record was written. Outputs live under
`EdgeGeneration/output/relation_policy_ablation_v1/`.

Compared methods:

- Historical strict direct-relation review on the fixed 24 real pairs.
- Existing non-exclusive multisignal proposal prompt on those same pairs.
- Existing proposals followed by a source-grounded verifier checking every one
  of the five signals, including signals absent from the proposal. Each label
  has its own direction, anchors, reason and ACCEPT/REJECT/UNCERTAIN status.

The verifier permits implicit explanation and scoped factual examples without
requiring identical events. It distinguishes those from same-claim identity,
requires compatible scope, and disallows invented citation/author intent.
It is another call to the same model, not an independent annotator.

Evaluation inventory: 24 frozen real cases, eight manually authored synthetic
controls (four positive, four negative), eight reversed-input cases (the seven
previous non-UNRELATED proposals and one negative). Labels and case metadata
are stored separately from model input. The original 24 input texts/descriptions
remain unchanged. Strict-review controls were not run, so control comparisons
cover the existing multisignal policy versus per-label verification only.

Inspect `summary.json`, `results.jsonl`, and `report.html` after completion.
Compare which real labels survive, whether uncertainty is retained, positive
control coverage, negative control rejection, invalid outputs, and orientation
stability. The report does not estimate real-corpus precision or recall. No
production edges are written. Sixteen retrieval/validation tests passed before
submission.

Progress: `status.json` and
`EdgeGeneration/logs/label-verification-5150318.out`.
