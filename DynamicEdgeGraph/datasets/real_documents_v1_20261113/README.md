# Real documents v1 — 100-document inventory (2026-11-14)

This workspace now has a 100-document inventory for ordinary real documents, not a benchmark:

- 25 existing documents referenced from the legacy node dataset (`node_vqa_reuse_v1_20261113`);
- 75 downloaded PDF documents in this directory.

The 75 new PDFs include NASA Spinoff archive issues, NIH MedlinePlus Magazine issues, WHO magazines, an OECD report, and an open arXiv paper. Files are under `pdfs/`.

- `document_inventory_100.jsonl` is the combined 100-document directory.
- `source_manifest.jsonl` lists all 75 downloaded PDFs with source URL, size, SHA-256, and PDF-header validation.
- The 25 legacy documents are references only; their original assets remain untouched in the old dataset directory.
- This collection has not yet been parsed into pages/nodes.
- CiteVQA is used only as a scale reference, not as a source or benchmark input.
- Public availability does not automatically grant redistribution rights; retain source terms.
