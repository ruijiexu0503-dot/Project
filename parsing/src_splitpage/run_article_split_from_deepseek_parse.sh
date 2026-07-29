#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  src_splitpage/run_article_split_from_deepseek_parse.sh [options]

Runs the article/page-range split planner directly from DeepSeekOCR2 parse
results. No layout detection, no hybrid alignment, no enrichment.

Options:
  --parse-root DIR      Input root containing <doc_id>/page_XXXX folders.
                        Default: output/deepseekocr2_split_render
  --out-root DIR        Output root for article_split_plan.json files.
                        Default: output/article_split_plans_parse_only
  --python PYTHON       Python executable.
                        Default: .venv/bin/python if available, else python
  --doc-id DOC_ID       Run only one document.
  --overwrite           Regenerate existing article_split_plan.json files.
  -h, --help            Show this help.

Examples:
  src_splitpage/run_article_split_from_deepseek_parse.sh --doc-id CERNCourier2022NovDec-digitaledition --overwrite

  src_splitpage/run_article_split_from_deepseek_parse.sh --overwrite
EOF
}

PARSE_ROOT="output/deepseekocr2_split_render"
OUT_ROOT="output/article_split_plans_parse_only"
PYTHON_BIN=""
DOC_ID=""
OVERWRITE=0
SCRIPT_PATH="src_splitpage/src/plan_article_splits_from_hybrid_parse.py"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --parse-root)
      PARSE_ROOT="${2:-}"
      shift 2
      ;;
    --out-root)
      OUT_ROOT="${2:-}"
      shift 2
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    --doc-id)
      DOC_ID="${2:-}"
      shift 2
      ;;
    --overwrite)
      OVERWRITE=1
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

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python"
  fi
fi

if [[ ! -d "$PARSE_ROOT" ]]; then
  echo "Error: parse root does not exist: $PARSE_ROOT" >&2
  exit 1
fi

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "Error: planner script not found: $SCRIPT_PATH" >&2
  exit 1
fi

mkdir -p "$OUT_ROOT"

DOCS=()
if [[ -n "$DOC_ID" ]]; then
  DOCS+=("$DOC_ID")
else
  while IFS= read -r -d '' doc_dir; do
    DOCS+=("$(basename "$doc_dir")")
  done < <(find "$PARSE_ROOT" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
fi

if [[ "${#DOCS[@]}" -eq 0 ]]; then
  echo "Error: no document folders found in: $PARSE_ROOT" >&2
  exit 1
fi

done_count=0
skip_count=0
fail_count=0

for current_doc_id in "${DOCS[@]}"; do
  parse_dir="$PARSE_ROOT/$current_doc_id"
  out_json="$OUT_ROOT/$current_doc_id/article_split_plan.json"

  echo "==> $current_doc_id"

  if [[ ! -d "$parse_dir" ]]; then
    echo "    skip: missing parse dir: $parse_dir"
    skip_count=$((skip_count + 1))
    continue
  fi

  if [[ -f "$out_json" && "$OVERWRITE" -ne 1 ]]; then
    echo "    skip: output exists: $out_json"
    skip_count=$((skip_count + 1))
    continue
  fi

  mkdir -p "$(dirname "$out_json")"

  if "$PYTHON_BIN" "$SCRIPT_PATH" \
    --input-kind parse \
    --doc-id "$current_doc_id" \
    --parse-root "$parse_dir" \
    --out "$out_json"; then
    done_count=$((done_count + 1))
  else
    echo "    failed: $current_doc_id" >&2
    echo "$current_doc_id" >> "$OUT_ROOT/failed_article_split_docs.txt"
    fail_count=$((fail_count + 1))
  fi
done

echo ""
echo "Done."
echo "  generated: $done_count"
echo "  skipped:   $skip_count"
echo "  failed:    $fail_count"
echo "  out root:  $OUT_ROOT"
