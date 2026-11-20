# Automatic Source Integrity and Canonical Mapping gates

The two gates are evaluated independently and do not require a uniform human review of original PDFs.

## Canonical Mapping

For the legacy frozen corpus, the program verifies canonical-ID presence and uniqueness, Node-ID equality, document/page membership, and membership in the referenced frozen node JSONL. All 550 legacy nodes pass automatic mapping.

For the ten Pilot Evidence Units from complete new periodicals, the program materializes a frozen canonical Node Pool in real_canonical_nodes_pilot_r1.jsonl. IDs are deterministic functions of document, page, and parser element index. The auditable Evidence-Unit mapping is stored in automatic_evidence_unit_mapping.jsonl. All ten mappings pass.

## Source Integrity

The program checks source/page file existence, bbox structure, non-empty content (except visual nodes), agreement with frozen source-node text, and conservative severe-OCR patterns. Page images for new periodicals are resolved automatically from the layout-visualization directory.

- All 99 evidence references used by the 50 Pilot drafts pass Source Integrity.
- Across the full 550-node legacy pool, 545 pass and 5 are blocked for severe repeated-symbol OCR. These five nodes are excluded individually; none is used by the Pilot.

## Separation from semantic review

Passing these gates establishes traceability and unambiguous mapping only. Question validity, answer grounding, evidence sufficiency, multi-node necessity, duplicates, and single-node shortcuts remain the responsibility of the independent semantic reviewer and deterministic QA checks.
