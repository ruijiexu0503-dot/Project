#!/bin/bash
#SBATCH --job-name=doc_profile_all
#SBATCH --partition=accelerated-h100
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=logs/doc_profile_all_%j.out
#SBATCH --error=logs/doc_profile_all_%j.err

set -euo pipefail

# Run from project root:
#   sbatch src/run_doc_profile_all.sbatch
#
# This is NOT an array job.
# It scans all document folders and processes them one by one on one GPU.

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"

MD_ROOT_BASE="${MD_ROOT_BASE:-output/hybrid_deepseek_layout_mvp/export_md_by_page}"
IMAGE_ROOT_BASE="${IMAGE_ROOT_BASE:-output/render_result}"
OUT_ROOT="${OUT_ROOT:-output/doc_profiles}"
MODEL_PATH="${MODEL_PATH:-external/models/Qwen2.5-VL-7B-Instruct}"

FRONT_PAGES="${FRONT_PAGES:-3}"
BACK_PAGES="${BACK_PAGES:-2}"
MAX_CHARS_PER_PAGE="${MAX_CHARS_PER_PAGE:-2500}"
MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-1200}"

cd "$PROJECT_ROOT"

mkdir -p logs
mkdir -p "$OUT_ROOT"

echo "============================================================"
echo "[INFO] job id:       ${SLURM_JOB_ID:-NA}"
echo "[INFO] node:         $(hostname)"
echo "[INFO] project root: $PROJECT_ROOT"
echo "[INFO] md base:      $MD_ROOT_BASE"
echo "[INFO] image base:   $IMAGE_ROOT_BASE"
echo "[INFO] out root:     $OUT_ROOT"
echo "[INFO] model path:   $MODEL_PATH"
echo "============================================================"

if [[ ! -d "$MD_ROOT_BASE" ]]; then
  echo "[ERROR] MD_ROOT_BASE not found: $MD_ROOT_BASE"
  exit 1
fi

if [[ ! -d "$IMAGE_ROOT_BASE" ]]; then
  echo "[ERROR] IMAGE_ROOT_BASE not found: $IMAGE_ROOT_BASE"
  exit 1
fi

if [[ ! -f "src/classify_doc_with_vlm.py" ]]; then
  echo "[ERROR] missing script: src/classify_doc_with_vlm.py"
  echo "Please copy classify_doc_with_vlm_fixed.py to src/classify_doc_with_vlm.py first."
  exit 1
fi

source .venv_vlm/bin/activate

python - <<'PY'
import torch
print("[INFO] torch:", torch.__version__)
print("[INFO] cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("[INFO] cuda device:", torch.cuda.get_device_name(0))
PY

echo ""
echo "[INFO] scanning documents..."
echo ""

DOCS=()

while IFS= read -r -d '' d; do
  doc_id="$(basename "$d")"
  md_root="${MD_ROOT_BASE}/${doc_id}"
  image_root="${IMAGE_ROOT_BASE}/${doc_id}"

  if [[ -d "$image_root" ]]; then
    DOCS+=("$doc_id")
  else
    echo "[WARN] skip $doc_id because image dir is missing: $image_root"
  fi
done < <(find "$MD_ROOT_BASE" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)

N="${#DOCS[@]}"

if [[ "$N" -eq 0 ]]; then
  echo "[ERROR] no documents found."
  exit 1
fi

echo "[INFO] number of docs: $N"
printf "  - %s\n" "${DOCS[@]}"
echo ""

DONE_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0

for DOC_ID in "${DOCS[@]}"; do
  MD_ROOT="${MD_ROOT_BASE}/${DOC_ID}"
  IMAGE_ROOT="${IMAGE_ROOT_BASE}/${DOC_ID}"
  DOC_OUT_DIR="${OUT_ROOT}/${DOC_ID}"
  OUT_JSON="${DOC_OUT_DIR}/doc_profile.json"
  PROMPT_TXT="${DOC_OUT_DIR}/prompt.txt"

  echo "============================================================"
  echo "[INFO] processing doc: $DOC_ID"
  echo "[INFO] md root:    $MD_ROOT"
  echo "[INFO] image root: $IMAGE_ROOT"
  echo "[INFO] out json:   $OUT_JSON"
  echo "============================================================"

  mkdir -p "$DOC_OUT_DIR"

  if [[ -f "$OUT_JSON" ]]; then
    echo "[INFO] output already exists, skipping: $OUT_JSON"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi

  set +e

  python src/classify_doc_with_vlm.py \
    --doc-id "$DOC_ID" \
    --image-root "$IMAGE_ROOT" \
    --md-root "$MD_ROOT" \
    --model-path "$MODEL_PATH" \
    --out "$OUT_JSON" \
    --front-pages "$FRONT_PAGES" \
    --back-pages "$BACK_PAGES" \
    --max-chars-per-page "$MAX_CHARS_PER_PAGE" \
    --max-new-tokens "$MAX_NEW_TOKENS" \
    --save-prompt "$PROMPT_TXT"

  STATUS=$?

  set -e

  if [[ "$STATUS" -ne 0 ]]; then
    echo "[ERROR] failed doc: $DOC_ID"
    echo "$DOC_ID" >> "${OUT_ROOT}/failed_docs.txt"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi

  echo "[OK] finished doc: $DOC_ID"
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
echo "[DONE] all document profile jobs finished"
echo "[INFO] done:   $DONE_COUNT"
echo "[INFO] skip:   $SKIP_COUNT"
echo "[INFO] failed: $FAIL_COUNT"
echo "[INFO] output root: $OUT_ROOT"
echo "============================================================"

echo ""
echo "[INFO] quick summary:"
find "$OUT_ROOT" -mindepth 2 -maxdepth 2 -name "doc_profile.json" | sort | while read -r f; do
  doc_id="$(basename "$(dirname "$f")")"
  echo "----- $doc_id -----"
  jq -r '"doc_type=\(.doc_type) confidence=\(.confidence) strategy=\(.segmentation_strategy) node=\(.node_strategy)"' "$f" 2>/dev/null || true
done
EOF
