#!/usr/bin/env bash
#SBATCH --job-name=val-dispatch
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%j.out
#SBATCH --error=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
BASE=DynamicEdgeGraph/datasets/validation_newdocs_20261119
TOTAL=$(EvidenceNet/.venv_qwen/bin/python -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["batches"]))' "$BASE/prepared/manifest.json")
JOB=$(sbatch --parsable --account=hk-project-p0025545 --partition=gpu-h100 --time=01:00:00 --array="0-$((TOTAL-1))%2" "$BASE/nodes.sbatch")
echo "submitted_node_array=$JOB batches=$TOTAL"
