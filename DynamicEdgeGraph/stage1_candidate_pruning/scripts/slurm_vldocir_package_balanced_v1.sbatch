#!/bin/bash
#SBATCH --job-name=vldocir-balanced-v1
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_balanced_v1_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_balanced_v1_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
BASE=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-abc-score-support-pruning-20261109
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.package_balanced_v1 \
 --cross "$BASE/cross_scores_126094" \
 --balanced "$BASE/normalized_abc_search_126279/recommended_configs/balanced" \
 --views DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107/retrieval_views.jsonl \
 --nodes DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-html-nodes-20261107/canonical_nodes.jsonl \
 --out DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir_balanced_v1
