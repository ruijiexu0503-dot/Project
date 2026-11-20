# Bounded hybrid node-generation pilot (2026-10-07)

This pilot tests an **opt-in node-generation branch** on the same prepared member-asset representations as the previous [model comparison](matched_node_generation_comparison_2026-10-06.md). The first three pages are development cases; `gw150914_detection/page_0002` was reviewed and frozen as a held-out check before hybrid inference. Review labels are assistant source review, not independent human ground truth. Production EvidenceNodes and the active Step-2A entrypoint were not changed.

## Method

1. Preserve parser atoms, source fragments, geometry members, native visual members and structural sidecars. A crop-only Qwen3.5-35B description is attached to each visual; Qwen3-Embedding-0.6B and geometry score parser-typed caption candidates and adjacent text candidates. This is a Qwen-assisted baseline because image descriptions use Qwen.
2. Present **all adjacent non-structural text-atom pairs** on each page to a separate, bounded Qwen3.5-35B call. The call sees source suffix/prefix, embedding cosine and geometry score and decides only `CONTINUATION` vs `SEPARATE`. Short text immediately after a heading is separately classified `DECK`, `BODY` or `UNRESOLVED`. It cannot create source IDs, alter captions, or merge visuals.
3. Deterministic assembly applies only validated decisions. A malformed or incomplete Qwen response falls back to the unchanged baseline nodes for that page. The pipeline checks input/prompt/candidate hashes, one-time fragment and visual coverage, native-member coverage, and model provenance. All output is marked `production_modified: false`.

The fixed review has 17 adjacent-pair decisions, three required same-sentence continuations, two role candidates and four clear visual-caption pairs across four pages. The held-out page has one required continuation (`D005` ends “detected”; `D006` starts “the coincident signal”).

## Frozen result

| Arm, four pages | Reviewed structural atoms in evidence nodes | Wrong body-pair merges | Required continuations missed | Clear caption bindings | Source coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Embedding + geometry baseline | 1 | 0 | 3/3 | 4/4 | 4/4 |
| Bounded hybrid | 0 | 0 | 1/3 | 4/4 | 4/4 |
| End-to-end Qwen3.5-35B reference | 6 | 5 | 1/3 | 4/4 | Qwen schema 4/4 |

The hybrid correctly moved DLR page 9's deck `D001` out of evidence nodes and joined the DLR page 17 and held-out GW page 2 continuations. It made no reviewed false merge or caption regression. It **still missed** GW page 4's `D006`–`D007` continuation: the bounded Qwen response treated the left side as a complete sentence even though it ends with “and their”. Of 17 reviewed adjacent pairs, it identified two of three continuations and rejected all 14 reviewed non-continuations. It classified both role candidates correctly (`D001` as deck, held-out `D005` as body).

The [predeclared small-sample gate](../scripts/evaluate_hybrid_node_pilot.py) passes: no reviewed regression, improved held-out continuation, and all Qwen decisions valid. Passing licenses **opt-in integration only**. Four pages have no table node and no ambiguous multi-image caption case. The baseline's three clear captions were also selected by geometry alone, so this run does not isolate an embedding benefit. The result does not justify replacing the default node builder or a broad test without independent labels.

## Pipeline integration

The [opt-in pipeline entrypoint](../pipeline_steps/step2_b_hybrid_member_nodes.py) accepts any prepared member-asset root with a `manifest.json` and per-page `input_representation.json` plus `original.png`. It runs the baseline and bounded Qwen stages sequentially and writes separate `embedding_geometry/` and `hybrid/` outputs. `--validate-only` checks an existing run without inference. The [dev launcher](../../_archive/2026-10-09-launchers/current/run_hybrid_member_nodes_dev.sbatch) is available; it is not part of the active deterministic Step-2A path. Exact source/member coverage failure or invalid Qwen decisions cause a nonzero pipeline exit, with per-page baseline fallback preserved for review.

Artifacts: [pilot evaluation](../output/hybrid_node_pilot_20261007/evaluation.json), [source review](../config/reviews/node_generation/hybrid_node_review_20261007.json), [fresh integrated evaluation](../output/hybrid_member_pipeline_v1/hybrid/evaluation.json), and [fresh pipeline validation manifest](../output/hybrid_member_pipeline_v1/hybrid_pipeline_manifest.json). Pilot GPU job `53327` completed. The new entrypoint also ran **from scratch** as job `53352` in 5m26s; all four pages passed source/member validation and the same frozen semantic gate, with identical applied continuation/role decisions. The failure fallback was checked separately: an invalid decision preserved baseline membership, and a stale prompt hash was rejected.
