#!/usr/bin/env bash
# Parse the only accepted short-document candidate that has not yet run.
#SBATCH --job-name=short017-dolphin
#SBATCH --account=hk-project-p0021977
# This 32-page document fits safely within the one-hour dev-H100 window based
# on the completed short-corpus timings (32 pages: roughly 8--11 minutes of
# page inference, before model-loading overhead).
#SBATCH --partition=dev-gpu-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=DynamicEdgeGraph/datasets/real_documents_v1_20261113/incoming_short_pdf_candidates_20261117/pipeline_to_nodes_v1_20261117/logs/%x-%j.out
#SBATCH --error=DynamicEdgeGraph/datasets/real_documents_v1_20261113/incoming_short_pdf_candidates_20261117/pipeline_to_nodes_v1_20261117/logs/%x-%j.err

set -euo pipefail
cd "${SLURM_SUBMIT_DIR}"
source current/env.sh

ROOT=DynamicEdgeGraph/datasets/real_documents_v1_20261113/incoming_short_pdf_candidates_20261117
PIPELINE="$ROOT/pipeline_to_nodes_v1_20261117"
RAW_INDEX=16
mkdir -p "$PIPELINE/logs" "$PIPELINE/work" "$PIPELINE/parsed" "$PIPELINE/cache/huggingface" "$PIPELINE/runtime_manifests"

MANIFEST="$PIPELINE/runtime_manifests/manifest_${RAW_INDEX}.json"
DOC_ID=$(EvidenceNet/.venv_qwen/bin/python - "$ROOT/source_manifest.jsonl" "$ROOT/pdfs" "$RAW_INDEX" "$MANIFEST" <<'PY'
import json
import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
pdf_dir = Path(sys.argv[2])
raw_index = int(sys.argv[3])
target = Path(sys.argv[4])
records = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
accepted = [record for record in records if record["status"] == "ACCEPTED_20_TO_50_PAGES"]
if raw_index != 16 or len(accepted) != 17:
    raise SystemExit(f"short-document allowlist changed: index={raw_index}, accepted={len(accepted)}")
record = accepted[raw_index]
haystack = " ".join(str(record.get(key, "")) for key in ("filename", "title", "source_url")).lower()
if "nasa" in haystack or "spinoff" in haystack:
    raise SystemExit(f"NASA guard rejected short candidate: {record['filename']}")
slug = re.sub(r"[^a-z0-9]+", "_", Path(record["filename"]).stem.lower()).strip("_")
doc_id = f"short_{raw_index + 1:03d}_{slug}"
document = {
    "document_id": doc_id,
    "title": record["title"],
    "document_type": record["document_type"],
    "input_pdf": str((pdf_dir / record["filename"]).resolve()),
    "source_url": record["source_url"],
    "source_sha256": record["sha256"],
    "audit_pages": [],
}
target.write_text(json.dumps({"experiment": "short_public_documents_v1_20261117", "documents": [document]}, indent=2) + "\n")
print(doc_id)
PY
)

export HF_HOME="$PIPELINE/cache/huggingface"
export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True PYTHONUNBUFFERED=1 OMP_NUM_THREADS=8

echo "Parsing approved non-NASA short document ${DOC_ID}"
parsing/.venv_vlm/bin/python parsing/experiments/dolphin_v2_pilot/run_pdf_corpus.py \
  --manifest "$MANIFEST" \
  --model parsing/experiments/dolphin_v2_pilot/models/Dolphin-v2 \
  --work "$PIPELINE/work" \
  --output "$PIPELINE/parsed" \
  --document-id "$DOC_ID" \
  --resume --defer-publish --max-batch-size 2
