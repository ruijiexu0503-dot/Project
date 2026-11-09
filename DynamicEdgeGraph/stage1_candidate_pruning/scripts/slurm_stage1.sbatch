#!/usr/bin/env bash
# Configure --account/--partition/--gres for the current HoReKa2 association.
# This template intentionally contains no guessed project or queue.
#SBATCH --job-name=stage1-pruning
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
set -euo pipefail
CONFIG="${1:?pass a config path}"
PYTHON="${PYTHON:-$PWD/.venv-magazine-exp1/bin/python}"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.type_aware_eligibility --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.audit_inputs --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.retrieve_candidates --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.sweep_thresholds --config "$CONFIG"
"$PYTHON" -m DynamicEdgeGraph.stage1_candidate_pruning.src.evaluate --config "$CONFIG"
