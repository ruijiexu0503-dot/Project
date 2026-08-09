#!/bin/bash
#SBATCH --job-name=mag-bge-devcpu
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_cpuonly
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=logs/mag-bge-devcpu-%j.out
#SBATCH --error=logs/mag-bge-devcpu-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
M="/home/hk-project-p0025545/dv3352/Project/external/models/Qwen3.5-35B-A3B"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}" MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
"$P/.venv_qwen/bin/python" -m evidence_graph.split_semantic_run preprocess \
  --doc-id CERNCourier2025JanFeb-digitaledition --model "$M"
