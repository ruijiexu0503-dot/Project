# Current pipeline map

Post-node integration update (2026-10-21): see
[current/EDGE_PIPELINE.md](current/EDGE_PIPELINE.md) for the reusable edge entrypoint,
Qwen3-Embedding-8B selection from the newer matched comparisons, conservative
candidate allocation, multimodal verification and isolated proposal/review exports.
This supersedes the older 0.6B recommendation for NEW edge retrieval runs only;
upstream node generation and frozen experiments remain unchanged.

Last reconciled: **2026-10-18**. This document is the operational map for new
work. [`PIPELINE_STEPS.md`](PIPELINE_STEPS.md) retains detailed contracts and
[`PIPELINE_DECISIONS.md`](PIPELINE_DECISIONS.md) retains the decision history.

The promoted hybrid document path is summarized in
[`current/MAIN_PIPELINE.md`](current/MAIN_PIPELINE.md). It adds a lossless Dolphin
text contract (`text` for provenance, `semantic_text` for inference), hybrid
EvidenceNode generation, Qwen article membership and separately validated
within-article reading order. Semantic edge generation starts after this handoff
and remains on `feature/evidence-edges`.

The current retrieval experiment uses Dolphin official page-image parsing and
the opt-in hybrid-v2 EvidenceNode branch (embedding + geometry + bounded Qwen).
The paired 49-page v2 regression completed: both arms passed structural coverage,
blocked all 15 known wrong joins and retained all 3 table atoms. The embedding
arm retained 2/2 specified mixed-material continuations; the geometry arm retained
0/2. Both still miss a reviewed cross-figure continuation and leak one slide
headline. Boundary v3 failed validation and is not the selected experiment path.
These are development regressions, not independent accuracy measurements.

The [VL-DocIR pilot](EvidenceNet/experiments/vldocir/README.md) schedules complete
parsing, EvidenceNode generation and matched retrieval controls on 24 queries /
518 pages. Full scores are pending. Existing article/NEXT/semantic graphs use
component IDs and still require adaptation to hybrid EvidenceNode IDs; this
retrieval comparison does not include graph expansion. Default Step-2A remains
unchanged. Earlier experiments below explain the development history.

Matched three-page node-generation pilot: Qwen3.5-9B, Qwen3.5-35B-A3B,
Qwen3.5-122B-A10B, Qwen3.6-35B-A3B, and a Qwen-assisted embedding+geometry
baseline were compared on source-addressed node roles, caption attachments,
and sentence continuations. The conservative baseline avoided broad merges but
missed both reviewed continuations; Qwen3.5-35B passed all three assembly-schema
checks but still leaked headings and overmerged the photo article. Embedding made
no observable node decision difference on these three pages. No production
promotion. See the [matched comparison](EvidenceNet/docs/matched_node_generation_comparison_2026-10-06.md).

An opt-in bounded hybrid member-asset node branch is now available at
[`step2_b_hybrid_member_nodes.py`](EvidenceNet/pipeline_steps/step2_b_hybrid_member_nodes.py).
The four-page shadow pilot improved reviewed structure/continuation errors
without adding reviewed false merges or caption errors, including one held-out
GW page. One continuation remains missed. The active deterministic Step-2A path
is unchanged; the branch requires explicit invocation and complete source/member
validation. See the [hybrid pilot](EvidenceNet/docs/hybrid_node_generation_pilot_2026-10-07.md).
The subsequent [seven-material shadow check](EvidenceNet/docs/hybrid_node_mixed_material_pilot_2026-10-07.md)
joined two additional cross-column continuations but also merged one colon-led
annual-report list under the strict same-sentence policy. Table atoms still remain
outside retrievable evidence nodes, and slide headlines need their own role handling.
This prevents default promotion.
The larger [49-page v7 stress run](EvidenceNet/docs/hybrid_node_49page_stress_2026-10-07.md)
completed with source coverage and valid Qwen decisions on every page, but at
least 15 of 71 added joins were source-reviewed as incorrect under the strict
same-sentence policy, and all three table atoms remained outside retrievable
nodes. The default path remains unchanged.

Earlier decision (D-037): the opt-in grounded-v3 prompt **did not pass** the matched
12-visual GPU comparison (52533). Clearly unsupported accepted edges stayed 3→3;
supported edges dropped 13→9 and clean positive controls 7/7→6/7. Keep the legacy
prompt default; no broader run was submitted. These are assistant-reviewed
diagnostic cases, not independent precision estimates. Prior jobs are complete:
48023 repaired 5/8 frozen failed flows; 48027 had nine complete pages and one flow
failure. Twelve completed experiment directories and four logs are now archived
with verified hashes and old-path aliases. See the
[comparison and archive report](EvidenceNet/docs/prompt_comparison_and_archive_2026-10-06.md).

## Selected results and repository organization (D-031)

Start with [`current/README.md`](current/README.md) for the result-to-pipeline map,
measured comparisons and HoReKa2 launchers. Metrics are extracted from existing
files with source hashes in `current/json/metrics.json`; this cleanup ran no inference.

- The current 49-page v7 run has **29 complete, 5 partial, 15 flow-failed** pages.
  v5 has **31 complete, 3 partial, 15 flow-failed**. Both are retained; differing
  validation policies prevent interpreting completion count as semantic accuracy.
- The retained bounded v4 candidate passes structural checks on 5/5 pages, with
  semantic review still pending. Labelled multimodal v2 passes coverage on 2/2.
- HoReKa2 member-asset 35B passes 4/4 pages; 122B passes 2/4, with one generation
  failure. Prefer the 35B pilot for this matched run, without claiming corpus-wide
  semantic superiority.
- The v7 edge adapter imports 34 pages and exposes 431 units, 37 local relations,
  and 2,403 candidates; it does not produce verified cross-document edges.
- The 94-unit embedding benchmark favors Qwen3-Embedding-0.6B on its exact-unit
  recovery proxy. Keep all comparison arms and the BGE-based ANN baseline.

Unselected historical artifacts and their unneeded launchers/scripts are now
under `_archive/2026-10-04/` at their original relative paths. Required imports,
test dependencies and retained input/provenance roots stay in place. Consult
`current/json/archive-plan.json` for any historical path below; the historical notes
are not a promise that every superseded directory remains at the old location.
No shadow method is promoted to production by this reorganization.

## What is currently safe to call the baseline

```text
source document
  -> existing rendered-page input root
  -> DeepSeekOCR2 + PP-DocLayout + provenance-checked alignment
  -> aligned page blocks / geometry_members
  -> deterministic EvidenceNode build (configuration-gated template keys)
  -> structural graph and audit
```

This baseline preserves geometry provenance. It is not yet the final magazine
reconstruction system: it does not claim validated article boundaries,
cross-page merges, visual ownership, or semantic edges.

Source-capability routing and reversible per-page view selection are target
preprocessing stages; the Step-1 runner does not yet invoke them automatically.

| Stage | Baseline entrypoint / output | Status |
|---|---|---|
| Source capability route | `parsing/src/visual_source_capabilities.py` | active contract |
| Reversible source-page routing | `EvidenceNet/scripts/audit_hybrid_spread_routing.py` | shadow; accepted design |
| DeepSeek parse → layout → alignment → export | `parsing/pipeline_steps/step1_run_parsing_pipeline.sbatch` | active |
| Deterministic node build | `EvidenceNet/pipeline_steps/step2_a_evidencenet_build_nodes.py` | active |
| Safe recurring-template interface | `EvidenceNet/scripts/materialize_safe_template_keys.py` | config-gated; detector shadow |
| Structural validation / visualization | `python -m evidence_graph validate` / `visualize` | active |

## Data contracts that every branch must preserve

1. A source page remains the authoritative canvas. Split/crop views are
   reversible inference views with a transform back to it.
2. A logical OCR block may have several `geometry_members`; do not fabricate a
   union bbox or zip text fragments to members.
3. Text spans may be split only with parent block ID and exact character offsets.
   Span geometry stays `source_block_only_no_fragment_bbox` unless independently
   observed.
4. Native PDF visual members, raster masks, vector drawings and parser boxes are
   different evidence types. Zero raster assets does not mean zero visuals.
5. Unresolved, structural, advertisement and suspicious-template material stays
   addressable. Only a mapped `SAFE_TEMPLATE` may be excluded through
   `template_keys`.
6. Every shadow output must state its input root, parser/view route, model,
   validation status, and `production_modified: false`.

## Shadow branches — do not chain them as if they were production

D-033: opt-in `span-id-v1` replaces generated quotations with source-addressed
evidence selection; caption/association safeguards remain mandatory. A reviewed
visual-role map binds decisions to page/crop hashes and geometry; two inspected
logos are excluded from semantic candidates while retaining their components.
Unreviewed visuals remain UNKNOWN. A 248-pair blind review package hides routes
and preserves union sampling probabilities for matched-budget yield estimation.
No semantic labels yet. Details and GPU status:
[`report`](EvidenceNet/docs/span_grounding_and_blind_review_2026-10-04.md).

D-032: opt-in `bounded-v1` integrates one bounded duplicate repair, explicit
zero-text visual routing, and independently validated supporting anchors.
Recovered pages remain partial with review metadata. Windowed dense retrieval
keeps exact unit-text offsets and offers matched lexical/dense/hybrid budgets.
Frozen-response regression: 34 valid flows unchanged, five duplicate repairs,
three visual-only routes, seven failures; local relations 37 → 39. These are
structural checks, not semantic accuracy. Implementation, GPU checks and commands:
[`integration report`](EvidenceNet/docs/bounded_recovery_integration_2026-10-04.md).

D-030: v7 CPU shadow validates relation records individually and logs rejected
records without discarding valid sibling relations. Mixed results remain partial.
All direct captions require target-specific layout justification and attachment
type (standalone_target or explicit_shared_panel); the prompt includes both fields
in its output template. Same 49-page manifest, matching validated v6 flows reused,
one attempt per inference, no automatic resubmission. Output: `relation_first_corpus_shadow_v7_cpu/`.

D-029: v6 CPU shadow removes hard content-item ownership filtering for nearby
text (normalized gap <= 0.15, geometry score <= 0.35; at most nine candidates).
Body-flow text cannot be CAPTION_FOR. Long page-furniture fragments can be
reviewed as captions with explicit layout justification, without relabeling or
duplicating their original structural nodes. OCR is unchanged. The 49-page
launcher reuses matching validated v5 flows; each new inference still gets one
attempt and failures do not abort the batch. Output: `relation_first_corpus_shadow_v6_cpu/`.
Twelve runner tests plus seven bounded-composite tests passed before submission.

D-028 supersedes the fail-fast rollout: job array 5171057 processes all 49 pages
on CPU in two sequential shards, recording validation failures and continuing.
Each flow/visual defaults to one model attempt; resume skips recorded failures.
Same-pair source claims become supporting spans of one relation. Outputs under
`relation_first_corpus_shadow_v5_cpu/shard_*/` distinguish batch completion from
page validation success. Ten tests and all 49 input preflights passed.

D-027: full CPU evidence processing is submitted as job 5171031 for GW150914
page 2 and DLR pages 9/12. Output is `relation_first_corpus_shadow_v4_cpu/`.
This is the first full-pipeline CPU run; broader 49-page execution awaits review.

D-026: Qwen3.5-35B-A3B completed short text and image inference on pure CPU in
job 5171018. FP32 / 32 threads: image generation 17.275 seconds for 42 tokens
including prefill, peak process RSS 196.888 GiB. The runner now accepts explicit
CPU configuration; full evidence-page performance and quality still need testing.

D-025: the D-024 parser completed, but Qwen shard 0 failed all nine processed
pages and timed out. Shards 1/2 were quota-blocked and are now held. Project GPU
usage is 193122/180000 granted hours. Flow-prompt/schema and checkpoint fixes
passed local tests; the three-page v4 smoke launcher awaits additional GPU
allocation. It has not yet been validated by a real model run.

Relation-first retry D-024 samples 25 sources / 49 pages, preserving independent
components and source-anchored links. Its preflight and local-check results are
engineering checks only, not evidence of association accuracy. GPU results will
be written under `EvidenceNet/output/relation_first_corpus_shadow_v3/shard_*/`.
The earlier cross-corpus job 5169484 failed before any final evidence page;
5170705 was canceled for inspection. See D-024 for limitations and execution.

| Branch | Question | Latest result | Current disposition |
|---|---|---|---|
| Dolphin-v2 matched parsing | Can Dolphin replace DeepSeek on identical views? | Useful types/geometry, but quality differs by document and overlay text needs separate recovery. | evaluating parser branch |
| PDF-native / layer assets | Can hidden/overlapped visual components be retained? | Works for born-digital PDF assets; cannot recover hidden layers from raster input and does not cover vector-only figures by itself. | shadow enrichment |
| Page route (split vs intact) | Is a source page a normal spread or cross-gutter composition? | DLR five-page audit supports per-page reversible routing. | shadow design, not runner default |
| Article/reading-flow reconstruction | Can Qwen form content items and local reading flows? | `flow_first_evidence_pilot_v3_page009` is valid for one difficult page; not yet cross-document evidence. | leading reconstruction candidate, still shadow |
| Composite caption/visual assembly | Can caption + native panel form a safe composite EvidenceNode? | Latest recomposed v3 completed but all 3 pages failed validator. | diagnostic only; do not promote |
| Joint article/order/node prompt | Can one Qwen response do all three decisions? | v3 completed, but only 4/7 tasks validated; mixed OCR spans and repeated ledgers exposed schema failure. | frozen diagnostic; do not use as baseline |
| Pairwise embedding order | Can BGE/geometry rank a successor? | useful audit signal only; no global decode or production writeback. | frozen audit |
| Cross-page continuation | Can page endings be joined generically? | candidate/audit work only. | shadow |
| Internal semantic relations | Can retrieved node pairs form edges? | coarse taxonomy and independent `REFERENCES` are benchmark/shadow only. | shadow |
| Cross-document `CITES` / `RELATED` | Can papers/magazines connect across documents? | exact citation and bounded discovery remain isolated under `OfflineCitationGraph/` and `EdgeGeneration/`. | shadow |

## The reconstruction branch to continue

Do **not** ask one response to maintain duplicated ownership lists, reading-order
lists, node membership lists, and caption-binding lists. The joint-boundary v3
failure showed that Qwen can identify a caption or mixed span while emitting an
internally inconsistent ledger.

The next controlled experiment should use the `flow-first` decomposition:

```text
aligned blocks + visual-panel proposals
  -> one Qwen call: article ownership + ordered reading flows
  -> validator: exact one-time source disposition and continuation adjacency
  -> deterministic text candidates within each flow (preserve sentence continuations)
  -> bounded Qwen decisions: one visual and candidate captions at a time
  -> deterministic assembly of TEXT / VISUAL / COMPOSITE nodes
  -> validator: node coverage, caption/panel consistency, no split sentence
```

This is not a return to page-wide geometric order. It keeps article ownership,
within-article reading flow, and node boundary distinct, while avoiding mutually
redundant output representations. A later version may combine the two calls only
after this representation validates across documents.

Coverage validation is not semantic validation. A structural `other` assignment
must remain an addressable UNRESOLVED text candidate, not leave the evidence
inventory. Caption roles and image associations need source review even when
coverage passes. Ambiguous or conflicting associations retain standalone nodes.

The controlled assembly regression is
`EvidenceNet/scripts/run_bounded_composite_pilot.py`: it reuses the frozen v3
reading flows, restores uncertain structural text, and tests bounded caption
binding on pages 9/12/17. The v2 shadow run adds a second association audit,
distinct exact source anchors for shared captions, and direct explanatory prose
candidates when no caption candidates exist. Suspect text remains UNRESOLVED;
all experimental nodes remain retrieval-ineligible pending semantic review.
It does not establish reading-flow correctness or
general visual fallback coverage.

The v3 geometry shadow regression adds member-level edge distance, alignment and
intervening-content hints to bounded candidate selection. Whitespace-only quote
normalization preserves exact source spans. Geometry-only links remain pending,
not merged. It also runs Dolphin GW150914 pages 2/4 with newly inferred Qwen
reading flows and existing complete-figure crops. This is not a new native-image
extraction route; transparent-member boxes remain approximate spatial support.

Relevant scripts are `EvidenceNet/scripts/run_flow_first_evidence_pilot.py`,
`run_semantic_panel_evidence_pilot.py`, and
`run_composite_evidence_pilot.py`. The latter two are input/panel variants, not
separate production pipelines.

## Output naming and repository organization

- `parsing/output/`: parser and aligned-page outputs.
- `parsing/audits/`: source-capability, native-layer, mask and provenance audits.
- `EvidenceNet/output/evidence_graph/<doc>/`: baseline graph outputs.
- `EvidenceNet/output/<experiment_name>/`: isolated reconstruction, footer,
  parser, or semantic experiments. Never use as an implicit upstream input.
- `EvidenceNet/scripts/` and `EvidenceNet/slurm/` remain flat for now because
  retained launchers encode paths. Superseded scripts/launchers and results are
  grouped under `_archive/2026-10-04/`; `current/` is the curated entrypoint.

## Explicit non-goals for the current baseline

- Do not make Dolphin the default parser yet.
- Do not make page splitting, template exclusion, article grouping, cross-page
  merging, visual descriptions, or semantic edges production defaults.
- Do not delete advertisements based on classifier role.
- Do not use `NEXT`/`PREVIOUS` as semantic edges; ordinary sequence belongs in
  metadata, and logical continuation needs separate proof.
