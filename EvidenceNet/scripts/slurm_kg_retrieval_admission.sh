#!/bin/bash
#SBATCH --job-name=kg-admission
#SBATCH --partition=dev-cpu
#SBATCH --account=hk-project-p0025545
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:20:00
#SBATCH --output=slurm-kg-admission-%j.out

# CPU-only admission audit against existing frozen HoreKa2 artifacts.
# No model loading, embedding, OCR, or Qwen. The output path is new per job.
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project

PYTHON=./.venv-magazine-exp1/bin/python
OUTPUT="EvidenceNet/output/kg_retrieval_admission_job_${SLURM_JOB_ID}"
echo "host=$(hostname) job=${SLURM_JOB_ID} output=$OUTPUT"

"$PYTHON" -m pytest EvidenceNet/tests/test_kg_retrieval_admission.py -q
"$PYTHON" EvidenceNet/scripts/audit_kg_retrieval_admission.py \
  --navigation EvidenceNet/output/top10_node_navigation_20261029/navigation.jsonl \
  --edges EvidenceNet/output/kg_link_prediction_bounded_verification_ultra_smoke_v1_20261102/accepted_new_edges_model_only.jsonl \
  --budget 20 --core 10 --graph-slots 3 --out "$OUTPUT"

echo "admission_report=$OUTPUT/summary.json"
