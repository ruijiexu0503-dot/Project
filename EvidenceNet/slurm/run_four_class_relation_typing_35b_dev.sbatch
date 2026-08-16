#!/bin/bash
#SBATCH --job-name=four-type-35b
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:11:20
#SBATCH --output=logs/four-type-35b-%j.out
#SBATCH --error=logs/four-type-35b-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

for MODEL_NAME in Qwen3.5-35B-A3B Qwen3.6-35B-A3B; do
  MODEL="$P/../external/models/$MODEL_NAME"
  RESULT="$P/output/four_class_relation_typing/$MODEL_NAME/gw150914_detection"
  "$P/.venv_qwen/bin/python" -m evidence_graph.run_four_class_relation_typing \
    --model "$MODEL" --output "$RESULT" --generation-tokens 120 \
    --maximum-runtime-minutes 4.5
  if "$P/.venv_qwen/bin/python" -c \
    "import json; from pathlib import Path; raise SystemExit(0 if json.loads(Path('$RESULT/status.json').read_text()).get('complete') else 1)"; then
    "$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_four_class_relation_typing \
      --predictions "$RESULT/predictions.jsonl"
  else
    echo "$MODEL_NAME CHECKPOINT_INCOMPLETE"
  fi
done
