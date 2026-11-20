# Data release contents

## Included in Git

- Gold-200 QA and direct audit reports;
- Snapshot A/B/C/D canonical node pools required by the mixed-corpus Gold data;
- frozen-corpus node indexes and eligibility/mapping audits;
- automatic review and export scripts;
- document-disjoint train/test JSONL and split manifest;
- source inventory and SHA-256 manifests.

## Excluded from normal Git history

- 146 raw PDFs (about 2.04 GB total);
- parser work directories and copied page images;
- model weights and downloaded dependencies;
- logs, caches, checkpoints, embeddings, and failed cluster run output;
- duplicate large seed files that can be regenerated from canonical pools.

Raw PDF bundles are optional release assets. They must be packaged in parts
smaller than the hosting limit and accompanied by SHA-256 hashes. Compression
does not replace the per-file source manifest. Copyright and redistribution
rights must be checked before publishing third-party PDFs.

## Current Gold statistics

| Category | Count | Share |
|---|---:|---:|
| Single node | 40 | 20% |
| Cross-page | 60 | 30% |
| Cross-document | 100 | 50% |
| Total | 200 | 100% |

The 200 records cover 56 documents and 290 unique Gold Node IDs.
