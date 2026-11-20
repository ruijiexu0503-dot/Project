#!/usr/bin/env bash
# Additive snapshot/answer generation job. Submit with --dependency=afterok:135007.
#SBATCH --job-name=qa300-snapb-gen
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=gpu-h100,gpu-h200,gpu-h200-8
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=12
#SBATCH --mem=160G
#SBATCH --time=10:00:00
#SBATCH --output=DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/logs/%x-%j.out
#SBATCH --error=DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/logs/%x-%j.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source current/env.sh
export OMP_NUM_THREADS=8 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True PYTHONUNBUFFERED=1

BASE=DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/scripts
PYTHON=EvidenceNet/.venv_qwen/bin/python

"${PYTHON}" "${BASE}/prepare_snapshot_b_short.py"
"${PYTHON}" "${BASE}/discover_snapshot_b_short.py"
"${PYTHON}" "${BASE}/generate_snapshot_b_answers.py"
