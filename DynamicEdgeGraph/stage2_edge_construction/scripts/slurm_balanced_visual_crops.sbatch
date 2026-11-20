#!/bin/bash
#SBATCH --job-name=stage2-balanced-crops
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --output=DynamicEdgeGraph/stage2_edge_construction/outputs/balanced_v1_visual/slurm-crops-%j.out
#SBATCH --error=DynamicEdgeGraph/stage2_edge_construction/outputs/balanced_v1_visual/slurm-crops-%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
source EvidenceNet/.venv_qwen/bin/activate
BASE=DynamicEdgeGraph/stage1_candidate_pruning/outputs
OUT=DynamicEdgeGraph/stage2_edge_construction/outputs/balanced_v1_visual
python DynamicEdgeGraph/stage2_edge_construction/src/prepare_balanced_image_nodes.py --catalog "$BASE/vldocir_balanced_v1/node_catalog.jsonl" --canonical-nodes "$BASE/vldocir-representative-html-nodes-20261107/canonical_nodes.jsonl" --out "$OUT"
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_multimodal_preflight --nodes "$OUT/balanced_image_nodes.jsonl" --page-root DynamicEdgeGraph/stage1_candidate_pruning/.cache/vldocir_representative/pages --out "$OUT" --emit-crops
