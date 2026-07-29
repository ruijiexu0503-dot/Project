#!/bin/bash
#SBATCH --job-name=article_split_parse
#SBATCH --partition=cpuonly
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --output=logs/article_split_parse_%j.out
#SBATCH --error=logs/article_split_parse_%j.err

set -euo pipefail

# Run all documents:
#   sbatch src_splitpage/run_article_split_from_hybrid_parse.sbatch
#
# Run one document:
#   sbatch --export=ALL,DOC_ID=CERNCourier2022NovDec-digitaledition src_splitpage/run_article_split_from_hybrid_parse.sbatch

PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
ENRICHED_ROOT="${ENRICHED_ROOT:-output/hybrid_deepseek_layout_mvp/enriched_json}"
OUT_ROOT="${OUT_ROOT:-output/article_split_plans}"
SCRIPT_PATH="${SCRIPT_PATH:-src_splitpage/src/plan_article_splits_from_hybrid_parse.py}"
VENV_DIR="${VENV_DIR:-.venv}"
DOC_ID="${DOC_ID:-}"
OVERWRITE="${OVERWRITE:-0}"

cd "$PROJECT_ROOT"

mkdir -p logs
mkdir -p "$OUT_ROOT"

echo "============================================================"
echo "[INFO] job id:        ${SLURM_JOB_ID:-NA}"
echo "[INFO] node:          $(hostname)"
echo "[INFO] project root:  $PROJECT_ROOT"
echo "[INFO] enriched root: $ENRICHED_ROOT"
echo "[INFO] out root:      $OUT_ROOT"
echo "[INFO] script path:   $SCRIPT_PATH"
echo "[INFO] venv dir:      $VENV_DIR"
echo "[INFO] doc id:        ${DOC_ID:-ALL}"
echo "[INFO] overwrite:     $OVERWRITE"
echo "============================================================"

if [[ ! -d "$ENRICHED_ROOT" ]]; then
  echo "[ERROR] ENRICHED_ROOT not found: $ENRICHED_ROOT"
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

DOCS=()
if [[ -n "$DOC_ID" ]]; then
  DOCS+=("$DOC_ID")
else
  while IFS= read -r -d '' d; do
    DOCS+=("$(basename "$d")")
  done < <(find "$ENRICHED_ROOT" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
fi

if [[ "${#DOCS[@]}" -eq 0 ]]; then
  echo "[ERROR] no document folders found in: $ENRICHED_ROOT"
  exit 1
fi

DONE_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0

for CURRENT_DOC_ID in "${DOCS[@]}"; do
  ENRICHED_DIR="${ENRICHED_ROOT}/${CURRENT_DOC_ID}"
  OUT_JSON="${OUT_ROOT}/${CURRENT_DOC_ID}/article_split_plan.json"

  echo "============================================================"
  echo "[INFO] processing doc: $CURRENT_DOC_ID"
  echo "[INFO] enriched dir: $ENRICHED_DIR"
  echo "[INFO] out json:     $OUT_JSON"
  echo "============================================================"

  if [[ ! -d "$ENRICHED_DIR" ]]; then
    echo "[WARN] skip, enriched dir missing: $ENRICHED_DIR"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi

  if [[ -f "$OUT_JSON" && "$OVERWRITE" != "1" ]]; then
    echo "[INFO] output already exists, skipping: $OUT_JSON"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi

  mkdir -p "$(dirname "$OUT_JSON")"

  set +e
  python "$SCRIPT_PATH" \
    --doc-id "$CURRENT_DOC_ID" \
    --enriched-json-dir "$ENRICHED_DIR" \
    --out "$OUT_JSON"
  STATUS=$?
  set -e

  if [[ "$STATUS" -ne 0 ]]; then
    echo "[ERROR] failed doc: $CURRENT_DOC_ID"
    echo "$CURRENT_DOC_ID" >> "${OUT_ROOT}/failed_article_split_docs.txt"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi

  echo "[OK] finished doc: $CURRENT_DOC_ID"
  DONE_COUNT=$((DONE_COUNT + 1))
done

echo ""
echo "============================================================"
echo "[DONE] article split planning finished"
echo "[INFO] done:   $DONE_COUNT"
echo "[INFO] skip:   $SKIP_COUNT"
echo "[INFO] failed: $FAIL_COUNT"
echo "[INFO] output root: $OUT_ROOT"
echo "============================================================"
