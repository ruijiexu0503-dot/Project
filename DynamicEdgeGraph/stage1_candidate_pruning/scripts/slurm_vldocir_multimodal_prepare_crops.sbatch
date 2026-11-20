#!/bin/bash
#SBATCH --job-name=vldocir-mm-crops
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=02:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_mm_crops_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_mm_crops_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_multimodal_preflight \
  --nodes DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-html-nodes-20261107/canonical_nodes.jsonl \
  --page-root DynamicEdgeGraph/stage1_candidate_pruning/.cache/vldocir_representative/pages \
  --out DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-multimodal-enrichment-v1 \
  --emit-crops
