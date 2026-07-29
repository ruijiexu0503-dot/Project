#!/bin/bash
#SBATCH --job-name=evidencenet-boundary-compare
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=01:00:00
#SBATCH --output=logs/evidencenet-boundary-compare-%j.out
#SBATCH --error=logs/evidencenet-boundary-compare-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="/hkfs/home/project/hk-project-p0025545/dv3352/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
cd "${PROJECT_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1
srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph.boundary_experiments \
  --config config/evidence_graph.yaml --model "${MODEL}" --docs \
  "CERNCourier2025JanFeb-digitaledition" \
  "Luminous Garden Agnes Northrop and the Women of Tiffany Studios" \
  "gw150914_gr_test"
