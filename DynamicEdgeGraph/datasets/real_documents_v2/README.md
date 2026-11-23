# Real PDF Corpus v2 — 80 source candidates

**Status: SOURCE DISCOVERY ONLY. NOT 80 verified PDFs.**

This corpus explicitly excludes all NASA Spinoff and all VL-DocIR HTML assets. The 80 entries in `source_manifest_candidates.jsonl` are research leads, not accepted files. A source may be a direct PDF URL (`url_type=direct_pdf`) or a publication/collection landing page (`url_type=publication_page`). Landing pages **must be resolved to one specific PDF each** before acceptance; collection pages are not yet individual documents. Some direct PDF URLs may also fail or change. All entries currently have `verification_status=unverified_candidate`.

## Actual candidate composition

- Scientific papers: 24
- Scientific assessments: 8
- Health reports: 8
- Statistical/policy reports: 8
- Technical standards: 8
- Financial reports: 8
- Engineering manuals/datasheets: 8
- Geography, maps and archives: 8

This is an initial *source discovery* distribution, not a final document-type balance. Reduce papers and replace any invalid or redundant sources during curation.

## Acceptance requirements

1. Resolve a unique **direct PDF** URL for each candidate.
2. Download and verify PDF magic header, readability, page count, file size, SHA256 and final URL.
3. Reject duplicates/near-duplicates and inaccessible sources; record rejection reason.
4. Audit text, figures, tables, formulas, diagrams, maps and scanned pages.
5. Balance topics, publishers and page counts; target approximately 80 PDFs and 2,500–4,000 pages, but quality over count.
6. Preserve old v1 manifest as provenance, without copying excluded binaries. Assign stable v2 IDs only after acceptance and do not reuse canonical node IDs.
7. Freeze an accepted manifest separately before Colab parsing. Do not run parsing on this unverified candidate list.

## URL semantics

`source_url`: discovered lead; `source_pdf_url` only populated for direct-PDF-looking links; `source_page_url` for landing pages. None have been binary-verified. `page_count` and `sha256` remain null pending actual download.
