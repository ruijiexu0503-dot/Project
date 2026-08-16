#!/bin/bash
#SBATCH --job-name=center-edge-35b
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated-h100
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:14:50
#SBATCH --output=logs/center-edge-35b-%j.out
#SBATCH --error=logs/center-edge-35b-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
TASKS="$P/output/comparative_edge_selection/shared/gw150914_detection/center_tasks.jsonl"
RESULT="$P/output/comparative_edge_selection/Qwen3.5-35B-A3B/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.run_comparative_edge_selection \
  --model "$MODEL" --tasks "$TASKS" --output "$RESULT" \
  --generation-tokens 720 --maximum-runtime-minutes 12
