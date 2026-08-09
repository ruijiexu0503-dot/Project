#!/bin/bash
#SBATCH --job-name=q25-high-recall
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=01:00:00
#SBATCH --output=logs/q25-high-recall-%j.out
#SBATCH --error=logs/q25-high-recall-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
"$P/.venv_qwen/bin/python" -m evidence_graph.high_recall_proposer \
  --model "$P/../external/models/Qwen2.5-VL-7B-Instruct" \
  --output "$P/output/high_recall_proposer/Qwen2.5-VL-7B-Instruct/gw150914_detection"
