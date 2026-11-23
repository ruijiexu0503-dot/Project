# Real PDF Corpus v2 — candidate registry

**Status:** candidate selection only; not a finalized, downloaded corpus.

- Target: ~80 independent PDF documents and ~3,000 pages, subject to download and page-count audit.
- Hard exclusion: **NASA Spinoff (all years)**. No NASA Spinoff records are permitted in v2.
- VL-DocIR/HTML is out of scope.
- Keep v1 manifest unchanged for provenance; do not copy excluded PDF binaries into v2.
- Existing v1 documents are candidates, not automatically accepted. Current seed: 8 candidates (7 v1 and 1 new).
- Do not treat an official source URL as proof that the PDF is currently downloadable.
- Preserve original v1 IDs in legacy_document_id; assign distinct v2 IDs; no canonical node IDs should be reused without remapping.

## Planned composition (80 documents)

| Type | Target |
| --- | ---: |
| Scientific research papers | 14 |
| Engineering manuals and technical reports | 12 |
| Financial annual reports | 8 |
| Statistical and policy reports | 12 |
| Maps, geography and environmental reports | 8 |
| Historical scanned archives | 6 |
| Product catalogues and specification sheets | 8 |
| Medical and public-health reports | 8 |
| Other complex-layout documents | 4 |

The quotas are goals, not fabricated records. Select multiple independent publishers, balance page counts, and ensure cross-document topic clusters with complementary evidence.

## Acceptance gates

1. Source URL resolves to a real PDF, not HTML or a redirect to an error page.
2. PDF opens successfully, record actual page_count, bytes and SHA256.
3. Detect exact duplicates by SHA256 and near-duplicates by title/content.
4. Audit layout types (text, tables, figures, diagrams, formulas, maps, scans).
5. Review topical diversity and limit any single publisher/series concentration.
6. Freeze a separately named accepted manifest only after verification; then run parsing and assign canonical node IDs.

## Fields

- `selection_status`: `candidate_from_v1` or `candidate_new`; not an acceptance claim.
- `download_status`: starts `not_verified_in_v2`.
- `expected_sha256` / `expected_bytes`: historical v1 observations, not current downloads.
- `sha256` / `page_count`: null until v2 binary audit.

## Colab note

Pull the updated feature branch into the persisted Drive repository before using this registry. Download PDF binaries to Drive or /content, not GitHub; keep manifests in Git.
