#!/bin/bash
#SBATCH --job-name=paper-hi-recall
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=12:00:00
#SBATCH --output=logs/paper-hi-recall-%j.out
#SBATCH --error=logs/paper-hi-recall-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
SOURCE="$P/output/scientific_body_high_recall/shared_candidates/gw150914_detection"
RESULT="$P/output/scientific_body_high_recall/Qwen3.5-35B-A3B/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.prepare_scientific_high_recall
"$P/.venv_qwen/bin/python" -m evidence_graph.verify_scientific_body_coarse \
  --model "$MODEL" --source "$SOURCE" --output "$RESULT" --chunk-size 5
"$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_scientific_staged \
  --source "$SOURCE" --result "$RESULT"
