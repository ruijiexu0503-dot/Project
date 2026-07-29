#!/bin/bash
#SBATCH --job-name=evidencenet-report
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --output=logs/evidencenet-report-%j.out
#SBATCH --error=logs/evidencenet-report-%j.err

set -euo pipefail
cd "/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
.venv_qwen/bin/python -m evidence_graph.corpus_diagnostics --config config/evidence_graph.yaml --manifest config/corpus_documents.txt
