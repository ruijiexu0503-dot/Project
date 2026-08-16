#!/bin/bash
#SBATCH --job-name=current-sem-retype
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:12:00
#SBATCH --output=logs/current-sem-retype-%j.out
#SBATCH --error=logs/current-sem-retype-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
TASKS="$P/output/current_graph_semantic_retyping/shared/gw150914_detection/blind_tasks.jsonl"
RESULT="$P/output/current_graph_semantic_retyping/Qwen3.5-35B-A3B/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.run_split_taxonomy_relation_typing \
  --model "$MODEL" \
  --tasks "$TASKS" \
  --output "$RESULT" \
  --generation-tokens 220 \
  --maximum-runtime-minutes 9.5
