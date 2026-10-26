# Current pipeline versus every-node candidate coverage

User choice: every node retrieves candidates; the same verifier may reject all
its candidates. There is no forced minimum semantic degree.

The frozen 518-page/24-query pilot caches completed Dolphin parsing and hybrid-v2
node generation. This run performs new offline candidate generation and
multimodal edge verification, runs current Qwen membership/reading flows, and
evaluates final page rankings. It is a regression/integration run on inspected
queries, not the official full-corpus result. The upstream nodes are reused,
not claimed as freshly generated. Expanding to the official corpus also needs
scalable ANN candidate retrieval; this pilot uses blocked exact view retrieval.

## Construction

The current adapter is rerun, preserving source roles. Existing 8B view vectors
are reused only after exact view-content and model-file checks. Current sparse
selection uses the existing dense/BM25/identifier pool, article routes, escape
and explicit-reference quotas. The every-node selector takes top-1 distinct
target by the same pool's RRF for every represented node. Nodes omitted by the
four-word view filter receive original eligible member views encoded by the
same 8B model, then exact nearest-distinct-node fallback. Empty/ineligible
content is counted as unavailable rather than hidden from the denominator.

Both candidate sets are frozen without queries/gold. Their unique union is
verified once using the current original multimodal control, with source crops,
the same prompts and source-role/export checks. Accepted/rejected/review records
are projected back into each arm. Shared pairs therefore have identical
decisions. More candidates have an explicit higher offline compute cost.

Current reading stage runs per known single HTML document, using Qwen membership
and fixed-membership reading flows. Actual NEXT edges are imported with node-ID,
document/article, DAG and source-manifest checks; PREVIOUS is their exact inverse.
This current code emits only page-local flows under the single-document profile.
It does not guarantee all nodes are in one chain, and unresolved/excluded/singleton
coverage is reported. No cross-page adjacency is fabricated.

## Matched retrieval

| Run | Candidate pages |
| --- | --- |
| node_raw | Frozen dense page ranking |
| node | Dense top20, BGE |
| reading | Dense core10, bounded one-hop NEXT/PREVIOUS, dense fill to20, BGE |
| sparse_pipeline | Same reading policy + current sparse verified graph, BGE |
| all_node_pipeline | Same reading policy + every-node verified graph, BGE |
| ColNomic_raw | Cached local ColNomic-7B base-model page ranking |
| ColNomic_BGE | ColNomic top20 + exactly the same BGE/page text |

Sparse and every-node graphs use the same offline original-anchor pair encoding
(192 tokens per endpoint, AB/BA, 8B encoder). Up to100 edges are scanned per query.
Reading adds at most3 new pages beyond the dense core10; semantic endpoints use
remaining slots; all arms end with20 unique pages. Same-page NEXT traversals are
logged but cannot improve page recall merely by existing. The two highest frozen
0.6B-hit windows are identical reranker evidence for a given query/page across
all arms. This isolates graph candidate supply, not contextual window rewriting.
Edge scores never add a final page bonus. No query-time document/edge re-encoding.

ColNomic query texts and official page identities/image hashes are checked for
equality. This is not a reproduction of the official context/ensemble reranker.
Gold is first opened by report after graphs/candidates are frozen. Reports include
macro/micro/by-type Recall, nDCG, RecallAll, nDCGAll at3/5/10 and mAP@3/5/10/full,
paired AP@5 wins/losses/ties, full runs, search paths, and an HTML report.

## Execution

`run_vldocir_pipeline_comparison.py` stages: prepare, smoke, worker, collect,
encode-edges, retrieve, report. The preparation job produces all candidates and
source-grounded verifier inputs, then verifies up to12 real pairs across modalities
and runs one Qwen reading page. Sixteen independent build shards, at most two
simultaneously, run only after preparation/smoke succeeds. Each uses the same
checkpointable verifier and builds reading flows for its assigned documents.
The final evaluation depends on all build shards succeeding. Missing workers,
invalid reading outputs or incomplete reranker scores stop final reporting.

Prepared submit scripts: `migration/horeka-vldocir-pipeline-compare-20261025/`.
These scripts do not alter the older jobs 5211791 or 5211803. Submission IDs and
actual states are recorded separately after successful Slurm submission.
