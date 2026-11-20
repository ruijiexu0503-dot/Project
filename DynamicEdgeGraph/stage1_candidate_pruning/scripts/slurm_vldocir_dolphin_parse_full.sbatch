#!/bin/bash
#SBATCH --job-name=vldocir-dolphin-v1
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:55:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_dolphin_v1_%A_%a.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_dolphin_v1_%A_%a.err
set -euo pipefail
if [[ -z "${SLURM_ARRAY_TASK_ID:-}" ]]; then
  echo "This script must be submitted with sbatch --array=<start>-<end>%4" >&2
  exit 2
fi
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
# Reuse EvidenceNet's Qwen/Dolphin runtime. PyMuPDF resides in the existing
# document-parsing venv; both are Python 3.11 and import-tested together.
PYTHON=EvidenceNet/.venv_qwen/bin/python
PYTHONPATH=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/parsing/.venv_docparse/lib/python3.11/site-packages
export PYTHONPATH
BASE=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-multimodal-dolphin-v1
OFFSET=$((SLURM_ARRAY_TASK_ID * 6))
"$PYTHON" EvidenceNet/scripts/parse_vldocir_pages.py \
  --pages "$BASE/pages.jsonl" \
  --output "$BASE/dolphin_pages" \
  --model parsing/experiments/dolphin_v2_pilot/models/Dolphin-v2 \
  --offset "$OFFSET" --limit 6 --max-side 2000
