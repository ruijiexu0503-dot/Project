#!/bin/bash
#SBATCH --job-name=evidencenet-formula
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:30:00
#SBATCH --output=logs/evidencenet-formula-%j.out
#SBATCH --error=logs/evidencenet-formula-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
DOC_ID="${DOC_ID:-gw150914_detection}"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph enrich-formulas \
  --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
