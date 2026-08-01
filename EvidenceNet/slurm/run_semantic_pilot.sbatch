#!/bin/bash
#SBATCH --job-name=evidencenet-pilot
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --output=logs/evidencenet-pilot-%j.out
#SBATCH --error=logs/evidencenet-pilot-%j.err

set -euo pipefail

PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
DOC_ID="${DOC_ID:-gw150914_detection}"
CONFIG_PATH="${CONFIG_PATH:-config/evidence_graph.yaml}"

cd "${PROJECT_DIR}"

export TOKENIZERS_PARALLELISM=false
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-16}"

PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Python environment not found: ${PYTHON}" >&2
  exit 2
fi

srun "${PYTHON}" - <<'PY'
import torch
if not torch.cuda.is_available():
    raise SystemExit("No CUDA GPU is visible inside the Slurm allocation")
print(f"CUDA devices: {torch.cuda.device_count()}")
print(f"GPU: {torch.cuda.get_device_name(0)}")
print(f"CUDA runtime: {torch.version.cuda}")
PY

srun "${PYTHON}" -m evidence_graph semantic-pilot \
  --doc-id "${DOC_ID}" \
  --config "${CONFIG_PATH}"

srun "${PYTHON}" -m evidence_graph.visualize \
  --doc-id "${DOC_ID}" \
  --config "${CONFIG_PATH}"
