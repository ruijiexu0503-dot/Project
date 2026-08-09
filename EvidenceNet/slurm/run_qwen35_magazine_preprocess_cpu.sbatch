#!/bin/bash
#SBATCH --job-name=mag-pre-cpu
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=64
#SBATCH --mem=256G
#SBATCH --time=08:00:00
#SBATCH --output=logs/mag-pre-cpu-%j.out
#SBATCH --error=logs/mag-pre-cpu-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
M="/home/hk-project-p0025545/dv3352/Project/external/models/Qwen3.5-35B-A3B"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
"$P/.venv_qwen/bin/python" -m evidence_graph.split_semantic_run preprocess \
  --doc-id CERNCourier2025JanFeb-digitaledition --model "$M"
