#!/bin/bash
#SBATCH --job-name=qwen35-rel-pilot
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=01:00:00
#SBATCH --output=logs/qwen35-rel-pilot-%j.out
#SBATCH --error=logs/qwen35-rel-pilot-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="/home/hk-project-p0025545/dv3352/Project/external/models/Qwen3.5-35B-A3B"
DOC_ID="CERNCourier2025JanFeb-digitaledition"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
"${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph.comparative_semantic_run \
  --doc-id "${DOC_ID}" --model "${MODEL}" --config config/evidence_graph.yaml --pilot
