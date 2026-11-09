#!/bin/bash
#SBATCH --job-name=vldocir-freeze-dev
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=00:55:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_freeze_dev_%A_%a.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_freeze_dev_%A_%a.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
test -x "$PYTHON"
: "${ROUTE:?submit with --export=ALL,ROUTE=...}"
: "${SHARD_SIZE:?submit with --export=ALL,SHARD_SIZE=...}"
START_SHARD="${START_SHARD:-0}"
SHARDS_PER_JOB="${SHARDS_PER_JOB:-5}"
TOTAL=104318
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107
for OFFSET in $(seq 0 $((SHARDS_PER_JOB - 1))); do
  INDEX=$((START_SHARD + OFFSET))
  START=$((INDEX * SHARD_SIZE))
  if [ "$START" -ge "$TOTAL" ]; then break; fi
  END=$((START + SHARD_SIZE))
  if [ "$END" -gt "$TOTAL" ]; then END=$TOTAL; fi
  "$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_freeze_embeddings \
    --views "$RUN/retrieval_views.jsonl" --output "$RUN/models" --route "$ROUTE" --device cuda --start "$START" --end "$END"
done
