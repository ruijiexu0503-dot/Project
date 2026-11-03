#!/bin/bash
#SBATCH --job-name=kg-edge-audit
#SBATCH --partition=dev-cpu
#SBATCH --account=hk-project-p0025545
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --output=slurm-kg-edge-audit-%j.out

set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project

PYTHON=./.venv-magazine-exp1/bin/python
OUTPUT="EvidenceNet/output/kg_accepted_edge_audit_job_${SLURM_JOB_ID}"
echo "host=$(hostname) job=${SLURM_JOB_ID}"
"$PYTHON" -m pytest EvidenceNet/tests/test_kg_accepted_edge_evidence.py -q
"$PYTHON" EvidenceNet/scripts/audit_kg_accepted_edge_evidence.py --out "$OUTPUT"
echo "review_queue=$OUTPUT/edge_review_queue.jsonl"
echo "summary=$OUTPUT/summary.json"
