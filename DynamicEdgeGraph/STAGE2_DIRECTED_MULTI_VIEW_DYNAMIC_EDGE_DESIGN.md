# DynamicEdgeGraph — Stage 2: Directed Multi-view Dynamic Edge Embeddings

> **Design notes / research hypothesis, not an implemented or validated model**  
> Date: 2026-11-08  
> Project: `ruijiexu0503-dot/Project` · Branch: `feature/evidence-edges`  
> Intended repository path: `DynamicEdgeGraph/STAGE2_DIRECTED_MULTI_VIEW_DYNAMIC_EDGE_DESIGN.md`

## 0. One-sentence idea

Given **frozen, independent Node representations** and a **sparse set of candidate Node pairs** produced by query-independent Stage 1 retrieval, construct **high-dimensional, directed Edge embeddings** from multiple frozen encoder views; optionally discover **soft relation prototypes** by clustering the initial Edge representations; and update Edge states via **local edge-to-edge QKV attention**, without updating the original Node embeddings.

This is a **continuous latent relation graph**, not a graph where a single similarity scalar replaces an Edge embedding, and not necessarily a graph with a predefined relation-type taxonomy.

## 1. Starting point and explicit assumptions

- The VL-DocIR RepresentativeSubset adapter produced **139 documents, 2,948 pages and 112,591 canonical Nodes**. The published retrieval experiment used **104,318 retrieval views**; the remaining **8,273 visual-URL Nodes** remain in the canonical universe but were not encoded by these text-based routes. **View count is not automatically unique Node count**: retain the canonical ID mapping and eligibility audit.
- Five frozen dense retrieval matrices: Qwen3 (1024-d), GTE-Qwen (1536-d), BGE-en-ICL (4096-d), MXBAI (1024-d), GTE-large (1024-d); BM25 is a sixth, sparse **retrieval route**, not a sixth dense vector view.
- Stage 1 currently yields **undirected, unverified candidate pairs**, e.g. Top-20 union **6,655,617** and Top-100 union **34,558,320** on the large corpus. These numbers are *not* counts of accepted semantic relations.
- Structural relations (reading order, parent/child, caption/asset, etc.) come from a **separate Structural Graph pipeline**; they must retain their provenance. Stage 2 may experimentally use them as contextual signals, but should never silently relabel structural edges as semantic evidence.
- Stage 1 is **query-independent**. Neither this document nor the proposed architecture requires **Query Split** to generate candidate pairs or construct the base graph.

### Hard constraints

1. Canonical Node IDs, source content, provenance and **all frozen Node embeddings** remain immutable.
2. Retrieval-specific embeddings are *read-only views*. We may train small **projection / edge interaction modules** in Stage 2, but must not fine-tune or overwrite the frozen encoders.
3. **An Edge is a vector-valued state**, not merely one scalar weight or one cosine score. Scores, confidence heuristics and route provenance are useful *metadata*, not substitutes for the Edge embedding.
4. **Direction matters**: `e_(i→j)` and `e_(j→i)` are separately constructed / represented and must not be assumed equal or exact negatives. A directed candidate does not automatically become a confirmed directed relation.
5. Avoid all-pairs computation and global edge-to-edge attention over millions of edges. Graph operations must be sparse, bounded and reproducible.
6. Do not assume the existence of reliable Node–Node relation labels or treat retrieval absence as a permanent negative relation.

## 2. Three distinct decisions (do not conflate)

| Question | Meaning | Current approach |
|---|---|---|
| **Candidate connectivity** | Should pair `{i,j}` be *considered*? | Stage 1 multi-route retrieval, threshold / candidate-budget pruning; unverified, undirected discovery |
| **Directed Edge representation** | What high-dimensional information captures `i→j`? | Stage 2 asymmetric, multi-view Pair features → Edge embedding |
| **Edge existence/type/strength after reasoning** | Which directions deserve to persist, and what do they mean? | Downstream decision; not solved by a high raw score or clustering alone |

A scalar `weight` can be stored alongside a vector for ranking or gating. It should **not** collapse the vector-valued Edge state.

## 3. Frozen multi-view Node representation

For Node `i`, retain the five encoder representations as a **collection of views**:

\[
H_i = \{h_i^{(1)}, h_i^{(2)}, \ldots, h_i^{(5)}\}, \qquad h_i^{(r)}\in\mathbb R^{d_r}.
\]

Since the five dimensions differ, this collection is **not immediately a rectangular three-dimensional tensor**. Two implementations are valid:

- **Preferred archival representation:** keep five distinct frozen matrices + manifests / canonical-node mapping. No lossy forced alignment.
- **Working model representation:** route-specific learned projections to a shared `d_model` produce five *tokens* per Node or per Edge; only these derived tokens can be stacked as `[N, R, d_model]` (where views exist).

Use an explicit availability mask when a Node lacks a view. Preserve original normalized values and encoder-specific score metrics; **do not add or compare raw vectors across unrelated encoder spaces**.

## 4. Initial *directed* Edge construction

For each undirected Stage 1 candidate `{i,j}`, Stage 2 may evaluate one or both directions independently. For each dense route `r`, construct asymmetric pair features in its **own** vector space:

\[
\phi_{i\to j}^{(r)} = [\ h_i^{(r)}\ ;\ h_j^{(r)}\ ;\ (h_j^{(r)}-h_i^{(r)})\ ;\ h_i^{(r)}\odot h_j^{(r)}\ ].
\]

The source and target slots plus **signed difference** retain orientation. Element-wise product is a symmetric complement; it does *not* replace direction. For a deliberately simple comparison, also compute:

\[
\mathrm{mid}_{ij}^{(r)}=\tfrac12(h_i^{(r)}+h_j^{(r)}),\qquad
\mathrm{diff}_{i\to j}^{(r)}=h_j^{(r)}-h_i^{(r)}.
\]

**Interpretation caveat:** midpoint usually captures *shared topic*; signed difference captures *direction in embedding space*. Neither automatically encodes `SUPPORTS`, `CAUSES`, `CONTRADICTS`, etc. Their utility must be tested. The construction should compare:

- **Baseline A1:** midpoint-only (intentionally symmetric).
- **Baseline A2:** signed difference (directional, inexpensive).
- **Baseline A3:** concatenated source / target / signed difference / interaction features.
- **Model B:** adaptive multi-view fusion of A3-style per-route features.

For each route: `p_(i→j)^r = P_r(phi_(i→j)^r) ∈ R^d_model`, where `P_r` is trainable **only if a learning objective is defined**. BM25 score, route rank, mutual discovery and raw retrieval confidence proxies are **separate auxiliary metadata**; missing route observations are marked `NOT_OBSERVED`, not zero affinity.

## 5. QKV module 1 — Adaptive multi-view Edge fusion

Treat the projected **per-route pair features** of a single directed pair as a small set of tokens. A pair-conditioned query attends over the available route-specific keys / values:

\[
q_{ij}=W_Q\,\mathrm{Pool}(p_{i\to j}^{(1)},\ldots,p_{i\to j}^{(R)}),\quad
k_{ij}^{(r)}=W_K p_{i\to j}^{(r)},\quad
v_{ij}^{(r)}=W_V p_{i\to j}^{(r)},
\]

\[
\alpha_{ij}^{(r)}=\operatorname{softmax}_r\!\left(\frac{q_{ij}^{\top}k_{ij}^{(r)}}{\sqrt{d_k}}\right),\qquad
 e_{i\to j}^{(0)}=\sum_r\alpha_{ij}^{(r)}v_{ij}^{(r)}.
\]

Potential multi-head extension; keep residual pair information accessible to guard against fusion bottlenecks. **Attention weights are scalars, but the output Edge state is a vector**. Attention weights are not calibrated probabilities of a semantic relation.

This is **adaptive Edge initialization**, not yet dynamic *graph-context* updating. A QKV module with only one key has trivial softmax weight 1; the multiple view tokens are the meaningful alternatives here.

## 6. Clustering — where and why

**Place relation clustering after initial Edge embeddings and before cluster-guided contextual updating.** Cluster **Edge embeddings** rather than automatically clustering Node embeddings.

- Node clustering answers “which Nodes share topics?” and remains a separate baseline.
- Edge clustering seeks “which **directed relation patterns** share structure across topics or documents?” This is a *hypothesis*, not guaranteed by midpoint/difference embeddings.
- Community detection clusters connected *graph topology* and is a different procedure.

### Relation prototypes and soft membership

Fit or update `K` relation-prototype vectors `c_1,...,c_K` from a representative, sampled set of initial directed Edge embeddings, then compute soft membership:

\[
a_{ij,k}=\operatorname{softmax}_k\left(\frac{\operatorname{sim}(e_{i\to j}^{(0)},c_k)}{T}\right).
\]

This assignment is **not** a relation probability and does not force every Edge into one hard-coded class. Use the top few prototype vectors (or an attention-based prototype memory) as additional context for that Edge. Prefer sampled / mini-batch / periodically updated prototypes rather than K-means on all millions of Edge vectors after every update.

**Failure modes to audit:** topic/domain clustering rather than relation clustering; popular clusters absorbing all pairs; unstable clusters; prototype leakage of document identity; high-frequency generic formula relationships dominating. Compare to a **no-prototype** model rather than assuming clustering helps.

## 7. QKV module 2 — Local directed Edge-to-Edge updating

For the target Edge `i→j`, let `N_E(i→j)` be a **bounded set of context Edges** with explicit role/direction labels, e.g. `i→k`, `k→j`, incoming/outgoing neighbors, and selected two-hop directed paths. Only such selected local Edges—not every graph Edge—participate in QKV:

\[
q_{ij}^{(t)}=W_Q^E e_{i\to j}^{(t)},\qquad
k_{uv}^{(t)}=W_K^E[e_{u\to v}^{(t)};\mathrm{role}(uv,ij)],\qquad
v_{uv}^{(t)}=W_V^E e_{u\to v}^{(t)}.
\]

\[
 m_{ij}^{(t)}=\operatorname{Attention}\big(q_{ij}^{(t)},\{(k_{uv}^{(t)},v_{uv}^{(t)}):(u,v)\in N_E(i\to j)\}\big).
\]

The `role` or path encoding distinguishes `i→k→j` from `j→k→i`. Optionally include the top associated **relation prototypes** as additional key/value tokens. Update via a residual gated state function:

\[
 e_{i\to j}^{(t+1)}=e_{i\to j}^{(t)}+g_\theta(e_{i\to j}^{(t)},m_{ij}^{(t)},H_i,H_j).
\]

The function may be an MLP / GRU-like gate. The frozen Node tensors `H_i,H_j` are **read-only conditioning inputs** at every layer. Structural edges, if used, must be tagged as `STRUCTURAL_CONTEXT`, never confused with output semantic edges.

Here **dynamic** means *edge states evolve across graph-context propagation steps* (or upon a changed graph). With an identical graph, frozen inputs and deterministic model, repeated inference need not change them. This does **not** require user-query conditioning or Query Split.

### Optional iterative clustering/update cycle

`initial directed edges → soft prototype discovery → local QKV update → updated edges → occasional prototype refresh`. This is **proposed and optional**, not a requirement to rerun full clustering on every layer.

## 8. Training is a separate open problem

The five dense encoders are pretrained and frozen. But any newly introduced `P_r`, `W_Q/K/V`, gates, or trainable prototypes **will not be meaningful without a training / self-supervision objective**.

Potential research directions, **not yet selected**:

- **Masked edge-context prediction:** predict a withheld edge feature or its multi-view signal from bounded adjacent edges; avoid simply copying a retrieval score used to generate that edge.
- **Cross-view consistency with diversity preservation:** perturb/drop retrieval views while preserving the directed pair identity; discourage constant vectors and preserve genuinely unique single-route information.
- **Graph-path composition / contextual reconstruction:** distinguish real short directed paths from carefully constructed alternatives using graph topology and provenance; do not treat every unobserved pair as an absolute negative.
- **Independent evidence anchors:** exploit high-precision reference/citation or document structure only as explicit, provenance-aware *weak* signals; do not let the model win by learning document-adjacency shortcuts.

No artificial binary Node-pair “true relation” label is mandated for Stage 1. Stage 2 may still need a clear measurable objective and external task evaluation to demonstrate that relation vectors capture more than document topics.

## 9. Ablations and evaluation plan

| Experiment | Edge features | Multi-view attention | Local edge QKV | Prototypes | Purpose |
|---|---|---|---|---|---|
| A1 | Midpoint | No | No | No | Symmetric topical baseline |
| A2 | Signed difference | No | No | No | Cheapest directional baseline |
| A3 | Source/target/diff/product | No | No | No | More expressive fixed directional features |
| B | Learned multi-view directed pair fusion | Yes | No | No | Adaptive initial relation representation |
| C | B + local directed edge context | Yes | Yes | No | Value of dynamic contextual updating |
| D | C + soft relation prototypes | Yes | Yes | Yes | Incremental value of clustering |

Additional checks:

1. **Direction swap:** `e_(i→j)` vs `e_(j→i)` must be independently represented, not trivially identical; asymmetry alone is **not** evidence of correct direction semantics.
2. **Cross-topic relation pattern:** do Edge clusters express recurring relation modes across domains, or simply separate medicine / physics / finance topics?
3. **Prototype ablation:** D vs C, controlling model size, candidate budget and runtime.
4. **Context ablation:** C vs B, and perturb / restrict local edge neighborhoods to check whether contextual updates carry nontrivial information.
5. **Retrieval/evidence utility:** evaluate on held-out downstream tasks with evidence provenance where possible; these *evaluation queries* do not imply Query Split or query-dependent Stage 1 graph construction.
6. **Efficiency:** runtime, memory, active edge states, batch size and candidate scaling at matched budgets. Report uncertainty and limits; clustering compactness alone does not establish meaningful relations.

## 10. Scale and implementation guardrails

- Stage 1 may yield **millions to tens of millions of undirected candidates**. Expanding *both directions* can double the provisional directed edge state count; do not allocate full high-dimensional state for every pair by default.
- Keep **five frozen Node embedding matrices**, a **canonical ID map**, and compact candidate `(src,dst,route-provenance,score)` records as primary assets. Compute pair features **on demand / in chunks**.
- Select a **working candidate budget** before training; batch and stream; shard by Edge ID; use bounded local neighborhoods (e.g. compare 8 / 16 / 32 neighbors as *experimental settings*, not facts).
- A compressed dynamic Edge state of ~64–256 dimensions is an *engineering option*; do not confuse it with discarding source views, which remain accessible.
- Fit prototypes from representative stratified edge samples and perform batched soft assignments; do not build a dense edge-by-edge similarity matrix.
- Separate directed Edge identity and retrieval direction: being discovered from `i` to `j` via ANN does **not** mean the semantic relation must point `i→j`.
- For the 8,273 visual-URL Nodes currently outside text retrieval, record coverage limits explicitly. A future visual route requires genuine visual inputs or validated descriptions, not a guessed text embedding.

## 11. Confirmed direction vs unresolved choices

### Agreed working direction

- Keep Node embeddings frozen and all five encoder views available, without blind summation.
- Stage 1 outputs query-independent, unverified sparse candidate pairs; Structural Graph is built separately.
- Use **high-dimensional directed** Edge representations; retain simple signed-difference / midpoint baselines.
- Consider **QKV twice**: multi-view initialization, then local directed edge-to-edge contextual updating.
- Experiment with **soft clustering of Edge embeddings into relation prototypes** between initialization and contextual updating; compare to no-cluster control.
- Avoid replacing Edge embeddings by scalar confidence or routing score.

### Must be resolved experimentally

- Which initial pair feature / projection and common dimension best preserve useful relation information?
- How should we learn QKV and prototypes **without** assuming a closed relation taxonomy or universally valid pair labels?
- How to construct trustworthy local directed contexts and control false-path propagation?
- How many prototypes / neighbors, how often to refresh, and how to prevent topic collapse?
- What graph budget and downstream measurement justify added Stage 2 cost?
- Whether an Edge should persist in one direction, both, or neither after learning—the representation alone does not decide existence.

## 12. Papers to read (conceptual precedents, not direct implementations)

- Hussain et al., **Edge-augmented Graph Transformer (EGT)**, KDD 2022 — evolving explicit Edge channels: <https://arxiv.org/abs/2108.03348>
- Christopoulou et al., **Connecting the Dots: Document-level Neural Relation Extraction with Edge-oriented Graphs**, EMNLP 2019 — edge-oriented document reasoning: <https://aclanthology.org/D19-1498/>
- Battaglia et al., **Relational Inductive Biases, Deep Learning, and Graph Networks**, 2018 — edge-state update formulation: <https://arxiv.org/abs/1806.01261>
- **Edge Representation Learning with Hypergraphs**, NeurIPS 2021 — edge-centric message passing / clustering motivation: <https://papers.nips.cc/paper_files/paper/2021/hash/3def184ad8f4755ff269862ea77393dd-Abstract.html>
- **SLAPS**, NeurIPS 2021 — self-supervised graph structure learning background: <https://proceedings.neurips.cc/paper/2021/hash/bf499a12e998d178afd964adf64a60cb-Abstract.html>

---

**Status:** Conceptual design approved for exploration. **No Stage 2 training, semantic edge acceptance, or empirical performance claim is made by this document.**