#!/bin/bash
#SBATCH --job-name=vldocir-abc-prune
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=04:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_abc_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_abc_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
ROOT=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-abc-score-support-pruning-20261109
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.run_abc_pruning --cross "$ROOT/cross_scores_126094" --run DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-stage1-ann-top100-20261108 --views DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107/retrieval_views.jsonl --nodes DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-html-nodes-20261107/canonical_nodes.jsonl --config DynamicEdgeGraph/stage1_candidate_pruning/configs/vldocir_abc_pruning_20261109.json --out "$ROOT/abc_results_${SLURM_JOB_ID}"
