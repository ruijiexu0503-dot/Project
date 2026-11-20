#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
CHECK_OUT="${CHECK_OUT:-EvidenceNet/output/current_preflight_$(date +%Y%m%d_%H%M%S)}"
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_relation_first_corpus_shadow.py \
  --sources EvidenceNet/config/sources/relation_first_multisample_sources.json \
  --output "$CHECK_OUT" \
  --fresh-root parsing/experiments/dolphin_v2_pilot/work/relation_first_fresh \
  --staged-sources EvidenceNet/output/relation_first_corpus_shadow_v1/staged_sources \
  --pptx-audit EvidenceNet/output/relation_first_corpus_shadow_v1/pptx_native \
  --device cpu --local-check
EvidenceNet/.venv_qwen/bin/python - "$CHECK_OUT/summary.json" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
print({k: v for k, v in report.items() if k != 'pages'})
assert report['selected_pages'] == report['processed_pages'] == 49
assert report['validation_failed_pages'] == 0
PY
