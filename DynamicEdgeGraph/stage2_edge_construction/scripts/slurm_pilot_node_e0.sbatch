#!/bin/bash
# 24-query Pilot GPU phase: route verified node content -> one frozen encoder space.
# The dependent CPU script performs candidate construction and E0 algebra.
#SBATCH --job-name=stage2-pilot-node-embed
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=00:55:00
#SBATCH --output=DynamicEdgeGraph/stage2_edge_construction/outputs/pilot_node_representation_v1/slurm-%j.out
#SBATCH --error=DynamicEdgeGraph/stage2_edge_construction/outputs/pilot_node_representation_v1/slurm-%j.err
set -euo pipefail

cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
source EvidenceNet/.venv_qwen/bin/activate

NODE_CONFIG=DynamicEdgeGraph/stage2_edge_construction/configs/pilot_node_embeddings.json
EDGE_CONFIG=DynamicEdgeGraph/stage2_edge_construction/configs/pilot_e0.json

python DynamicEdgeGraph/stage2_edge_construction/src/node_representations.py --config "$NODE_CONFIG"
python DynamicEdgeGraph/stage2_edge_construction/src/encode_node_embeddings.py --config "$NODE_CONFIG"
