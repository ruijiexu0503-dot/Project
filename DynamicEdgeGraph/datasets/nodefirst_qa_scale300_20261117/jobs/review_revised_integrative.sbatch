#!/usr/bin/env bash
#SBATCH --job-name=qa300-rev-int-audit
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=gpu-h100,gpu-h200,gpu-h200-8
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=12
#SBATCH --mem=160G
#SBATCH --time=03:00:00
#SBATCH --output=DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/logs/%x-%j.out
#SBATCH --error=DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/logs/%x-%j.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source current/env.sh
export OMP_NUM_THREADS=8 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True PYTHONUNBUFFERED=1
EvidenceNet/.venv_qwen/bin/python DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/scripts/review_revised_integrative.py
