#!/bin/bash
#SBATCH --job-name=edge-v2-eval
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:05:00
#SBATCH --output=logs/edge-v2-eval-%j.out
#SBATCH --error=logs/edge-v2-eval-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
ROOT="$P/output/existence_prompt_v2_pilot"
cd "$P"

"$P/.venv_qwen/bin/python" -m evidence_graph.evaluate_existence_prompt_v2_pilot \
  --tasks "$ROOT/shared/gw150914_detection/blind_tasks.jsonl" \
  --predictions \
    "$ROOT/Qwen3.5-35B-A3B/gw150914_detection/shard_0/predictions.jsonl" \
    "$ROOT/Qwen3.5-35B-A3B/gw150914_detection/shard_1/predictions.jsonl" \
  --ground-truth "$P/evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl" \
  --v1-diagnostics "$P/output/freeform_edge_existence/Qwen3.5-35B-A3B/gw150914_detection/evaluation_retry/diagnostics.jsonl" \
  --output "$ROOT/Qwen3.5-35B-A3B/gw150914_detection/evaluation"
