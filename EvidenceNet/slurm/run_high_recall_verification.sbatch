#!/bin/bash
#SBATCH --job-name=high-recall-verify
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=04:00:00
#SBATCH --output=logs/high-recall-verify-%j.out
#SBATCH --error=logs/high-recall-verify-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL_NAME="${MODEL_NAME:?Set MODEL_NAME}"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
"$P/.venv_qwen/bin/python" -m evidence_graph.verify_high_recall_proposals \
  --model "$P/../external/models/$MODEL_NAME" \
  --output "$P/output/high_recall_verification/$MODEL_NAME/gw150914_detection"
