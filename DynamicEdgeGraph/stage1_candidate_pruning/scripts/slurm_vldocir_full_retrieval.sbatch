#!/bin/bash
#SBATCH --job-name=vldocir-stage1-ann
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=32
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_stage1_ann_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_stage1_ann_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-stage1-ann-top100-20261108
VIEWS=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107/retrieval_views.jsonl
MODELS=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107/models
mkdir -p "$RUN"
for ROUTE in qwen3_0_6b_dense gte_qwen2_1_5b_dense bge_en_icl_dense mxbai_dense gte_large_dense bm25; do
  "$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_full_retrieval --views "$VIEWS" --models-root "$MODELS" --output "$RUN" --route "$ROUTE" --batch-size 256 --ef-search 256
done
