#!/bin/bash
#SBATCH --job-name=dolphin_v2_xdoc
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=parsing/experiments/dolphin_v2_pilot/logs/%x_%j.out
#SBATCH --error=parsing/experiments/dolphin_v2_pilot/logs/%x_%j.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"

PILOT_DIR="parsing/experiments/dolphin_v2_pilot"
mkdir -p "${PILOT_DIR}/logs" "${PILOT_DIR}/work" "${PILOT_DIR}/output"

export HF_HOME="${PILOT_DIR}/cache/huggingface"
export TRANSFORMERS_OFFLINE=1
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

parsing/.venv_vlm/bin/python "${PILOT_DIR}/run_pilot.py" \
  --output "${PILOT_DIR}/work" \
  --resume \
  --max-batch-size 2

parsing/.venv_vlm/bin/python "${PILOT_DIR}/build_comparison_report.py" \
  --work "${PILOT_DIR}/work" \
  --output "${PILOT_DIR}/output"
