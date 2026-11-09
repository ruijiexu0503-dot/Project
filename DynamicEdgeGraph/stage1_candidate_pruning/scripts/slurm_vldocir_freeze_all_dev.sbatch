#!/bin/bash
#SBATCH --job-name=vldocir-freeze-all
#SBATCH --account=hk-project-p0021977
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --time=00:55:00
#SBATCH --output=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_freeze_all_%j.out
#SBATCH --error=DynamicEdgeGraph/stage1_candidate_pruning/logs/vldocir_freeze_all_%j.err
set -euo pipefail
cd /hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
PYTHON=/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/.venv-magazine-exp1/bin/python
RUN=DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-representative-frozen-embeddings-20261107
TOTAL=104318

# Existing shards are detected by the Python worker and skipped without loading a model.
# The individual slices remain independently durable if this developer job is interrupted.
run_route() {
  ROUTE="$1"; SIZE="$2"; COUNT="$3"
  for INDEX in $(seq 0 "$COUNT"); do
    START=$((INDEX * SIZE))
    if [ "$START" -ge "$TOTAL" ]; then break; fi
    END=$((START + SIZE)); if [ "$END" -gt "$TOTAL" ]; then END=$TOTAL; fi
    echo "route=$ROUTE range=[$START,$END)"
    "$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.vldocir_freeze_embeddings \
      --views "$RUN/retrieval_views.jsonl" --output "$RUN/models" --route "$ROUTE" --device cuda --start "$START" --end "$END"
  done
}
run_route qwen3_0_6b_dense 10000 10
run_route gte_qwen2_1_5b_dense 5000 20
run_route bge_en_icl_dense 10000 10
run_route mxbai_dense 10000 10
run_route gte_large_dense 10000 10
