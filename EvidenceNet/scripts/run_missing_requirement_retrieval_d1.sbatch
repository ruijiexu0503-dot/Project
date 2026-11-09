#!/usr/bin/env bash
#SBATCH --job-name=evidence-d1
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev-cpu
#SBATCH --nodes=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=160G
#SBATCH --time=01:00:00
#SBATCH --output=EvidenceNet/output/missing_requirement_retrieval_d1_v1_20261106/slurm-%j.out
#SBATCH --error=EvidenceNet/output/missing_requirement_retrieval_d1_v1_20261106/slurm-%j.err
set -euo pipefail

cd "${SLURM_SUBMIT_DIR}"
export HF_HOME="${HF_HOME:-$PWD/.cache/huggingface}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=16 MKL_NUM_THREADS=16
python="$PWD/EvidenceNet/.venv_qwen/bin/python"
exec "$python" EvidenceNet/scripts/run_missing_requirement_retrieval_d1.py \
  --output EvidenceNet/output/missing_requirement_retrieval_d1_v1_20261106 \
  --model EvidenceNet/models/Qwen3-Embedding-8B
