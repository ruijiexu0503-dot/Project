#!/bin/bash
#SBATCH --job-name=controlled-2x2
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_cpuonly
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=logs/controlled-2x2-%j.out
#SBATCH --error=logs/controlled-2x2-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
BGE="/hkfs/home/project/hk-project-p0025545/dv3352/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
DOC="CERNCourier2025JanFeb-digitaledition"
Q35="$P/output/qwen35_semantic_graphs/Qwen3.5-35B-A3B/evidence_graph/$DOC/evidence_nodes.jsonl"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}" MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
"$P/.venv_qwen/bin/python" -m evidence_graph.controlled_segmentation_matrix \
  --qwen25-nodes "$P/output/evidence_graph/$DOC/evidence_nodes.jsonl" \
  --qwen35-nodes "$Q35" \
  --bge-model "$BGE" \
  --aligned-dir "$P/../parsing/output/hybrid_deepseek_layout_split_render/aligned_json/$DOC" \
  --output-dir "$P/output/segmentation_comparisons/$DOC/controlled_2x2"
