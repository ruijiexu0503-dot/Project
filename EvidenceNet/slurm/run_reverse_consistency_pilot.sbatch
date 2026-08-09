#!/bin/bash
#SBATCH --job-name=reverse-pilot
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=01:00:00
#SBATCH --output=logs/reverse-pilot-%j.out
#SBATCH --error=logs/reverse-pilot-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL_NAME="${MODEL_NAME:?Set MODEL_NAME to a local checkpoint directory name}"
RUN_LABEL="${RUN_LABEL:-balanced-v4}"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
"$P/.venv_qwen/bin/python" -m evidence_graph.reverse_consistency_pilot \
  --model "$P/../external/models/$MODEL_NAME" \
  --output "$P/output/reverse_consistency_pilot/$RUN_LABEL/$MODEL_NAME/gw150914_detection"
