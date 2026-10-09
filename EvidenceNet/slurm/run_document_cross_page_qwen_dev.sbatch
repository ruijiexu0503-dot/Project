#!/bin/bash
#SBATCH --job-name=doc-xpage-qwen-v2
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:14:50
#SBATCH --output=logs/doc-xpage-qwen-%j.out
#SBATCH --error=logs/doc-xpage-qwen-%j.err

set -euo pipefail
PROJECT="/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project"
cd "$PROJECT/EvidenceNet"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$PROJECT/EvidenceNet/.venv_qwen/bin/python" scripts/run_document_cross_page_qwen.py \
  --candidates "$PROJECT/EvidenceNet/output/document_article_graph_46209_v7/cross_page_candidates.jsonl" \
  --output "$PROJECT/EvidenceNet/output/document_cross_page_qwen_46209_v3_two_stage" \
  --model "$PROJECT/external/models/Qwen3.5-35B-A3B"
