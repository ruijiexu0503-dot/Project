#!/bin/bash
# Small query-independent Stage-1 v1 validation on the frozen 24-query Pilot corpus.
# It does not read queries, relevance labels, or structural edges.
#SBATCH --job-name=vldocir-pilot-s1v1
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_pilot_s1v1_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_pilot_s1v1_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project

PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-pilot-stage1-v1
SOURCE=DynamicEdgeGraph/stage2_edge_construction/outputs/pilot_node_representation_v1
CHECKPOINTS="$RUN/checkpoints"
mkdir -p "$CHECKPOINTS"

# Markers are written only after the preceding command succeeded (set -e).  Along
# with the immutable view_vectors.npy + embedding_summary.json produced per route,
# they make a later 1-hour dev rerun resume at the last finished phase.
checkpoint() {
  local phase="$1"
  printf '%s completed by Slurm job %s at %s\n' "$phase" "${SLURM_JOB_ID:-unknown}" "$(date -u +%FT%TZ)" > "$CHECKPOINTS/${phase}.complete"
}

if [[ ! -f "$CHECKPOINTS/00_input.complete" ]]; then
  "$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.prepare_pilot_stage1_v1 \
    --representations "$SOURCE/node_representations.jsonl" \
    --representation-manifest "$SOURCE/node_representation_manifest.json" \
    --output "$RUN"
  checkpoint 00_input
fi

# BGE-en-ICL remains diagnostic-only after its CLS-pooling audit, so it is not
# re-embedded here.  These are the four effective Dense routes for Stage-1 v1.
for ROUTE in qwen3_0_6b_dense gte_qwen2_1_5b_dense mxbai_dense gte_large_dense; do
  if [[ ! -f "$CHECKPOINTS/10_embedding_${ROUTE}.complete" ]]; then
    "$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_freeze_embeddings \
      --views "$RUN/retrieval_views.jsonl" --output "$RUN/models" --route "$ROUTE" \
      --device cuda --max-length 512
    checkpoint "10_embedding_${ROUTE}"
  fi
done

# Bounded ANN / sparse retrieval only; no all-pairs score matrix is constructed.
for ROUTE in qwen3_0_6b_dense gte_qwen2_1_5b_dense mxbai_dense gte_large_dense bm25; do
  if [[ ! -f "$CHECKPOINTS/20_retrieval_${ROUTE}.complete" ]]; then
    "$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_full_retrieval \
      --views "$RUN/retrieval_views.jsonl" --models-root "$RUN/models" --output "$RUN/candidates_top100" \
      --route "$ROUTE" --batch-size 256 --ef-search 256
    checkpoint "20_retrieval_${ROUTE}"
  fi
done

if [[ ! -f "$CHECKPOINTS/30_analysis.complete" ]]; then
  "$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_full_analysis \
    --run "$RUN/candidates_top100" --canonical-nodes "$RUN/canonical_nodes.jsonl" \
    --views "$RUN/retrieval_views.jsonl" \
    --routes qwen3_0_6b_dense gte_qwen2_1_5b_dense mxbai_dense gte_large_dense bm25
  checkpoint 30_analysis
fi
