#!/bin/bash
#SBATCH --job-name=expanded-reverse
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=01:00:00
#SBATCH --output=logs/expanded-reverse-%j.out
#SBATCH --error=logs/expanded-reverse-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL_NAME="${MODEL_NAME:?Set MODEL_NAME}"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
"$P/.venv_qwen/bin/python" -m evidence_graph.expanded_reverse_pilot \
  --model "$P/../external/models/$MODEL_NAME" \
  --output "$P/output/expanded_reverse_pilot/$MODEL_NAME/gw150914_detection"
