#!/bin/bash
#SBATCH --job-name=cern-ad-pilot
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=slurm-pilot-%j.out

set -euo pipefail

ROOT=/hkfs/home/project/hk-project-p0025545/dv3352/Project
cd $ROOT

# Activate project venv if present (adjust path if needed)
source $ROOT/parsing/.venv/bin/activate || true

python -m cern_advertisement_detection_pilot.src.run_pilot --image-root parsing/output/deepseekocr2_split_render/CERNCourier2022NovDec-digitaledition --model-dir external/models/TransDLANet --checkpoint '' --device cuda:0 --limit 30
