#!/usr/bin/env bash
#SBATCH --job-name=val-dispatch
#SBATCH --account=hk-project-pai00096
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%j.out
#SBATCH --error=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%j.err
set -euo pipefail
ROOT=/hkfs/home/project/hk-project-p0025545/dv3352/Project;cd "$ROOT"
BASE=DynamicEdgeGraph/datasets/validation_newdocs_20261119
TOTAL=$(EvidenceNet/.venv_qwen/bin/python -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["batches"]))' "$BASE/prepared/manifest.json")
JOB=$(sbatch --parsable --account=hk-project-pai00096 --partition=accelerated --time=00:30:00 --array="0-$((TOTAL-1))%2" "$BASE/horeka_nodes.sbatch")
echo "submitted_node_array=$JOB batches=$TOTAL"
