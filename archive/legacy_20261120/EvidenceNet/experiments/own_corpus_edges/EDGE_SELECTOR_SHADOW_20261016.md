# Cross-article edge selector shadow experiments

2026-10-16. These experiments reuse frozen retrieval views, vectors and candidate
pairs. They do not alter evidence nodes, production candidate files or graph edges.
Reference labels are read only after each candidate list is frozen.

## Fixed comparison

The current hierarchical selector retains 1,301 pairs and covers 10/26 provisional
positive development cases, while admitting 2/27 difficult negative cases as
candidates. Candidate inclusion is not an accepted semantic edge.

Two H100 jobs scored all 41,186 frozen initial pairs and 46,922 unique source-mapped
view alignments with the existing `bge-reranker-v2-m3` model:

- 82585, one-way best-alignment scoring: completed in 1m28s, exit 0.
- 82590, mean of both endpoint orientations: completed in 2m10s, exit 0.

| Fixed 1,301-pair selector | Positive coverage | Difficult negative candidates |
| --- | ---: | ---: |
| Current hierarchical selector | 10/26 | 2/27 |
| One-way reranker, global | 4/26 | 0/27 |
| One-way retrieval/reranker RRF | 9/26 | 2/27 |
| Symmetric reranker, global | 4/26 | 0/27 |
| Symmetric retrieval/reranker RRF | 9/26 | 2/27 |

The generic reranker is conservative but unsuitable as a replacement selector: it
removes difficult negatives by also removing most true scientific method/claim
correspondences. Bidirectional scoring does not repair the failure.

## Target-node deduplication

The original dense and BM25 top-30 operate on retrieval views, so repeated views
from one target node can consume multiple ranks. A shadow implementation first
deduplicates by target node and then keeps 30 unique target nodes.

- Initial pool grows from 41,186 to 50,872 pairs.
- Initial positive coverage remains 24/26; P11 and P12 are still absent.
- The first 1,301 final candidates retain the same 10 positives and two difficult
  negatives as the current selector.

This is a valid robustness correction, but it does not solve the measured recall
bottleneck. P11 is absent because its generic multi-head-attention wording is not a
top-30 node match under the current representation, rather than because duplicate
views crowd it out.

## Budget expansion diagnostic

Increasing `pairs_per_article` while retaining the old degree policy gives only
13/26 positives at more than 3,000 final pairs. Removing the local degree cap and
retaining up to 512 pairs per routed article pair reaches 16/26 at about 6,596
unique candidates. Pure budget expansion is therefore too inefficient.

## Exploratory identifier-conditioned lane

A post-result exploratory selector uses sentence-level views and ranks pairs within
each shared-identifier cluster before filling the remaining budget from the current
hierarchical candidates. Reserving the top 20% for identifier groups containing
100--500 pairs gives 13/26 positives at the same 1,301-pair budget, including P01,
with 3/27 difficult negatives entering the candidate set.

This is not an unbiased improvement claim: the group-size and fraction settings
were inspected on the development cases. It is evidence for the next experiment:
freeze a general identifier/component-conditioned allocation policy, then evaluate
it on held-out article pairs. Named-method claims, generic components and formulas
should use separate lanes rather than one global relevance rank.

## Artifacts

- `EvidenceNet/output/edge_selector_reranker_v1_20261016/`
- `EvidenceNet/output/edge_selector_reranker_symmetric_v1_20261016/`
- `EvidenceNet/output/node_dedup_edge_retrieval_v1_20261016/`
- `EvidenceNet/scripts/run_edge_selector_reranker.py`
- `EvidenceNet/scripts/run_edge_selector_reranker_symmetric.py`
- `EvidenceNet/scripts/compare_node_dedup_edge_retrieval.py`

Focused test functions for alignment deduplication, orientation-independent pair
keys, unique off-route escape and target-node top-k pass under the project Qwen
environment. That environment has NumPy but no pytest package, so the functions
were invoked directly. Python compilation, shell syntax and whitespace checks pass.
