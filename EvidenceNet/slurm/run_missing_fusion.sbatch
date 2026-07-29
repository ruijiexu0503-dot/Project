#!/bin/bash
#SBATCH --job-name=evidencenet-fusion
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=01:00:00
#SBATCH --array=0-1
#SBATCH --output=logs/evidencenet-fusion-%A_%a.out
#SBATCH --error=logs/evidencenet-fusion-%A_%a.err

set -euo pipefail
EVIDENCENET_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
PARSING_DIR="/home/hk-project-p0025545/dv3352/Project/parsing"
MODEL_DIR="/home/hk-project-p0025545/dv3352/Project/external/models/Qwen2.5-VL-7B-Instruct"
VLM_PYTHON="${PARSING_DIR}/.venv_vlm/bin/python"
DOCS=("CyberPhysicalModelingChapter4" "Luminous Garden Agnes Northrop and the Women of Tiffany Studios")
DOC_NAME="${DOCS[${SLURM_ARRAY_TASK_ID}]}"
WORK_DIR="${EVIDENCENET_DIR}/output/fusion_work/${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
TARGET_ROOT="${PARSING_DIR}/output/processed_vlm_md_by_doc"

mkdir -p "${WORK_DIR}"
cd "${PARSING_DIR}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1

"${VLM_PYTHON}" src/vlm_group_to_md.py \
  --render-dir output/deepseekocr2_split_render \
  --out-dir "${WORK_DIR}" \
  --model-path "${MODEL_DIR}" \
  --only-doc "${DOC_NAME}" \
  --max-new-tokens 1024 \
  --max-visual-crops 8

DOC_KEY="$(awk '/^doc_id:/{print $2; exit}' "${WORK_DIR}/semantic_groups.md")"
if [[ -z "${DOC_KEY}" ]]; then
  echo "Could not recover doc_id from generated semantic_groups.md" >&2
  exit 1
fi
TARGET_DIR="${TARGET_ROOT}/${DOC_KEY}"
mkdir -p "${TARGET_DIR}"
cp "${WORK_DIR}/semantic_groups.md" "${TARGET_DIR}/semantic_groups.md"

"${VLM_PYTHON}" src/generate_semantic_group_crops.py \
  --input "${TARGET_DIR}/semantic_groups.md" \
  --project-root "${PARSING_DIR}" \
  --overwrite

echo "Generated fused outputs for ${DOC_NAME} at ${TARGET_DIR}"
