#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  src_splitpage/run_split_pipeline.sh [options]

Runs these steps:
  1. detect_document_split_mode.py
  2. apply_document_split.py
  3. optionally render every final document page-by-page

Options:
  --input-dir DIR        Folder containing input PDF files.
                         Default: data/incoming
  --decision-dir DIR     Output folder for split_decision.json files.
                         Default: output/split_decisions
  --split-dir DIR        Output folder for split PDFs/images.
                         Default: output/split_pages
  --render-pages         Render every document after splitting logic.
                         If split PDF exists, render that; otherwise render original PDF.
  --render-dir DIR       Output folder for rendered final pages.
                         Default: output/split_render_result
  --python PYTHON        Python executable.
                         Default: .venv/bin/python if available, else python
  --copy-unsplit         Copy documents/pages even when should_split is false.
  -h, --help             Show this help.

Examples:
  src_splitpage/run_split_pipeline.sh

  src_splitpage/run_split_pipeline.sh --input-dir data/incoming
EOF
}

INPUT_DIR="data/incoming"
DECISION_DIR="output/split_decisions"
SPLIT_DIR="output/split_pages"
RENDER_DIR="output/split_render_result"
PYTHON_BIN=""
COPY_UNSPLIT=0
RENDER_PAGES=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input-dir)
      INPUT_DIR="${2:-}"
      shift 2
      ;;
    --decision-dir)
      DECISION_DIR="${2:-}"
      shift 2
      ;;
    --split-dir)
      SPLIT_DIR="${2:-}"
      shift 2
      ;;
    --render-pages)
      RENDER_PAGES=1
      shift
      ;;
    --render-dir)
      RENDER_DIR="${2:-}"
      shift 2
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    --copy-unsplit)
      COPY_UNSPLIT=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -d "$INPUT_DIR" ]]; then
  echo "Error: input directory does not exist: $INPUT_DIR" >&2
  exit 1
fi

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python"
  fi
fi

DETECT_SCRIPT="src_splitpage/src/detect_document_split_mode.py"
APPLY_SCRIPT="src_splitpage/src/apply_document_split.py"
RENDER_SCRIPT="src_splitpage/src/render_split_result_pages.py"

if [[ ! -f "$DETECT_SCRIPT" ]]; then
  echo "Error: detector script not found: $DETECT_SCRIPT" >&2
  exit 1
fi

if [[ ! -f "$APPLY_SCRIPT" ]]; then
  echo "Error: split script not found: $APPLY_SCRIPT" >&2
  exit 1
fi

if [[ "$RENDER_PAGES" -eq 1 && ! -f "$RENDER_SCRIPT" ]]; then
  echo "Error: render script not found: $RENDER_SCRIPT" >&2
  exit 1
fi

mkdir -p "$DECISION_DIR" "$SPLIT_DIR"
if [[ "$RENDER_PAGES" -eq 1 ]]; then
  mkdir -p "$RENDER_DIR"
fi

COPY_ARGS=()
if [[ "$COPY_UNSPLIT" -eq 1 ]]; then
  COPY_ARGS=(--copy-unsplit)
fi

process_one() {
  local input_path="$1"
  local doc_id="$2"
  local decision_path="$DECISION_DIR/$doc_id/split_decision.json"
  local output_path="$SPLIT_DIR/$doc_id"

  echo "==> Detecting split mode: $doc_id"
  "$PYTHON_BIN" "$DETECT_SCRIPT" \
    --input "$input_path" \
    --out "$decision_path"

  echo "==> Applying split decision: $doc_id"
  "$PYTHON_BIN" "$APPLY_SCRIPT" \
    --input "$input_path" \
    --decision "$decision_path" \
    --out "$output_path" \
    "${COPY_ARGS[@]}"

  if [[ "$RENDER_PAGES" -eq 1 ]]; then
    local split_pdf="$output_path/${doc_id}_split.pdf"
    local render_input="$input_path"
    local render_mode="original"
    if [[ -f "$split_pdf" ]]; then
      render_input="$split_pdf"
      render_mode="split"
    fi

    echo "==> Rendering final pages ($render_mode): $doc_id"
    "$PYTHON_BIN" "$RENDER_SCRIPT" \
      --input "$render_input" \
      --out "$RENDER_DIR/$doc_id" \
      --document-id "$doc_id"
  fi

  echo "==> Done: $doc_id"
}

processed=0

for pdf in "$INPUT_DIR"/*.pdf; do
  [[ -f "$pdf" ]] || continue
  doc_id="$(basename "$pdf" .pdf)"
  process_one "$pdf" "$doc_id"
  processed=$((processed + 1))
done

if [[ "$processed" -eq 0 ]]; then
  echo "No PDF files found in: $INPUT_DIR" >&2
  exit 1
fi

echo "All done. Processed $processed document(s)."
