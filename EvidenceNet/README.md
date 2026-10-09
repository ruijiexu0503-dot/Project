# EvidenceNet

For the current operational map, read
[`../PIPELINE_CURRENT.md`](../PIPELINE_CURRENT.md). Detailed page-routing,
parser, and production/shadow contracts remain in
[`../PIPELINE_STEPS.md`](../PIPELINE_STEPS.md).
Accepted and superseded design choices are tracked in
[`../PIPELINE_DECISIONS.md`](../PIPELINE_DECISIONS.md).

Phase 1 builds a deterministic, document-internal structural Evidence Graph from the existing aligned page JSON. It does not alter OCR/alignment outputs and does not create semantic edges.

Run the package commands below from `EvidenceNet/` with its local environment
(start at the repository root, then change directory):

```bash
cd EvidenceNet
.venv_qwen/bin/python -m evidence_graph \
  build-nodes --doc-id gw150914_detection --config config/evidence_graph.yaml
```

The CLI's `validate` and `run` commands also rebuild Phase 1; `validate` writes
fresh output. Configured canonicalization and magazine routing may run during
this build. Use a separate output configuration for frozen-input experiments.

The output is written to `output/evidence_graph/<doc_id>/`. Empty semantic-layer files are intentional until Phase 1 has been reviewed.

Document-level single-work versus multi-item detection and segmentation routing are documented in
[`docs/structure_detection/README.md`](docs/structure_detection/README.md).

Run the bounded semantic pilot (the supplied configuration limits it to 25 nodes;
this command needs the configured local Qwen model and GPU):

```bash
.venv_qwen/bin/python -m evidence_graph \
  semantic-pilot --doc-id gw150914_detection --config config/evidence_graph.yaml
```

The old `slurm/run_semantic_pilot.sbatch` is archived. HoReKa2 launchers are
indexed in [`../current/README.md`](../current/README.md); relation-first
semantic experiments use a different input contract from this package CLI.

This package's legacy semantic pilot uses document-local TF–IDF vectors in `embedding_vectors.jsonl`.
Hybrid node generation and VL-DocIR retrieval separately use Qwen3-Embedding-0.6B.
They are never exported as graph edges. Semantic relations are accepted only after conservative LLM
verification, exact supporting-span checks, and the configured confidence threshold.

Build the self-contained semantic-edge review visualization:

```bash
.venv_qwen/bin/python -m evidence_graph.visualize \
  --doc-id gw150914_detection --config config/evidence_graph.yaml
```

After the multimodal phase, materialize the production canonical graph. Raw graph artifacts remain
unchanged in `output/evidence_graph/<doc_id>`; the canonical graph is written to
`output/canonical_graph/<doc_id>`.

```bash
.venv_qwen/bin/python -m evidence_graph \
  materialize-canonical --doc-id detr --config config/evidence_graph.yaml
.venv_qwen/bin/python -m evidence_graph \
  visualize-canonical --doc-id detr --config config/evidence_graph.yaml
```

Canonicalization absorbs linked caption/image/table fragments, stores reading order as metadata,
remaps downstream endpoints through `node_aliases.jsonl`, and emits deterministic explicit-label
`REFERENCES` edges. Configured `semantic_sources` can also import accepted semantic edges;
legacy semantic predictions are excluded by the supplied configuration. Formula “where” backreferences and anaphora remain in
`shadow_discourse_edges.jsonl` and are not part of the production graph.

The current hybrid-v2 EvidenceNode branch is opt-in. Its source coverage and
known-error regression checks do not establish independent semantic accuracy.
Article membership, reading `NEXT` edges and semantic edges still need adaptation
to these node IDs. See the [v2 audit](docs/hybrid_evidence_node_v2_2026-10-08.md),
[article graph contract](experiments/document_article_graph/README.md), and
[VL-DocIR experiment](experiments/vldocir/README.md).
