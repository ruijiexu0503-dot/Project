#!/bin/bash
#SBATCH --job-name=evidencenet-cern-full
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=24:00:00
#SBATCH --output=logs/evidencenet-cern-full-%j.out
#SBATCH --error=logs/evidencenet-cern-full-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
DOC_ID="CERNCourier2025JanFeb-digitaledition"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"
srun "${PYTHON}" -m evidence_graph semantic-full --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PYTHON}" -m evidence_graph.hierarchical_visualize --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
