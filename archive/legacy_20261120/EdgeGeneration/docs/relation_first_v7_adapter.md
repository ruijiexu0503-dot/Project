# v7 evidence -> edge-generation adapter

Run from the project root, using a fresh output name for each snapshot:

```bash
EvidenceNet/.venv_qwen/bin/python EdgeGeneration/scripts/prepare_relation_first_inputs.py \
  --source EvidenceNet/output/relation_first_corpus_shadow_v7_cpu \
  --output EdgeGeneration/output/relation_first_v7_edge_input_snapshot_NEW
```

The adapter reads both shard directories. Only structurally valid `complete` or
`partial` pages with all required files are imported. Partial does not mean all
visuals were judged successfully. Failed/missing/changing pages stay in the
manifest; they are not silently treated as processed. Raw input files are copied
under source_snapshots, with page-content hashes. Original outputs are read-only.
Images remain referenced by absolute path; migrate those assets as well if moving
JSON to a different machine. report.html embeds the preview images it displays.

## Outputs and semantics

- units.jsonl: all imported components, including structural candidates and
  visuals with no textual description. Original IDs, source fragments, geometry,
  completeness, review state, presentations, and native assets are preserved.
  `unit_id`/`text` serve retrieval consumers; `node_id`/`doc_id`/`evidence_type`
  also match existing multimodal trial conventions. No GPU is needed to export.
- local_visual_text_relations.jsonl: original directed CAPTION_FOR/ILLUSTRATES
  (and any other upstream labels), with their full validation/provenance payload.
  These are never relabeled as cross-article or evidence-semantic edges.
- candidate_pairs.jsonl and scoped *_candidates.jsonl: bounded lexical-posting
  retrieval candidates, NOT ANN results or accepted semantic edges. Common terms
  have a posting cap, with at most top-k outgoing candidates per unit/scope before
  symmetric deduplication. There is no dense all-pairs matrix.
- quarantined_relations.jsonl: relations with unresolved endpoints.
- manifest.json: imported/skipped/deferred pages, hashes, scope counts and limits.
- report.html: top 20 candidate pairs per scope with source text and available
  upstream visual presentations. These are a review sample, not a scored gold set.

All units remain `retrieval_eligible: false` for production. The separate
`shadow_candidate_eligible` flag permits experimental retrieval on body/review
text of at least 20 characters. This threshold is a routing heuristic, not a
quality guarantee. SUSPECT flags on upstream links remain on the unit; suspect
link text is not used to build visual text proxies. Such text may still appear
as an explicitly unverified text-unit candidate. Visual proxies are labeled
linked text, not direct visual observation or independently corroborating evidence.

## Article scopes

CI_1 is only page-local. Its fully qualified key is `doc::page::CI_1`.
Without a reviewed cross-page article map, `article_id` is null:

- same local item: intra_local_item, a provisional article-internal candidate;
- different documents: cross_document;
- same document but different/unknown local items: same_document_article_unresolved.

For reviewed article assignments, pass --article-map map.json, mapping fully
qualified local item keys to document-local article IDs. The adapter namespaces
article IDs by document. Then same-document candidates can be classified as
intra_article/cross_article, including across pages. Do not feed null article IDs
into the legacy ANN script's singleton fallback and interpret its output as true
article grouping. The legacy ANN benchmark also needs newly generated aligned
embeddings and row mappings; this export does not supply or reuse stale vectors.

## Next inference stage

Build evidence first; retrieve scoped pairs second; let Qwen judge candidate
pairs third. Input includes both source units and their assets, uncertainty and
source anchors. Return zero or multiple relation labels; a shared image or shared
caption is not by itself an independent support edge. Preserve direction and
verbatim endpoint anchors. Only accepted, grounded evidence edges may contribute
to a document/article aggregate. This adapter does not yet invoke that judgment
or produce aggregate verified document edges. Existing page-level visual/text
judgments are reused rather than recomputed.

Tests:

```bash
EvidenceNet/.venv_qwen/bin/python -m unittest discover -s EdgeGeneration/tests -p test_relation_first_inputs.py
```
