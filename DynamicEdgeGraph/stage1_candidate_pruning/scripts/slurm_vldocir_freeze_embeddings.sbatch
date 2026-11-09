#!/bin/bash
#SBATCH --job-name=vldocir-freeze
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=24:00:00
#SBATCH --array=0-4
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_freeze_%A_%a.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_freeze_%A_%a.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
source .venv-magazine-exp1/bin/activate
ROUTES=(qwen3_0_6b_dense gte_qwen2_1_5b_dense bge_en_icl_dense mxbai_dense gte_large_dense)
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_freeze_embeddings \
  --views "$RUN/retrieval_views.jsonl" --output "$RUN/models" --route "${ROUTES[$SLURM_ARRAY_TASK_ID]}" --device cuda
