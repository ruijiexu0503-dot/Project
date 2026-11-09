# Stage 1: Multi-route candidate pruning

This is a read-only, candidate-generation experiment. It never changes
EvidenceNet nodes or embeddings and never treats a query evidence label as a
Node--Node edge label. Retrieval is bounded: dense search uses FAISS HNSW ANN,
BM25 uses an inverted index, and structural construction is outside the
semantic-candidate Stage 1 union.

Every pipeline entry point first runs the additive Type-aware Retrieval View
Eligibility Audit. It has no global minimum-token gate: it preserves the
1,204-node frozen-view baseline, reuses Formula views, creates separate views
for eligible short text/formula/identifier Nodes, and records visual or policy
excluded Nodes for review. It never overwrites existing views or embeddings.
The additive views are an audited input for a future explicitly configured
coverage-expansion route; they are not silently merged into baseline metrics.

## Run

```bash
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.type_aware_eligibility \
  --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.audit_inputs \
  --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.retrieve_candidates \
  --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.sweep_thresholds \
  --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.evaluate \
  --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
```

Use `pilot.yaml` on a GPU Slurm job after auditing paths and resource
availability. `slurm_stage1.sbatch` is deliberately account/partition neutral.
The checked-in configs target the gated
`anonymous-8421/VL-DocIR-RepresentativeSubset` repository and download only
its `questions.jsonl` and `question_evidences.jsonl` files through the
authenticated Hugging Face environment. They do not target the full VL-DocIR
question corpus. Absent or incompatible inputs are reported rather than
silently substituted.

Outputs are versioned under `outputs/<run_id>/`. Thresholds are route-specific.
Without independently verified Node-pair labels, metrics are explicitly
reported as unavailable rather than fabricated.
