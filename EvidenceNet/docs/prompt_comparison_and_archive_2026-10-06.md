# Prompt-only comparison and experiment archive — 2026-10-06

**Decision: NOT PASSED. Do not promote grounded-v3 or submit the broader run.**
The default prompt policy remains `legacy`. A clearer general prompt did not
remove the known semantic failures, and it lost useful relations.

## What changed and how it was tested

Add opt-in `--edge-prompt-policy grounded-v3` with a compact decision order:
identify the target's visible content, identify the primary span's proposition,
then require a concrete correspondence. Define captions separately from credits,
require target-specific attachment, permit empty output, and distinguish visual
illustration from independent verification of facts. This version removes the
benchmark-specific examples used by legacy span-id-v2.

Job **52533** ran two sequential two-H100 dev tasks. Both completed with exit 0:
legacy-v2 took **7m43s**; grounded-v3 took **5m28s**. There were **12 visual cases
on 10 pages**, comprising five known-failure targets, three positive-control
targets and four additional transfer-control targets. These are purposive
diagnostic samples, not an independent accuracy benchmark.

Both arms used the same original source page and target crop, frozen 46209 flows,
candidate IDs/text/order, span-id-v2 segmentation, validators, model configuration,
greedy decoding and 1200-token output budget. Only the prompt changed. Neither arm
reran flow generation; CLAD therefore remained evaluable despite its flow failure
in the earlier end-to-end test. Source image hashes were checked before inference.
Both recorded validator/helper hashes match the saved `code_at_execution/` files.

The decision criteria were written before inspecting the arm outputs: complete
source review, no new response/source-address failures, retention of a supported relation for all
seven positive visuals, at least 50% fewer clearly unsupported accepted edges,
and no new serious semantic error. Raw edge counts alone cannot pass the gate.

## Source-reviewed results

The assistant inspected source pages, target crops and all **32 accepted edges**
across both arms. Labels below are assistant source review, **not human GT** and
not a generalizable precision estimate.

| Measure | Legacy-v2 | Grounded-v3 |
|---|---:|---:|
| Completed visual cases | 12/12 | 12/12 |
| Invalid whole responses | 0 | 0 |
| Rejected wrong-unit/unknown evidence span IDs | 0 | 1 |
| Proposed edges | 19 | 15 |
| Accepted after identical validation | 19 | 13 |
| Supported associations | 13 | 9 |
| Clearly unsupported associations | 3 | 3 |
| Uncertain association/evidence scope | 3 | 1 |
| Positive visuals retaining a supported edge | 7/7 | 6/7 |

The three clear errors persist:

1. **Wrong target image:** the spring/mass crop is linked to the function-block
   description. V3's basis describes integrators and gains that occur in the
   other diagram on the full page, not the target crop.
2. **Topic substituted for visual evidence:** the numerical GB300 benchmark claim
   is justified by NVIDIA branding on an award belt.
3. **Wrong caption attachment:** text beneath the ambulance photograph is attached
   to the separate large river-vehicle image without explicit shared-panel wording.

There is also a regression in ML1 p3: the localization label genuinely belongs to
the kitten image, but V3 changes the association to `CAPTION_FOR` over a span that
bundles four labels for different images. Attachment scope remains uncertain until
the localization label can be addressed separately. This is not counted as a
cleanly retained positive. On the causal block diagram, V3 keeps one correct
equation but drops several other supported descriptions/equations. It also finds
one useful extra probability span in the entropy diagram; that gain does not
offset the remaining errors and lost positives.

Two V3 proposals were photo-credit-only evidence and were rejected by the existing
v2 validator. A V3 supporting span belonged to another text unit and was also
rejected; its valid primary edge was retained. Credit filtering is not a new
prompt success. Retained spans have valid source addresses, but exact grounding
still does not establish semantic support.

## Consequence and next experiment

No broader GPU job was submitted. The prepared
`_archive/2026-10-09-launchers/current/run_grounded_v3_regression.sbatch` checks `evaluation.json` for PASS and
exits before loading a model when the review gate fails. The initially prepared
expansion scope was the complete 49-page/25-document regression; **1048-page
inference has not been submitted**.

The next useful change is target-specific verification: inspect the crop alone
for ILLUSTRATES correspondence, then use page context separately for caption
attachment. A separately checked visual observation should prevent borrowing
features from another image. Multi-image label lists also need more specific
addressable spans. These are proposed next experiments, not implemented or
validated improvements in this report.

Artifacts under `EvidenceNet/output/prompt_comparison_20261006/`:

- `manifest.json`: both frozen prompts and matched source/candidate inputs.
- `decision_criteria.json`: recorded advancement criteria.
- `legacy-v2/`, `grounded-v3/`: raw responses, accepted/rejected edges and hashes.
- `source_review.json`: per-edge labels bound to both output summary hashes.
- `evaluation.json`: computed NOT_PASSED decision and counts.
- `comparison.html`: source page/target crop and side-by-side reviewed outputs.
- `code_at_execution/`: matching runtime source snapshots.

## Earlier short experiments and archival

The previously queued jobs are now complete. **48023** repaired **5/8** frozen
failed flows using six additional model calls; three remain failed (missing basis,
mistyped ID and malformed verbose JSON). These are structural flow repairs, not
complete regenerated nodes/edges or verified ownership. **48027** processed ten
pages: nine complete, one CLAD flow failure, 16 local relations. Completion is not
a semantic quality result, and a failed page's absent edges cannot be counted as
an improvement.

Archived **12 completed experiment directories and four logs**, **1,441 files**,
348,908,318 bytes, under `_archive/2026-10-06-experiments/`. Every regular file was
hash-verified. The archive manifest also records relative symlinks and their
targets. Original paths remain compatibility symlinks, so reports and provenance
references still work. The 46209 baseline, active prompt comparison, semantic
audit labels, source/model data and ongoing runtime dependencies remain active.

Index: `current/json/experiment-archive-20261006.json`; full manifest:
`_archive/2026-10-06-experiments/manifest.json`.
Restore without overwriting changed paths:

```bash
EvidenceNet/.venv_qwen/bin/python current/archive_recent_experiments.py --restore
```

Validation: **42 relevant tests passed** (14 relation-first, 8 bounded recovery,
5 assignment patch, 9 grounding, 4 adapter, 2 new prompt/frozen-input integration),
plus compilation, launcher syntax, hash verification and an archive/restore smoke
check including a relative symlink. The tests establish implementation behavior;
the semantic decision comes from the source review above.
