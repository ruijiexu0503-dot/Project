# Grounded-v3 on the 49-page corpus — 2026-10-07

**Decision: NOT PASSED. Keep `legacy-v2` as the default edge prompt.** The larger matched comparison did not reverse yesterday's pilot result: grounded-v3 retained fewer source-supported relations, kept the known wrong-target links, and introduced a new logo-to-learning error.

## Scope and method

After the 49-page hybrid-node stress run finished, Slurm array **55636** ran a prompt-only comparison on the same source-page images. All eight two-H100 dev tasks completed with exit code 0. The source set has 49 pages from 25 documents; the frozen baseline provides **35 eligible visual cases on 19 pages from 14 documents**. The other pages cannot contribute a paired visual-edge prompt result without selected candidate ledgers; eight baseline pages had failed flows. This is therefore a comparison within the 49-page corpus, **not a 49-page end-to-end pipeline score**.

Both arms received the same full-page and target images, frozen flows, selected candidate IDs/text/order, span-id-v2 segmentation and validator, Qwen3.5-35B-A3B model, greedy decoding and 1,200-token budget. Only the edge prompt changed. All source-page image hashes were checked against the hybrid-node stress inputs, and each image hash was checked again before inference. The 12 earlier pilot cases have byte-identical images and prompts in this manifest. Some repeated model outputs differed slightly despite identical inputs, so all results below compare the two arms from this run.

## Results after source review

The assistant reviewed all **75 accepted edges** using the frozen source spans and target crops, and checked full pages for disputed attachments. Thirty-one labels from yesterday were reused only when the relation, source unit and anchor matched exactly; 44 edges were newly reviewed. These are assistant judgments, **not independent human ground truth or a general precision estimate**.

| Scope / measure | Legacy-v2 | Grounded-v3 |
|---|---:|---:|
| Eligible visual cases | 35/35 | 35/35 |
| Invalid complete responses | 0 | 0 |
| Source-address rejections | 0 | 1 |
| Proposed / accepted edges | 41 / 41 | 37 / 34 |
| Supported accepted edges | 30 | 20 |
| Clearly unsupported accepted edges | 5 | 6 |
| Uncertain attachment or span scope | 6 | 8 |
| Seven previously reviewed positive visuals retained | 7/7 | 6/7 |

The original 12 cases account for **15 supported / 3 unsupported / 3 uncertain** legacy edges versus **9 / 3 / 1** grounded-v3 edges. On the 23 newly added cases, legacy has **15 / 2 / 3**, while grounded-v3 has **11 / 3 / 7**. Thus the larger sample adds evidence of lost supported links and more uncertain scope; it does not dilute the original failures.

The three known errors persist in both arms: the spring/mass target borrows the other block diagram's description; an NVIDIA-branded award belt is treated as evidence for a GB300 numerical performance claim; and a rescue caption attached to the ambulance photograph is also attached to the separate river-vehicle image. Grounded-v3 additionally links a **KIT institutional logo** to a statement about learning through rewards and penalties, while legacy leaves that target empty. Both arms also confuse the separate “the spheres” logo with the photo of Amazon's glass domes; the generated bases describe vegetation absent from the target crop.

Grounded-v3 drops four of five accepted relations on the causal block diagram and four of six on the FMU diagram. It changes several supervised-learning list associations into `CAPTION_FOR` over a four-item span shared by separate images, so the target-specific label remains uncertain. A grounded-v3 supporting span on the causal block case also failed source-address validation; the valid primary edge was retained.

The predeclared gate required complete source review, no new invalid/source-address failures, all seven positive visuals retained, no increase in clearly unsupported accepted edges, no loss of supported edges and no new serious semantic error. Only complete review and response validity passed. No default-policy change or broader pipeline run was submitted.

## Artifacts and verification

- `EvidenceNet/output/grounded_v3_49page_prompt_only_20261007/manifest.json`: frozen cases, inputs, images and prompts.
- `decision_criteria.json`: criteria recorded before output inspection.
- `batch_0`–`batch_3`, `legacy-v2/summary.json`, `grounded-v3/summary.json`: raw and aggregated model results.
- `source_review.json`, `evaluation.json`, `comparison.html`: per-edge review, computed decision and side-by-side visual gallery.
- `_archive/2026-10-09-launchers/current/run_grounded_v3_49page_prompt_only_dev.sbatch`: dev GPU launcher.

Checks: all eight Slurm tasks completed successfully; aggregation verified manifest hash and exact case coverage; the evaluation verified identical model and validation-code fingerprints across arms. Python compilation and the two grounded-prompt pipeline unit tests passed.
