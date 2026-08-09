#!/bin/bash
#SBATCH --job-name=qwen35-semantic-all
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=24:00:00
#SBATCH --output=logs/qwen35-semantic-all-%j.out
#SBATCH --error=logs/qwen35-semantic-all-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="/home/hk-project-p0025545/dv3352/Project/external/models/Qwen3.5-35B-A3B"
MANIFEST="${PROJECT_DIR}/config/qwen35_semantic_documents.txt"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"

while IFS= read -r DOC_ID; do
  [[ -z "${DOC_ID}" ]] && continue
  echo "Starting semantic graph: ${DOC_ID}"
  srun "${PYTHON}" -m evidence_graph.comparative_semantic_run \
    --doc-id "${DOC_ID}" --model "${MODEL}" --config config/evidence_graph.yaml
done < "${MANIFEST}"
