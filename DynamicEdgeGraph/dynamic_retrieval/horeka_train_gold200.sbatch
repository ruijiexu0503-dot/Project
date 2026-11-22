#!/usr/bin/env bash
#SBATCH --job-name=gold200-ranker
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=gpu-h100
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=00:10:00
#SBATCH --output=DynamicEdgeGraph/dynamic_retrieval/logs/gold200-ranker-%j.out
#SBATCH --error=DynamicEdgeGraph/dynamic_retrieval/logs/gold200-ranker-%j.err
set -euo pipefail
ROOT=/hkfs/home/project/hk-project-p0025545/dv3352/Project
cd "$ROOT"
export OMP_NUM_THREADS=12 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True PYTHONUNBUFFERED=1 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
DATA=DynamicEdgeGraph/dynamic_retrieval/runs/gold200_frozen_ranker_v1_20261119
OUT="$DATA/training_gain_a_horeka_${SLURM_JOB_ID}"
EvidenceNet/.venv_qwen/bin/python DynamicEdgeGraph/dynamic_retrieval/src/train_gold_frozen_ranker.py --data "$DATA" --out "$OUT" --model EvidenceNet/models/Qwen3-Embedding-0.6B --epochs 12 --batch-size 64 --seed 17 --enable-a-head --gain-weight 0.2
