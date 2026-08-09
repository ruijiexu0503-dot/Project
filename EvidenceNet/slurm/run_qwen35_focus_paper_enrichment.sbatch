#!/bin/bash
#SBATCH --job-name=q35-paper-enrich
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=08:00:00
#SBATCH --output=logs/q35-paper-enrich-%j.out
#SBATCH --error=logs/q35-paper-enrich-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "$P"; export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
"$P/.venv_qwen/bin/python" -m evidence_graph.comparative_enrichment \
  --doc-id gw150914_detection --config config/qwen35_fast_segmentation.yaml
