#!/bin/bash
#SBATCH --job-name=edge-prompt-v2
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated-h100
#SBATCH --array=0-1%2
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:10:00
#SBATCH --output=logs/edge-prompt-v2-%A_%a.out
#SBATCH --error=logs/edge-prompt-v2-%A_%a.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
TASKS="$P/output/existence_prompt_v2_pilot/shared/gw150914_detection/blind_tasks_shard_${SLURM_ARRAY_TASK_ID}.jsonl"
RESULT="$P/output/existence_prompt_v2_pilot/Qwen3.5-35B-A3B/gw150914_detection/shard_${SLURM_ARRAY_TASK_ID}"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.run_existence_prompt_v2 \
  --model "$MODEL" --tasks "$TASKS" --output "$RESULT" \
  --generation-tokens 300 --maximum-runtime-minutes 8
