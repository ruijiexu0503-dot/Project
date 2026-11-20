#!/usr/bin/env bash
#SBATCH --job-name=gold200-ranker
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=12
#SBATCH --mem=96G
#SBATCH --time=04:00:00
#SBATCH --output=DynamicEdgeGraph/dynamic_retrieval/logs/gold200-ranker-%j.out
#SBATCH --error=DynamicEdgeGraph/dynamic_retrieval/logs/gold200-ranker-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source current/env.sh
export OMP_NUM_THREADS=8 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
DATA=DynamicEdgeGraph/dynamic_retrieval/runs/gold200_frozen_ranker_v1_20261119
OUT="$DATA/training_${SLURM_JOB_ID}"
EvidenceNet/.venv_qwen/bin/python DynamicEdgeGraph/dynamic_retrieval/src/train_gold_frozen_ranker.py \
  --data "$DATA" \
  --out "$OUT" \
  --model EvidenceNet/models/Qwen3-Embedding-0.6B \
  --epochs 12 \
  --batch-size 64 \
  --seed 17
