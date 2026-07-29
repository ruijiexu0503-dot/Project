#!/bin/bash
#SBATCH --job-name=evidencenet-structure-ads
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=03:00:00
#SBATCH --output=logs/evidencenet-structure-ads-%j.out
#SBATCH --error=logs/evidencenet-structure-ads-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "${PROJECT_DIR}"
mapfile -t DOCS < config/corpus_documents.txt
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"

srun "${PYTHON}" -m evidence_graph.document_profiler --config config/evidence_graph.yaml --docs "${DOCS[@]}"
srun "${PYTHON}" -m evidence_graph.ad_filter --config config/evidence_graph.yaml --docs \
  CERNCourier2022NovDec-digitaledition \
  CERNCourier2025JanFeb-digitaledition \
  CERNCourier2026MayJun-digitaledition
srun "${PYTHON}" -m evidence_graph.segmentation_review --config config/evidence_graph.yaml
