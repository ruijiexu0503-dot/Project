#!/bin/bash
#SBATCH --job-name=evidencenet-corpus-all
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH --output=logs/evidencenet-corpus-all-%j.out
#SBATCH --error=logs/evidencenet-corpus-all-%j.err

set -uo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "${PROJECT_DIR}"
mapfile -t DOCS < config/corpus_documents.txt
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"
FAILED=()

for DOC_ID in "${DOCS[@]}"; do
  echo "===== START ${DOC_ID} ====="
  if srun "${PYTHON}" -m evidence_graph run --doc-id "${DOC_ID}" --config config/evidence_graph.yaml \
    && srun "${PYTHON}" -m evidence_graph.multimodal --doc-id "${DOC_ID}" --config config/evidence_graph.yaml \
    && srun "${PYTHON}" -m evidence_graph semantic-pilot --doc-id "${DOC_ID}" --config config/evidence_graph.yaml \
    && srun "${PYTHON}" -m evidence_graph adjudicate-pilot --doc-id "${DOC_ID}" --config config/evidence_graph.yaml \
    && srun "${PYTHON}" -m evidence_graph.visualize --doc-id "${DOC_ID}" --config config/evidence_graph.yaml \
    && srun "${PYTHON}" -m evidence_graph.adjudication_report --doc-id "${DOC_ID}" --config config/evidence_graph.yaml; then
    echo "===== COMPLETE ${DOC_ID} ====="
  else
    echo "===== FAILED ${DOC_ID}; CONTINUING =====" >&2
    FAILED+=("${DOC_ID}")
  fi
done

echo "Processed ${#DOCS[@]} documents; failures: ${#FAILED[@]}"
if ((${#FAILED[@]})); then
  printf 'FAILED_DOCUMENT: %s\n' "${FAILED[@]}" >&2
  exit 1
fi
