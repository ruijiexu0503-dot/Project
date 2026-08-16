#!/bin/bash
#SBATCH --job-name=finalize-small-edge
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:05:00
#SBATCH --output=logs/finalize-small-edge-%j.out
#SBATCH --error=logs/finalize-small-edge-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
TASKS="$P/output/two_version_edge_typing/shared/gw150914_detection/blind_tasks.jsonl"
PRED="$P/output/small_direct_edge_cross_encoder/bge_m3/gw_a_edge_predictions.jsonl"
A_GRAPH="$P/output/two_version_edge_graphs/gw150914_detection/version_a_profile"
GRAPH="$P/output/small_direct_edge_precision_graph/gw150914_detection"
cd "$P"

"$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_strict_direct_edge_validation \
  --tasks "$TASKS" --predictions "$PRED" \
  --ground-truth evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl \
  --output "$GRAPH/evaluation"

"$P/.venv_qwen/bin/python" -m evidence_graph.build_strict_precision_graph \
  --document-id gw150914_detection --a-graph "$A_GRAPH" --predictions "$PRED" \
  --output "$GRAPH"

"$P/.venv_qwen/bin/python" -m evidence_graph.canonical_visualize \
  --doc-id gw150914_detection --config config/evidence_graph.yaml \
  --graph-root "$GRAPH" --output "$GRAPH/gw150914_small_model_precision_graph.html" \
  --title "GW150914 · BGE-M3 Small-Model Precision Graph"
