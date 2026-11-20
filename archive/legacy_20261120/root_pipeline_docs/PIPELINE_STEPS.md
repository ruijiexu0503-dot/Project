# EvidenceNet pipeline: current implementation and target routing

Last detailed audit: **2026-09-09**. Current reconciliation: see
[`PIPELINE_CURRENT.md`](PIPELINE_CURRENT.md) (**2026-10-04**).

For selected measured results, HoReKa2 commands and the current storage layout,
start with [`current/README.md`](current/README.md). D-031 groups historical
experiments under `_archive/2026-10-04/` without changing these method contracts.
Historical paths can be resolved using `current/json/archive-plan.json`.
The additional seven-script archive is indexed in
`current/json/superseded-scripts-20261004.json`; see `current/GIT_CLEANUP.md` for
restoration and generated-file ignore rules. Current runtime inputs stay in place.

D-032 adds opt-in bounded flow recovery and windowed candidate retrieval. Its
contracts and validation are recorded in the
[integration report](EvidenceNet/docs/bounded_recovery_integration_2026-10-04.md).
Recovered flows retain review flags; missing IDs still fail. Retrieval windows
use exact offsets in unit text, retain parent geometry without invented window
boxes, and produce unverified candidates under equal per-scope review budgets.

D-033 adds source-span IDs for local relation anchors, a source-bound reviewed
visual-role map, and a blinded matched-budget candidate review package. Nodes,
source geometry and default quote mode are preserved. Valid span IDs establish
source location only; they do not validate relation semantics. See the
[implementation record](EvidenceNet/docs/span_grounding_and_blind_review_2026-10-04.md).

D-035 inventories all 1048 source pages and starts a latest-policy 49-page
all-document regression before full-page expansion; see
[`current/ALL_DATA_RUN.md`](current/ALL_DATA_RUN.md) for exact submitted scope.

This is the human-facing source of truth for the pipeline. It deliberately
separates the currently executable stable path from shadow experiments. For the
rationale and history of each policy, see [`PIPELINE_DECISIONS.md`](PIPELINE_DECISIONS.md).

## End-to-end map

```text
PDF / born-digital document
  |
  +-- 0. source-page analysis and reversible page views ........ SHADOW
  |      per source page: SPLIT_PHYSICAL_PAGES | INTACT_SPREAD | UNRESOLVED
  |
  +-- 1. parsing
  |      parser branch: DeepSeekOCR2 ............................ ACTIVE
  |                   | Dolphin-v2 .............................. EVALUATING
  |      layout detection ....................................... ACTIVE (DeepSeek path)
  |      OCR/layout alignment + geometry provenance ............. ACTIVE
  |      enriched page JSON / Markdown / visual crops ........... ACTIVE
  |
  +-- 2. document reconstruction
  |      single work vs multi-item profile ...................... ACTIVE utility
  |      article/content-item grouping + reading order .......... SHADOW
  |      contextual visual descriptions ......................... SHADOW
  |      cross-page continuation ................................ SHADOW
  |
  +-- 3. EvidenceNode construction
  |      evidence_content node build + structural graph ......... ACTIVE
  |      approved SAFE_TEMPLATE interface ....................... ACTIVE, config-gated
  |      advertisement retained as evidence ..................... SHADOW/config-gated
  |      non-evidence structural materialization ................ NOT YET IMPLEMENTED
  |
  +-- 4. document-internal relations
  |      candidate retrieval .................................... SHADOW
  |      edge existence + semantic type/direction ............... SHADOW
  |      independent REFERENCES detection ....................... SHADOW
  |
  +-- 5. cross-document graphs
         exact scholarly CITES .................................. ISOLATED PILOT
         non-citation RELATED discovery ......................... ISOLATED PILOT
```

## Non-negotiable data contracts

- Preserve the original PDF/source-page image.
- Crops and split pages are reversible inference views, not replacement source
  pages. Store the transform back to the source-page coordinate system.
- Carry OCR geometry through explicit grounding provenance. Do not align lists
  with a simple `zip` unless identity/count validation proves correspondence.
- A logical block with multiple physical regions retains `geometry_members[]`.
  Do not fabricate a union bbox as if it were an observed region.
- On count/schema/page-dimension/sequence mismatch, mark geometry unresolved;
  do not guess from reading order or text.
- Keep incomplete content visible. Uncertainty is metadata, not deletion.
- Shadow runs write to independent directories and never overwrite production.

## Step 0 — Source-page state and reversible routing

Status: **SHADOW; accepted design, not yet the default parsing runner**.

The final routing decision is made for each source PDF page, not once for the
entire magazine. A document-level spread detector may be used only as a cheap
pre-screen; it must not override the per-page decision.

| Per-page state | Meaning | Inference input |
|---|---|---|
| `SPLIT_PHYSICAL_PAGES` | Two facing pages and no verified cross-gutter visual | left and right reversible views |
| `INTACT_SPREAD` | A visual/content object is reliably verified across the gutter | intact spread plus optional left/right context views |
| `UNRESOLVED` | Required mapping or evidence is missing/ambiguous | preserve intact source page for review |

Current generic acceptance for an intact spread uses direct PDF/render-layer
provenance or verified pixel-continuity evidence. It does not use magazine name,
text, colour, or an odd/even-page rule.

Implementation and audited example:

- `EvidenceNet/scripts/audit_hybrid_spread_routing.py`
- `EvidenceNet/output/hybrid_spread_routing_5page_pilot/DLRmagazine_176_EN/`

The audited DLR sample routes source pages 0004/0007 to split views and
0009/0013/0017 to intact-spread inference. Article continuation and recurring
editorial lanes remain document-level linkage tasks after a page is split.

Important current limitation: `parsing/pipeline_steps/step1_run_parsing_pipeline.sbatch`
still consumes `parsing/output/split_render_result`. The adaptive three-state
router must be integrated explicitly before it is production behavior.

## Step 1 — Parsing and geometry-preserving alignment

### Source capability routing

Parsing pixels and recovering native visual layers are separate capabilities.
Before visual-asset processing, route the source with
`parsing/src/visual_source_capabilities.py`:

- `PDF_NATIVE_LAYERS`: native PDF content stream, z-order, clip paths and the
  renderer-derived dual-mask shadow experiment are available.
- `RASTER_VISIBLE_ONLY`: PNG/JPEG/WebP/BMP/TIFF files or page-image sequences
  can continue through OCR/layout, but prove only visible pixels.  Their
  `layer_mask` is unavailable and hidden extent must not be fabricated.
- `NATIVE_ADAPTER_REQUIRED`: DOCX/HTML/EPUB require a format-native object
  adapter before claiming layers.  Converting them to PDF is permitted only as
  a rendered-pixel fallback and does not restore original layer provenance.

The PPTX pilot now routes separately as `PPTX_NATIVE_OBJECTS_SHADOW`: native
shape bboxes, object z-order, group membership, picture blobs and crop metadata
are preserved by `parsing/src/audit_pptx_native_objects.py`.  It is not yet an
active parser because this environment lacks a faithful PowerPoint-compatible
renderer; pixel-exact visible masks, effects, SmartArt and animations therefore
remain unresolved.  DOCX/HTML/EPUB still use `NATIVE_ADAPTER_REQUIRED`.

Downstream schemas must tolerate `layer_mask_status=unavailable_flattened_source`.
An unavailable layer mask is not evidence that the asset should be dropped.

### 1A–1D DeepSeekOCR2 path

Status: **ACTIVE**.

Preferred runner:

```bash
cd parsing
sbatch pipeline_steps/step1_run_parsing_pipeline.sbatch
```

One document:

```bash
cd parsing
sbatch --export=ALL,DOC_ID=<DOC_ID> pipeline_steps/step1_run_parsing_pipeline.sbatch
```

| Order | Entrypoint | Actual implementation | Main output |
|---|---|---|---|
| 1A | `parsing/pipeline_steps/step1_a_parsing_deepseek_ocr.py` | `parsing/src/deepseekocr2_parsing/parse_incoming_deepseekocr2_bbox.py` | `parsing/output/deepseekocr2_split_render/<doc>/page_XXXX/` |
| 1B | `parsing/pipeline_steps/step1_b_parsing_layout_detection.py` | `parsing/src/layout_detection/run_pp_doclayout_detection.py` | `parsing/output/layout_detection_split_render/<doc>/page_XXXX.json` |
| 1C | `parsing/pipeline_steps/step1_c_parsing_hybrid_alignment.py` | `parsing/src/hybrid_align_deepseek_layout.py` | `parsing/output/hybrid_deepseek_layout_split_render/aligned_json/<doc>/page_XXXX.json` |
| 1D | `parsing/pipeline_steps/step1_d_parsing_enrich_export.py` | `parsing/src/enrich_hybrid_aligned_and_export_page_md.py` | `enriched_json/`, `export_md_by_page/`, `visual_region_crops/` |

The compatibility orchestrator is
`parsing/src_splitpage/run_parse_layout_from_split_render.sbatch`. The numbered
files are thin, stable entrypoints around the existing implementations.

Geometry provenance at 1A → 1C validates schema, page dimensions, sequence,
grounding-group count, and multi-member preservation. Missing geometry from a
failed validation remains unresolved.

### Dolphin-v2 parser branch

Status: **EVALUATING**.

Dolphin-v2 runs only in:

```text
parsing/experiments/dolphin_v2_pilot/
```

Its native labels (including header/footer/table/figure) and bboxes are parser
outputs, not approved template deletion decisions. A fair comparison with
DeepSeek must use the same per-page route and physical view. An uncut Dolphin run
is useful as a parser audit, but it must not be mixed with split DeepSeek pages in
formal downstream metrics.

Adapter under development:

```text
EvidenceNet/scripts/prepare_dolphin_deepseek_matched_pipeline.py
```

## Step 2 — Document reconstruction

### 2A Document structure profile

Status: **ACTIVE utility**.

The deterministic profiler routes a document to:

- `SINGLE_STRUCTURED_WORK`: preserve one top-level work; or
- `MULTI_ITEM_COLLECTION`: allow article/content-item segmentation.

It is conservative: without strong multi-item evidence it preserves one work.
See `EvidenceNet/docs/structure_detection/README.md` for features and commands.

### 2B Article grouping and reading order

Status: **SHADOW**.

For magazines and mixed pages, reading order has three levels:

1. group blocks/visuals into an article or content item;
2. order blocks inside that content item;
3. order content items at page/document level.

The current Qwen3.5 shadow implementation is:

```text
EvidenceNet/scripts/run_evidence_unit_shadow_pilot.py
EvidenceNet/slurm/run_evidence_unit_shadow_pilot_all_types.sbatch
EvidenceNet/config/qwen35_fast_segmentation.yaml
```

It must not treat an entire multi-article page as one geometric sequence. Images,
figures, captions, sidebars, and advertisements are explicit objects in the
request. A visual interruption should not prematurely terminate unfinished text.

The earlier embedding + bbox pairwise-successor ranking is frozen as an audit; it
does not write `final_order`, `document_order`, or EvidenceNodes.

### 2C Visual description and contextual grounding

Status: **SHADOW**.

Visuals should receive a visibly grounded description. Nearby text, captions,
and deictic phrases such as “shown below” or “on the right” are candidate context,
not truth. The description must report disagreement between pixels and referring
text instead of copying the text claim blindly.

Relevant scripts:

```text
EvidenceNet/scripts/run_contextual_visual_enrichment_pilot.py
EvidenceNet/scripts/audit_deictic_visual_references.py
EvidenceNet/scripts/run_deictic_visual_adjudication_pilot.py
```

### 2D Cross-page continuation

Status: **SHADOW**.

Cross-page joining is separate from page splitting. Candidate cues include
incomplete sentence/paragraph state, next-page compatibility, article identity,
geometry/column continuity, and explicit continuation markers when present. No
single marker is required, and a missing marker is not a negative label. Outputs
retain exact per-page geometry members.

## Step 3 — EvidenceNode construction and inclusion

### 3A Deterministic build

Status: **ACTIVE**.

```bash
cd EvidenceNet
python pipeline_steps/step2_a_evidencenet_build_nodes.py \
  --doc-id <DOC_ID> \
  --config config/evidence_graph.yaml
```

Main output:

```text
EvidenceNet/output/evidence_graph/<doc>/evidence_nodes.jsonl
```

Current default uses one aligned block per provisional node, does not merge
continuations, and keeps incomplete nodes. Geometry and `geometry_members[]` are
copied from aligned blocks; this step does not invent missing bboxes.

Current structural output still emits `NEXT`/`PREVIOUS` between consecutive
EvidenceNodes and may add `CONTINUES_TO`. This is the implementation as it exists,
not the final taxonomy decision. The target design stores ordinary reading order
as metadata and reserves `CONTINUES` for verified logical continuation.

### Inclusion policy

| Input class | Current implementation | Accepted target policy |
|---|---|---|
| approved `SAFE_TEMPLATE` successfully mapped to an aligned block | may be excluded through explicit `template_keys` | exclude, retaining reconstruction metadata |
| suspicious recurring layout | retained unless another role rule removes it | keep |
| unresolved template mapping | retained unless another role rule removes it | keep |
| advertisement role | excluded by the old default; restored only when `include_advertisement_blocks` is enabled | keep as a normal node and preserve original role metadata |
| structural/non-evidence item | classified, but generally not materialized because `evidence_builder.py` currently creates nodes only for `evidence_content` | preserve as a structural node or metadata object |
| incomplete or bboxless `evidence_content` | kept | keep and mark uncertainty |

The `template_keys` and advertisement-inclusion behaviors are configuration-gated.
Only the CERN isolated before/after interface has been audited; the generic footer
detector is not automatically productionized across all magazines.

Therefore “all source material remains addressable” is an accepted requirement,
but is not yet fully implemented for non-evidence structural roles. This gap must
be measured before the builder is promoted as lossless.

## Step 4 — Document-internal relation graph

Status: **SHADOW**. Do not confuse older canonical/legacy semantic output with
the current experiment.

```text
EvidenceNodes
  -> BGE-M3 candidate retrieval (retrieval only; similarity is not an edge)
  -> one-call hierarchical Qwen verification
       1. edge_exists
       2. if true: semantic type and semantic-role direction
       3. independently: explicit REFERENCES true/false and its direction
```

Current coarse semantic taxonomy:

- `CONTRIBUTES_TO`
- `MODIFIES`
- `CONTRASTS_WITH` (symmetric)

`REFERENCES` is an independent discourse dimension and may coexist with a
semantic relation on the same pair. When `edge_exists=false`, semantic label and
direction must be null. An explicit reference requires a localizable cue; topical
similarity is insufficient.

Candidate generation, verification, and typing remain benchmark/shadow work.
`EvidenceNet/pipeline_steps/step3_a_candidate_retrieval_experiment.py` is an
evaluation entrypoint, not a production stage.

## Step 5 — Cross-document relations

Two distinct graphs are kept separate:

1. `CITES`: exact citation provenance from citation mention and bibliography
   entry, with persistent unresolved targets that can resolve when a new offline
   paper arrives. See `OfflineCitationGraph/`.
2. `RELATED`: non-citation topical/conceptual discovery. Article/section-level
   representations retrieve a bounded candidate set; distance alone never
   materializes an edge. See `EdgeGeneration/`.

Magazine ↔ paper discovery belongs to `RELATED`, unless the magazine contains an
explicit, resolvable scholarly citation.

Indexed retrieval experiment (D-012, **SHADOW**):
`EdgeGeneration/scripts/run_ann_candidate_pilot.py` compares cached-vector
HNSW and exact search, fuses article/local/lexical candidates, and audits bounded
candidate budgets. The `run_ann_candidate_pilot.sbatch` wrapper runs on Horeka
`dev_cpuonly`; it does not encode new vectors or use GPUs. Outputs separate real
retrieval fidelity, provisional relation labels, and synthetic scaling. Persisted
indexes and the SQLite cache contain unverified candidates, not semantic edges.

Evidence-level diagnostic (D-013, **SHADOW**):
`EdgeGeneration/scripts/audit_cross_article_evidence.py` compares global
evidence retrieval, target-article diversity, and article-routed candidates.
It preserves endpoint IDs, member node IDs and pages; unverified semantic fields
remain null. Historical paper section/page units are explicitly marked as needing
atomic endpoint resolution. Final cross-article evidence edges must use canonical
EvidenceNodes with validated Qwen ownership and a separate semantic decision.

Description comparison (D-014, **SHADOW**):
`EdgeGeneration/scripts/run_qwen35_description_trial.py` matches existing
Qwen3.5 enrichment records to canonical snapshots, compares original and
description/key-point retrieval with BGE-M3 CLS embeddings, and requests a bounded
Qwen3.5 review of stratified candidates. This experiment excludes same-document
pairs and does not use legacy magazine grouping to infer article ownership.

The edge-generation experiments, Slurm wrappers, reports and migration notes are
contained in `EdgeGeneration/` (D-017). `CrossDocumentDiscovery` is a temporary
compatibility path to that directory.

## Output and provenance rules

D-016 (**SHADOW**) adds independent per-signal verification to the existing
proposal policy, evaluated on the same 24 real pairs, eight synthetic controls,
and eight swapped-order cases. `run_relation_policy_ablation.py` keeps control
labels out of model inputs and exports per-label direction, anchors and decisions.
This is a policy diagnostic, not a production-edge promotion or human benchmark.

D-015 (**SHADOW**) reuses the existing `existence-multisignal-context-v2` prompt
and parser on D-014's same 24 pairs. The cross-document
`compare_multisignal_review.py` script prepares matched inputs and reports old/new
judgments. Independent signals may coexist; possible relations remain unresolved
and no semantic direction or production edge is inferred in this screening step.

Every run should record at least:

- source document and page-view policy;
- parser/alignment version and exact input root;
- node count and inclusion policy;
- embedding model and candidate policy, if used;
- LLM/VLM model, prompt/taxonomy version, and decoding settings, if used;
- accepted/rejected/unresolved counts;
- `production_modified: false` for shadow work;
- paths to reports and machine-readable JSON/JSONL.

Do not compare runs unless page route, node input, candidate set, and evaluator
are matched or the difference is explicitly the ablated variable.

## Stable entrypoint naming

D-037 (2026-10-06): `--edge-prompt-policy grounded-v3` is an opt-in failed
comparison arm, not the default. Frozen 12-visual comparison 52533 retained the
same three clear errors and lost positives, so broader submission is disabled
by the review gate. Keep frozen prompts/raw results/review labels and source hashes.
Archive index: `current/json/experiment-archive-20261006.json`; old paths remain aliases.

D-036 (2026-10-05), relation-first shadow only: `bounded-v2` enumerates missing
source assignments after audited invalid-claim removal, allows one bounded patch
call, and reruns full flow validation. Recovered output stays partial and needs
semantic ownership review. `span-id-v2` preserves caption abbreviations in exact
spans, rejects credit/marker-only primaries, and strengthens visible-support
instructions. Hash-bound reviewed logos remain components but are excluded from
semantic candidates. Tests and local checks pass; completed GPU job 48023 repaired
5/8 frozen failed flows, and 48027 completed nine pages with one flow failure.
See `EvidenceNet/docs/assignment_patch_and_semantics_2026-10-05.md` for limits.

Relation-first shadow D-030 (2026-09-30): CPU v7 adds per-edge validation with
explicit rejection records and partial statuses, plus target-specific caption
attachment fields. Source text remains unchanged; production entrypoints unchanged.

Relation-first shadow D-029 (2026-09-30): CPU v6 tests bounded cross-content-item
text candidates, strict body-versus-caption validation, and layout-justified
recovery of possible captions labeled page furniture. Original structural nodes,
source spans and OCR are retained. This does not change the production entrypoints.
See PIPELINE_DECISIONS.md and _archive/2026-10-09-launchers/EvidenceNet/slurm/run_relation_first_v6_cpu.sbatch.

Stable wrappers use:

```text
step<major>_<letter>_<stage>_<action>.py
```

Implementation modules remain descriptively named. Add or update a thin stable
wrapper instead of renaming imported modules and breaking experiment provenance.
