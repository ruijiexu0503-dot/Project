# CiteVQA v1 data boundary

This directory is intentionally separate from `../real_documents_v1_20261113/`.
It must not share PDF roots, node IDs, parsed pages, frozen embeddings, candidate
graphs, or experiment outputs with the user-curated real-document corpus.

## Source and scope

- Dataset: `opendatalab/CiteVQA` on Hugging Face.
- Public assets fetched here: `data/validation/CiteVQA.json` and
  `data/download/pdf_source.csv`.
- Restricted assets: the 711 referenced PDFs are **not** downloaded here.  The
  official project directs users to a ModelScope approval process for those PDFs.
- Benchmark annotations remain immutable source data.  Any later adapter must
  write new artifacts below a separate run directory and retain the original
  question/evidence fields for evaluation only.

## Current task boundary

CiteVQA is an answer-plus-element-level-citation benchmark.  It is not input to
Stage 1 candidate generation, relation labels, or node-embedding training.  Its
questions and evidence annotations may only be read by a dedicated evaluation
adapter after a documented split is frozen.

## Layout

```text
citevqa_v1_20261115/
├── raw/huggingface/       # ignored public annotation/source-table copies
├── manifests/             # ignored audit and download manifests
├── scripts/               # versioned acquisition/audit tools
└── runs/                  # future CiteVQA-only parsing/evaluation runs
```

Run the public-only acquisition from the repository root:

```bash
.venv-magazine-exp1/bin/python \
  DynamicEdgeGraph/datasets/citevqa_v1_20261115/scripts/fetch_public_assets.py
```

The official dataset card documents 1,897 questions over 711 PDFs, with
element-level evidence fields including PDF name, page, bounding box and
necessity.  See the [official data card](https://huggingface.co/datasets/opendatalab/CiteVQA/blob/main/README.md)
and [official repository](https://github.com/opendatalab/CiteVQA).
