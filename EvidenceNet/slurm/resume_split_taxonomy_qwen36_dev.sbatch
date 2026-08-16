#!/bin/bash
#SBATCH --job-name=split-tax-q36-resume
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated,accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=00:05:00
#SBATCH --output=logs/split-tax-q36-resume-%j.out
#SBATCH --error=logs/split-tax-q36-resume-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.6-35B-A3B"
RESULT="$P/output/split_taxonomy_relation_typing/Qwen3.6-35B-A3B/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.run_split_taxonomy_relation_typing \
  --model "$MODEL" --output "$RESULT" --generation-tokens 220 \
  --maximum-runtime-minutes 2.5
"$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_split_taxonomy \
  --predictions "$RESULT/predictions.jsonl"
