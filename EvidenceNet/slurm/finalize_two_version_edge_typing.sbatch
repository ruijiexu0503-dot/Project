#!/bin/bash
#SBATCH --job-name=finalize-edge-v2
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:05:00
#SBATCH --output=logs/finalize-edge-v2-%j.out
#SBATCH --error=logs/finalize-edge-v2-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
CANONICAL="$P/output/canonical_graph/gw150914_detection"
SHARED="$P/output/two_version_edge_typing/shared/gw150914_detection"
PROFILE="$P/output/existence_prompt_v2_pilot/Qwen3.5-35B-A3B/gw150914_detection"
FIXED="$P/output/two_version_edge_typing/version_b_fixed/Qwen3.5-35B-A3B/gw150914_detection"
GRAPH="$P/output/two_version_edge_graphs/gw150914_detection"
cd "$P"

"$P/.venv_qwen/bin/python" -m evidence_graph.build_two_version_edge_graphs \
  --document-id gw150914_detection \
  --nodes "$CANONICAL/evidence_nodes.jsonl" \
  --references "$CANONICAL/discourse_edges.jsonl" \
  --structural-edges "$CANONICAL/structural_edges.jsonl" \
  --tasks "$SHARED/blind_tasks.jsonl" \
  --profile-predictions "$PROFILE/shard_0/predictions.jsonl" "$PROFILE/shard_1/predictions.jsonl" \
  --fixed-predictions "$FIXED/shard_0/predictions.jsonl" "$FIXED/shard_1/predictions.jsonl" \
  --output "$GRAPH"

"$P/.venv_qwen/bin/python" -m evidence_graph.canonical_visualize \
  --doc-id gw150914_detection --config config/evidence_graph.yaml \
  --graph-root "$GRAPH/version_a_profile" \
  --output "$GRAPH/version_a_profile/gw150914_version_a_profile.html" \
  --title "GW150914 · Version A · Non-exclusive Semantic Profile"

"$P/.venv_qwen/bin/python" -m evidence_graph.canonical_visualize \
  --doc-id gw150914_detection --config config/evidence_graph.yaml \
  --graph-root "$GRAPH/version_b_fixed" \
  --output "$GRAPH/version_b_fixed/gw150914_version_b_fixed.html" \
  --title "GW150914 · Version B · Exclusive Fixed Semantic Types"

"$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_two_version_edge_typing \
  --tasks "$SHARED/blind_tasks.jsonl" \
  --profile-predictions "$PROFILE/shard_0/predictions.jsonl" "$PROFILE/shard_1/predictions.jsonl" \
  --fixed-predictions "$FIXED/shard_0/predictions.jsonl" "$FIXED/shard_1/predictions.jsonl" \
  --existence-ground-truth evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl \
  --typing-ground-truth evaluation/ground_truth/gw150914_detection/split_taxonomy_relation_ground_truth.jsonl \
  --output "$GRAPH/comparison"
