#!/bin/bash
#SBATCH --job-name=vldocir-pages-v1
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_pages_v1_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_pages_v1_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.materialize_vldocir_fixed_pages \
  --documents DynamicEdgeGraph/stage1_candidate_pruning/.cache/vldocir_representative/documents.jsonl \
  --page-tars DynamicEdgeGraph/stage1_candidate_pruning/.cache/vldocir_representative/pages \
  --out DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-multimodal-dolphin-v1
