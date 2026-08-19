# Ordered pipeline entrypoints

This file is the human-facing map of the current production path. The ordered
entrypoint names are intentionally thin wrappers around the existing
implementation files so code history, imports, and older experiments remain
intact.

## Step 1 — Parsing and page alignment

Preferred runner:

```bash
cd parsing
sbatch pipeline_steps/step1_run_parsing_pipeline.sbatch
```

For one document:

```bash
cd parsing
sbatch --export=ALL,DOC_ID=<DOC_ID> pipeline_steps/step1_run_parsing_pipeline.sbatch
```

Execution order:

| Order | Human-facing entrypoint | Purpose | Existing implementation | Main output |
|---|---|---|---|---|
| 1A | `parsing/pipeline_steps/step1_a_parsing_deepseek_ocr.py` | DeepSeek OCR parsing and OCR geometry extraction | `parsing/src/deepseekocr2_parsing/parse_incoming_deepseekocr2_bbox.py` | `parsing/output/deepseekocr2_split_render/<doc>/page_XXXX/` |
| 1B | `parsing/pipeline_steps/step1_b_parsing_layout_detection.py` | PP-DocLayout page-region detection | `parsing/src/layout_detection/run_pp_doclayout_detection.py` | `parsing/output/layout_detection_split_render/<doc>/page_XXXX.json` |
| 1C | `parsing/pipeline_steps/step1_c_parsing_hybrid_alignment.py` | Align OCR blocks with layout detections | `parsing/src/hybrid_align_deepseek_layout.py` | `parsing/output/hybrid_deepseek_layout_split_render/aligned_json/<doc>/page_XXXX.json` |
| 1D | `parsing/pipeline_steps/step1_d_parsing_enrich_export.py` | Enrich aligned JSON and export page Markdown/crops | `parsing/src/enrich_hybrid_aligned_and_export_page_md.py` | `enriched_json`, `export_md_by_page`, `visual_region_crops` |

The older `parsing/src_splitpage/run_parse_layout_from_split_render.sbatch` is
kept as the implementation orchestrator for compatibility, but it now routes
through the ordered Step 1A–1D entrypoints above.

## Step 2 — EvidenceNet node construction

Current canonical entrypoint:

```bash
cd EvidenceNet
python pipeline_steps/step2_a_evidencenet_build_nodes.py \
  --doc-id <DOC_ID> \
  --config config/evidence_graph.yaml
```

| Order | Human-facing entrypoint | Purpose | Existing implementation | Main output |
|---|---|---|---|---|
| 2A | `EvidenceNet/pipeline_steps/step2_a_evidencenet_build_nodes.py` | Build deterministic EvidenceNodes and structural graph artifacts | `evidence_graph.cli -> pipeline.build_nodes -> evidence_builder` | `EvidenceNet/output/evidence_graph/<doc>/evidence_nodes.jsonl` and structural artifacts |

EvidenceNode geometry is provenance-preserving: bbox fields and
`geometry_members` are carried from aligned source blocks when present. Step 2
does not infer missing geometry.

## Experimental / historical paths — not part of the numbered production path

These files are intentionally **not** renamed into the numbered pipeline because
they are historical, experimental, or separate workflows:

- `parsing/src/box_repair/bbox_repair_layout.py`
  - historical bbox-repair path
  - output: `parsing/output/fused_layout_parsing/...`
- `parsing/src/box_repair/patch_md_bbox_comments.py`
  - model-output patch utility, not a normal page-processing step
- `EvidenceNet/scripts/fuse_aligned_document.py`
  - separate semantic-group fusion workflow
- `parsing/src/vlm_group_to_md.py`
  - separate VLM grouping/Markdown workflow
- semantic-edge experiments under `EvidenceNet/evidence_graph/`
  - remain unnumbered until the edge-existence/type pipeline is finalized

## Naming rule going forward

Use this convention for stable production entrypoints:

```text
step<major>_<letter>_<stage>_<action>.py
```

Examples:

```text
step1_a_parsing_deepseek_ocr.py
step1_b_parsing_layout_detection.py
step1_c_parsing_hybrid_alignment.py
step1_d_parsing_enrich_export.py
step2_a_evidencenet_build_nodes.py
```

Keep implementation modules descriptive and import-friendly; add or update the
numbered thin entrypoint instead of renaming deep internal modules that are
already imported elsewhere.
