# DATASET INVENTORY

## P0 conclusion

The old node-exploration dataset is documented by `EvidenceNet/experiments/own_corpus_edges/README.md` and `EvidenceNet/docs/hybrid_node_49page_stress_2026-10-07.md`. Lineage: `relation_first_corpus_shadow_v7_cpu` -> `hybrid_49page_stress_prepared_20261007` -> `hybrid_node_v2_61078/embedding_geometry` -> `own_corpus_edges_v1_20261011` (sidecar).

Counts: 25 documents, 49 pages, 761 parser atoms ({'furniture': 102, 'text': 554, 'heading': 74, 'caption': 28, 'table': 3}), 72 visual bundles, 550 Hybrid nodes, and 0/0/0 formal questions/answers/evidence Gold. The old edge manifest independently verifies 49 pages and 550 nodes.

Verified: local representations, prepared representations, node JSONL, source IDs, node/page/atom provenance, and page-image hashes where files exist. Not verified: original PDFs, normalized physical/display page numbering, dimensions/rotation, formal QA/evidence labels. Known source risks remain recorded rather than repaired.

All used filenames/paths are in `data_files_manifest.jsonl`; structured records are in `documents.jsonl`, `pages.jsonl`, `nodes.jsonl`, and `issues.jsonl`.
