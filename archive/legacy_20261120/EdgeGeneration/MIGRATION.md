# Edge-generation package migration guide

`EdgeGeneration/` is the self-contained home for the shadow work that proposes
and evaluates cross-document EvidenceNode edges. It is movable as one folder.
`CrossDocumentDiscovery` at the repository root is a compatibility symlink to
this directory; it can be omitted after downstream references have been updated.

## Included

| Directory | Contents |
| --- | --- |
| `scripts/` | Candidate retrieval, ANN scaling, relation-review, asset-report, and audit programs. |
| `slurm/` | GPU/CPU Slurm entry points. |
| `config/` | Explicit input manifests for the older retrieval experiments. |
| `tests/` | Isolated tests for the experiments. |
| `docs/` | Results and method notes, including reviewed positive examples. |
| `output/` | Reproducible shadow results; no production graph is modified. |

## External dependencies after migration

The scripts deliberately refer to the repository root for these inputs, rather
than copying them into this package:

1. `EvidenceNet/` for canonical EvidenceNodes, Qwen client code, and the Qwen
   model path configured in Slurm scripts.
2. `parsing/output/` for original page images and grounded coordinates used by
   `build_relation_asset_report.py`.
3. The local BGE-M3 model cache and `EdgeGeneration/.ann_deps` (FAISS).

For a stand-alone transfer, copy this folder together with those three inputs,
then adjust the `ROOT=` line in each file under `slurm/` to the new repository
root. All outputs should remain under `EdgeGeneration/output/`.

## Current boundary

The latest Qwen3.5 description trial indexed only text/formula nodes. That was
a controlled experimental filter, not a statement that figures or tables lack
textual evidence. Visual descriptions and table text are available inputs and
the next multimodal retrieval run must preserve `asset_path`, `bbox`, and
`visual_type` with each candidate endpoint.
