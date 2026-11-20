# Current pipeline

Updated: 2026-11-20.

## Active stages

| Stage | Active entrypoint or artifact | Status |
|---|---|---|
| PDF parsing | `parsing/pipeline_steps/step1_run_parsing_pipeline.sbatch` | active, resumable |
| Parser-to-node preparation | `EvidenceNet/scripts/prepare_vldocir_nodes.py` | active |
| Canonical node generation | `EvidenceNet/scripts/run_vldocir_nodes.py` | active; staged checkpoints |
| Retrieval materialization | `EvidenceNet/scripts/retrieve_vldocir.py` | active |
| QA generation and gates | `DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261119_snapshot_d/scripts/` | active automated workflow |
| Current Gold QA | `DynamicEdgeGraph/datasets/nodefirst_qa_codex_direct_20261119/qa_gold_codex_direct_cumulative_200.jsonl` | frozen Gold-200 |
| Document-disjoint split | `DynamicEdgeGraph/dynamic_retrieval/runs/gold200_frozen_ranker_v1_20261119/` | active baseline split |
| Ranker training | `DynamicEdgeGraph/dynamic_retrieval/src/train_gold_frozen_ranker.py` | active baseline |

## Gold export gate

Gold export is fully automated. Human approval is not a universal prerequisite.
Each accepted QA must pass source integrity, canonical mapping, claim-level
grounding, evidence sufficiency and necessity, duplicate checks, single-node
shortcut checks, independent model review, and deterministic program checks.

Source integrity, canonical mapping, and semantic grounding are distinct gates.
A failure in one is reported specifically rather than converted into a generic
manual-review requirement.

## Current limitations

- Gold count is 200, not 300.
- The 20/30/50 QA-category ratio is satisfied, but the held-out split has only
  19 examples and no single-node examples because it is split by connected
  document components.
- New validation documents were prepared for parsing/node generation, but the
  2026-11-20 HoreKa run failed before producing validation nodes.
- Training is a frozen embedding encoder plus `DynamicEdgeRanker`; it is not a
  full encoder fine-tune or LoRA run.
