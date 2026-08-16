#!/bin/bash
#SBATCH --job-name=freeform-exist
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --array=0-1
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:25:00
#SBATCH --output=logs/freeform-exist-%A_%a.out
#SBATCH --error=logs/freeform-exist-%A_%a.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
TASKS="$P/output/freeform_edge_existence/shared/gw150914_detection/blind_tasks_shard_${SLURM_ARRAY_TASK_ID}.jsonl"
RESULT="$P/output/freeform_edge_existence/Qwen3.5-35B-A3B/gw150914_detection/shard_${SLURM_ARRAY_TASK_ID}"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.run_freeform_edge_existence \
  --model "$MODEL" --tasks "$TASKS" --output "$RESULT" \
  --generation-tokens 190 --maximum-runtime-minutes 20
