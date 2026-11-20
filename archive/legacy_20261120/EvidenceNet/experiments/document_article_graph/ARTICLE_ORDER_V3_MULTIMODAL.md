# V3: separate composition from text–visual relations

## Result of GPU 80131

Review correction after user feedback: **A006/V001 is a valid same-specific-subject
connection**, since A006's `the ground` refers to the pictured Al-Ahly Stadium.
It is now retained as symmetric RELATED, distinct from the three feature-level
ILLUSTRATES relations. It does not claim that the interior rendering depicts
or proves the whole sports-city masterplan. The earlier **25% false-edge
claim is withdrawn**; that confused illustration scope with edge existence.
The source review and standalone viewer are updated; previous review files
are archived in `page_2/review_history/`. Original model responses, frozen
narrow references and comparison metrics remain historical and unchanged.

The job finished after **4m20s**, with overall exit 1 because one of 11
visual decisions failed source-excerpt validation. **All four node-generation
conditions completed**, with zero invalid attempts and every atom, fragment,
visual and native component accounted for exactly once. This is distinct
from V2's four failed composition conditions.

Article membership, title ownership and raw BODY order match the partial
CLAD references in every condition (11/11 sources, 2/2 titles, 7/7 reading
constraints). Both known continuation candidates are now available. Final
continuation recovery is 1/2 for article-first original/reversed, 2/2 for
reading-first original, and 1/2 for reading-first reversed. Importantly,
the original article-first and reading-first BODY requests have the **same
prompt/image fingerprint** (`23480d8dbd131ef6`) but different responses on
the quoted continuation. Greedy configuration therefore did not yield
identical output in this run. The difference cannot be attributed to stage
order; do not select a winner from these counts. A shared cache for identical
downstream requests would remove this confound in a later comparison.

Visual verification produced **10 valid decisions / 11 pairs**, with four
accepted ILLUSTRATES proposals, six rejected pairs and one format-pending
pair. Both frozen feature positives were accepted. Of the five frozen hard
negatives, four were rejected and one falsely accepted. The two swapped
project images were both rejected. These tiny, partially annotated counts
are diagnostic, not a precision estimate over the corpus; no other visual
relation type was validated by this page.

Source review of all four accepted proposals:

| Text / image | Review |
| --- | --- |
| A004 / V001 | Keep: sunken arena depiction |
| A006 / V001 | Keep as RELATED: same Al-Ahly Stadium, resolved through the title and preceding paragraph; does not illustrate the wider masterplan |
| A011 / V002 | Keep tent-form correspondence; does not prove the asserted cultural/historical origin |
| A012 / V002 | Keep tented-roof shape; material, translucency and platform height are not visually established |

Original proposals remain in `visual_semantic_edges.jsonl`. Separate
`reviewed_visual_semantic_edges.jsonl` files now contain three scoped
ILLUSTRATES edges and one symmetric RELATED edge per condition. `page_2/source_review.json` records
review decisions and corrections to two rejection reasons: ILLUSTRATES
does not require literal entity-name overlap or an explicit figure reference.
Nothing was promoted to the production graph.

The pending A008/V002 decision exposes an interface issue: the parser has
`forth-\ncoming`, while both generated excerpts use `forthcoming`. Exact
normalized substring matching rejects that harmless line-wrap repair.
It is counted as format pending, not a semantic false negative. Future
verification should use source-owned span IDs or a mapped dehyphenated
view, retaining the original source, instead of repeatedly copying excerpts.

The broader semantic distinction is visible in A006: shared specific stadium
identity establishes a useful navigation edge, while it does not establish
the specific wider-masterplan assertion. The next
verifier should separate depicted-feature correspondence from shared-entity
navigation, and check the supported subclaim rather than allowing an entire
paragraph to inherit support. The current pilot verifies raw source blocks
and maps the grounded decisions to final evidence nodes; final-node context
verification remains necessary before treating this as a general edge stage.

## Implementation and frozen protocol

### Interactive result viewer

Build the standalone HTML with:

```bash
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/build_article_order_review_viewer.py
```

Output: `EvidenceNet/output/article_reading_order_comparison_v3_gpu_20261015/viewer/index.html`.
The original page and both original crop files are embedded byte-for-byte,
with hash checks, so no local server or separate asset directory is needed.
It shows four condition variants, exact source members, structural titles,
article clusters, actual NEXT edges, scoped reviewed visual edges, the
rejected model edge and all 11 pair decisions. The default is article-first
original input, not the condition with the best continuation recovery.

The page overlay uses the original 1000×1276 coordinate space in an SVG
covering the image itself; separate source boxes are retained for merged
nodes. Chromium checks passed for node/edge details, condition switching,
all decision records, article filtering, title retention, zoom alignment
and narrow viewports, with no page errors. Checks and preview are saved as
`viewer/browser_check.json` and `viewer/preview.png`.

2026-10-15. User requested the next repair and emphasized that text/image
relations extend beyond captions. This isolated CLAD smoke retains V1/V2
records and production behavior. Entry point:
`EvidenceNet/scripts/compare_article_reading_order_v3.py`.

## Node composition

The two stage orders still share frozen roles, embeddings, descriptions,
model, source image, references and downstream rules. Both original and
reversed input presentations run, giving four conditions on page index 2.
New output: `EvidenceNet/output/article_reading_order_comparison_v3_gpu_20261015/`.

Submitted GPU job **80131**, launcher
`current/slurm/evidence_nodes/article_reading_v3_gpu_1h.sbatch`.
Actual-source preflight confirmed both CLAD continuation reference pairs
survive candidate filtering (2/2), zero caption candidates and nine same-article
text/visual pairs. This preflight is not a model inference result.

BODY continuation and actual CAPTION figure scope are separate tasks with
separate checkpoints and allowed-ID lists. Empty candidate tasks return an
audited deterministic empty value without inference. Unknown/extra IDs still
fail validation, with exact missing/extra IDs provided on retry; no invented
rows are silently removed. BODY requests expose only candidate endpoints,
not image-credit labels or unrelated sources. Page images remain available.

A bounded syntactic exception admits a short quoted term completing an
unfinished phrase, such as `known as a` → `"moussen" — ...`. It permits review,
not automatic merging. Closed sentences, independent new quotations and the
existing CERN A023→A024 negative remain blocked. Source traversal and exact
accounting checks remain mandatory.

## Independent text–visual edges

BODY-to-image association never merges those evidence nodes. Same-article
ownership routes candidates; per visual, at most six BODY/CAPTION blocks are
retrieved by frozen embedding cosine, with source-ID tie breaking. Whole-page
all-pairs comparison is not used for large pages. Candidate recall remains a
separate limitation: this smoke has only nine same-article text/visual pairs.

Verification sees exactly one original crop, existing Qwen description and
one original text block, without article membership or other images. Source
pair decisions are cached once and mapped to the final evidence-node IDs in
each condition. This common downstream diagnostic is not an independent
four-arm semantic experiment. Accepted primary relations are:

| Relation | Direction | Required correspondence |
| --- | --- | --- |
| CAPTION_FOR | Text → visual | Actual CAPTION role, direct figure description |
| REFERENCES | Text → visual | Explicit figure/table marker matching the visible target |
| EXPLAINS | Text → visual | Explanation of a specific visible mechanism/encoding |
| ILLUSTRATES | Visual → text | Depiction of a specific feature/example asserted in text |
| SUPPORTS | Visual → text | Legible visual data supporting the textual result |

Only one primary relation is selected in this pilot. A stadium rendering
can illustrate a sunken pitch or tented roof; it does not prove promised
capacity, opening date, future club ownership or economic growth. Common
topic, name, membership or proximity alone is insufficient. ACCEPT requires
an exact text excerpt and a visible-feature anchor; caption roles/directions
and explicit reference markers are checked. Visual anchor truth still needs
source review and is exported as `MODEL_PROPOSED_REQUIRES_SOURCE_REVIEW`.

`visual_semantic_edges.jsonl` contains node-to-node proposals with raw-source
grounding. Multiple accepted source blocks mapping to one final node produce
one edge per relation with multiple grounding records. A caption already
inside a composite is recorded in `internal_visual_relations.jsonl`, avoiding
self edges. Source nodes remain intact; metadata and cross-article pairs
cannot enter these article-local edge exports.

## Small diagnostic references and completion

Frozen before inference and excluded from prompts: two source-reviewed
positive feature pairs (A004/V001 sunken pitch, A012/V002 tented roof), three
same-article unsupported-fact negatives, and two swapped-project image
negatives. The swapped pairs are evaluated but explicitly ineligible for
graph export even if accepted by the classifier. These are partial assistant
development annotations, dependent on the strict content-correspondence
definition, not a holdout benchmark or retrieval-quality evaluation.

Inspect all four condition summaries, source accounting, continuation
recovery, `page_2/visual_summary.json` and original crops before expanding.
The main report retains the 16-condition full-comparison accounting and adds
`smoke_complete` for the four submitted conditions. Model-valid visual output
does not by itself establish correct semantic edges.

183 tests passed: tracked suite plus article experiment tests, including
quoted-term candidate/assembly regression, empty-task no-inference behavior,
extra-ID rejection, metadata exclusion, source anchoring, direction/role
checks, cross-article export prevention, merging-edge grounding and internal
composite relations. Launcher syntax and source preparation are checked
before submission. GPU resource ceiling: one GPU, one hour.
