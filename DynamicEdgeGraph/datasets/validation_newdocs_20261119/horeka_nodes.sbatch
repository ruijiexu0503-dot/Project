#!/usr/bin/env bash
#SBATCH --job-name=val-nodes-a100
#SBATCH --account=hk-project-pai00096
#SBATCH --partition=accelerated
#SBATCH --nodes=1
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=220G
#SBATCH --time=01:00:00
#SBATCH --output=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%A_%a.out
#SBATCH --error=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%A_%a.err
set -euo pipefail
ROOT=/hkfs/home/project/hk-project-p0025545/dv3352/Project;cd "$ROOT"
export OMP_NUM_THREADS=12 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True PYTHONUNBUFFERED=1 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1
BASE=DynamicEdgeGraph/datasets/validation_newdocs_20261119
for stage in describe candidates decide assemble; do
 EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_vldocir_nodes.py "$stage" --source "$BASE/prepared" --output "$BASE/nodes" --batch "$SLURM_ARRAY_TASK_ID"
done
