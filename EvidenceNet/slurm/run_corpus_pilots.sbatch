#!/bin/bash
#SBATCH --job-name=evidencenet-corpus
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=04:00:00
#SBATCH --array=0-11%2
#SBATCH --output=logs/evidencenet-corpus-%A_%a.out
#SBATCH --error=logs/evidencenet-corpus-%A_%a.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "${PROJECT_DIR}"
mapfile -t DOCS < config/corpus_documents.txt
DOC_ID="${DOCS[${SLURM_ARRAY_TASK_ID}]}"
export TOKENIZERS_PARALLELISM=false TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1

srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph run --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph.multimodal --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph semantic-pilot --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph adjudicate-pilot --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph.visualize --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PROJECT_DIR}/.venv_qwen/bin/python" -m evidence_graph.adjudication_report --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
