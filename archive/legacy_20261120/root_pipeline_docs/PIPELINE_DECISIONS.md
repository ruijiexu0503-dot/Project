# Pipeline decision log

This file is append-only in spirit: supersede old decisions instead of silently
rewriting history. Each decision says whether the idea is active, shadow-only,
evaluating, frozen, or legacy. Update the corresponding step in
[`PIPELINE_STEPS.md`](PIPELINE_STEPS.md) at the same time.

## Decision record template

```markdown
### D-XXX — Short title

- Date: YYYY-MM-DD
- Status: ACTIVE | SHADOW | EVALUATING | FROZEN | LEGACY | SUPERSEDED
- Scope: affected step(s)
- Decision: exact behavior
- Why: evidence/rationale
- Implementation: scripts/configs
- Output/audit: paths or run IDs
- Production effect: none / config-gated / default
- Supersedes: D-XXX or none
- Revisit when: measurable condition
```

## Current decisions

### D-030 - Per-relation validation and target-specific caption attachment

- Date: 2026-09-30
- Status: SHADOW
- Scope: relation-first review and CPU v7 experiment; production unchanged.
- Evidence: v6 finished all 49 pages (29 complete, 5 partial, 15 flow_failed).
  Three structural caption reviews omitted the required layout field; one bad
  quote could discard all sibling edges. DLR012 rescue caption was also attached
  to the separate vehicle photo based on shared subject matter.
- Decision: validate each raw edge independently, retain accepted edges, export
  rejected raw records with indices/errors. A mixed visual and its page remain
  partial. Reject conflicting direct captions rather than selecting arbitrarily.
- Require caption_attachment and caption_layout_basis for every CAPTION_FOR.
  Explicit shared-panel wording is required for a caption shared across pictures;
  topic overlap is insufficient. These fields are explicit in the prompt template.
- Exact source quotation remains mandatory; no OCR/LaTeX repair or silent relation
  downgrade. Layout justification is a model claim, not verified ground truth.
- Validation: 14 runner tests and 7 shared component tests pass. Same-pair
  support grouping, source offsets, structural-node preservation and resume remain.
- Experiment: run_relation_first_v7_cpu.sbatch, same 49 pages in two serial CPU
  shards, reuse matching valid v6 flows. One attempt per stage, failures continue.
- Output: EvidenceNet/output/relation_first_corpus_shadow_v7_cpu/shard_*/.
- Submitted CPU array: 5172786. All 49 input adapter checks passed.
- Production effect: none; all nodes remain SHADOW_UNVERIFIED.

### D-029 - Bounded cross-item candidates and caption role review

- Date: 2026-09-30
- Status: SHADOW
- Scope: relation-first candidate selection and edge validation, not production.
- Decision: ownership remains recorded but nearby cross-item text is eligible;
  normalized gap <= 0.15 and geometry score <= 0.35 are experimental thresholds.
  Reserve candidate slots for cross-item text and possible structural captions;
  cap total candidates at nine. Geometry is not sufficient to create an edge.
- Body-flow text can be ILLUSTRATES, not CAPTION_FOR. Page-furniture fragments
  of at least 40 characters are a bounded recovery pool; caption edges require
  explicit caption_layout_basis. Preserve original role, node ID and source spans.
- Evidence: DLR009 ship caption was classified as page furniture and contains
  corrupted Dolphin OCR; DLR012 aerial visual had no same-owner text candidates.
  Neither geometry nor role recovery fixes OCR. Keep exact quotes and SUSPECT status.
- Implementation: run_relation_first_corpus_shadow.py, run_relation_first_v6_cpu.sbatch.
- Validation: 12 runner tests and 7 shared geometry/component tests pass,
  including structural-caption gallery export and resume. Existing v5 flow.json
  audit covered 32 pages/35 visuals; DLR009 ship caption and DLR012 aerial text
  now appear in candidate pools. This is candidate coverage, not semantic success.
- Experiment: same 49-page manifest, two sequential CPU shards; reuse valid v5
  flows only after input/config/source-image checks. Failed flows get one new
  attempt in this explicitly requested rerun; no automatic resubmissions.
- Output: EvidenceNet/output/relation_first_corpus_shadow_v6_cpu/shard_*/.
- Submitted: CPU array 5172264, initially PENDING (None); all 49 input adapter
  checks passed. No GPU jobs were released or resubmitted.
- Production effect: none. All components remain SHADOW_UNVERIFIED.
- Limitations: a true caption misclassified as body will remain conservative;
  structural recovery excludes short fragments and roles other than page_furniture.

### D-028 - Record validation failures and continue the CPU batch

- Date: 2026-09-30
- Status: SHADOW
- Supersedes: D-027 fail-fast policy, per user request to avoid repeated submissions.
- Findings: job 5171031 completed reading-flow validation for GW150914 page 2,
  then stopped because several source-grounded claims used the same caption ID.
- Decision: default to one inference attempt per flow/visual. Mark validation
  failures explicitly and continue subsequent visuals/pages. A fully processed
  batch with invalid pages reports completed_with_failures and a failure count;
  this is distinct from valid evidence. Infrastructure errors and exhausted
  time budgets still stop with a nonzero exit. Resume skips recorded failures
  unless --retry-failed is explicitly supplied.
- Relation contract: normalize same-text/visual claims into one relation with
  independently source-validated supporting spans. Explicit CAPTION_FOR takes
  precedence over redundant ILLUSTRATES claims for that same caption; preserve
  all claimed relation types, source offsets, quality flags and explanations.
- Reuse: explicit --reuse-flow-root checks prompt inputs, source-image bytes,
  inference configuration and current flow validation before reusing a decision.
- Verification: 49 adapters passed preflight; 10 tests passed including failure
  continuation and no automatic replay of failed pages. Replaying the actual
  GW first response yields one CAPTION_FOR relation with five valid source spans.
- Execution: job array 5171057, two sequential CPU shards (25/24 pages), one
  submission, four-hour wall limit each, 220 GiB, FP32, 32 inference threads.
  Stop starting new inference calls after 3.5 hours per shard; in-flight calls
  remain subject to the Slurm wall limit. Reuse the validated GW flow from v4.
- Output: `EvidenceNet/output/relation_first_corpus_shadow_v5_cpu/shard_*/`.
- Production effect: none. Validation failure never means reviewed_no_match or
  retrieval eligibility. Outputs still require content review.

### D-027 - Three-page complete CPU evidence experiment

- Date: 2026-09-30
- Status: SHADOW
- Decision: following the successful D-026 CPU capability probe, run the full
  reading-flow, relation, component and gallery pipeline for GW150914 page 2
  and DLR source pages 9/12. Reuse completed Dolphin parsing and native DLR visuals.
- Resources: dev_cpuonly, FP32, 32 inference threads, 76 requested CPU cores,
  220 GiB RAM, two-hour wall limit, no GPU. Stop starting new model calls after
  90 minutes and stop the run on the first failed page. Retain resumable decisions.
- Implementation: `EvidenceNet/slurm/run_relation_first_v4_cpu.sbatch`.
- Job: 5171031, submitted after eight regression tests and Slurm preflight passed.
- Output: `EvidenceNet/output/relation_first_corpus_shadow_v4_cpu/`.
  `inference_status.json` and stdout record per-call stage and elapsed seconds;
  page folders retain raw model answers, validation and component galleries.
- Expansion: the 49-page manifest remains the planned broader sample. Do not
  automatically expand based only on job exit status; inspect these three pages.
- Production effect: none. GPU array 5170719 remains held.

### D-026 - CPU Qwen capability probe

- Date: 2026-09-30
- Status: SHADOW
- Decision: permit explicit `--device cpu --dtype float32 --cpu-threads N`
  in the relation-first runner. GPU defaults remain unchanged. Device and dtype
  are recorded in source representations and checkpoint signatures.
- Probe: run the existing Qwen3.5-35B-A3B weights fully on CPU, first generating
  a short text answer and then a short image-grounded answer. Verify all model
  parameters reside on CPU and record exact generated token counts, timings,
  peak process memory, and raw responses. This is not an evidence-quality test.
- Resources: dev_cpuonly, one node, 76 requested CPU cores, 32 inference
  threads, 220 GiB requested RAM, 30-minute wall limit, no GPU allocation.
- Implementation: `EvidenceNet/scripts/benchmark_qwen_cpu.py`,
  `EvidenceNet/slurm/benchmark_qwen_cpu.sbatch`.
- Job: 5171018; output `EvidenceNet/output/qwen_cpu_probe_5171018/benchmark.json`.
  Actual CPU generation completed on hkn0004, CUDA invisible, all parameters
  resident on CPU. Model load: 71.146 seconds; text: 15 generated tokens in
  4.682 seconds; image: 953 input tokens, 42 generated tokens in 17.275 seconds
  (includes prefill). Model storage in memory: 140428728072 bytes; process peak
  RSS: 196.888 GiB. Full evidence prompts may have larger time/memory requirements.
- Verification: eight relation-first tests pass, including CPU configuration and
  preservation of CUDA defaults. Full-size CPU text and image inference passed;
  full reading-flow/association quality and throughput remain unmeasured.
- Production effect: none. The original 49-page batch has not been moved to CPU.

### D-025 - Reading-flow contract repair and quota-blocked smoke test

- Date: 2026-09-30
- Status: SHADOW
- Findings: Dolphin job 5170718 completed. Qwen shard 5170719_0 timed out
  after nine pages failed reading-flow validation. Outputs confused member IDs
  with visual IDs, placed furniture outside content_items, and duplicated headings.
- Quota: `kit_project_usage` reported GPU Granted=180000 hours,
  Used=193122 hours (107.29%) for hk-project-p0025545. Pending shards 1/2
  originally showed AssocGrpGRESMinutes; both are now explicitly held to prevent
  restarting the failed experiment. Additional project GPU allocation is needed.
- Changes: compact source-only IDs in the flow prompt, explicit JSON nesting,
  schema validation before coverage checks, previous-response repair feedback,
  validated flow/per-visual checkpoints, optional fail-fast and inference budget.
- Verification: seven relation-first tests and seven bounded-composite tests
  pass; three-page local check passes. These do not establish model quality.
- Next run: `EvidenceNet/slurm/run_relation_first_v4_smoke.sbatch` selects
  GW150914 page 2 and DLR pages 9/12, two GPUs, 30-minute wall time. Stop
  starting inference calls after 20 minutes, fail on the first invalid page,
  and resume validated decisions. An in-flight generation may finish after
  the inference budget; Slurm still enforces the hard wall-time limit.
- Submission: prepared, not submitted because the project GPU budget is exhausted.
- Production effect: none. Expansion to the 49-page sample requires a successful
  real-model smoke run and review of its content, beyond local schema checks.

### D-024 - Checked multi-page relation-first retry

- Date: 2026-09-29
- Status: SHADOW
- Supersedes: D-023 sampling and failure reporting, not the production baseline.
- Findings: job 5169484 parsed nine new inputs but failed at the first Qwen
  reading-flow page. Retry 5170705 was canceled before this code audit.
- Scope: 25 document sources, 49 samples; two pages per multi-page source,
  DLR source pages 9/12/17, native PPTX slides 4/20, single-page posters exempt.
  Original cached render page numbers and new source-PDF page numbers are
  explicitly distinguished in the manifest. This is a regression/convenience
  sample, not a representative statistical benchmark.
- Changes: remove fabricated example IDs from prompts; retain structural
  components; group original blocks and same-sentence continuations; retain
  exact source anchors plus flow context; distinguish failed reviews from
  reviewed non-matches; expose shared-caption and explanatory composite views.
  CAPTION_FOR points from text to visual; ILLUSTRATES from visual to text.
- Validation: adapter preflight passed for 34 cached samples; 15 additional
  rendered pages need Dolphin inference. Local checks are not semantic validation.
  JPEG and image-only PDF posters currently have no Dolphin text and cannot
  demonstrate text-image association. PPTX canvas is approximate, not a faithful
  PowerPoint rendering. All component nodes remain retrieval-ineligible.
- Implementation: `EvidenceNet/config/sources/relation_first_multisample_sources.json`,
  `EvidenceNet/scripts/check_relation_first_inputs.py`,
  `_archive/2026-10-09-launchers/EvidenceNet/slurm/parse_relation_first_v3.sbatch`, and
  `EvidenceNet/slurm/run_relation_first_v3.sbatch`.
- Execution: Dolphin completion and strict input preflight gate three sequential
  Qwen array shards (17/16/16 pages). The dev QoS allows four submitted jobs and
  one running job; each shard has a one-hour limit and per-page resume records.
- Output: `EvidenceNet/output/relation_first_corpus_shadow_v3/shard_*/`.
- Submission: Dolphin job 5170718; Qwen array 5170719 (afterok:5170718).
  Both accepted by Slurm on 2026-09-29; Qwen is waiting on the dependency.
  Four new regression tests and seven bounded-composite tests passed; the full
  local-check runner completed 34 pages, 664 components and 62 visual components.
- Production effect: none. Human visual/semantic review remains required.

### D-023 - Relation-first cross-data shadow

- Date: 2026-09-28
- Status: EVALUATING
- Decision: retain text and visual components as independent nodes, generate
  reading flows first, then create source-anchored `CAPTION_FOR` and
  `ILLUSTRATES` relations. Caption composites are views over component nodes,
  not destructive membership merges.
- Scope: one representative page from every PDF source in `data/`, plus the
  native JPEG poster and the first PPTX slide. Reuse existing Dolphin results
  where present; render and parse the eight missing representative sources.
- Implementation: `EvidenceNet/scripts/run_relation_first_corpus_shadow.py`,
  `EvidenceNet/config/sources/relation_first_corpus_sources.json`, and
  `EvidenceNet/slurm/run_relation_first_corpus_shadow.sbatch`.
- Output/audit: `EvidenceNet/output/relation_first_corpus_shadow_v1/`, Slurm
  job 5169484. Static compilation and source coverage checks passed before
  submission.
- Production effect: none. PPTX preview is an approximate native-object canvas;
  all associated asset geometry and source blobs are retained independently.
- Revisit when: inspect retained relation spans, reading contexts, and
  cross-layout failures before comparing retrieval quality.

### D-022 - Opaque visual labels for semantic association review

- Date: 2026-09-26
- Status: SHADOW
- Decision: expose only position-stable opaque labels such as `VISUAL_01` to
  the second-stage semantic reviewer, then map accepted labels back to immutable
  source panel IDs before validation and materialization.
- Why: the v3 paper reviewer treated the parser-derived word `dolphin` in a
  visual ID as image content and rejected otherwise correct Figure 1/Figure 3
  caption associations.
- Output/audit: `EvidenceNet/output/bounded_composite_v4_geometry/`, Slurm
  job 5164209, completed successfully. The DLR 9/12/17 results were retained;
  GW150914 pages 2 and 4 each produced one figure-plus-caption composite.
- Production effect: none. The DLR page-9 ship text remains SUSPECT and
  retrieval-ineligible; opaque IDs prevent one observed metadata leak but do not
  establish general association accuracy.
- Supersedes: D-021 reviewer prompt handling of raw visual panel IDs.
- Revisit when: test arbitrary parser/path labels and more multi-panel papers.

### D-021 - Geometry-assisted association regression across magazine and paper

- Date: 2026-09-26
- Status: SHADOW
- Decision: add normalized member-box gaps, alignment and intervening geometry
  to caption/prose candidates, without using proximity as proof of ownership.
  Preserve unmatched nearby caption candidates in a pending ledger. Resolve
  whitespace-only quote differences back to unique exact source character spans.
- Scope: frozen DLR pages 9/12/17 plus Dolphin GW150914 pages 2/4. Paper reading
  flows are newly generated by Qwen before assembly. Existing complete-figure
  crops remain the paper visual representation; magazine native assets unchanged.
- Output/audit: `EvidenceNet/output/bounded_composite_v3_geometry/`, job 5164196.
  Six unit tests and five-page local coverage checks passed. Paper local checks
  use explicit coverage stubs, not validated reading order.
- Production effect: none. Candidate ranking uses a bounded heuristic; member
  boxes do not reproduce alpha support or PDF clipping. All nodes remain
  retrieval-ineligible pending semantic review. Single-text selection per visual
  remains a limitation; this is not full multi-paragraph relation recovery.
- Supersedes: D-020 literal-whitespace quote checks and caption-only priority.
- Revisit when: compare source components and accepted/pending links on all pages.

### D-020 - Anchored shared-caption and direct-explanation audit

- Date: 2026-09-26
- Status: SHADOW
- Scope: bounded reconstruction on frozen pages 9/12/17.
- Decision: audit each proposed text association with its proposed visuals and
  source page. Shared captions require distinct exact image-specific anchors;
  keep the caption once in one composite. Without caption candidates, consider
  owned prose only for direct explanation, never generic topical association.
  Mark suspect text UNRESOLVED and expose review status in the component gallery.
- Implementation: `EvidenceNet/scripts/run_bounded_composite_pilot.py` and
  `EvidenceNet/tests/test_bounded_composite.py`.
- Output/audit: `EvidenceNet/output/bounded_composite_v2/`; Slurm 5163996.
  Local three-page coverage checks and three focused unit tests passed.
- Production effect: none; all experimental nodes are retrieval-ineligible.
  Exact anchors constrain membership but do not prove semantic correctness;
  same-model second review is not independent validation or OCR correction.
- Supersedes: D-019 reject-all shared-caption behavior and caption-only candidates.
- Revisit when: inspect retained/rejected links and suspect text on all three pages.

### D-019 — Bounded caption binding with deterministic assembly

- Date: 2026-09-26
- Status: SHADOW
- Scope: reconstruction assembly after reading flows.
- Decision: use frozen v3 flows for a controlled regression; retain structural
  `other` fragments as UNRESOLVED text candidates. Form text units by contiguous
  source blocks and same-sentence links. Ask Qwen about one visual and candidate
  captions per call; derive unit types and membership in code. Conflicting
  bindings retain standalone visuals and text.
- Implementation: `EvidenceNet/scripts/run_bounded_composite_pilot.py`.
- Output/audit: `EvidenceNet/output/bounded_composite_v1_local_check/` and
  `EvidenceNet/output/bounded_composite_v1/`.
- Production effect: none. Coverage checks establish structural integrity only;
  recovered noise, source-text errors and mistaken role assignments still need
  semantic review. Page 17 without caption candidates remains text plus visual.
- Supersedes: D-018's unrestricted model assembly implementation, not its
  ownership-before-node principle.
- Revisit when: caption ownership is inspected on pages 9/12/17 and additional
  documents; do not promote based only on validator success.

### D-018 — Flow-first reconstruction is the only current article/node candidate

- Date: 2026-09-26
- Status: SHADOW
- Scope: Step 2B → Step 3 for mixed-layout documents
- Decision: keep article/content ownership and ordered reading flows separate
  from EvidenceNode assembly. A flow-first result must validate exact source
  coverage and continuation adjacency before a later node-assembly decision.
- Why: the joint-boundary v3 experiment required Qwen to maintain repeated
  ownership, order, node and caption ledgers. It completed, but only four of
  seven tasks validated; it recognised some caption links while emitting an
  inconsistent source disposition. The flow-first v3 page-0009 pilot is the
  current positive constrained result, but is insufficient for promotion.
- Implementation: `EvidenceNet/scripts/run_flow_first_evidence_pilot.py`;
  input/panel variants are `run_semantic_panel_evidence_pilot.py` and
  `run_composite_evidence_pilot.py`.
- Output/audit: `EvidenceNet/output/flow_first_evidence_pilot_v3_page009/`,
  `hybrid_boundary_joint_order_v3/`, and
  `composite_evidence_pilot_v3_recomposed_components/`.
- Production effect: none.
- Supersedes: none; it constrains the next experiment rather than replacing the
  deterministic builder.
- Revisit when: the same representation validates on matched magazine, paper,
  report and financial-document pages.

### D-001 — Geometry must retain grounding provenance

- Date: 2026-09-09
- Status: ACTIVE
- Scope: Step 1A → 1C and downstream visualizations
- Decision: validate schema, page dimensions, sequence, and grounding-group
  counts; preserve every `geometry_member`; mark mismatches unresolved. Never use
  positional `zip`, reading order, or text similarity to guess geometry, and
  never present a fabricated union as an observed bbox.
- Why: logical OCR blocks may have multiple physical members, including
  cross-column blocks.
- Implementation: `parsing/src/deepseekocr2_parsing/grounding_groups.py`,
  `parsing/src/deepseekocr2_parsing/parse_incoming_deepseekocr2_bbox.py`, and
  `parsing/src/hybrid_align_deepseek_layout.py`.
- Production effect: active provenance contract.
- Supersedes: earlier bbox restoration by positional correspondence.

### D-002 — Route two-page source pages individually

- Date: 2026-09-09
- Status: SHADOW
- Scope: Step 0
- Decision: assign each source page one of `SPLIT_PHYSICAL_PAGES`,
  `INTACT_SPREAD`, or `UNRESOLVED`. Use intact inference only when cross-gutter
  content has reliable PDF/render-layer or pixel-continuity evidence. Preserve
  the original canvas and reversible coordinate transforms in every case.
- Why: one magazine can contain ordinary facing pages and complex cross-spread
  images; a document-level split flag loses one of these cases.
- Implementation: `EvidenceNet/scripts/audit_hybrid_spread_routing.py`.
- Output/audit: `EvidenceNet/output/hybrid_spread_routing_5page_pilot/DLRmagazine_176_EN/`.
- Production effect: none yet; the current Step-1 runner still reads the existing
  split-render root.
- Supersedes: treating CLAD/DLR/CERN as uniformly split or uniformly uncut.
- Revisit when: the router is audited on whole documents and connected to parser
  input views without changing source geometry.

### D-003 — Evaluate Dolphin-v2 as a parser branch, not a result patch

- Date: 2026-09-09
- Status: EVALUATING
- Scope: Step 1
- Decision: keep Dolphin output isolated and compare it with DeepSeekOCR2 on
  matched documents, pages, and routed views. Do not edit parser outputs to make
  either branch resemble the other.
- Why: Dolphin provides useful native geometry and structural labels, but a fair
  downstream comparison requires identical page state.
- Implementation: `parsing/experiments/dolphin_v2_pilot/` and
  `EvidenceNet/scripts/prepare_dolphin_deepseek_matched_pipeline.py`.
- Production effect: none.
- Revisit when: matched EvidenceNode/article-order audits are complete.

### D-004 — Exclude only approved mapped templates

- Date: 2026-09-09
- Status: ACTIVE (config-gated interface); detector remains SHADOW
- Scope: Step 3
- Decision: only `SAFE_TEMPLATE` regions that map successfully to aligned blocks
  may enter `template_keys`. Suspicious recurring layout and unresolved mappings
  stay in the data. Preserve reconstruction metadata for skipped blocks.
- Why: recurrence alone can describe repeated body/caption layout or repeated ads.
- Implementation: `EvidenceNet/scripts/materialize_safe_template_keys.py` and
  the `template_keys` interface in `EvidenceNet/evidence_graph/pipeline.py`.
- Production effect: explicit-config only; audited initially on isolated CERN output.
- Revisit when: generic cross-document footer audits show no body false positives.

### D-005 — Advertisement classification is non-destructive

- Date: 2026-09-09
- Status: SHADOW/config-gated
- Scope: Step 3
- Decision: advertisement-role blocks remain ordinary EvidenceNodes and keep the
  original role as metadata. Advertisement classification alone cannot delete
  text, images, or captions.
- Why: normal content has been misclassified as advertisement.
- Implementation: `include_advertisement_blocks` handling in
  `EvidenceNet/evidence_graph/pipeline.py`.
- Production effect: enabled only by an explicit isolated configuration.
- Revisit when: before/after audits cover the full magazine corpus.

### D-006 — Separate article grouping from reading order

- Date: 2026-09-09
- Status: SHADOW
- Scope: Step 2B
- Decision: first identify content items/articles, then order blocks within each
  item, then order items. Do not impose one page-wide geometric order on
  multi-column, multi-article pages. Qwen3.5 is the current shadow model; the
  pairwise embedding+bbox successor experiment stays frozen.
- Why: page-wide ordering jumped between unfinished articles and omitted visuals.
- Implementation: `EvidenceNet/scripts/run_evidence_unit_shadow_pilot.py`.
- Production effect: none.
- Revisit when: parser-matched multi-document audit is complete and global
  consistency constraints are designed.

### D-007 — Visual descriptions use pixels plus contextual references

- Date: 2026-09-09
- Status: SHADOW
- Scope: Step 2C
- Decision: describe a figure/image from its pixels while using captions, nearby
  prose, and spatial/deictic cues as context. Record conflicts instead of copying
  a referring sentence as visual truth.
- Why: figures were absent from reading order or had descriptions too weak for
  downstream retrieval; deictic phrases can also point to the wrong nearby visual.
- Implementation: contextual visual enrichment and deictic-reference audit scripts.
- Production effect: none.

### D-008 — Cross-page continuation is an explicit downstream task

- Date: 2026-09-09
- Status: SHADOW
- Scope: Step 2D
- Decision: judge whether the last relevant text on one page is complete and
  whether the next page continues it. Use multiple cues; do not require a
  magazine-specific continuation symbol. Preserve both page geometries when
  representing a joined logical unit.
- Why: many magazines continue without a marker, while some markers are visual
  and unknown in advance.
- Production effect: none.

### D-009 — Keep content under uncertainty; materialize structural roles

- Date: 2026-09-09
- Status: SHADOW (partially implemented requirement)
- Scope: Step 3
- Decision: incomplete, bboxless, small, or structurally routed source material
  must not disappear silently. Keep evidence candidates or preserve them as
  structural objects/metadata with an explicit reason.
- Why: earlier role and provenance failures caused scientific evidence loss.
- Implementation: `keep_incomplete_nodes: true` already preserves incomplete
  `evidence_content`; micro-fragment consolidation remains diagnostic with
  `apply: false`. However, `evidence_builder.py` currently skips every role other
  than `evidence_content`, so general structural-role materialization is still a
  known implementation gap.
- Production effect: partial only; do not claim a lossless source inventory yet.

### D-010 — Semantic existence precedes coarse typing; REFERENCES is independent

- Date: 2026-09-09
- Status: SHADOW
- Scope: Step 4
- Decision: for each retrieved pair, first predict `edge_exists`. If true, type
  the semantic relation as `CONTRIBUTES_TO`, `MODIFIES`, or symmetric
  `CONTRASTS_WITH`, with semantic-role direction. Detect explicit `REFERENCES`
  independently with its own direction and cue. If false, semantic type and
  direction are null.
- Why: fine-grained mutually exclusive labels were difficult even for humans,
  and explicit discourse reference can coexist with semantic function.
- Implementation: current one-call hierarchical semantic pilot scripts.
- Production effect: none; legacy Qwen2.5 semantic results stay excluded.
- Supersedes: the mutually exclusive four-class system that treated REFERENCES
  as a semantic alternative.

### D-011 — Separate CITES from non-citation RELATED discovery

- Date: 2026-09-09
- Status: SHADOW (isolated pilots)
- Scope: Step 5
- Decision: build `CITES` from exact bibliography/citation provenance with
  persistent unresolved work identities. Build `RELATED` through bounded
  article/section retrieval and later verification. Similarity distance alone
  never creates either edge.
- Why: an article may be relevant without citing another, and a cited paper may
  enter the offline database after the source paper.
- Implementation: `OfflineCitationGraph/` and `EdgeGeneration/`.
- Production effect: none on EvidenceNet.

### D-012 — Audit indexed, bounded cross-article candidate retrieval

- Date: 2026-09-16
- Status: SHADOW
- Scope: Step 5, RELATED candidate retrieval only
- Decision: compare HNSW with an exact inner-product baseline on the same cached
  BGE-M3 vectors. Combine article means, local evidence hits, and corpus-derived
  lexical postings with RRF; cap candidates at 5/10/20 per article. Keep each
  retrieval route at 20 articles across the budget sweep. Exclude same-article
  hits, but allow distinct articles in the same magazine.
- Why: existing full similarity matrices do not scale; ANN fidelity and semantic
  candidate recall must be measured separately before promotion.
- Implementation: `EdgeGeneration/scripts/run_ann_candidate_pilot.py`
  and `_archive/2026-10-09-launchers/EdgeGeneration/slurm/run_ann_candidate_pilot.sbatch`.
- Output/audit: `EdgeGeneration/output/ann_candidate_pilot_<SLURM_JOB_ID>/`.
  Includes persisted indexes/mappings, candidate-only SQLite cache, provisional
  label audit, incremental append/reload checks, and synthetic scaling tests.
- Production effect: none. Synthetic vectors are not additional real documents;
  seven provisional evidence-pair labels are not article-level gold.
- Supersedes: none; existing small exact audits remain reference baselines.
- Revisit when: representative real-corpus candidate recall and downstream
  verification are measured, including local relations lost by article pooling.

### D-013 — Audit cross-article evidence candidates independently of article gates

- Date: 2026-09-17
- Status: SHADOW
- Scope: Step 5, evidence-level retrieval diagnostics
- Decision: preserve direct cross-article evidence ANN retrieval; compare ordinary
  top-k, target-article diversity caps, bounded article routing, and their unions.
  Reverse retrieval adds a candidate, not a semantic direction. Export provenance
  and unresolved atomic endpoint flags, with semantic fields left null.
- Why: article-pair coverage does not guarantee retrieval of the supporting
  evidence; many similar passages from one target article can crowd out others.
- Implementation: `EdgeGeneration/scripts/audit_cross_article_evidence.py`.
- Output/audit: `EdgeGeneration/output/cross_article_evidence_audit_v2/`.
- Production effect: none. This isolates retrieval on the historical snapshot;
  it does not claim to have connected complete Qwen article outputs or replaced
  paper sections with atomic EvidenceNodes. Seven provisional labels are diagnostic.
- Revisit when: validated Qwen ownership and canonical EvidenceNodes are joined,
  and candidate relations are verified with source-grounded semantic review.

### D-014 — Reuse provenance-checked Qwen3.5 descriptions for retrieval comparison

- Date: 2026-09-17
- Status: SHADOW
- Scope: cross-document evidence retrieval and model-only sample review
- Decision: use successful `qwen3_5_candidate` records from the enrichment
  comparison outputs, requiring baseline fields, node order/type and ID to match
  the canonical snapshot. Do not trust a model name in a directory as provenance.
  Compare original text, summary/key points, RRF fusion and route union on the
  same text/formula nodes of at least 25 words. Exclude reference/acknowledgment
  sections and log every exclusion.
- Implementation: `EdgeGeneration/scripts/run_qwen35_description_trial.py`
  and `_archive/2026-10-09-launchers/EdgeGeneration/slurm/run_qwen35_description_trial.sbatch`.
- Output: `EdgeGeneration/output/qwen35_description_trial_v1/`.
- Production effect: none. Three CERN issues and one paper; cross-document only.
  Does not infer same-magazine article ownership. Existing descriptions lack
  source-text hashes, so baseline matching is not a cryptographic text binding.
  Qwen3.5 review of 24 stratified candidates is not independent ground truth.
- Revisit when: sample evidence has been inspected and validated Qwen article
  ownership permits same-magazine evaluation on matched canonical nodes.

### D-015 — Existing multisignal policy on frozen cross-document pairs

- Date: 2026-09-17
- Status: SHADOW
- Scope: Step 5 semantic screening comparison
- Decision: rerun D-014's exact 24 pairs with the existing
  `existence-multisignal-context-v2` prompt/parser unchanged. Preserve original
  texts, descriptions, key points and metadata; add no neighboring context.
  Multiple signals can coexist; POSSIBLE_RELATION stays unresolved. This screening
  does not infer semantic direction.
- Implementation: `EdgeGeneration/scripts/compare_multisignal_review.py`
  and `_archive/2026-10-09-launchers/EdgeGeneration/slurm/run_multisignal_review.sbatch`.
- Output: `EdgeGeneration/output/qwen35_multisignal_review_v1/`.
- Production effect: none. A prompt-policy comparison, not a pure label-exclusivity
  ablation or independent accuracy estimate.
- Revisit when: old/new judgments and target anchors have been inspected.

### D-016 — Per-signal verification with frozen pairs and diagnostic controls

- Date: 2026-09-17
- Status: SHADOW
- Scope: Step 5 relation-policy comparison
- Decision: retain D-014/D-015 outputs as baselines; check all five independent
  signals against source text after the existing proposal stage. Each signal
  receives ACCEPT/REJECT/UNCERTAIN, direction, reason and target anchors. A single
  failed output cannot materialize a relation. No neighboring context is added.
- Implementation: `EdgeGeneration/scripts/run_relation_policy_ablation.py`
  and `_archive/2026-10-09-launchers/EdgeGeneration/slurm/run_relation_policy_ablation.sbatch`.
- Output: `EdgeGeneration/output/relation_policy_ablation_v1/`.
- Evaluation: 24 frozen real pairs, eight explicitly synthetic positive/negative
  controls with hidden labels, and eight reversed-orientation real pairs. Reuse
  original proposals for the 24 real pairs, generate proposals for new cases.
  Check coverage, exact target anchors, task IDs, and multiple simultaneous labels.
- Production effect: none. Same-model proposal/review is not independent human
  validation. Synthetic controls do not establish real-corpus precision/recall.
- Revisit when: compare retained edges, label changes, uncertainty, control
  outcomes, and orientation sensitivity; do not select by edge count alone.

### D-017 — Dedicated edge-generation package

- Date: 2026-09-20
- Status: SHADOW
- Scope: organization and migration of the cross-document edge experiments.
- Decision: locate candidate retrieval, semantic review, visual asset reporting,
  Slurm wrappers, test fixtures and their isolated outputs under
  `EdgeGeneration/`. Keep `CrossDocumentDiscovery` as a compatibility symlink
  while callers migrate. This changes no source EvidenceNode, visual asset, or
  materialized graph edge.
- Migration record: `EdgeGeneration/MIGRATION.md` identifies the external
  EvidenceNet, parsing geometry, BGE-M3, and Qwen dependencies.
- Revisit when: moving to a standalone repository; update Slurm `ROOT` paths
  for the target checkout before submission.

## Frozen and legacy notes

- The footer/template detector is frozen pending broader validation; do not tune
  CERN-specific geometry thresholds.
- Pairwise TF-IDF/BGE reading-order ranking is an audit only; no global decoding
  or production order write-back was approved.
- Old fine-grained semantic taxonomies and legacy Qwen2.5 semantic outputs remain
  available for provenance but are not the current target taxonomy.
- A document-level `should_split` decision is a legacy/pre-screening signal. It
  is not the accepted final page-routing policy.
- The current structural builder still emits `NEXT` and `PREVIOUS` edges. The
  accepted target is to keep ordinary order in metadata and reserve a continuation
  edge for verified logical continuation; this migration has not been implemented.

### D-031 — Curate measured results and archive unused experiments

- Date: 2026-10-04
- Status: ACTIVE repository organization; research statuses unchanged
- Scope: user-requested HoReKa2 experiment cleanup and result-to-pipeline registry.
- Decision: use `current/README.md` as the daily entrypoint. Keep stable parsing
  and structural nodes, v7 as the ongoing relation-first branch, v5 as its better
  completion-count comparator, bounded v4 and labelled multimodal v2 as limited
  candidates, the HoReKa2 member-asset 35B/122B comparison, split-taxonomy benchmarks,
  current edge inputs, embedding comparisons, ANN and exact-citation baselines.
- Evidence: `current/json/metrics.json` records values and SHA-256 hashes of original
  result files. v7's 29/49 complete pages do not dominate v5's 31/49; 34/49 pages
  are structurally valid in both. The 35B member-asset pilot is valid on 4/4 pages
  versus 2/4 for 122B. These limited results do not establish semantic superiority.
- Storage: rename unused experiments and independent old pilots under
  `_archive/2026-10-04/`, preserving original relative paths, a move journal and
  a non-overwriting restore command. Ignore that archive and `migration/` in Git.
  Keep referenced runtime/test code and required result/input dependencies.
- Production effect: no model inference, no changed prompts, thresholds, source
  geometry, ground truth or production graph. New HoReKa2 launchers write to
  distinct per-job output directories. No Git commit or source deletion requested.
- Limit: dependency scanning is conservative static reference analysis; the active
  import/test and 49-page preflight checks are recorded separately. Historical
  archived experiments may require restoration before execution. Frozen outputs
  retain original provenance paths; those strings are not portable run commands.

### D-032 — Bounded flow recovery and source-addressed retrieval windows

- Date: 2026-10-04
- Status: SHADOW; opt-in integration, no baseline promotion
- Decision: `--recovery-policy bounded-v1` permits one duplicate-occurrence
  assignment call with explicit abstention, followed by the original full flow
  validator. Missing IDs remain failures; no missing content is assigned to
  page furniture. Zero-text pages preserve visuals in a PAGE_CONTEXT item and
  require text recovery/review. Recovered pages remain partial and carry their
  recovery audit through checkpoints and the edge adapter.
- Local relations: validate the primary anchor first, retain independently valid
  supporting anchors, and log invalid extras. Primary-anchor and direct-caption
  safeguards remain mandatory. Rejected supporting spans keep the page partial.
- Retrieval: optionally tokenize long units into overlapping windows with exact
  offsets in unit text, retain original node endpoints, and aggregate by maximum
  window cosine. Recompute lexical candidates on the same eligible units; expose
  lexical/dense/hybrid lists with equal final pair budgets per scope.
- Evidence: 28 relevant tests passed. Frozen-response regression preserves all
  34 valid v7 flows, repairs five duplicate assignments, routes three zero-text
  pages, and leaves seven failures (42/49 structurally valid). Valid local links
  increase from 37 to 39 on identical saved proposals. This is neither a fresh
  49-page inference run nor independent semantic evaluation.
- Implementation and dev GPU launchers: see
  `EvidenceNet/docs/bounded_recovery_integration_2026-10-04.md` and `current/`.
- Production effect: none; independent outputs, defaults retained. No inferred
  window geometry, source-text edits, or verified cross-document edges.
- Limits: visual-only routing does not recover OCR; duplicate choices need
  semantic review; maximum-window scores can favor long units. Semantic recall
  and precision require independent labels under the matched pair budgets.

### D-033 — Source-span selection, reviewed visual roles and blind candidate review

- Date: 2026-10-04
- Status: SHADOW; opt-in implementation and isolated validation
- Decision: offer `--anchor-protocol span-id-v1` for local relations. The model
  selects IDs from exact candidate text spans; the program resolves offsets and
  copies source text. Unknown/wrong-unit IDs and mixed generated quotes fail.
  Existing caption constraints and bounded per-support rejection remain active.
- Visual roles: accept a source-reviewed map bound to full-page hash, crop hash
  and geometry. The two inspected Hallmarks sidebar marks are Europe PMC logos;
  preserve their components but skip semantic candidates. Explicit reviewer
  provenance is `assistant_visual_review`, not human GT. Unlisted visuals remain
  UNKNOWN; no size-based exclusion or general automatic classifier is implied.
- Review: sample independently from each matched 600-pair candidate arm and each
  scope, deduplicate, randomize order and endpoint orientation, and hide routes
  and scores in a separate evaluation directory. The 248-pair reviewer package
  includes source images and an exportable form. Save union inclusion probabilities
  and estimate yield with inverse-probability ratio weights after labels finish.
- Evidence: 37 relevant tests, JavaScript syntax validation, and two-page local
  runner/adapter checks passed. GPU job 45701 submitted for actual span selection.
  No independent semantic labels exist; source-address validity is not accuracy.
- Production effect: none. Default quote mode and original nodes/geometry remain;
  no new OCR or node segmentation. Model-only review cannot be claimed as human GT.
- Details: `EvidenceNet/docs/span_grounding_and_blind_review_2026-10-04.md`.

### D-034 — Reduce generated-file Git noise and archive superseded scripts

- Date: 2026-10-04
- Status: ACTIVE repository organization; pipeline policies unchanged
- Decision: ignore generated parsing audit subdirectories, Dolphin work/staged
  input directories, and locally installed vendor/ANN dependencies. Keep root
  audit scripts, experimental drivers, configuration, tests and current launchers
  visible to Git; retain all ignored runtime data at their existing paths.
- Archive seven untracked superseded exploratory scripts/launchers under
  `_archive/2026-10-04-superseded-scripts/`, preserving relative paths, content
  hashes and a non-overwriting restore command. No active code references or
  queued/running jobs depend on these files at cleanup time.
- Validation: all 49 input preflights pass; exact status counts and preservation
  checks are recorded in `current/GIT_CLEANUP.md`.
- Git effect: no commit, staging, index removal, reset or hiding of tracked
  changes. The 260 pre-existing tracked deletions remain visible; .gitignore
  cannot suppress them. Archive files are retained, not deleted.

### D-035 — Inventory all source pages and start latest-policy regression

- Date: 2026-10-04
- Status: SHADOW execution; full-page expansion pending engineering checks
- Scope: user-requested test of all documents in data. Inventory finds 25 source
  documents and 1048 source pages/slides/images, plus three metadata files.
- Decision: first run the latest bounded-v1/span-id-v1 policy on the existing
  49-page all-document regression set. Job 46209 has seven sequential two-GPU
  shards, two hours maximum each. Dependent job 46210 imports valid/partial pages
  and generates windowed/lexical/hybrid candidates. Outputs are isolated.
- Expansion: 483 parser-cache candidate pages require provenance verification;
  37 native PPTX slides match source hash but have rendering limitations. Source
  PDF page numbering must remain distinct from split-render numbering. Exact
  dense retrieval needs bounded-memory implementation before corpus expansion.
- Validation: 25 files readable, no exact file duplicates, all 1048 pages enumerated;
  previous 49-page source preflight passes. This is not 1048-page model completion.
- Limits: no new independent semantic labels; candidates are not verified edges.
  Details and job paths: `current/ALL_DATA_RUN.md`.

### D-036 — Bounded assignment patch and source-grounded semantic corrections

- Date: 2026-10-05
- Status: SHADOW implemented; local validation passed; GPU tests queued
- Decision: add bounded-v2 missing/duplicate assignment repair with exact typed
  source coverage, existing-item ownership, one additional model call, explicit
  abstention and original full validation. Invalid claims are removed with audit;
  real source text is never removed. Recovered pages remain partial/needs_review.
- Semantic audit: inspect all 42 local-edge texts and sources for 23 purposively
  selected edges. Assistant review finds 7 rejected associations, 3 needing better
  primary evidence, 3 uncertain, 10 supported. This is not independent human GT
  or a representative precision estimate; 19 edges lack full source visual review.
- Correction: opt-in span-id-v2 keeps caption prefixes/abbreviations attached to
  description, rejects marker/short-photo-credit primaries, and requires a basis
  supported by the primary evidence. Add hash-bound reviewed KIT/EIS logo roles.
- Validation: 40 relevant tests; all 49 local pipeline checks. Frozen replay leaves
  41 valid flows unchanged and repairs two failures without inference. Jobs 48023
  (8 failed flows) and 48027 (10 semantic pages) are queued sequentially on dev.
  GPU outcomes are not yet available; no promotion or full-data expansion.
- Details: `EvidenceNet/docs/assignment_patch_and_semantics_2026-10-05.md`.

### D-037 — Reject prompt-only promotion and archive completed experiments

- Date: 2026-10-06
- Status: SHADOW evaluated, NOT PASSED; no broader GPU submission
- User authorization: try revised prompts, evaluate, submit broader testing only
  if the result is good, and archive previous experiment records.
- Change: add optional grounded-v3 general target/evidence/relationship decision
  prompt. Keep legacy default. Freeze page/crop, reading flow, candidates, v2
  spans, validation and decoding; only the prompt differs in GPU job 52533.
- Evidence: 12 cases per arm, both completed; 32 accepted edges source-reviewed
  by the assistant. Legacy→v3: accepted 19→13, supported 13→9, unsupported 3→3,
  uncertain 3→1; positive visuals 7/7→6/7. V3 also proposes one wrong-unit support
  span rejected by validation. Counts are diagnostic, not independent accuracy.
- Decision: no promotion or expanded run. A prepared 49-page launcher checks the
  explicit review gate and exits when it has not passed. No 1048-page job submitted.
  Next proposed work separates target-crop verification from page-layout context;
  it is not claimed implemented or validated here.
- Prior outcomes: 48023 structurally repaired 5/8 failed responses; 48027 completed
  nine pages and failed one flow. Do not count that missing page as semantic gain.
- Archive: 12 completed experiment directories + 4 logs, 1,441 files, every regular
  file hash verified. Rename under `_archive/2026-10-06-experiments/` and leave
  old-path aliases; keep active baseline/input/comparison artifacts. Restore via
  `current/archive_recent_experiments.py --restore`; no deletion or Git commit.
- Validation: 42 relevant tests, syntax/compilation, matched execution-code hashes,
  archive integrity and relative-symlink restore smoke check.
- Details: `EvidenceNet/docs/prompt_comparison_and_archive_2026-10-06.md`.
