#!/bin/bash
#SBATCH --job-name=mag-segment-cpu
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_cpuonly
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --output=logs/mag-segment-cpu-%j.out
#SBATCH --error=logs/mag-segment-cpu-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
R="$P/output/qwen35_semantic_graphs/Qwen3.5-35B-A3B/evidence_graph/CERNCourier2025JanFeb-digitaledition"
cd "$P"
"$P/.venv_qwen/bin/python" -m evidence_graph.page_aware_segmentation \
  --nodes "$R/evidence_nodes.jsonl" --embeddings "$R/semantic_full_embedding_vectors.jsonl" \
  --aligned-dir "$P/../parsing/output/hybrid_deepseek_layout_split_render/aligned_json/CERNCourier2025JanFeb-digitaledition" \
  --output-dir output/segmentation_comparisons/CERNCourier2025JanFeb-digitaledition/qwen35_bge_m3 \
  --label qwen3.5_bge_m3
