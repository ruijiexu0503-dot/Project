#!/bin/bash
#SBATCH --job-name=kg-verify-v2-prep
#SBATCH --partition=dev-cpu
#SBATCH --account=hk-project-p0025545
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=slurm-kg-verify-v2-prep-%j.out

# Read-only source preservation; prepare new 20-pair v2 verifier input snapshot.
# No model inference, GPU allocation, or modifications to the old v1 experiment.
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project

PYTHON=./.venv-magazine-exp1/bin/python
OUT="EvidenceNet/output/kg_link_prediction_bounded_identity_v2_prepare_${SLURM_JOB_ID}"
"$PYTHON" -m pytest \
    EvidenceNet/tests/test_kg_link_prediction_bounded_verifier.py \
    EvidenceNet/tests/test_kg_bounded_verifier_v2_identity.py -q
"$PYTHON" EvidenceNet/scripts/run_kg_link_prediction_bounded_verifier.py prepare \
    --out "$OUT" \
    --model external/models/Qwen3.5-35B-A3B
echo "V2_PREPARED_OUT=$OUT"
echo "V2_PREP_ONLY_NO_GPU_INFERENCE=1"
