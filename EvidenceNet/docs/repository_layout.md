# EvidenceNet repository layout

This file documents the code paths that are part of the current executable pipeline and separates them from archived experiments.

## Current pipeline entry points

- `evidence_graph/cli.py` – package CLI (`python -m evidence_graph ...`).
- `evidence_graph/build_nodes.py` – Phase-1 node-building entry point.
- `evidence_graph/pipeline.py` – Phase-1 orchestration.
- `evidence_graph/semantic_pipeline.py` – content-unit segmentation and semantic-edge stages.
- `evidence_graph/canonical_pipeline.py` – production canonical graph materialization.
- `evidence_graph/canonical_batch.py` – corpus canonicalization.
- `evidence_graph/canonical_visualize.py` – canonical-graph visualization.

## Phase-1 runtime modules

The current Phase-1 pipeline directly depends on:

`config.py`, `loader.py`, `reading_order.py`, `block_classifier.py`, `magazine_role_router.py`,
`aligned_fragment_consolidation.py`, `metadata_extractor.py`, `section_builder.py`, `evidence_builder.py`,
`schemas.py`, `structural_graph.py`, `validator.py`, `statistics.py`, `exporter.py`, and `io_utils.py`.

`aligned_fragment_consolidation.py` is currently diagnostic-only in production (`apply: false`). It is kept in the runtime package because `pipeline.py` still calls it to generate review artifacts.

## Semantic/canonical runtime modules

The semantic pipeline imports `candidate_generator.py`, `embeddings.py`, `enrichment.py`, `llm_client.py`,
`relation_ontology.py`, `relation_verifier.py`, `adversarial_verifier.py`, and `article_segmentation.py`.
Canonicalization additionally uses `canonical_evidence.py` and `rule_based_reference_grounding.py`.

## Archived code

Clearly obsolete or superseded modules are moved under `archive/` instead of being deleted. They are retained for provenance and comparison, but they are not imported by the current pipeline.

- `archive/fragment_experiments/` – superseded fragment-detection attempts.
- `archive/legacy_pipelines/` – alternative end-to-end pipelines not used by the current CLI.
- `archive/visualization_experiments/` – superseded one-off visualizers.

## Conservative cleanup policy

Many other files under `evidence_graph/` are experiment/evaluation scripts. Some are referenced by existing `slurm/` jobs even though they are not part of the production CLI pipeline. They are intentionally **not moved yet** in this cleanup pass, because moving them without updating their launchers would silently break reproducibility. Once a script and all launchers can be migrated together, it should be placed under a dedicated `experiments/` or `evaluation/` package.

The goal is: production runtime stays small and explicit; historical experiments remain reproducible; nothing is deleted merely because it is not currently active.
