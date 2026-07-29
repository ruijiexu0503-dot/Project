#!/bin/bash
#SBATCH --job-name=dsocr2_bbox
#SBATCH --partition=accelerated
#SBATCH --output=logs/dsocr2_bbox_%j.out
#SBATCH --error=logs/dsocr2_bbox_%j.err
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --gres=gpu:1

set -euo pipefail

cd "${SLURM_SUBMIT_DIR}"

mkdir -p logs
mkdir -p output/render_result
mkdir -p data/processed
mkdir -p data/failed

source .venv/bin/activate

export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

export HF_HOME="${SLURM_SUBMIT_DIR}/.cache/huggingface"
export TRANSFORMERS_CACHE="${HF_HOME}/transformers"
export TORCH_HOME="${SLURM_SUBMIT_DIR}/.cache/torch"

python src/deepseekocr2_parsing/parse_incoming_deepseekocr2_bbox.py \
  --incoming data/incoming \
  --output output/render_result \
  --model-name external/DeepSeek-OCR-2-hf \
  --bbox-scale norm999 \
  --skip-existing \
  --no-flash-attn \
  --move-processed \
  --processed-dir data/processed \
  --failed-dir data/failed