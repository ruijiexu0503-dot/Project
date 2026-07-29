#!/bin/bash
#SBATCH --job-name=evidencenet-hybrid-units
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=12:00:00
#SBATCH --output=logs/evidencenet-hybrid-units-%j.out
#SBATCH --error=logs/evidencenet-hybrid-units-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
BGE_MODEL="/hkfs/home/project/hk-project-p0025545/dv3352/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
cd "${PROJECT_DIR}"
mapfile -t DOCS < config/corpus_documents.txt
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"

srun "${PYTHON}" -m evidence_graph.boundary_experiments --config config/evidence_graph.yaml \
  --model "${BGE_MODEL}" --docs "${DOCS[@]}"
srun "${PYTHON}" -m evidence_graph.hybrid_boundary_verifier --config config/evidence_graph.yaml \
  --comparison output/evidence_graph/boundary_method_comparison.json
