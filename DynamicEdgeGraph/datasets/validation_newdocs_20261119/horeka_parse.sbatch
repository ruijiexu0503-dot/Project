#!/usr/bin/env bash
#SBATCH --job-name=val-parse-a100
#SBATCH --account=hk-project-pai00096
#SBATCH --partition=accelerated
#SBATCH --nodes=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=100G
#SBATCH --time=01:00:00
#SBATCH --array=0-1%2
#SBATCH --output=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%A_%a.out
#SBATCH --error=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%A_%a.err
set -euo pipefail
ROOT=/hkfs/home/project/hk-project-p0025545/dv3352/Project;cd "$ROOT"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
BASE=DynamicEdgeGraph/datasets/validation_newdocs_20261119;MANIFEST="$BASE/manifest_horeka.json"
DOC_ID=$(EvidenceNet/.venv_qwen/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["documents"][int(sys.argv[2])]["document_id"])' "$MANIFEST" "$SLURM_ARRAY_TASK_ID")
parsing/.venv_vlm/bin/python parsing/experiments/dolphin_v2_pilot/run_pdf_corpus.py --manifest "$MANIFEST" --model parsing/experiments/dolphin_v2_pilot/models/Dolphin-v2 --work "$BASE/work" --output "$BASE/parsed" --document-id "$DOC_ID" --resume --defer-publish --max-batch-size 2
