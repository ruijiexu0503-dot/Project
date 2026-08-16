#!/bin/bash
#SBATCH --job-name=paper-verify-35b
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=01:00:00
#SBATCH --output=logs/paper-verify-35b-%j.out
#SBATCH --error=logs/paper-verify-35b-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
SOURCE="$P/output/scientific_body_cascade/Qwen3.5-9B-adaptive/gw150914_detection"
RESULT="$P/output/scientific_body_cascade/Qwen3.5-35B-A3B/gw150914_detection"
BASE="$P/output/scientific_body_cascade/shared_candidates/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

# This exits nonzero before model loading when the screen is incomplete, has
# recall below 0.90, or forwards more than 180 pairs.
"$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_scientific_screening \
  --source "$BASE" --screening "$SOURCE" --minimum-recall .90 --maximum-forwarded 180

"$P/.venv_qwen/bin/python" -m evidence_graph.verify_scientific_body_coarse \
  --model "$MODEL" --source "$SOURCE" --output "$RESULT" \
  --chunk-size 16 --batch-size 8 --generation-tokens 2200 \
  --retry-generation-tokens 1000 --maximum-runtime-minutes 45

if "$P/.venv_qwen/bin/python" -c \
  'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("complete") else 1)' \
  "$RESULT/status.json"; then
  "$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_scientific_staged \
    --source "$SOURCE" --result "$RESULT"
else
  "$P/.venv_qwen/bin/python" -c \
    'import json,sys; s=json.load(open(sys.argv[1])); print("Checkpoint saved: {}/{} pairs".format(s["processed"],s["total"]))' \
    "$RESULT/status.json"
fi
