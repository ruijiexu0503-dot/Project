#!/bin/bash
#SBATCH --job-name=other-magazines
#SBATCH --account=hk-project-p0025545
#SBATCH --partition=dev_cpuonly
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=logs/other-magazines-%j.out
#SBATCH --error=logs/other-magazines-%j.err

set -euo pipefail
P="/home/hk-project-p0025545/dv3352/Project/EvidenceNet"
BGE="/hkfs/home/project/hk-project-p0025545/dv3352/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"
ALIGNED="$P/../parsing/output/hybrid_deepseek_layout_split_render/aligned_json"
cd "$P"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONUNBUFFERED=1
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}" MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

for DOC in CERNCourier2022NovDec-digitaledition CERNCourier2026MayJun-digitaledition; do
  NODES="$P/output/evidence_graph/$DOC/evidence_nodes.jsonl"
  ROOT="$P/output/segmentation_comparisons/$DOC/current_pipeline"
  "$P/.venv_qwen/bin/python" -m evidence_graph.embeddings \
    --nodes "$NODES" --output "$ROOT/embedding_vectors.jsonl" \
    --metadata-output "$ROOT/embedding_metadata.json" --model-path "$BGE"
  "$P/.venv_qwen/bin/python" -m evidence_graph.page_aware_segmentation \
    --nodes "$NODES" --embeddings "$ROOT/embedding_vectors.jsonl" --aligned-dir "$ALIGNED/$DOC" \
    --output-dir "$ROOT/local" --label "$DOC-qwen2.5-bge-m3"
  "$P/.venv_qwen/bin/python" -m evidence_graph.title_context_validation \
    --nodes "$NODES" --node-embeddings "$ROOT/embedding_vectors.jsonl" --aligned-dir "$ALIGNED/$DOC" \
    --bge-model "$BGE" --output-dir "$ROOT/title_context"
  "$P/.venv_qwen/bin/python" -m evidence_graph.refine_segmentation_with_titles \
    --nodes "$NODES" --assignments "$ROOT/local/assignments.jsonl" \
    --diagnostics "$ROOT/local/boundary_diagnostics.jsonl" --title-audit "$ROOT/title_context/title_context_audit.jsonl" \
    --output-dir "$ROOT/title_refined" --skip-reference-evaluation
  "$P/.venv_qwen/bin/python" -m evidence_graph.global_merge_refinement \
    --nodes "$NODES" --embeddings "$ROOT/embedding_vectors.jsonl" \
    --assignments "$ROOT/title_refined/assignments.jsonl" --diagnostics "$ROOT/local/boundary_diagnostics.jsonl" \
    --title-audit "$ROOT/title_context/title_context_audit.jsonl" --output-dir "$ROOT/global_merge" \
    --skip-reference-evaluation
done
