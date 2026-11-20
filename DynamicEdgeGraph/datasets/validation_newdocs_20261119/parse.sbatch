#!/usr/bin/env bash
#SBATCH --job-name=val-parse
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --array=0-1%2
#SBATCH --output=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%A_%a.out
#SBATCH --error=DynamicEdgeGraph/datasets/validation_newdocs_20261119/logs/%x-%A_%a.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}";source current/env.sh
BASE=DynamicEdgeGraph/datasets/validation_newdocs_20261119;MANIFEST="$BASE/manifest.json"
DOC_ID=$(EvidenceNet/.venv_qwen/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["documents"][int(sys.argv[2])]["document_id"])' "$MANIFEST" "$SLURM_ARRAY_TASK_ID")
parsing/.venv_vlm/bin/python parsing/experiments/dolphin_v2_pilot/run_pdf_corpus.py --manifest "$MANIFEST" --model parsing/experiments/dolphin_v2_pilot/models/Dolphin-v2 --work "$BASE/work" --output "$BASE/parsed" --document-id "$DOC_ID" --resume --defer-publish --max-batch-size 2
