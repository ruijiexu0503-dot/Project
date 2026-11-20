#!/usr/bin/env bash
#SBATCH --job-name=val-nodes
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=gpu-h100
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=12
#SBATCH --mem=160G
#SBATCH --time=08:00:00
#SBATCH --output=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%A_%a.out
#SBATCH --error=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%A_%a.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}";source current/env.sh
export OMP_NUM_THREADS=8 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
BASE=DynamicEdgeGraph/datasets/validation_newdocs_20261119
for stage in describe candidates decide assemble; do
 EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_vldocir_nodes.py "$stage" --source "$BASE/prepared" --output "$BASE/nodes" --batch "$SLURM_ARRAY_TASK_ID"
done
