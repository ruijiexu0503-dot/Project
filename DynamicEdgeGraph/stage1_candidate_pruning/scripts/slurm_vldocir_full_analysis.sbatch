#!/bin/bash
#SBATCH --job-name=vldocir-stage1-analysis
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=24:00:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_stage1_analysis_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_stage1_analysis_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-stage1-ann-top100-20261108
NODES=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-html-nodes-20261107/canonical_nodes.jsonl
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_full_analysis --run "$RUN" --canonical-nodes "$NODES"
