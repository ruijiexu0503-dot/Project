#!/bin/bash
#SBATCH --job-name=finalize-strict-edge
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:05:00
#SBATCH --output=logs/finalize-strict-edge-%j.out
#SBATCH --error=logs/finalize-strict-edge-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
TASKS="$P/output/two_version_edge_typing/shared/gw150914_detection/blind_tasks.jsonl"
PRED="$P/output/strict_direct_edge_validation/Qwen3.5-35B-A3B/gw150914_detection"
A_GRAPH="$P/output/two_version_edge_graphs/gw150914_detection/version_a_profile"
GRAPH="$P/output/strict_precision_graph/gw150914_detection"
cd "$P"

"$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_strict_direct_edge_validation \
  --tasks "$TASKS" \
  --predictions "$PRED/shard_0/predictions.jsonl" "$PRED/shard_1/predictions.jsonl" \
  --ground-truth evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl \
  --output "$GRAPH/evaluation"

"$P/.venv_qwen/bin/python" -m evidence_graph.build_strict_precision_graph \
  --document-id gw150914_detection --a-graph "$A_GRAPH" \
  --predictions "$PRED/shard_0/predictions.jsonl" "$PRED/shard_1/predictions.jsonl" \
  --output "$GRAPH"

"$P/.venv_qwen/bin/python" -m evidence_graph.canonical_visualize \
  --doc-id gw150914_detection --config config/evidence_graph.yaml \
  --graph-root "$GRAPH" --output "$GRAPH/gw150914_strict_precision_graph.html" \
  --title "GW150914 · Strict Direct-Edge Precision Graph"
