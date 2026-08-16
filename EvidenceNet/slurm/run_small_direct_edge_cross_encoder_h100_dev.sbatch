#!/bin/bash
#SBATCH --job-name=small-edge-xenc
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_accelerated-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=00:25:00
#SBATCH --output=logs/small-edge-xenc-%j.out
#SBATCH --error=logs/small-edge-xenc-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
MODEL="/home/hk-project-p0025545/dv3352/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
OUT="$P/output/small_direct_edge_cross_encoder/bge_m3"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1

"$P/.venv_qwen/bin/python" -m evidence_graph.train_small_direct_edge_cross_encoder \
  --model "$MODEL" \
  --gw-nodes output/canonical_graph/gw150914_detection/evidence_nodes.jsonl \
  --gw-ground-truth evaluation/ground_truth/gw150914_detection/all_pairs_ground_truth.jsonl \
  --detr-nodes output/canonical_graph/detr/evidence_nodes.jsonl \
  --detr-ground-truth evaluation/ground_truth/detr/taxonomy_free_strict_audit_v1/taxonomy_free_strict_audit_gt.jsonl \
  --a-tasks output/two_version_edge_typing/shared/gw150914_detection/blind_tasks.jsonl \
  --output "$OUT" --epochs 4 --batch-size 8 --eval-batch-size 16 \
  --max-length 512 --train-last-n-layers 4
