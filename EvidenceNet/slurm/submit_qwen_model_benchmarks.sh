#!/bin/bash
set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL_ROOT="/home/hk-project-p0025545/dv3352/Project/external/models"
cd "${PROJECT_DIR}"
mkdir -p logs

submit() {
  local gpus="$1" memory="$2" model="$3"
  sbatch --gres="gpu:${gpus}" --mem="${memory}" --export="ALL,MODEL=${MODEL_ROOT}/${model}" \
    slurm/run_qwen_model_benchmark.sbatch
}

# Baseline and 35B MoE checkpoints each fit on one H100 (94 GB).
submit 1 128G Qwen2.5-VL-7B-Instruct
submit 1 256G Qwen3.5-35B-A3B
submit 1 256G Qwen3.6-35B-A3B
# The 122B checkpoint is sharded over the four H100s in one node.
submit 4 700G Qwen3.5-122B-A10B
