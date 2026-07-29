#!/bin/bash
#SBATCH --job-name=pp_doclayout_skip
#SBATCH --partition=accelerated
#SBATCH --output=logs/pp_doclayout_skip_%j.out
#SBATCH --error=logs/pp_doclayout_skip_%j.err
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gres=gpu:1

set -euo pipefail

cd "${SLURM_SUBMIT_DIR}"

mkdir -p logs
mkdir -p output/layout_detection
mkdir -p output/layout_detection_vis

source .venv_layout/bin/activate

echo "=== Job info ==="
hostname
date
nvidia-smi || true

echo "=== Python / Paddle check ==="
python - <<'PY'
import sys
print("python:", sys.executable)

import paddle
print("paddle:", paddle.__version__)
print("compiled with cuda:", paddle.is_compiled_with_cuda())
paddle.utils.run_check()
PY

echo "=== Run PP-DocLayout on output/render_result, skip existing pages ==="

python src/layout_detection/run_pp_doclayout_detection.py \
  --image-root output/render_result \
  --output-root output/layout_detection \
  --vis-root output/layout_detection_vis \
  --model-dir external/models/PP-DocLayout-L \
  --device gpu:0 \
  --batch-size 1 \
  --layout-nms \
  --skip-existing \
  2>&1 | tee logs/layout_detection_skip_existing_${SLURM_JOB_ID}.log

echo "=== Done ==="
date