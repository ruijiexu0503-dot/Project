#!/bin/bash
#SBATCH --job-name=q36-paper-post
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=logs/q36-paper-post-%j.out
#SBATCH --error=logs/q36-paper-post-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
M="$P/../external/models/Qwen3.6-35B-A3B"
E="$P/../external/models/Qwen3.5-35B-A3B"
cd "$P"
"$P/.venv_qwen/bin/python" -m evidence_graph.split_semantic_run postprocess \
  --doc-id gw150914_detection --model "$M" --enrichment-model "$E"
