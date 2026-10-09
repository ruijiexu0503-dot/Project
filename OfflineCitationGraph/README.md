# OfflineCitationGraph

An isolated, offline-first experiment for incremental scholarly citation resolution. It does not modify `EvidenceNet/` or `parsing/`.

Core rule: citation existence comes from source-document provenance (citation mention + bibliography entry), while the target document may arrive later. A missing target creates a persistent placeholder. When a later PDF supplies the same DOI/arXiv identifier, the registry attaches that asset and materializes `source work -> CITES -> target work` without rerunning the source document.

Data layers:

- `works`: version-independent scholarly identity.
- `document_assets`: concrete local PDFs and SHA-256 checksums.
- `bibliography_entries`: parsing-layer reference records; never EvidenceNodes.
- `citation_mentions`: source block and citation cue provenance.
- `citation_edges`: only materialized targets.
- `unresolved_references`: persistent claims awaiting later documents.

Run the included A-first/B-later pilot:

```bash
cd OfflineCitationGraph
python scripts/run_incremental_pilot.py
```

The pilot ingests GW150914 first, exports a source-only snapshot, then adds four cited PDFs one at a time and exports a snapshot after every arrival.
