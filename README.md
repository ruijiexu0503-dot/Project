# EvidenceNet / DynamicEdgeGraph

This repository contains the current Node-first document QA pipeline and its
retrieval model. The active path is intentionally smaller than the historical
research tree:

1. parse PDF pages with the resumable parsing pipeline;
2. construct source-addressed canonical EvidenceNodes;
3. generate and automatically audit Node-first QA;
4. export Gold QA only after deterministic source/mapping gates, claim-level
   grounding review, node-necessity review, and shortcut checks;
5. train the frozen-encoder dynamic ranker from a document-disjoint split.

Start with [PIPELINE_CURRENT.md](PIPELINE_CURRENT.md) and
[PIPELINE_STEPS.md](PIPELINE_STEPS.md). Dataset contents and release exclusions
are documented in [DATA_RELEASE.md](DATA_RELEASE.md).

The current checked Gold dataset contains **200 QA pairs**: 40 single-node,
60 cross-page, and 100 cross-document. It is not yet the requested 300-example
training release. The document-disjoint baseline split contains 181 train and
19 test examples; new-document validation remains pending.

Historical designs, one-off launchers, and superseded experiments are retained
under [archive/](archive/README.md). They are preserved for provenance but are
not imported by the active pipeline.

Model weights, caches, cluster logs, full parser work directories, page images,
and raw PDFs are not stored in normal Git history. Their hashes and packaging
policy are recorded in `release_manifests/`.
