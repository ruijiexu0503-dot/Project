# Direct QA Batch 02 and cumulative-200 report

## Outcome

- Batch 02: 100/100 passed the deterministic second-pass audit.
- Cumulative export: 200 records; original Batch 01 and all upstream JSONL files remain unchanged.
- Distribution: 40 Single Node (20%), 60 Cross-page (30%), 100 Cross-document (50%).
- Cross-document split: 70 two-document (35% of all QA), 30 three-plus-document (15% of all QA).
- No scheduler or GPU/model generation job was submitted.

## Batch 02 correction loop

The first Batch 02 audit passed 86/100. Thirteen inherited Cross-page candidates lacked an exclusive claim for every node, and one legacy record had non-contiguous evidence indices. The thirteen weak records were replaced with directly curated cross-page syntheses; the legacy indices were normalized without changing evidence text or offsets. The second audit passed 100/100.

## Automatic gates

- All 195 Batch 02 evidence references have locatable source JSON and page images.
- All 370 Batch 02 claim spans match the exact source substrings and offsets.
- Cross-page topology and Cross-document document-count topology pass.
- Every multi-node record has at least one exclusive answer claim per evidence node.
- No exact or token-Jaccard >= 0.65 question duplicate was found across Batch 01 and Batch 02.

## Cumulative evidence statistics

- Evidence references: 391
- Unique canonical nodes: 290
- Unique documents: 56
- Maximum node reuse: 6
- Node types: {"COMPOSITE": 50, "TABLE": 24, "TEXT": 188, "PARA": 81, "IMAGE": 47, "CAPTION": 1}

## Review semantics

`DIRECT_REVIEW_ACCEPT` means direct Codex semantic curation plus deterministic Source/Mapping, exact-span, topology, necessity, and duplicate checks. It is not mislabeled as an independent-model verdict and does not require manual approval.
