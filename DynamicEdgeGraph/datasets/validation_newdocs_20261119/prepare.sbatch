#!/usr/bin/env bash
#SBATCH --job-name=val-prepare
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%j.out
#SBATCH --error=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}";source current/env.sh
BASE=DynamicEdgeGraph/datasets/validation_newdocs_20261119
EvidenceNet/.venv_qwen/bin/python "$BASE/prepare_nodes.py" --manifest "$BASE/manifest.json" --work "$BASE/work" --out "$BASE/prepared"
