#!/bin/bash
#SBATCH --job-name=body-sem-stats
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=logs/body-sem-stats-%j.out
#SBATCH --error=logs/body-sem-stats-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet";cd "$P"
"$P/.venv_qwen/bin/python" -m evidence_graph.analyze_body_comparison
