# Dolphin-v2 parsing pilot

Updated 2026-10-09. This directory contains parser experiments, not the default
DeepSeek parsing pipeline. Source code, configs and documentation are versioned;
local vendor code, weights, inputs, work directories and outputs are ignored.

Isolated, cross-document comparison between the official ByteDance Dolphin-v2 parser and existing DeepSeekOCR2 outputs.

- No production parsing, alignment, EvidenceNode, or routing output is modified.
- Official code is vendored under `vendor/Dolphin`.
- Official weights are local under `models/Dolphin-v2`.
- Raw official output and per-page checkpoints stay under `work/<case_id>`.
- `output/` contains only the report, summary, manifest, and compact per-case comparison artifacts.
- The final visual report is `output/dolphin_v2_vs_deepseekocr2_report.html`.

The original comparison uses `run_pilot.py` and `build_comparison_report.py`.
From the repository root on HoReKa2, override the launcher's old HoReKa1 partition:

```bash
mkdir -p parsing/experiments/dolphin_v2_pilot/logs
sbatch --partition=gpu-h200,gpu-h100 \
  parsing/experiments/dolphin_v2_pilot/run_dolphin_v2_pilot.sbatch
```

`run_pdf_corpus.py` parses full PDFs with per-page checkpoints and separate
publishing. Each manifest chooses its work/output roots; these are not all under
the original `work/<case_id>` structure. Current document-graph parsing uses
`current/slurm/document_graph/run_document_graph_dolphin_dev.sbatch` with document/page-range settings.

VL-DocIR uses official page images rather than re-rendered PDFs. Its runner is
`EvidenceNet/scripts/parse_vldocir_pages.py`; the submitted task chain and input
requirements are in the [VL-DocIR README](../../../EvidenceNet/experiments/vldocir/README.md).
Parsing alone does not generate EvidenceNodes or validate article/semantic edges.
