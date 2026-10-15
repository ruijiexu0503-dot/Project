# VL-DocIR integration pilot

Dataset: https://huggingface.co/datasets/anonymous-8421/VL-DocIR

Pinned revision: `40a1818110c20e9279bbb4a3b6283ceac2d631ba`.

## Current state (2026-10-11)

All 518 pages and 130 node batches passed coverage checks. Retrieval job **66352**
completed all six arms. The no-edge results are frozen as
`vldocir_no_edge_v1_20261011`; see [baseline contract and scores](BASELINE.md).
The job table below records the original submission; recovery jobs replaced
failed or cancelled stages. Later edge runs must preserve the frozen baseline inputs.

Authenticated access succeeded using the existing default Hugging Face credential.
The project `current/env.sh` changes HF_HOME and enables offline mode, so downloads
must run separately from that model-inference environment. Never put tokens in scripts.

Metadata and all 32 selected page shards have been downloaded under
`data/benchmarks/VL-DocIR`. All 518 selected PNG pages were decoded successfully;
`pilot_20261009/image_pages.jsonl` records official document/page IDs, dimensions,
local paths and SHA-256 hashes. These generated dataset records are ignored by Git.

The frozen pilot contains 24 queries: one per source (arxiv, pubmed, sec, wiki)
and question type (six types). Selection restricts relevant documents to at most
32 pages and includes all their pages, plus one distractor document per source.
This is a small, selected-corpus integration experiment, not an official score.
All 40 distinct gold evidence pages are present in the 518-page search corpus.
Queries used by retrieval contain no answers, evidence or ratings. Labels are
used for corpus selection and evaluation only, never parsing or node creation.

Dolphin smoke job **62693** completed successfully (four pages, 3m33s), using
`current/slurm/vldocir/run_vldocir_dolphin_smoke_dev.sbatch`: four pages, one per source, single
H100, 14m30s limit. Outputs go to `EvidenceNet/output/vldocir_pilot_20261009/dolphin`.
It is a parsing-only job.
The runner records resized-image coordinates and scale factors to original images.

## Submitted pipeline

| Job | Stage | Dependency |
|---|---|---|
| 63390 | Four-page hybrid-v2 node smoke test, two dev batches | None; smoke parsing finished |
| 63392 | All 518 pages, Dolphin, 87 dev batches | None; existing four pages reused |
| 63398 | Prepare frozen node representations | afterok 63390 and 63392 |
| 63402 | Full hybrid-v2 EvidenceNode generation and strict coverage audits | afterok 63398 |
| 63403 | Six retrieval controls and metrics | afterok 63402 |

The full node job contains 8 normal H100/H200 tasks (at most 2 simultaneous), covering
130 four-page batches exactly once. An initial 130-task submission was rejected
by the cluster submission limit; it did not create a job. Parsing and retrieval
request 14m30s each; full node jobs have an 8-hour maximum each. Partition lists
and parser concurrency were expanded as described below.
Dependencies require success, so missing parser pages, invalid Qwen decisions or
node coverage failures stop downstream scoring rather than excluding failures.

Scheduling update: pending tasks in 63392 and retrieval job 63403 now allow
gpu-h200, gpu-h200-8, gpu-h100 and dev-gpu-h100. The parser array throttle is 4.
63402 allows the three normal H200/H100 partitions with throttle 2. Existing
running tasks retain their allocations; IDs and dependencies are unchanged.
The visible partition list contains no B100/B200. Node free-resource details are
restricted; multi-partition eligibility does not guarantee an earlier start.

`prepare_vldocir_nodes.py` preserves all element text exactly, makes parser figures
visual bundles, retains tables, and stores headings separately. Source headers,
footers and page numbers are excluded from evidence. A source/geometry rule
preserves a Wikipedia main heading incorrectly labeled `header`; the brand
header stays furniture. Manual smoke inspection found an invented Chinese
phrase in the Wikipedia brand-header OCR; raw parser output is retained for audit.

`retrieve_vldocir.py` compares `page_mean`, `page_windows`, `parser_atoms`,
`parser_atoms_visual`, `hybrid_text` and `hybrid_visual`. All arms share document
titles/source page headings (64-token context cap), the same Qwen3-Embedding-0.6B
encoder and complete 384-token windows with stride 320. Visual arms use identical
Qwen descriptions. The main matched grouping comparison is `hybrid_visual` versus
`parser_atoms_visual`; `hybrid_text` versus `parser_atoms` isolates source text.
`page_mean` pools page windows; other arms take maximum window/unit scores per page.
Headings remain addressable as structural retrieval units without becoming evidence.

Reports will appear in `EvidenceNet/output/vldocir_pilot_20261009/retrieval/`:
`report.md`, `comparison.json`, per-arm score/metric JSONLs, and node/page provenance.
The comparison includes an exploratory paired, type-stratified bootstrap for
macro nDCG@5. No graph expansion is used in these controls.

## Evaluation constraints

Rank unique official pages and evaluate Recall/nDCG and RecallAll/nDCGAll at
3, 5, 10, including six-type macro. Treat the selected corpus and 24 queries as a
workflow pilot. A larger frozen holdout and corpus are needed for quality claims.
Graph-expansion comparisons require separately integrated real EvidenceNode edges.

`scripts/evaluate_vldocir.py` implements the metrics and rejects missing gold pages,
unknown queries/pages and missing node-to-page provenance. Eight tests pass across
metrics, adapter source preservation, coordinates, complete token windows and
matched retrieval inputs (including title retention and furniture exclusion).
Retrieval results are available in the frozen baseline. Hybrid visual nDCG@5 is
71.76%, versus 71.32% for parser atoms with the same descriptions; the exploratory
bootstrap interval crosses zero. No full-corpus superiority claim is supported.
