#!/usr/bin/env bash
#SBATCH --job-name=postergen-three
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=gpu-h200
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=12
#SBATCH --mem=160G
#SBATCH --time=00:40:00
#SBATCH --array=0-2%3
#SBATCH --output=experiments/postergen_pilot_20261009/more-%A_%a.out
#SBATCH --error=experiments/postergen_pilot_20261009/more-%A_%a.err
set -euo pipefail
source current/env.sh
export OMP_NUM_THREADS=8 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
cases=(gw150914_detection hallmarks_of_aging entropy)
EvidenceNet/.venv_qwen/bin/python experiments/postergen_pilot_20261009/run_more.py generate "${cases[$SLURM_ARRAY_TASK_ID]}"
