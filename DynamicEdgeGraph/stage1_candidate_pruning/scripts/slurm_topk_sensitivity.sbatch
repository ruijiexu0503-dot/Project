#!/usr/bin/env bash
# Array job for genuine bounded-ANN Top-K runs. Pass account/partition at sbatch.
#SBATCH --job-name=stage1-topk
#SBATCH --time=00:20:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --array=0-3
set -euo pipefail
ROOT="${SLURM_SUBMIT_DIR:-$PWD}"; cd "$ROOT"
K_VALUES=(20 50 200 500)
export STAGE1_TOP_K="${K_VALUES[$SLURM_ARRAY_TASK_ID]}"
export STAGE1_RUN_ID="pilot-20261106-hnsw-k${STAGE1_TOP_K}"
PYTHON="${PYTHON:-$ROOT/.venv-magazine-exp1/bin/python}"
CONFIG="DynamicEdgeGraph/stage1_candidate_pruning/configs/pilot.yaml"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.type_aware_eligibility --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.audit_inputs --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.retrieve_candidates --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.sweep_thresholds --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.evaluate --config "$CONFIG"
