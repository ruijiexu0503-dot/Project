#!/bin/bash
#SBATCH --job-name=vldocir-crossscore
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_crossscore_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_crossscore_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-stage1-ann-top100-20261108
OUT=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-abc-score-support-pruning-20261109/cross_scores_${SLURM_JOB_ID}
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.cross_score_effective_candidates --stats-db "$RUN/descriptive_stats_20261108/descriptive.sqlite" --models DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107/models --out "$OUT"
