#!/bin/bash
#SBATCH --job-name=long-range-35b
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated-h100
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:14:50
#SBATCH --output=logs/long-range-35b-%j.out
#SBATCH --error=logs/long-range-35b-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
TASKS="$P/output/sequential_long_range/shared/gw150914_detection/ranking_tasks.jsonl"
RESULT="$P/output/sequential_long_range/Qwen3.5-35B-A3B/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.run_sequential_long_range \
  --model "$MODEL" --tasks "$TASKS" --output "$RESULT" \
  --generation-tokens 420 --maximum-runtime-minutes 12
