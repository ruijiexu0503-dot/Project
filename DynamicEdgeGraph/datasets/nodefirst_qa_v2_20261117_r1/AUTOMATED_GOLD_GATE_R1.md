# Automated Node-first QA review and Gold export gate (r1)

This revision replaces blanket human-approval and original-PDF requirements with independent automated gates. Human review is optional escalation, not a universal prerequisite.

## Independent gates

### 1. Source Integrity

Source Integrity asks whether the frozen evidence is usable and traceable. The deterministic program checks source/page file existence, document and page identity, bbox structure, non-empty content, frozen-text agreement, page-image availability, and severe OCR patterns. A missing manually verified original PDF is not itself a failure.

Nodes fail individually when evidence is missing, unlocatable, seriously corrupted, or conflicts with its frozen source. A corpus is not blocked because a different node is bad.

### 2. Canonical Node Mapping

Mapping asks whether every evidence reference resolves unambiguously to one stable Node ID.

- Frozen legacy Nodes pass when their canonical ID is unique, document/page linkage is valid, and the exact Node exists in the referenced frozen node file.
- New-periodical Evidence Units are materialized into a versioned canonical Node Pool using deterministic document/page/element identity. Text and bbox must exactly match the frozen page JSON.
- Only failed or ambiguous mappings block export.

### 3. Semantic Grounding

An independent model reviews Question validity, Answer correctness, Evidence sufficiency, multi-node necessity, duplicates, and possible single-node shortcuts. Deterministic checks independently enforce schema, category constraints, exact duplicates, and reference validity.

For Cross-page and Cross-document records, every Gold Node must survive deletion ablation: removing it must make the complete answer unsupported. Parallel lists, loose analogies, generic governance transfer, and author-imposed joins fail.

## Automatic FINAL_ACCEPT

A QA is exported as FINAL_ACCEPT_AUTOMATIC when all of the following are true:

1. The independent model passes Question, Answer, sufficiency, necessity, and duplicate checks.
2. Deterministic category constraints pass.
3. Every canonical Node mapping is MAPPED_VERIFIED_AUTOMATIC.
4. Every cited Node is SOURCE_INTEGRITY_PASS.
5. No known single-node shortcut exists.
6. No deterministic exact duplicate exists.

No manual per-record approval or uniform original-PDF inspection is required.

## Distribution

Generation and replacement sampling continue to target 20% Single-node, 30% Cross-page, and 50% Cross-document. The accepted pool may be imbalanced after strict rejection. The release exporter therefore selects the largest deterministic subset that preserves 20/30/50 exactly; rejected quota positions must be replenished by new evidence-first candidates rather than by weakening necessity.
