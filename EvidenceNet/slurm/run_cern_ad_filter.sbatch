#!/bin/bash
#SBATCH --job-name=evidencenet-cern-ads
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=04:00:00
#SBATCH --output=logs/evidencenet-cern-ads-%j.out
#SBATCH --error=logs/evidencenet-cern-ads-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"

srun "${PYTHON}" -m evidence_graph.ad_filter --config config/evidence_graph.yaml --docs \
  CERNCourier2022NovDec-digitaledition \
  CERNCourier2025JanFeb-digitaledition \
  CERNCourier2026MayJun-digitaledition
