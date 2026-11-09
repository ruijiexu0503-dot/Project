#!/bin/bash
#SBATCH --job-name=vldocir-score-agree
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=cpu
#SBATCH --exclude=hk2n1129
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_score_agree_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_score_agree_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-stage1-ann-top100-20261108
BASE="$RUN/descriptive_stats_20261108"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_score_agreement_supplement --run "$RUN" --nodes DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-html-nodes-20261107/canonical_nodes.jsonl --stats-db "$BASE/descriptive.sqlite" --out "$BASE/score_agreement_supplement_20261108"
