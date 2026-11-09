#!/bin/bash
#SBATCH --job-name=vldocir-merge-embed
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=dev-cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=00:30:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_merge_embeddings_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_merge_embeddings_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107/models
for ROUTE in qwen3_0_6b_dense gte_qwen2_1_5b_dense bge_en_icl_dense mxbai_dense gte_large_dense; do
  "$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_merge_embedding_shards \
    --model-dir "$RUN/$ROUTE" --expected-views 104318
done
