#!/bin/bash
#SBATCH --job-name=detr-rank-35b
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated-h100
#SBATCH --array=0-3
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:14:50
#SBATCH --output=logs/detr-rank-35b-%A_%a.out
#SBATCH --error=logs/detr-rank-35b-%A_%a.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
SHARED="$P/output/cross_document_trial/detr"
TASKS="$SHARED/shard_${SLURM_ARRAY_TASK_ID}/ranking_tasks.jsonl"
RESULT="$SHARED/ranking/Qwen3.5-35B-A3B/shard_${SLURM_ARRAY_TASK_ID}"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.run_sequential_long_range \
  --model "$MODEL" --tasks "$TASKS" --output "$RESULT" \
  --generation-tokens 420 --maximum-runtime-minutes 12
