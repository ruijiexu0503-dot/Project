#!/bin/bash
#SBATCH --job-name=gw-contrib-profile
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated-h100
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:10:00
#SBATCH --output=logs/gw-contrib-profile-%j.out
#SBATCH --error=logs/gw-contrib-profile-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
TASKS="$P/output/current_graph_semantic_retyping/shared/gw150914_detection/blind_tasks.jsonl"
RESULT="$P/output/contribution_profile_typing/Qwen3.5-35B-A3B/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.run_contribution_profile_typing \
  --model "$MODEL" --tasks "$TASKS" --output "$RESULT" \
  --generation-tokens 280 --maximum-runtime-minutes 8
