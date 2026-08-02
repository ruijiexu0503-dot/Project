#!/bin/bash
set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL_ROOT="/home/hk-project-p0025545/dv3352/Project/external/models"
cd "${PROJECT_DIR}"
mkdir -p logs

submit() {
  local gpus="$1" memory="$2" model="$3" document_kind="$4" time_limit="$5"
  sbatch --gres="gpu:${gpus}" --mem="${memory}" \
    --time="${time_limit}" \
    --job-name="qwen-${model}-${document_kind}" \
    --export="ALL,MODEL=${MODEL_ROOT}/${model},DOCUMENT_KIND=${document_kind}" \
    slurm/run_qwen_full_documents.sbatch
}

for document_kind in magazine paper slides illustrated_booklet; do
  case "${document_kind}" in
    magazine) time_limit=12:00:00 ;;
    paper) time_limit=08:00:00 ;;
    slides) time_limit=04:00:00 ;;
    illustrated_booklet) time_limit=06:00:00 ;;
  esac
  submit 1 128G Qwen2.5-VL-7B-Instruct "${document_kind}" "${time_limit}"
  submit 1 256G Qwen3.5-35B-A3B "${document_kind}" "${time_limit}"
  submit 1 256G Qwen3.6-35B-A3B "${document_kind}" "${time_limit}"
  submit 4 700G Qwen3.5-122B-A10B "${document_kind}" "${time_limit}"
done
