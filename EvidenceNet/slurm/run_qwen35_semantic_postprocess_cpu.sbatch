#!/bin/bash
#SBATCH --job-name=sem-post-cpu
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --array=0-1%2
#SBATCH --output=logs/sem-post-cpu-%A_%a.out
#SBATCH --error=logs/sem-post-cpu-%A_%a.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
M="/home/hk-project-p0025545/dv3352/Project/external/models/Qwen3.5-35B-A3B"
D="$(sed -n "$((SLURM_ARRAY_TASK_ID + 1))p" "$P/config/qwen35_focus_documents.txt")"
cd "$P"
"$P/.venv_qwen/bin/python" -m evidence_graph.split_semantic_run postprocess --doc-id "$D" --model "$M"
