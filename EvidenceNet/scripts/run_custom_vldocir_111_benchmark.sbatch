#!/usr/bin/env bash
#SBATCH --job-name=custom-vldocir-111
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev-cpu
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=240G
#SBATCH --time=01:00:00
#SBATCH --output=EvidenceNet/output/custom_vldocir_benchmark_v1_20261106/slurm-%j.out
#SBATCH --error=EvidenceNet/output/custom_vldocir_benchmark_v1_20261106/slurm-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=32 MKL_NUM_THREADS=32
python="$PWD/EvidenceNet/.venv_qwen/bin/python"
exec "$python" EvidenceNet/scripts/run_custom_vldocir_111_benchmark.py \
  --doc-manifest EvidenceNet/output/custom_vldocir_subset_v2_20261106/doc_page_complete_111_manifest.jsonl \
  --bbox-manifest EvidenceNet/output/custom_vldocir_subset_v2_20261106/bbox_complete_111_manifest.jsonl \
  --out EvidenceNet/output/custom_vldocir_benchmark_v1_20261106
