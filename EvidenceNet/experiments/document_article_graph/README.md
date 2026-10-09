# Document article graph shadow stage

Updated 2026-10-09. The commands below consume component-based relation-first
snapshots. This adapter has not been switched to the hybrid-v2 `evidence_nodes.jsonl`
IDs, and the VL-DocIR node retrieval experiment does not use these graph edges.
Headings are structural context; footer/page-number components are excluded evidence.

This stage keeps three concepts separate:

- `article_id` is node membership metadata;
- reading order is a directed `NEXT` edge inside one article;
- semantic relations are generated downstream and may only connect nodes with the same explicit `article_id`.

An `article_id` with `assignment_status=PAGE_LOCAL_ONLY` is a provisional page
cluster. It becomes cross-page confirmed only after a positive boundary decision;
the output does not claim that every provisional cluster is a complete article.

Cross-page review supports five labels. `SAME_SENTENCE` and
`SAME_ARTICLE_NEW_NODE` join article membership and add a reading edge.
`SAME_ARTICLE_NO_EDGE` joins membership without claiming adjacency.
`NEW_CONTENT` keeps the items separate. `UNCERTAIN` is deferred.

Create a document graph from the relation-first snapshot:

```bash
PYTHONPATH=EvidenceNet python EvidenceNet/pipeline_steps/step2_c_document_article_graph.py \
  --source EvidenceNet/output/latest_regression_46209 \
  --decisions EvidenceNet/experiments/document_article_graph/climate_change_pages_5_6_decisions.json \
  --document-modes EvidenceNet/experiments/document_article_graph/document_modes_pilot.json \
  --output EvidenceNet/output/document_article_graph_46209_v7
```

Prepare strict same-article semantic candidates and import the reading edges:

```bash
python EdgeGeneration/scripts/prepare_relation_first_inputs.py \
  --source EvidenceNet/output/latest_regression_46209 \
  --document-graph EvidenceNet/output/document_article_graph_46209_v7 \
  --semantic-scope-policy intra_article_only \
  --output EdgeGeneration/output/document_scoped_46209_v8
```

The edge adapter excludes structural `page_furniture` and `logo` components
from `units.jsonl`. It keeps them in `excluded_non_evidence_units.jsonl` for
provenance and role-correction review; they never enter reading or semantic edges.
Substantial text with a grounded `CAPTION_FOR` relation is the bounded exception:
it is recovered as a caption with unresolved article membership rather than
discarded because of an upstream role error.

The included decision file is a source-reviewed integration fixture, not an
independently annotated quality benchmark. It shows a
sentence split at `wind | turbine`, a caption that must stay separate, and a
same-article footnote flow that must not create a `NEXT` edge.

`document_modes_pilot.json` demonstrates the paper policy. A
`single_article` document assigns all non-page-context content, including figures
and captions, to one document-level article. Cross-page decisions still control
reading adjacency; the profile never creates cross-page `NEXT` edges by itself.
