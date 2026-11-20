#!/bin/bash
# One real dev-H100 EvidenceNet Dolphin task followed by one dependent successor.
# Keeping exactly one queued GPU job avoids HoReKa2 dev QOS submit-count limits.
#SBATCH --job-name=vldocir-dolphin-v1
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:55:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_dolphin_chain_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_dolphin_chain_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project

: "${PILOT_PAGE_TASK:?submit with --export=ALL,PILOT_PAGE_TASK=<0..491>}"
if (( PILOT_PAGE_TASK < 0 || PILOT_PAGE_TASK > 491 )); then
  echo "invalid PILOT_PAGE_TASK=$PILOT_PAGE_TASK" >&2
  exit 2
fi

PYTHON=EvidenceNet/.venv_qwen/bin/python
export PYTHONPATH=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/parsing/.venv_docparse/lib/python3.11/site-packages
BASE=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-multimodal-dolphin-v1
OFFSET=$((PILOT_PAGE_TASK * 6))
"$PYTHON" EvidenceNet/scripts/parse_vldocir_pages.py \
  --pages "$BASE/pages.jsonl" --output "$BASE/dolphin_pages" \
  --model parsing/experiments/dolphin_v2_pilot/models/Dolphin-v2 \
  --offset "$OFFSET" --limit 6 --max-side 2000

NEXT=$((PILOT_PAGE_TASK + 1))
if (( NEXT <= 491 )); then
  sbatch --dependency="afterok:${SLURM_JOB_ID}" --export="ALL,PILOT_PAGE_TASK=${NEXT}" \
    DynamicEdgeGraph/stage1_candidate_pruning/scripts/slurm_vldocir_dolphin_chain.sbatch
fi
