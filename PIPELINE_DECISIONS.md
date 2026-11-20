# Pipeline decisions

## 2026-11-20: Node-first QA is the active path

- The active release is built around canonical EvidenceNodes and automatic QA
  gates, not mandatory per-example human approval.
- The current verified release is Gold-200; 300 remains a target.
- Historical experiments and superseded launchers are preserved under
  `archive/legacy_20261120/`.
- Raw PDFs, page images, model weights, caches, and cluster outputs are kept out
  of normal Git history. Release manifests provide hashes and provenance.
- Dataset versions are never overwritten.
