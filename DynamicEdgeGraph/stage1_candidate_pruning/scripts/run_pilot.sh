#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
CONFIG="${1:-DynamicEdgeGraph/stage1_candidate_pruning/configs/pilot.yaml}"
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.type_aware_eligibility --config "$CONFIG"
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.audit_inputs --config "$CONFIG"
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.retrieve_candidates --config "$CONFIG"
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.sweep_thresholds --config "$CONFIG"
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.evaluate --config "$CONFIG"
