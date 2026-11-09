#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.type_aware_eligibility --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.audit_inputs --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.retrieve_candidates --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.sweep_thresholds --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.evaluate --config DynamicEdgeGraph/stage1_candidate_pruning/configs/smoke.yaml
