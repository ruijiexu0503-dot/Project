#!/bin/bash
#SBATCH --job-name=parse_layout_split
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/parse_layout_split_%j.out
#SBATCH --error=logs/parse_layout_split_%j.err

set -euo pipefail

# Legacy orchestrator retained for compatibility.
# Preferred human-facing entrypoint:
#   sbatch pipeline_steps/step1_run_parsing_pipeline.sbatch
#
# Canonical execution order:
#   Step 1A -> DeepSeek OCR parsing
#   Step 1B -> PP-DocLayout detection
#   Step 1C -> Hybrid OCR/layout alignment
#   Step 1D -> Enrichment + page Markdown/crop export
#
# Run all split-rendered docs:
#   sbatch pipeline_steps/step1_run_parsing_pipeline.sbatch
#
# Run one doc:
#   sbatch --export=ALL,DOC_ID=CERNCourier2022NovDec-digitaledition pipeline_steps/step1_run_parsing_pipeline.sbatch
#
# Quick smoke test on first N pages after filtering:
#   sbatch --export=ALL,DOC_ID=CERNCourier2022NovDec-digitaledition,LIMIT=5 pipeline_steps/step1_run_parsing_pipeline.sbatch

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
SPLIT_RENDER_ROOT="${SPLIT_RENDER_ROOT:-output/split_render_result}"

# Staging roots. These are symlink trees derived from SPLIT_RENDER_ROOT.
STAGED_IMAGE_ROOT="${STAGED_IMAGE_ROOT:-output/split_render_result_page_dirs}"

# DeepSeek parser writes output as DEEPSEEK_ROOT/<doc_id>/page_XXXX.
DEEPSEEK_ROOT="${DEEPSEEK_ROOT:-output/deepseekocr2_split_render}"

LAYOUT_ROOT="${LAYOUT_ROOT:-output/layout_detection_split_render}"
LAYOUT_VIS_ROOT="${LAYOUT_VIS_ROOT:-output/layout_detection_split_render_vis}"

HYBRID_BASE="${HYBRID_BASE:-output/hybrid_deepseek_layout_split_render}"
ALIGNED_ROOT="${ALIGNED_ROOT:-${HYBRID_BASE}/aligned_json}"
DEBUG_VIS_ROOT="${DEBUG_VIS_ROOT:-${HYBRID_BASE}/debug_vis}"
ENRICHED_ROOT="${ENRICHED_ROOT:-${HYBRID_BASE}/enriched_json}"
EXPORT_MD_ROOT="${EXPORT_MD_ROOT:-${HYBRID_BASE}/export_md_by_page}"
CROP_ROOT="${CROP_ROOT:-${HYBRID_BASE}/visual_region_crops}"

PARSE_VENV_DIR="${PARSE_VENV_DIR:-.venv}"
LAYOUT_VENV_DIR="${LAYOUT_VENV_DIR:-.venv_layout}"
HYBRID_VENV_DIR="${HYBRID_VENV_DIR:-.venv}"

# Human-facing ordered wrappers. They delegate to the original implementation
# files so history/imports remain stable while the execution order is obvious.
DEEPSEEK_SCRIPT="${DEEPSEEK_SCRIPT:-pipeline_steps/step1_a_parsing_deepseek_ocr.py}"
LAYOUT_SCRIPT="${LAYOUT_SCRIPT:-pipeline_steps/step1_b_parsing_layout_detection.py}"
ALIGN_SCRIPT="${ALIGN_SCRIPT:-pipeline_steps/step1_c_parsing_hybrid_alignment.py}"
ENRICH_SCRIPT="${ENRICH_SCRIPT:-pipeline_steps/step1_d_parsing_enrich_export.py}"

DEEPSEEK_MODEL_NAME="${DEEPSEEK_MODEL_NAME:-deepseek-ai/DeepSeek-OCR-2}"
LAYOUT_MODEL_NAME="${LAYOUT_MODEL_NAME:-PP-DocLayout-L}"
LAYOUT_MODEL_DIR="${LAYOUT_MODEL_DIR:-external/models/PP-DocLayout-L}"
LAYOUT_DEVICE="${LAYOUT_DEVICE:-gpu:0}"

DOC_ID="${DOC_ID:-}"
LIMIT="${LIMIT:-}"
MAX_DOCS="${MAX_DOCS:-}"
OVERWRITE_STAGE="${OVERWRITE_STAGE:-1}"
RESUME="${RESUME:-1}"
MAKE_LAYOUT_VIS="${MAKE_LAYOUT_VIS:-1}"
MAKE_ALIGN_VIS="${MAKE_ALIGN_VIS:-1}"
MAKE_CROPS="${MAKE_CROPS:-1}"
ALLOW_EMPTY_BBOX="${ALLOW_EMPTY_BBOX:-1}"
NO_FLASH_ATTN="${NO_FLASH_ATTN:-0}"

cd "$PROJECT_ROOT"

mkdir -p logs

export PROJECT_ROOT SPLIT_RENDER_ROOT STAGED_IMAGE_ROOT
export DEEPSEEK_ROOT LAYOUT_ROOT LAYOUT_VIS_ROOT HYBRID_BASE
export ALIGNED_ROOT DEBUG_VIS_ROOT ENRICHED_ROOT EXPORT_MD_ROOT CROP_ROOT
export DOC_ID LIMIT MAX_DOCS OVERWRITE_STAGE RESUME

echo "============================================================"
echo "[INFO] job id:             ${SLURM_JOB_ID:-NA}"
echo "[INFO] node:               $(hostname)"
echo "[INFO] project root:       $PROJECT_ROOT"
echo "[INFO] split render root:  $SPLIT_RENDER_ROOT"
echo "[INFO] doc id:             ${DOC_ID:-ALL}"
echo "[INFO] limit:              ${LIMIT:-none}"
echo "[INFO] staged image root:  $STAGED_IMAGE_ROOT"
echo "[INFO] deepseek root:      $DEEPSEEK_ROOT"
echo "[INFO] layout root:        $LAYOUT_ROOT"
echo "[INFO] hybrid base:        $HYBRID_BASE"
echo "============================================================"

for required_path in "$SPLIT_RENDER_ROOT" "$DEEPSEEK_SCRIPT" "$LAYOUT_SCRIPT" "$ALIGN_SCRIPT" "$ENRICH_SCRIPT"; do
  if [[ ! -e "$required_path" ]]; then
    echo "[ERROR] required path not found: $required_path"
    exit 1
  fi
done

for venv_dir in "$PARSE_VENV_DIR" "$LAYOUT_VENV_DIR" "$HYBRID_VENV_DIR"; do
  if [[ ! -f "$venv_dir/bin/activate" ]]; then
    echo "[ERROR] virtualenv activate script not found: $venv_dir/bin/activate"
    exit 1
  fi
done

echo "[INFO] staging split-rendered pages..."
source "$HYBRID_VENV_DIR/bin/activate"
python - <<'PY'
import os
import re
import shutil
from pathlib import Path

split_render_root = Path(os.environ["SPLIT_RENDER_ROOT"])
staged_image_root = Path(os.environ["STAGED_IMAGE_ROOT"])
doc_filter = os.environ.get("DOC_ID") or ""
limit = os.environ.get("LIMIT") or ""
max_docs = os.environ.get("MAX_DOCS") or ""
overwrite_stage = os.environ.get("OVERWRITE_STAGE", "1") == "1"

if overwrite_stage:
    if staged_image_root.exists():
        shutil.rmtree(staged_image_root)

staged_image_root.mkdir(parents=True, exist_ok=True)

doc_dirs = sorted(p for p in split_render_root.iterdir() if p.is_dir())
if doc_filter:
    doc_dirs = [p for p in doc_dirs if p.name == doc_filter]
if max_docs:
    doc_dirs = doc_dirs[: int(max_docs)]

staged_count = 0

for doc_dir in doc_dirs:
    pages_dir = doc_dir / "pages"
    if not pages_dir.is_dir():
        print(f"[WARN] skip missing pages dir: {pages_dir}")
        continue

    images = sorted(p for p in pages_dir.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})
    for image in images:
        m = re.search(r"page[_-]?(\d+)", image.stem, flags=re.IGNORECASE)
        if not m:
            print(f"[WARN] skip page image with no page number: {image}")
            continue

        page_num = int(m.group(1))
        page_name = f"page_{page_num:04d}"
        doc_id = doc_dir.name

        staged_page_dir = staged_image_root / doc_id / page_name
        staged_page_dir.mkdir(parents=True, exist_ok=True)
        staged_page_image = staged_page_dir / "page.png"
        if staged_page_image.exists() or staged_page_image.is_symlink():
            staged_page_image.unlink()
        staged_page_image.symlink_to(image.resolve())

        staged_count += 1

        if limit and staged_count >= int(limit):
            break
    if limit and staged_count >= int(limit):
        break

print(f"[INFO] staged page images: {staged_count}")
if not staged_count:
    raise SystemExit("[ERROR] no split-rendered page images were staged")
PY
deactivate

echo "============================================================"
echo "[STEP 1A] DeepSeekOCR2 parsing"
echo "============================================================"
source "$PARSE_VENV_DIR/bin/activate"
python - <<'PY'
import torch
print("[INFO] torch:", torch.__version__)
print("[INFO] cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("[INFO] cuda device:", torch.cuda.get_device_name(0))
PY

PARSE_CMD=(
  python "$DEEPSEEK_SCRIPT"
  --incoming "$SPLIT_RENDER_ROOT"
  --output "$DEEPSEEK_ROOT"
  --render-result-input
  --model-name "$DEEPSEEK_MODEL_NAME"
)

if [[ -n "$DOC_ID" ]]; then
  PARSE_CMD+=(--doc-id "$DOC_ID")
fi
if [[ -n "$LIMIT" ]]; then
  PARSE_CMD+=(--max-pages-total "$LIMIT")
fi
if [[ -n "$MAX_DOCS" ]]; then
  PARSE_CMD+=(--max-docs "$MAX_DOCS")
fi
if [[ "$RESUME" == "1" ]]; then
  PARSE_CMD+=(--skip-existing)
fi
if [[ "$ALLOW_EMPTY_BBOX" == "1" ]]; then
  PARSE_CMD+=(--allow-empty-bbox)
fi
if [[ "$NO_FLASH_ATTN" == "1" ]]; then
  PARSE_CMD+=(--no-flash-attn)
fi

"${PARSE_CMD[@]}"
deactivate

echo "============================================================"
echo "[STEP 1B] PP-DocLayout detection"
echo "============================================================"
source "$LAYOUT_VENV_DIR/bin/activate"

LAYOUT_CMD=(
  python "$LAYOUT_SCRIPT"
  --image-root "$STAGED_IMAGE_ROOT"
  --output-root "$LAYOUT_ROOT"
  --model-name "$LAYOUT_MODEL_NAME"
  --device "$LAYOUT_DEVICE"
  --layout-nms
)

if [[ -n "$LAYOUT_MODEL_DIR" ]]; then
  LAYOUT_CMD+=(--model-dir "$LAYOUT_MODEL_DIR")
fi
if [[ "$MAKE_LAYOUT_VIS" == "1" ]]; then
  LAYOUT_CMD+=(--vis-root "$LAYOUT_VIS_ROOT")
fi
if [[ "$RESUME" == "1" ]]; then
  LAYOUT_CMD+=(--skip-existing)
fi

"${LAYOUT_CMD[@]}"
deactivate

echo "============================================================"
echo "[STEP 1C] Hybrid alignment"
echo "============================================================"
source "$HYBRID_VENV_DIR/bin/activate"

ALIGN_CMD=(
  python "$ALIGN_SCRIPT"
  --deepseek-root "$DEEPSEEK_ROOT"
  --layout-root "$LAYOUT_ROOT"
  --out-root "$ALIGNED_ROOT"
)

if [[ "$MAKE_ALIGN_VIS" == "1" ]]; then
  ALIGN_CMD+=(--vis-root "$DEBUG_VIS_ROOT")
else
  ALIGN_CMD+=(--vis-root "")
fi
if [[ -n "$DOC_ID" ]]; then
  ALIGN_CMD+=(--doc "$DOC_ID")
fi

"${ALIGN_CMD[@]}"

echo "============================================================"
echo "[STEP 1D] Enrich aligned JSON and export Markdown"
echo "============================================================"

ENRICH_CMD=(
  python "$ENRICH_SCRIPT"
  --input-root "$ALIGNED_ROOT"
  --out-json-root "$ENRICHED_ROOT"
  --out-md-root "$EXPORT_MD_ROOT"
  --crop-root "$CROP_ROOT"
)

if [[ -n "$DOC_ID" ]]; then
  ENRICH_CMD+=(--doc "$DOC_ID")
fi
if [[ "$MAKE_CROPS" != "1" ]]; then
  ENRICH_CMD+=(--no-crops)
fi

"${ENRICH_CMD[@]}"
deactivate

echo ""
echo "============================================================"
echo "[DONE] Step 1 parsing/layout pipeline finished"
echo "[INFO] staged images:    $STAGED_IMAGE_ROOT"
echo "[INFO] parser outputs:   $DEEPSEEK_ROOT"
echo "[INFO] layout JSON:      $LAYOUT_ROOT"
echo "[INFO] aligned JSON:     $ALIGNED_ROOT"
echo "[INFO] enriched JSON:    $ENRICHED_ROOT"
echo "[INFO] page Markdown:    $EXPORT_MD_ROOT"
echo "============================================================"
