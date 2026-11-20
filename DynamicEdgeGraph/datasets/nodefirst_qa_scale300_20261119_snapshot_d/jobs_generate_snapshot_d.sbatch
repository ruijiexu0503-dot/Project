#!/usr/bin/env bash
#SBATCH --job-name=qa300-snapd-gen
#SBATCH --account=hk-project-pai00096
#SBATCH --partition=accelerated
#SBATCH --nodes=1
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=220G
#SBATCH --time=12:00:00
#SBATCH --output=DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261119_snapshot_d/logs/%x-%A_%a.out
#SBATCH --error=DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261119_snapshot_d/logs/%x-%A_%a.err

set -euo pipefail
ROOT=/hkfs/home/project/hk-project-p0025545/dv3352/Project
cd "$ROOT"
export OMP_NUM_THREADS=12 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export PYTHONUNBUFFERED=1 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
export QA_SHARDS=16
"$ROOT/EvidenceNet/.venv_qwen/bin/python" \
  DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261119_snapshot_d/scripts/generate_snapshot_d_shard.py
