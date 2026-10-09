#!/usr/bin/env bash
#SBATCH --job-name=postergen-detr-pilot
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=12
#SBATCH --mem=160G
#SBATCH --time=00:14:30
#SBATCH --output=experiments/postergen_pilot_20261009/gpu-%j.out
#SBATCH --error=experiments/postergen_pilot_20261009/gpu-%j.err
set -euo pipefail
source current/env.sh
export OMP_NUM_THREADS=8 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
EvidenceNet/.venv_qwen/bin/python experiments/postergen_pilot_20261009/run_pilot.py generate
