#!/bin/bash
#SBATCH --job-name=qwen35-enrich-rem
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=12:00:00
#SBATCH --array=0-7%2
#SBATCH --output=logs/qwen35-enrich-rem-%A_%a.out
#SBATCH --error=logs/qwen35-enrich-rem-%A_%a.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MANIFEST="${PROJECT_DIR}/config/qwen35_enrichment_remaining_documents.txt"
DOC_ID="$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "${MANIFEST}")"
if [[ -z "${DOC_ID}" ]]; then
  echo "No document for array index ${SLURM_ARRAY_TASK_ID}" >&2
  exit 2
fi
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
"${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph.comparative_enrichment \
  --doc-id "${DOC_ID}" --config config/qwen35_fast_segmentation.yaml
