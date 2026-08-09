#!/bin/bash
#SBATCH --job-name=body-coarse-stats
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=logs/body-coarse-stats-%j.out
#SBATCH --error=logs/body-coarse-stats-%j.err

set -euo pipefail
cd /home/hk-project-p0025545/dv3352/Project/EvidenceNet
.venv_qwen/bin/python -m evidence_graph.analyze_coarse_body_comparison
