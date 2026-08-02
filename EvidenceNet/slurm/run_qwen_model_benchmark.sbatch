#!/bin/bash
#SBATCH --job-name=evidencenet-qwen-bench
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated-h100
#SBATCH --gres=gpu:4
#SBATCH --cpus-per-task=32
#SBATCH --mem=700G
#SBATCH --time=24:00:00
#SBATCH --output=logs/qwen-model-benchmark-%j.out
#SBATCH --error=logs/qwen-model-benchmark-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="${MODEL:?Submit with MODEL=/absolute/local/checkpoint/path}"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph.model_benchmark \
  --model "${MODEL}" --pairs-per-document "${PAIRS_PER_DOCUMENT:-40}"
