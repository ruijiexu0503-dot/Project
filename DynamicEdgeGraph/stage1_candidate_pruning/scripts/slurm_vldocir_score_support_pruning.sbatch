#!/bin/bash
#SBATCH --job-name=vldocir-prune-ss
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=cpu
#SBATCH --exclude=hk2n1129
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=08:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_prune_ss_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_prune_ss_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-stage1-ann-top100-20261108
BASE="$RUN/descriptive_stats_20261108"
OUT=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-score-support-pruning-20261109/experiments/score_support_top100_${SLURM_JOB_ID}
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.run_score_support_pruning --run "$RUN" --nodes DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-html-nodes-20261107/canonical_nodes.jsonl --views DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107/retrieval_views.jsonl --stats-db "$BASE/descriptive.sqlite" --config DynamicEdgeGraph/stage1_candidate_pruning/configs/vldocir_score_support_pruning_20261109.json --out "$OUT"
