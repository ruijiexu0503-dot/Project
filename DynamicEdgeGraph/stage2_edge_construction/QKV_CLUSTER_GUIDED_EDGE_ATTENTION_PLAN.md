# Cluster-guided Dynamic Edge Retrieval: minimal QKV specification

The primary objective is Evidence Retrieval Performance. Cluster compactness,
edge cosine, and directional diagnostics are secondary diagnostics only.

## Literature mapping

- [Edge Set Attention](https://www.nature.com/articles/s41467-025-60252-z): use edges as attention primitives and restrict attention with a graph-derived mask. This project will use a sparse edge-neighborhood mask, not global edge-set attention.
- [Routing Transformer](https://aclanthology.org/2021.tacl-1.4/): use clustering as content-based sparse routing. K=32 is a routing index, never a relation type.
- [ColBERT-PRF](https://doi.org/10.1145/3572405): centroids can be query-local feedback vectors. Query-adaptive prototypes are a separate later PRF arm, not the fixed global prototype arm.
- [Edge-augmented Graph Transformer](https://arxiv.org/abs/2108.03348): keep a residual edge channel while allowing its features to evolve across attention layers.
- [GNN-RAG](https://aclanthology.org/2025.findings-acl.856/): query relevance and neighbor relevance must both affect retrieval. The Candidate Graph is not treated as a verified knowledge graph.

## Verified Pilot inputs and limits

- 24 queries, 518 pages, 7,288 compatible Qwen3-Embedding-0.6B node vectors.
- Static Pilot Candidate Union: 950,871 undirected pairs. Full directed E0 materialization would be 1,901,742 x 2,048 float32 values, about 14.5 GiB; the first implementation must generate active edges on demand.
- Existing K=32 clusters cover only the 10,000 directed E0 sample edges (about 79 MiB), so that sample cannot silently become the full graph cache.
- The sample has 5,273 source nodes; source-degree P95 is 4 and max is 9. A bounded topology neighborhood of eight edges is feasible for the sample self-supervised stage.
- The 24 queries have six types with four queries each and no source/document-family field. They are insufficient for a credible supervised final result.

## Module A: sparse Cluster-guided Edge-Edge Attention

For directed E0 edge `e=[m;d]` in 2048 dimensions, use a learned bottleneck `z=LN(W_in e)` in 128 dimensions. Q, K, and V are learned projections, never random weights:

```text
q_e = W_Q z_e
k_u = W_K z_u
v_u = W_V z_u
attention(e,u) = softmax_u(q_e dot k_u / sqrt(128) + sparse_mask(e,u))
z_updated = z_e + gate_e * W_O * sum_u(attention(e,u) * v_u)
e_updated = e + W_out z_updated
```

Each edge has at most 16 context edges:

1. Up to eight real topology neighbors that share a source or target endpoint.
2. Up to eight edges routed to the same hard K=32 cluster.
3. If no context exists, use only the self/residual path.

The no-clustering attention control has identical QKV dimensions, layers, and total neighborhood budget, but draws all 16 contexts from topology/content-nearest edges. Thus only neighborhood construction differs.

## Training without Relation Type labels

Edge-only self-supervised pretraining does not read queries or Gold:

1. Mask midpoint or difference input channels and predict the frozen original edge with InfoNCE/cosine reconstruction. Mask or gate the residual during this task to prevent an identity shortcut.
2. Use two independently sampled legal edge neighborhoods and require cross-view consistency; add variance/covariance regularization to prevent collapse.
3. Keep reversal and cluster diagnostics, but select no model based on them alone.

Query-Edge routing may later use separate training queries with Gold page supervision. A fixed one-hop candidate pool contains a NO_EXPAND token and target edges; use a marginal listwise objective over edges whose target page is Gold. Test queries must be disjoint.

## Split discipline

The current Pilot may only be a development smoke. If an internal split is unavoidable, fix 2 train / 1 validation / 1 test query per question type (12/6/6) before training; tune only on train/validation. Six test queries are not a publishable final evaluation. A real routing model requires a separately frozen train/validation query set with document-family separation from test.

## Module B and cost

At retrieval time, build only the one-hop active subgraph from frozen Seeds. Query plus source node creates the query-side state; updated edge is K and edge/target evidence is V. Retain NO_EXPAND and no-edge ranking. Page dedup and fusion remain identical across arms.

The minimal QKV module has about 1.1M parameters for 2048-to-128 input/output and 128-dimensional Q/K/V/O. For the 10,000-edge sample, batch 512 and neighborhood 16 fit easily in less than 1 GiB activation memory. The current active retrieval graph has about 32,220 scored directed edges; generate channels and cluster assignments on demand rather than materializing the full graph. Record active edges, attention pairs, time, peak memory, and page candidates.

## Required comparisons

Compare A No-edge, B Target-only, C Original Edge, D Static Prototype, Edge-Edge Attention without clustering, Cluster-guided Edge-Edge Attention, and later Query-adaptive Prototype. Every arm must share Query set, Candidate Graph, Seeds, page fusion, evidence budget, parameter count, and neighborhood budget. Report RecallAll@5, nDCGAll@5, Recall/nDCG, New Gold Pages, actual attention/scoring count, and cost.
