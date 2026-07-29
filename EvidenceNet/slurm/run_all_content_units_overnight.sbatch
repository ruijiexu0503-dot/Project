#!/bin/bash
#SBATCH --job-name=evidencenet-unified-adj
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH --output=logs/evidencenet-unified-adj-%j.out
#SBATCH --error=logs/evidencenet-unified-adj-%j.err

set -uo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "${PROJECT_DIR}"
mapfile -t DOCS < config/corpus_documents.txt
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"
FAILED=()

for DOC_ID in "${DOCS[@]}"; do
  echo "===== UNIFIED ADJACENT RELATIONSHIPS ${DOC_ID} ====="
  if srun "${PYTHON}" -m evidence_graph segment-content-units --doc-id "${DOC_ID}" --config config/evidence_graph.yaml; then
    echo "===== COMPLETE ${DOC_ID} ====="
  else
    echo "===== INCOMPLETE ${DOC_ID}; CHECKPOINT RETAINED; CONTINUING =====" >&2
    FAILED+=("${DOC_ID}")
  fi
done

echo "Attempted ${#DOCS[@]} documents; incomplete: ${#FAILED[@]}"
if ((${#FAILED[@]})); then
  printf 'INCOMPLETE_DOCUMENT: %s\n' "${FAILED[@]}" >&2
  exit 1
fi
