#!/bin/bash
#SBATCH --job-name=evidencenet-luminous-visual
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_cpuonly
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=logs/evidencenet-luminous-visual-%j.out
#SBATCH --error=logs/evidencenet-luminous-visual-%j.err

set -euo pipefail
PROJECT_DIR="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
DOC_ID="Luminous Garden Agnes Northrop and the Women of Tiffany Studios"
cd "${PROJECT_DIR}"
PYTHON="${PROJECT_DIR}/.venv_qwen/bin/python"

srun "${PYTHON}" -m evidence_graph.multimodal --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PYTHON}" -m evidence_graph.visualize --doc-id "${DOC_ID}" --config config/evidence_graph.yaml
srun "${PYTHON}" -m evidence_graph.corpus_diagnostics --config config/evidence_graph.yaml --manifest config/corpus_documents.txt

echo "Updated Luminous Garden same-page visual context and review graph."
