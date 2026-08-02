#!/bin/bash
#SBATCH --job-name=direct-vlm-cern
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=12:00:00
#SBATCH --output=logs/direct-vlm-cern-%j.out
#SBATCH --error=logs/direct-vlm-cern-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
"${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph.direct_vlm_pipeline \
  --doc-id CERNCourier2025JanFeb-digitaledition --config config/qwen35_fast_segmentation.yaml
