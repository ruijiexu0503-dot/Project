# Non-text evidence representation comparison

Matched three-arm development experiment, 2026-10-15. This isolates how non-text node members are represented to the four-tag relation classifier. The existing 58-case description run (78065) continues separately; its scores are not substituted into this comparison because its system prompt and inference entry point differ.

Submitted CPU job: **78086**, `split-modality-3arm`.

## Conditions

| Arm | Ordinary eligible text and captions | Each visual/table member |
| --- | --- | --- |
| description | Unchanged | Qwen description only |
| raw | Unchanged | Original crop only |
| mixed | Unchanged | Same description plus same original crop |

All three arms use the same Qwen3.5-35B-A3B model, CPU bfloat16, neutral system and task prompt, four semantic definitions and role-based direction rules, independent REFERENCES schema, endpoint order, provisional reference annotations, 400-token limit, two-attempt limit and deterministic generation. All arms use `generate_raw_with_images`, including the description arm with zero images. There is no conversation history between calls. Arm order is deterministically alternated by case ID to avoid always running one arm first.

The subset contains all 14 cases with eligible non-text members in `data/benchmarks/evidence_edges_v1_20261014`: P14/P15/P16/P18–P23, N04/N11/N21/N22, U02. These use eight unique visual members and one table. Thirteen cases involve visual members, two involve the table, and P15 involves both. The remaining 44 text-only cases are not repeated three times. This small subset includes repeated assets and is not an independent test set or a retrieval evaluation.

The eight existing descriptions are reused byte-for-byte, with their Qwen generation records preserved. The table is currently represented by parsed HTML and has no visual description. Its original table crop is extracted from the prepared source page at the parser's coordinates, checked to contain the full table, and described once with the original crop-description prompt, model and 180-token limit. That single description is reused by description and mixed arms. Description generation is completed and all three sets of inference inputs are hash-frozen before any relation predictions.

The table's parsed HTML is retained in the source audit but omitted from every classifier arm: supplying it to the raw arm would introduce an extra textual representation. Ordinary text and captions are preserved. Original assets are retained for inspection. Generated descriptions cannot serve as proof of an explicit original-document citation; reference cues must be owned by original text.

## Run

```bash
.venv-magazine-exp1/bin/python EvidenceNet/scripts/run_split_modality_comparison.py prepare
sbatch current/slurm/traffic_relevance/split_modality_comparison_cpu.sbatch
```

Output directory: `EvidenceNet/output/split_taxonomy_modality_comparison_v1_20261015/`.

- `protocol.json`, `manifest.json`: fixed experimental design and source/code hashes.
- `assets.jsonl`, `assets/`: original members, description provenance, table HTML audit and table crop.
- `descriptions.jsonl`: existing descriptions plus the newly generated table description.
- `inference_manifest.json`: exact frozen descriptions, prompts and all three arms' inputs.
- `{description,raw,mixed}/inputs.jsonl`, `predictions.jsonl`, `metrics.json`: arm-specific immutable inputs, raw attempts, normalized predictions, timing and metrics.
- `REPORT.md`, `comparison.json`, `case_comparison.jsonl`: progress, matched win/loss counts and every case across all three arms.

Scores use source-reviewed provisional functional readings, not independently adjudicated expert gold. U02 is semantically unresolved and excluded from semantic accuracy; alternative legitimate functions/directions for P14/P21/P22 were frozen earlier. Invalid and missing outputs are reported separately and excluded from paired win/loss counts. Inspect the same paired cases for missed edges, spurious edges, label/direction changes, and independent reference errors. A changed answer is not automatically an improvement. If a description omits or misstates a detail, distinguish that from a classifier error by reviewing the retained crop.

Validation: six focused tests passed across the suite and comparison runners. They check that the three conditions differ only in non-text representation, ordinary text/captions are identical, table HTML and excluded metadata do not leak into classifier inputs, image numbers remain owned by the right endpoint, and invalid/missing/unresolved cases do not become paired successes or negatives. Preparation verified all 14 cases and nine non-text assets.
