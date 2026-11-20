# Data Readiness

## P0 conclusion

- Raw selected assets: **94 documents**; HTML/metadata were checked per document during canonicalization.
- Canonical nodes: **51471**. Empty visual elements are retained with masks; empty nonvisual elements are excluded with reasons.
- Exact evidence→node mapping: **406/413 (98.3%)**.
- Primary learning/evaluation unit is **page-level weak supervision**. Node search is allowed, but only exact mapped evidence nodes have any node-level annotation; other nodes are unknown, not negative.
- Nodes, compatible embeddings, and a static candidate graph have not yet been built. Training is therefore blocked until those derived assets are generated in this new namespace.
