# EvidenceNet

Phase 1 builds a deterministic, document-internal structural Evidence Graph from the existing aligned page JSON. It does not alter OCR/alignment outputs and does not create semantic edges.

```bash
python -m evidence_graph.build_nodes --doc-id gw150914_detection --config config/evidence_graph.yaml
python -m evidence_graph.validate --doc-id gw150914_detection --config config/evidence_graph.yaml
python -m evidence_graph run --doc-id gw150914_detection --config config/evidence_graph.yaml
```

The output is written to `output/evidence_graph/<doc_id>/`. Empty semantic-layer files are intentional until Phase 1 has been reviewed.

Run the bounded Phase 2/3 pilot (25 nodes; never the full document):

```bash
.venv_qwen/bin/python -m evidence_graph semantic-pilot --doc-id gw150914_detection --config config/evidence_graph.yaml
```

On Horeka, submit the GPU pilot from the repository root:

```bash
sbatch slurm/run_semantic_pilot.sbatch
```

The script defaults to account `hk-project-p0025545`, the `accelerated` partition, one GPU, 128 GB
host memory, and an eight-hour limit. Override the document/config without editing it:

```bash
DOC_ID=gw150914_detection CONFIG_PATH=config/evidence_graph.yaml sbatch slurm/run_semantic_pilot.sbatch
```

Embeddings are document-local TF–IDF retrieval vectors stored separately in `embedding_vectors.jsonl`.
They are never exported as graph edges. Semantic relations are accepted only after conservative LLM
verification, exact supporting-span checks, and the configured confidence threshold.

Build the self-contained semantic-edge review visualization:

```bash
python -m evidence_graph.visualize --doc-id gw150914_detection --config config/evidence_graph.yaml
```
