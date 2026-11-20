# Hybrid node generation across seven material types (2026-10-07)

This is an opt-in shadow comparison of the existing embedding/geometry baseline and bounded Qwen hybrid node branch. Seven pages were selected and the [source-review labels](../config/reviews/node_generation/hybrid_mixed_material_review_20261007.json) were written **before** mixed-material model inference. Labels are assistant review of source images and atoms, not independent human ground truth. The [preparation manifest](../output/hybrid_mixed_material_prepared_20261007/manifest.json) records the exact source representation and image hashes. Normalization only added parser-order indices and empty native-component arrays required by the member-asset branch; it did not change text fragments, bounding boxes, or visual bundles. Production nodes and the default Step-2A pipeline were not touched.

| Material (one page each) | Baseline | Bounded hybrid | Main observation |
| --- | --- | --- | --- |
| Text-only research paper (DETR) | No reviewed boundary error | Same | Both keep headings and running header out of evidence. |
| Research paper with table (GW polarization) | Misses two same-sentence parser splits | Joins both correctly | **Both leave the table atom in the structural sidecar and its caption unassigned**, so the table cannot be retrieved as an EvidenceNode. |
| Illustrated book (Luminous Garden) | Both image-caption pairs correct | Same | The stained-glass crop description includes specific names/manufacturer text not supported by the source caption and too small to verify in the crop; generated description needs a stricter visibility rule. |
| Presentation slide (Amazon Spheres) | Headline treated as evidence; photo not linked to it | Same | Parser marks the slide headline as generic text rather than heading/caption. |
| Government report (NIST AI RMF) | No reviewed boundary error | Same | List remains separate from the prose introduction under the same-sentence policy. |
| Annual report (NVIDIA) | No reviewed boundary error | Merges colon-led list with introduction | Under the predeclared **same grammatical sentence** rule this is one wrong merge, even though the introduction and bullets are topically related. |
| Image-only poster (NASA) | One visual node and a descriptive summary | Same | Visual source is retained; values remain in free-form description, without individually addressable source text or verified numeric extraction. |

## Frozen comparison

| Reviewed measure, seven pages | Embedding + geometry | Bounded hybrid |
| --- | ---: | ---: |
| Complete fragment/visual source coverage | 7/7 | 7/7 |
| Structural atoms in evidence | 1 | 1 |
| Wrong text merges under same-sentence policy | 0 | 1 |
| Required same-sentence continuations joined | 0/2 | 2/2 |
| Clear visual-caption bindings | 2/2 | 2/2 |
| Slide photo-headline context bindings | 0/1 | 0/1 |
| Table atoms represented as evidence | 0/1 | 0/1 |
| Image-only poster visual retained | 1/1 | 1/1 |

All seven Qwen decision responses were schema-valid. The hybrid joins `A_003`–`A_004` ("The simplest solution is" / "for the waves ...") and `A_004`–`A_005` ("linear polarization constraint" / "is defined ...") on the two-column table page. It also joins NVIDIA `A_011`–`A_012` because a colon introduces bullets; this violates the pilot's deliberately narrow same-sentence rule. The visual-caption success on the illustrated-book page is shared by both arms and does not isolate an embedding gain. Complete source coverage only proves content is present either in nodes or the structural/unresolved sidecar; it does **not** imply table retrievability.

The stained-glass description claims that text below the illustration names “Mr. Frank R. Crosby” and “the American Stained Glass Co.” The source caption identifies “Rudy Brothers Company” and a *Competitive Design for Stained Glass Window*. Because the printed text inside the 208-pixel-wide crop is too small to read confidently, those model-generated attributions must not be treated as sourced facts. This is a descriptive grounding failure independent of the node-boundary result.

## Decision

Do **not** promote this branch to the default pipeline or submit a broad corpus run yet. Before that, add a deterministic guard for colon-to-bullet transitions, represent parser `table` atoms with their captions as retrievable table nodes, handle slide headlines and photo context, and constrain image descriptions to visibly legible content. Then repeat with more pages per category and independent review. This pilot is diagnostic, not an estimate of corpus-level precision.

Artifacts: [run validation manifest](../output/hybrid_mixed_material_run_20261007/hybrid_pipeline_manifest.json), [per-page comparison](../output/hybrid_mixed_material_run_20261007/mixed_material_evaluation.json), [prepared inputs](../output/hybrid_mixed_material_prepared_20261007/manifest.json), and GPU job `53395` log in `EvidenceNet/logs/`.
