#!/usr/bin/env bash
# CPU template for frozen-vector HNSW/BM25/structural retrieval.  No account
# or partition is hard-coded; pass those at sbatch submission time.
#SBATCH --job-name=stage1-hnsw
#SBATCH --time=00:20:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
set -euo pipefail
CONFIG="${1:?pass a config path}"
ROOT="${SLURM_SUBMIT_DIR:-$PWD}"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/.venv-magazine-exp1/bin/python}"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.type_aware_eligibility --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.audit_inputs --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.retrieve_candidates --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.sweep_thresholds --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.evaluate --config "$CONFIG"
