#!/usr/bin/env bash
#SBATCH --job-name=val-prepare
#SBATCH --account=hk-project-pai00096
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%j.out
#SBATCH --error=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%j.err
set -euo pipefail
ROOT=/hkfs/home/project/hk-project-p0025545/dv3352/Project;cd "$ROOT"
BASE=DynamicEdgeGraph/datasets/validation_newdocs_20261119
EvidenceNet/.venv_qwen/bin/python "$BASE/prepare_nodes.py" --manifest "$BASE/manifest_horeka.json" --work "$BASE/work" --out "$BASE/prepared"
