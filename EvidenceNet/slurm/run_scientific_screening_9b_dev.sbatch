#!/bin/bash
#SBATCH --job-name=paper-screen-9b
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=12
#SBATCH --mem=96G
#SBATCH --time=01:00:00
#SBATCH --output=logs/paper-screen-9b-%j.out
#SBATCH --error=logs/paper-screen-9b-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-9B"
SOURCE="$P/output/scientific_body_cascade/shared_candidates/gw150914_detection"
RESULT="$P/output/scientific_body_cascade/Qwen3.5-9B-adaptive/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.prepare_scientific_high_recall \
  --distance-window 12 --output-root "$P/output/scientific_body_cascade/shared_candidates"
"$P/.venv_qwen/bin/python" -m evidence_graph.screen_scientific_relations \
  --model "$MODEL" --source "$SOURCE" --output "$RESULT" \
  --batch-size 10 --maximum-runtime-minutes 40 --generation-tokens 1800

if "$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_scientific_screening \
  --source "$SOURCE" --screening "$RESULT" --minimum-recall .90 --maximum-forwarded 180; then
  echo "SCREENING_GATE=PASS"
else
  echo "SCREENING_GATE=FAIL_OR_INCOMPLETE"
fi
