#!/bin/bash
# CPU phase. Submit with --dependency=afterok:<pilot-node-embedding-job>.
#SBATCH --job-name=stage2-pilot-e0
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=DynamicEdgeGraph/stage2_edge_construction/outputs/pilot_e0/slurm-%j.out
#SBATCH --error=DynamicEdgeGraph/stage2_edge_construction/outputs/pilot_e0/slurm-%j.err
set -euo pipefail

cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
source EvidenceNet/.venv_qwen/bin/activate
EDGE_CONFIG=DynamicEdgeGraph/stage2_edge_construction/configs/pilot_e0.json

python DynamicEdgeGraph/stage2_edge_construction/src/prepare_pilot_pairs.py --config "$EDGE_CONFIG"
python DynamicEdgeGraph/stage2_edge_construction/src/build_edges.py --config "$EDGE_CONFIG"
python DynamicEdgeGraph/stage2_edge_construction/src/evaluate_edges.py --run-dir DynamicEdgeGraph/stage2_edge_construction/outputs/pilot_e0
