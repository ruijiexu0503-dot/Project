#!/bin/bash
#SBATCH --job-name=q36-paper-rel
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=08:00:00
#SBATCH --output=logs/q36-paper-rel-%j.out
#SBATCH --error=logs/q36-paper-rel-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
M="$P/../external/models/Qwen3.6-35B-A3B"
E="$P/../external/models/Qwen3.5-35B-A3B"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
"$P/.venv_qwen/bin/python" -m evidence_graph.split_semantic_run verify \
  --doc-id gw150914_detection --model "$M" --enrichment-model "$E"
