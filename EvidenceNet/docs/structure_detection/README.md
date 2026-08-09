# Document Structure Detection and Segmentation Routing

## Purpose

EvidenceNet must decide whether a document is:

- `SINGLE_STRUCTURED_WORK`: one work containing internal sections, figures, references, or other components; or
- `MULTI_ITEM_COLLECTION`: several independent works, such as articles in a magazine.

Only a `MULTI_ITEM_COLLECTION` is passed to content-item segmentation. Every other document is
preserved as one top-level item. This prevents a scientific paper from being split into separate
items at its figures, acknowledgments, references, author list, or affiliations.

The detector is deterministic and document-local. It does not call an LLM or VLM, does not require
the user to supply a document type, and does not modify Evidence nodes or structural edges.

## Pipeline position

```text
Source parsing
  → Evidence-node generation
  → structural QA
  → document structure profiling
      ├── SINGLE_STRUCTURED_WORK
      │     → preserve one top-level content item
      │     → retain existing internal sections
      └── MULTI_ITEM_COLLECTION
            → generate document-local embeddings
            → run content-item segmentation
            → run title and global boundary refinement
  → semantic candidate generation and verification
```

The implementation is in:

- `evidence_graph/structure_profile.py`: feature extraction, scoring, and binary decision;
- `evidence_graph/structure_routed_segmentation.py`: application of the decision to all completed
  Evidence graphs.

## Input

The profiler consumes a document's `evidence_nodes.jsonl`. It uses these existing fields:

- `document_order`
- `section_path`
- `plain_text`

Nodes are sorted by `document_order`. Consecutive nodes with the same non-empty `section_path` form
a section run.

## Extracted features

### Continuous numbered-section hierarchy

The detector extracts top-level Roman or Arabic section numbers.

Roman sequences are considered monotonic when at least three values increase, for example:

```text
I. INTRODUCTION
II. OBSERVATION
III. DETECTORS
...
VIII. CONCLUSION
```

Arabic sequences must be continuous and start at 1, for example `1, 2, 3, 4`. This stricter rule
prevents unrelated numbered magazine headings such as `1, 2, 3, 5, 6, 7` from imitating a paper
hierarchy.

### Scholarly front sequence

The first portion of the section sequence is checked for:

- `Abstract`; and
- `Introduction` or `Keywords`.

Their joint presence supports a single structured work.

### Citation continuity

`citation_node_density` is the fraction of Evidence nodes containing bracketed citations such as:

```text
[12]
[4–7]
[4, 8, 12]
```

A citation system repeated throughout a document strongly supports a single scholarly work.

### Terminal scholarly matter

The final 35% of the document is checked for:

- acknowledgments;
- references;
- bibliography;
- appendices; or
- a sufficiently dense sequence of reference entries beginning with `[number]`.

This is supporting evidence only; it cannot determine the profile by itself because magazines may
also contain the word “references.”

### Section-run statistics

The profiler measures:

- number of unique section paths;
- number of consecutive section runs;
- average Evidence nodes per section run;
- section transition rate; and
- unique-heading density.

Many short, rapidly changing, non-scholarly heading runs support a multi-item collection. Long,
stable runs support a single structured work.

### Single unbroken structure

A document with at least 50 nodes and no more than one detected section receives modest
single-work support. This safely handles papers whose section extraction failed while their nodes
still form one continuous document.

## Scores

The profiler calculates two auditable scores.

### Single-work score

| Component | Maximum weight |
|---|---:|
| Monotonic numbered sections | 0.28 |
| Abstract/introduction front sequence | 0.18 |
| Citation continuity | 0.28 |
| Terminal scholarly matter | 0.13 |
| Long section runs | 0.08 |
| Low section churn | 0.05 |
| Single unbroken section system | 0.12 |

### Multi-item score

| Component | Maximum weight |
|---|---:|
| Many independent headings | 0.30 |
| Short heading runs | 0.22 |
| High section churn | 0.20 |
| Heading density | 0.16 |
| Non-scholarly heading resets | 0.12 |

Multi-item components are reduced when a continuous numbered hierarchy, scholarly front sequence,
or dense citation system is present. This prevents a long paper with many subsections from being
mistaken for a magazine.

The exact component contributions are included in every output report under `score_components`.

## Binary decision and safe default

A document is classified as `MULTI_ITEM_COLLECTION` only when:

```text
multi_item_score >= 0.62
and
multi_item_score - single_work_score >= 0.15
```

Otherwise it is classified as `SINGLE_STRUCTURED_WORK`.

This asymmetry is intentional. A false multi-item classification can destructively restrict graph
construction by placing one work into unrelated items. Preserving a genuine collection under one
common parent is safer: tentative boundaries and semantic edges can still be retained.

The report records why the decision was made:

- `strong_multi_item_evidence`
- `strong_single_work_evidence`
- `conservative_default_no_strong_multi_item_evidence`

Low-confidence documents therefore remain visible for evaluation without requiring a third
`UNKNOWN` routing state.

## Downstream behavior

### `SINGLE_STRUCTURED_WORK`

All Evidence nodes receive the same top-level assignment:

```json
{
  "segment_id": "SEGMENT_0001",
  "content_item_id": "ITEM_0001"
}
```

Existing section paths and structural edges remain unchanged. Semantic candidate generation may
operate across internal sections because they belong to the same work.

### `MULTI_ITEM_COLLECTION`

The routing runner generates document-local embeddings and invokes the page-aware content-item
separator. The separator may subsequently use title-context validation and global merge
refinement. Advertisements are treated as ordinary topic-shifting content, not as a special class.

## Output schema

Example scientific-paper profile:

```json
{
  "profile": "SINGLE_STRUCTURED_WORK",
  "inferred_type": "scientific_paper_like",
  "confidence": 0.8102,
  "scores": {
    "single_structured_work": 0.8102,
    "multi_item_collection": 0.0267,
    "margin": 0.7835
  },
  "pipeline_action": "PRESERVE_ONE_TOP_LEVEL_ITEM",
  "decision_basis": "strong_single_work_evidence",
  "uses_llm_or_vlm": false
}
```

Example magazine profile:

```json
{
  "profile": "MULTI_ITEM_COLLECTION",
  "inferred_type": "periodical_or_collection_like",
  "pipeline_action": "RUN_CONTENT_ITEM_SEGMENTATION",
  "decision_basis": "strong_multi_item_evidence",
  "uses_llm_or_vlm": false
}
```

`inferred_type` is descriptive metadata only. Routing depends on `profile`, not on whether the
document is explicitly called a paper, magazine, slide deck, report, or booklet.

## Commands

Profile one document:

```bash
python -m evidence_graph.structure_profile \
  --nodes output/evidence_graph/gw150914_detection/evidence_nodes.jsonl \
  --output output/structure_profiles/gw150914_detection.json
```

Apply completed profiles to all Evidence graphs:

```bash
python -m evidence_graph.structure_routed_segmentation \
  --graph-root output/evidence_graph \
  --profile-root output/structure_profiles \
  --aligned-root ../parsing/output/hybrid_deepseek_layout_split_render/aligned_json \
  --output-root output/structure_routed_segmentation
```

The batch summary is written to:

```text
output/structure_routed_segmentation/summary.json
```

## Current Qwen 2.5 test result

Thirteen completed graphs were profiled with the same rules.

`MULTI_ITEM_COLLECTION`:

- CERN Courier 2022
- CERN Courier 2025
- CERN Courier 2026

`SINGLE_STRUCTURED_WORK`:

- CyberPhysicalModeling Chapter 4
- Growth Regressions for Country Analysis
- Luminous Garden
- Climate Change with Machine Learning
- DETR
- A Mathematical Theory of Communication
- three GW150914 papers
- Hallmarks of Aging

Only the three magazines were routed into content-item segmentation.

## Limitations

- The thresholds have been evaluated on a small collection and require validation on more document
  families.
- Citation detection currently focuses on bracketed numeric citations. Author-year citations and
  historical citation formats require additional patterns.
- Proceedings containing multiple papers need repeated title/author/abstract/reference-cycle
  detection.
- Missing or incorrect `section_path` values weaken the profile.
- A slide deck and a chapter can receive a conservative single-work default even when their
  descriptive type remains `unspecified`; this is intentional routing behavior.
- Structure profiling decides whether top-level separation is allowed. It does not validate every
  internal section or guarantee that magazine boundaries are correct.

The Evidence nodes and structural graph remain authoritative and unchanged throughout profiling and
routing.
