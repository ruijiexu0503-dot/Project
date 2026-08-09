#!/bin/bash
#SBATCH --job-name=sem-verify-gpu
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=24:00:00
#SBATCH --array=0-1%2
#SBATCH --output=logs/sem-verify-gpu-%A_%a.out
#SBATCH --error=logs/sem-verify-gpu-%A_%a.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
M="/home/hk-project-p0025545/dv3352/Project/external/models/Qwen3.5-35B-A3B"
D="$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "$P/config/qwen35_focus_documents.txt")"
cd "$P"; export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
"$P/.venv_qwen/bin/python" -m evidence_graph.split_semantic_run verify --doc-id "$D" --model "$M"
