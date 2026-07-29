#!/bin/bash
#SBATCH --job-name=evidencenet-fusion-index
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --output=logs/evidencenet-fusion-index-%j.out
#SBATCH --error=logs/evidencenet-fusion-index-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
"${PROJECT_DIR}/.venv_qwen/bin/python" "${PROJECT_DIR}/scripts/rebuild_fusion_index.py" \
  --root "/home/hk-project-p0025545/dv3352/Project/parsing/output/processed_vlm_md_by_doc"
