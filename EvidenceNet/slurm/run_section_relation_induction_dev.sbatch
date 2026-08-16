#!/bin/bash
#SBATCH --job-name=paper-group-rel
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated
#SBATCH --gres=gpu:2
#SBATCH --cpus-per-task=16
#SBATCH --mem=192G
#SBATCH --time=01:00:00
#SBATCH --output=logs/paper-group-rel-%j.out
#SBATCH --error=logs/paper-group-rel-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="$P/../external/models/Qwen3.5-35B-A3B"
SOURCE="$P/output/scientific_body_semantics/shared_candidates/gw150914_detection"
RESULT="$P/output/scientific_grouped_relations/Qwen3.5-35B-A3B/gw150914_detection"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
"$P/.venv_qwen/bin/python" -m evidence_graph.section_relation_induction \
  --model "$MODEL" --source "$SOURCE" --output "$RESULT" \
  --maximum-relations-per-group 16 --maximum-runtime-minutes 45
