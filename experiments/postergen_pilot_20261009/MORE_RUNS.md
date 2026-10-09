# Three additional poster runs — 2026-10-09

Requested after reviewing the DETR pilot. Uses the same official PosterGen
prompts, layout/styling/renderer and local Qwen3.5-35B-A3B model. No production
pipeline or original DETR output is overwritten.

| Case | Text input | Candidate visuals |
| --- | --- | --- |
| GW150914 discovery | Existing parsed pages 1–8 | Figures 1–3 and Table I |
| The Hallmarks of Aging (2013 review) | Existing parsed pages 1–21, before References | Figures 1, 3, 6, 7 on pages 37, 41, 46, 47 |
| A Mathematical Theory of Communication | Existing parsed pages 1–51, including the earlier Part I appendices; final pages 52–55 omitted | Figures 1, 7, 8, 9 |

Unlike the original DETR crop preparation, detector boxes are padded by up to
12 PDF points to recover cut-off edge labels, constrained by adjacent captions
and page boundaries. Source boxes and actual crop rectangles are both recorded.
Entropy Figure 9 has no top padding to exclude preceding prose. Hallmarks
Figure 6 was missed by the existing visual detector: the single large native
PDF image on page 46 supplies an explicitly marked fallback bounding box.
No new image content is invented.

Submission **61971**, array indices 0/1/2 correspond to the table order above.
Partition `gpu-h200`, two GPUs per case, at most three concurrent cases, 40-minute
limit per case. This resource allocation differs from DETR's H100 development
job; runtime numbers must not be treated as a controlled speed comparison.
The initial concurrency limit of two was raised to three while the first two
cases ran, allowing the already-submitted entropy task to start sooner.

```bash
# From repository root; prepare refuses to overwrite inputs after model calls.
EvidenceNet/.venv_qwen/bin/python experiments/postergen_pilot_20261009/run_more.py prepare gw150914_detection
sbatch experiments/postergen_pilot_20261009/run_more.sbatch
# After successful model generation, render, audit and copy deliverables:
EvidenceNet/.venv_qwen/bin/python experiments/postergen_pilot_20261009/run_more.py finish gw150914_detection
```

Each output goes to `data/generated_posters/<case>_20261009/` and contains PPTX,
PDF, preview PNG and structural audit. Original inputs, raw model calls and
intermediate states remain under this experiment's `output/<case>/`.

Review will check source consistency and actual rendered output. Structural
checks alone cannot certify numeric comparisons, medical evidence scope,
theorem assumptions, figure relevance, or local text collisions.
