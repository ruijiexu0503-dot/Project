#!/bin/bash
#SBATCH --job-name=rename_pages_vlm
#SBATCH --partition=accelerated
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/rename_pages_vlm_%j.out
#SBATCH --error=logs/rename_pages_vlm_%j.err

set -euo pipefail

# Run from project root:
#   sbatch src_splitpage/run_rename_logical_pages_vlm.sbatch
#
# Optional single-document run:
#   sbatch --export=ALL,DOC_ID=CERNCourier2022NovDec-digitaledition src_splitpage/run_rename_logical_pages_vlm.sbatch
#
# Optional quick test:
#   sbatch --export=ALL,DOC_ID=CERNCourier2022NovDec-digitaledition,LIMIT=5 src_splitpage/run_rename_logical_pages_vlm.sbatch

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
IMAGE_ROOT_BASE="${IMAGE_ROOT_BASE:-output/split_render_result}"
OUT_ROOT="${OUT_ROOT:-output/numbered_pages}"
MODEL_PATH="${MODEL_PATH:-external/models/Qwen2.5-VL-7B-Instruct}"
SCRIPT_PATH="${SCRIPT_PATH:-src_splitpage/src/rename_logical_pages_with_vlm.py}"
VENV_DIR="${VENV_DIR:-.venv_vlm}"
DOC_ID="${DOC_ID:-}"
LIMIT="${LIMIT:-}"
MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-96}"
RESUME="${RESUME:-1}"
OVERWRITE="${OVERWRITE:-0}"

cd "$PROJECT_ROOT"

mkdir -p logs
mkdir -p "$OUT_ROOT"

echo "============================================================"
echo "[INFO] job id:        ${SLURM_JOB_ID:-NA}"
echo "[INFO] node:          $(hostname)"
echo "[INFO] project root:  $PROJECT_ROOT"
echo "[INFO] image root:    $IMAGE_ROOT_BASE"
echo "[INFO] out root:      $OUT_ROOT"
echo "[INFO] model path:    $MODEL_PATH"
echo "[INFO] script path:   $SCRIPT_PATH"
echo "[INFO] venv dir:      $VENV_DIR"
echo "[INFO] doc id:        ${DOC_ID:-ALL}"
echo "[INFO] limit:         ${LIMIT:-none}"
echo "[INFO] resume:        $RESUME"
echo "[INFO] overwrite:     $OVERWRITE"
echo "============================================================"

if [[ ! -d "$IMAGE_ROOT_BASE" ]]; then
  echo "[ERROR] IMAGE_ROOT_BASE not found: $IMAGE_ROOT_BASE"
  exit 1
fi

if [[ ! -d "$MODEL_PATH" ]]; then
  echo "[ERROR] MODEL_PATH not found: $MODEL_PATH"
  exit 1
fi

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "[ERROR] missing script: $SCRIPT_PATH"
  exit 1
fi

if [[ ! -f "$VENV_DIR/bin/activate" ]]; then
  echo "[ERROR] virtualenv activate script not found: $VENV_DIR/bin/activate"
  exit 1
fi

source "$VENV_DIR/bin/activate"

python - <<'PY'
import sys
import torch
import transformers
print("[INFO] python:", sys.executable)
print("[INFO] torch:", torch.__version__)
print("[INFO] transformers:", transformers.__version__)
print("[INFO] cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("[INFO] cuda device:", torch.cuda.get_device_name(0))
PY

DOCS=()

if [[ -n "$DOC_ID" ]]; then
  DOCS+=("$DOC_ID")
else
  while IFS= read -r -d '' d; do
    DOCS+=("$(basename "$d")")
  done < <(find "$IMAGE_ROOT_BASE" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
fi

if [[ "${#DOCS[@]}" -eq 0 ]]; then
  echo "[ERROR] no document folders found in: $IMAGE_ROOT_BASE"
  exit 1
fi

echo "[INFO] number of docs: ${#DOCS[@]}"
printf "  - %s\n" "${DOCS[@]}"
echo ""

DONE_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0

for CURRENT_DOC_ID in "${DOCS[@]}"; do
  IMAGE_DIR="${IMAGE_ROOT_BASE}/${CURRENT_DOC_ID}/pages"
  DOC_OUT_DIR="${OUT_ROOT}/${CURRENT_DOC_ID}"
  RENAME_LOG="${DOC_OUT_DIR}/rename_log.tsv"

  echo "============================================================"
  echo "[INFO] processing doc: $CURRENT_DOC_ID"
  echo "[INFO] image dir: $IMAGE_DIR"
  echo "[INFO] out dir:   $DOC_OUT_DIR"
  echo "============================================================"

  if [[ ! -d "$IMAGE_DIR" ]]; then
    echo "[WARN] skip, image pages dir missing: $IMAGE_DIR"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi

  if [[ -f "$RENAME_LOG" && "$OVERWRITE" != "1" ]]; then
    echo "[INFO] rename log already exists, skipping: $RENAME_LOG"
    echo "[INFO] set OVERWRITE=1 to rerun."
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi

  mkdir -p "$DOC_OUT_DIR"

  CMD=(
    python "$SCRIPT_PATH"
    --image-dir "$IMAGE_DIR"
    --model-path "$MODEL_PATH"
    --out-dir "$DOC_OUT_DIR"
    --max-new-tokens "$MAX_NEW_TOKENS"
  )

  if [[ "$RESUME" == "1" ]]; then
    CMD+=(--resume)
  fi

  if [[ -n "$LIMIT" ]]; then
    CMD+=(--limit "$LIMIT")
  fi

  set +e
  "${CMD[@]}"
  STATUS=$?
  set -e

  if [[ "$STATUS" -ne 0 ]]; then
    echo "[ERROR] failed doc: $CURRENT_DOC_ID"
    echo "$CURRENT_DOC_ID" >> "${OUT_ROOT}/failed_rename_docs.txt"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi

  echo "[OK] finished doc: $CURRENT_DOC_ID"
  DONE_COUNT=$((DONE_COUNT + 1))

  python - <<'PY'
import gc
gc.collect()
try:
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
except Exception:
    pass
PY
done

echo ""
echo "============================================================"
echo "[DONE] logical page rename jobs finished"
echo "[INFO] done:   $DONE_COUNT"
echo "[INFO] skip:   $SKIP_COUNT"
echo "[INFO] failed: $FAIL_COUNT"
echo "[INFO] output root: $OUT_ROOT"
echo "============================================================"
