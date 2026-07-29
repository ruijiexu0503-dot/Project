#!/bin/bash
#SBATCH --job-name=evidencenet-audit
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=02:00:00
#SBATCH --output=logs/evidencenet-audit-%j.out
#SBATCH --error=logs/evidencenet-audit-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph adjudicate-pilot \
  --doc-id gw150914_detection --config config/evidence_graph.yaml
