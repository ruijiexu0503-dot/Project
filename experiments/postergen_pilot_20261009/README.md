# Existing parsing → PosterGen pilot

Isolated experiment requested 2026-10-09. No production pipeline defaults or
artifacts are changed. Official upstream: https://github.com/Y-Research-SBU/PosterGen
at commit `8a54325f871ee10fa6545de3b3a9b771aa12620c` in `external/PosterGen`.

## Suitable local material

- `data/processed/detr.pdf`: chosen first; original PDF, existing full-page OCR,
  method diagrams and quantitative tables. Good for evaluating both narrative
  and three-column layout. Main paper is pages 1–17; references and appendix are
  excluded from this bounded pilot.
- `data/processed/gw150914_detection.pdf`: suitable next; a clear discovery story
  and quantitative evidence, also useful for testing author-list handling.
- `data/processed/hallmarks_of_aging.pdf`: suitable later; a review article with
  many concepts, so coverage and visual density need a different assessment.
- Whole magazines are not a good first input: the existing article grouping is
  still a shadow branch, and combining unrelated articles would obscure whether
  failures arise from parsing or poster composition.

## What is being run

1. Read the existing DeepSeekOCR2 enriched Markdown under
   `parsing/output/hybrid_deepseek_layout_split_render/enriched_json/detr`.
2. Select five source visuals on pages 2, 7, 9, 11 and 16. Exclude caption regions
   from image candidates. Re-render the original PDF at 4× using existing layout
   boxes. Extract caption text from the corresponding source-PDF caption boxes.
   This is a bounded, explicit selection, not a validated general caption linker.
3. Use the four upstream parser prompts to extract metadata, narrative, sections,
   and visual roles. Marker extraction is replaced by the existing local parser.
4. Call upstream Curator, Color, SectionTitleDesigner, LayoutWithBalancer,
   FontAgent, and Renderer without editing their code. A local adapter replaces
   the cloud-model wrapper with the existing EvidenceNet Transformers client and
   Qwen3.5-35B-A3B (thinking disabled, deterministic decoding).
5. Render the resulting PPTX through a locally extracted official LibreOffice
   25.8.7 distribution, then rasterize its PDF for inspection.

No logo was supplied; the upstream visual-based color fallback is used. There is
no invented institution or conference branding. This is an adapted local-model
run, **not** a reproduction of the authors' cloud-model benchmark.

## Run from repository root

```bash
EvidenceNet/.venv_qwen/bin/python experiments/postergen_pilot_20261009/run_pilot.py prepare
sbatch experiments/postergen_pilot_20261009/run_gpu.sbatch
EvidenceNet/.venv_qwen/bin/python experiments/postergen_pilot_20261009/run_pilot.py render
```

Initial submission: job **61935**, dev-gpu-h100, 2 GPUs, 14:30 time limit.
Completed successfully in **13:37**. PPTX/PDF/PNG generated and inspected;
see [the review and artifact links](REVIEW.md) for actual results and limitations.
Identical model requests are cached by prompt hash for retrying interrupted runs.
All outputs live under `output/detr/`, including source hashes and region IDs,
raw model calls, intermediate layouts, the editable PPTX and rendered preview.
Token counts are text-only counts, excluding image and template tokens.

Dependencies are installed in `deps/`, not in the existing virtual environment:
`python-pptx==1.0.2`, `PyMuPDF==1.28.2`, `qrcode==8.2`,
`json-repair==0.63.5`, `lxml==6.1.3`, `XlsxWriter==3.2.9`.

## Review criteria

- Grounding: title/authors, numerical claims and stated limitations match source.
- Coverage: task, architecture, training objective, COCO detection evidence,
  segmentation extension and limitations remain understandable.
- Layout: no clipping or overlap; readable text and table sizes; balanced columns.
- Source limitations: original geometry and OCR review flags are retained in the
  manifest. Successful generation does not validate all source associations.

Final findings are recorded separately after inspecting the actual rendered
poster. Queue submission alone is not generation success.
