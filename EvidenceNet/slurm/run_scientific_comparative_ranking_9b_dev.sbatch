#!/bin/bash
#SBATCH --job-name=paper-rank-9b
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=12
#SBATCH --mem=96G
#SBATCH --time=00:50:00
#SBATCH --output=logs/paper-rank-9b-%j.out
#SBATCH --error=logs/paper-rank-9b-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-9B"
SCREENING="$P/output/scientific_body_cascade/Qwen3.5-9B-adaptive/gw150914_detection"
RESULT="$P/output/scientific_comparative_ranking/Qwen3.5-9B/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.rank_scientific_relations \
  --screening "$SCREENING" --model "$MODEL" --output "$RESULT" \
  --maximum-runtime-minutes 42 --generation-tokens 700

if "$P/.venv_qwen/bin/python" -c \
  "import json; from pathlib import Path; raise SystemExit(0 if json.loads(Path('$RESULT/status.json').read_text()).get('complete') else 1)"; then
  "$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_scientific_ranking \
    --screening "$SCREENING" --ranking "$RESULT"
else
  echo "RANKING_CHECKPOINT_INCOMPLETE"
fi
