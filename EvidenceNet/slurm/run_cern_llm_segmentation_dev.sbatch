#!/bin/bash
#SBATCH --job-name=evidencenet-cern-segment
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=01:00:00
#SBATCH --output=logs/evidencenet-cern-segment-%j.out
#SBATCH --error=logs/evidencenet-cern-segment-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
DOC_ID="CERNCourier2025JanFeb-digitaledition"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"

srun "${PYTHON}" -m evidence_graph semantic-pilot --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PYTHON}" -m evidence_graph adjudicate-pilot --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PYTHON}" -m evidence_graph.visualize --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PYTHON}" -m evidence_graph.adjudication_report --doc-id "${DOC_ID}" --config config/evidence_graph.yaml

echo "Completed all-adjacent-pair LLM content-unit segmentation and semantic pilot for ${DOC_ID}."
