# DynamicEdgeGraph — Stage 1: Multi-route Retrieval-based Candidate Pruning

> **Implementation specification for Codex / development agent**  
> Version: 2026-11-06 · Scope: **Stage 1 only** · Project: `ruijiexu0503-dot/Project`, working branch `feature/evidence-edges`

## 0. Objective and constraints

Our overall long-term design consists of **immutable, independent, minimal-semantic-unit Node embeddings** and potentially **dynamic Edge embeddings**. This document covers **only the first stage**: prune implausible Node pairs using existing, pretrained retrieval methods and select defensible thresholds, **before** generating, updating, training, or verifying any dynamic Edge embedding.

Stage 1 must answer:

1. With fixed Node embeddings and pretrained retrievers, how many of the possible pairs can we remove cheaply?
2. How many independently verified, truly useful relations survive the candidate filter (candidate recall)?
3. Which retrieval routes are complementary? Are low-similarity but genuinely related cross-document/cross-modal pairs rescued by another route?
4. Where is the pruning–recall operating point, under a fixed computational and candidate budget?

**Non-negotiable:**

- **Do not fine-tune or train any retrieval model in Stage 1.** Pretrained inference only; choose thresholds on a distinct development set or documented review panel.
- **Do not modify, overwrite, or regenerate the original Node embeddings.** Preserve Node IDs, content, modality, source document/page, and reproducible source mapping.
- **Do not conflate similarity with a confirmed evidence relation.** Stage 1 returns *candidate pairs*, not accepted graph edges or typed relations.
- **Do not compute all `n × n` pair scores and then threshold them.** Candidate generation itself must be index-/retrieval-based (or bounded structural lookup); exact scoring is allowed only on retrieved candidates.
- No LLM edge verification, dynamic Edge embedding, QKV/attention training, or graph message passing in this phase.
- Keep the existing `EvidenceNet/`, `EdgeGeneration/`, `OfflineCitationGraph/`, `CrossDocumentDiscovery/`, and frozen outputs unchanged. The new experiment is additive/read-only with respect to these inputs.
- No invented paths or assumptions about currently mounted cluster datasets. Audit actual paths and schemas first and record them in a manifest.

## 1. First action: create a **new top-level project folder** and Stage 1 subfolder

From the **existing Project repository root**, create a brand-new top-level directory, separate from `EvidenceNet/`:

```text
Project/
├── EvidenceNet/                     # EXISTING — do not change
├── EdgeGeneration/                  # EXISTING — do not change
├── ...
└── DynamicEdgeGraph/                # NEW — overall research workspace
    ├── README.md                    # Overall design, frozen-Node contract, phase map
    └── stage1_candidate_pruning/    # NEW — implement ONLY Stage 1 here
        ├── README.md                # How to run, intended semantics, constraints
        ├── configs/
        │   ├── smoke.yaml
        │   └── pilot.yaml
        ├── src/
        │   ├── audit_inputs.py
        │   ├── adapters.py
        │   ├── retrieve_candidates.py
        │   ├── sweep_thresholds.py
        │   └── evaluate.py
        ├── scripts/
        │   ├── run_smoke.sh
        │   ├── run_pilot.sh
        │   └── slurm_stage1.sbatch   # Configurable template only; no guessed account/partition
        ├── tests/
        ├── outputs/                  # generated; ignored by git
        └── reports/                  # small reproducible Markdown/JSON summaries
```

Create only the top-level project folder and **this first-stage subfolder** for now. Describe Stage 2 (dynamic Edge embeddings) in the root `README.md` as future work, but **do not implement Stage 2, and do not pre-create a Stage 2 source tree**.

Place a local `.gitignore` where appropriate so weights, cache, large JSONL, vector files, downloaded pages, and `outputs/` are not committed. Use paths relative to the repository root in configuration where possible. Do not move files from existing experiments.

## 2. Available resources and known project context

### 2.1 GPU is available now

- The user can run GPU workloads on HoreKa2; first inspect the current GPU node/Slurm configuration and actual CUDA availability (`nvidia-smi`, `torch.cuda.is_available()`, current queue/account constraints).
- Prefer GPU for **batched encoding or index/search where it demonstrably helps**; CPU BM25 and simple graph/structural lookups are fine.
- Reuse frozen vectors when they already match the desired retrieval configuration; **do not recompute them merely because a GPU is available**.
- Make device, batch size, GPU memory/precision, model IDs and versions configurable. Offer a CPU smoke fallback; avoid OOM by bounded batches.
- Do not hard-code a job ID, a partition, a resource limit, an environment path, or a Hugging Face access token.

### 2.2 Existing frozen EvidenceNet baseline — audit before use

Prior pilot context (must be rechecked in the actual workspace, **not assumed to hold for a new dataset**):

- Existing 32-document/518-page EvidenceNet pilot contains **7,291 Nodes**.
- A frozen, fair-comparison universe contains **6,520 Nodes** with embeddings.
- A prior candidate experiment used `EvidenceNet/scripts/run_kg_link_prediction_p1_p2.py` and reported highly overlapping P1/P2 candidates (1,086 common out of 1,088 per route). This is a motivation to measure *route complementarity*, not an output to copy as a new result.
- The prior program uses a frozen prep directory and averaged frozen view vectors; inspect its manifests/contracts before reusing it.
- Existing formula/structure/retrieval utilities are under `EvidenceNet/scripts/` (for example `formula_structure_index.py`, `formula_retrieval_views.py`, `run_formula_retrieval_comparison.py`, `vldocir_candidate_comparison.py`). Reuse proven adapters as **imports or read-only adapters**, not by duplicating or mutating legacy pipelines.

**Action:** create `input_audit.json` recording node universe, available embeddings, dimensions, model, modality coverage, dataset origin, source file paths, SHA256, missing values, unique IDs, splits, and which route each node supports. Fail fast on silent drops.

### 2.3 Hugging Face 120-query representative subset — available

Dataset: [`anonymous-8421/VL-DocIR-RepresentativeSubset`](https://huggingface.co/datasets/anonymous-8421/VL-DocIR-RepresentativeSubset)

The official dataset card describes **120 queries** sampled as **4 sources × 6 evidence structure types × 5 queries**, with associated documents and page/evidence records. It is access-gated: authenticate through the user-provided Hugging Face environment/token without printing or committing credentials.

Evidence types: `Page-Single`, `Page-Multi`, `Doc-Adjacent`, `Doc-Near`, `Doc-Far`, `Cross-Doc`. Sources: Wikipedia, arXiv, PubMed, SEC.

**Important evaluation distinction:** the subset's labels are **query → evidence pages** (with more detailed element metadata), **not gold-positive Node↔Node edges**. The 120 queries can evaluate **downstream evidence accessibility/retrieval**, but **must not be treated as 120 positive edges or as complete pairwise ground truth**.

Start by detecting locally downloaded copies and the actual dataset schema. Only download the required files if not already present; the official subset is much smaller than the full VL-DocIR dataset, and Stage 1 must **not** download the full VL-DocIR corpus by accident.

Known possible integration issue: existing frozen 6,520-node corpus and the 120-query subset **may not cover the same documents/pages**. Run a deterministic mapping audit before any evaluation:

```text
120 source queries
  -> query_id, source, evidence_structure, evidence document/page keys
  -> document/page exists in stage-1 node corpus?
  -> mapped eligible Node IDs / evidence pages
  -> coverage and exclusion reason by query
```

A previously explored custom corpus-fixed sample may cover fewer than 120 queries; **do not silently report its metrics as a 120-query result**. Report counts, missing source documents, unmapped pages, and eligible evaluation denominator. If necessary, maintain two separate eval tracks:

- **Frozen corpus track**: current 6,520-node universe, compatible existing ground truth/review labels, comparable with old pilots.
- **Representative-subset track**: new HF 120-query subset, using its *actual* associated document/node universe after ingesting and mapping; report all 120 in a coverage audit and compute retrieval metrics only over valid eligible items, with exact denominator.

Do **not** merge these node universes or publish a cross-track metric as if the underlying corpus were identical.

## 3. Stage 1 pipeline

### Step A — Freeze and validate input adapters

- Define a canonical input contract for each Node: `node_id`, `document_id`, `page_number`, `modality`, `text` or relevant existing textual view, `embedding_ref` or `embedding`, `source_revision`.
- Keep raw text/visual metadata separate from the Node embedding; original embeddings remain immutable.
- Normalize IDs and maintain deterministic Node ID ↔ document/page mapping, especially for HF page-level relevance.
- Exclude self-pairs, deduplicate candidates, and preserve route provenance/rank/raw score.
- Record which Nodes are excluded (missing embeddings/text/unsupported modality) rather than implicitly removing them from the denominator.

### Step B — Retrieve candidate pairs with **pretrained** routes

Implement a configurable minimal set of **complementary routes**:

1. **Dense ANN**: frozen existing dense embeddings (e.g. the exact frozen Qwen3-Embedding view/config already used). Use FAISS or an equivalent efficient index; allow cosine via normalized vectors; tune `top_k` and score threshold. First reproduce a simple cosine-ANN baseline.
2. **Sparse lexical**: BM25 over existing Node text/views (or an already available sparse retriever). Scores and thresholds are route-specific. Shared terms are only a candidate signal, not proof of relation.
3. **Structural**: bounded candidates from existing document/page/reading-order/caption-asset relations, with documented edge-source restrictions. Structural adjacency is a *proposal signal*, not a verified semantic edge.
4. **Formula / modality-specific (optional, after audit)**: reuse existing formula structure retrieval or an available pretrained visual/late-interaction retriever where coverage and GPU memory make it justified. Keep the route separately identifiable. No new training.

A **route is a retrieval mechanism**, not an Edge type. Prefer **union of routed candidate lists**, not intersection:

```text
candidate(i) = UNION_r { j ∈ retrieved_topK_r(i) : score_r(i,j) ≥ threshold_r }
```

An ANN Top-K cap can miss relevant pairs regardless of threshold: explicitly separate *retrieval ceiling recall* (before threshold) from *threshold survival recall*. Do not compute pairwise all-vs-all scores as an intermediate output.

For directed retrieval `i -> j`, retain direction and rank in raw route files; for a Stage 1 undirected pair candidate output, canonicalize `(min(node_id), max(node_id))` and retain both discovery directions. Direction/type labels are a later stage.

### Step C — Threshold sweep **without training**

- Produce score distributions and route-specific candidate counts; **never compare raw BM25 values to raw cosine values using a shared numerical threshold**.
- Sweep `top_k` (e.g. 20, 50, 100, 200) and each route's score threshold/score quantile over a **fixed index**, recording the complete configuration. These are starting sweep values, not optimal settings.
- Support a simple **per-route OR gate**: retain a pair if any independent route meets its own threshold. Compare to Dense-only and Dense+BM25 baselines.
- Optionally explore post-retrieval reciprocal-rank fusion (RRF) as an *additional candidate ranking baseline*, but do not confuse a rank-fusion score with a calibrated probability or let RRF destroy per-route rescue behavior.
- Use a small, independently verified/held-out Node-pair review set to select thresholds. Separate **positives**, **hard negatives**, and **unknown/unlabeled**. Treat unknown as unknown, not automatically negative.
- Where exhaustive pair labels are unavailable, report **observed positive-edge recall** and qualified candidate reduction, never claim true corpus-wide Edge Recall. If necessary, construct a blinded manual review panel for missed low-similarity examples.
- Select the operating point with a prespecified constraint, e.g. maximize pruning subject to at least 95% *observed* positive-edge recall on a **development** set. This 95% is a configurable initial objective, not a guaranteed result. Validate on a distinct held-out set.

Core metrics:

```text
candidate_recall = observed_gold_positive_pairs_surviving / observed_gold_positive_pairs_in_universe
pruning_rate     = 1 - unique_retained_undirected_pairs / [N * (N-1) / 2]
route_novelty(r) = true_positive_pairs_only_found_by_route_r / all_observed_gold_positive_pairs
```

Report the denominator and candidate generation cost (GPU-hours/elapsed time/peak VRAM), plus comparisons at **matched candidate budgets**. A high pruning rate alone is not success if low-similarity true relations disappear.

### Step D — Evaluate with 120-query HF subset (downstream, *not* pairwise edge gold)

The HF label describes what **pages** answer each query. For compatible query/document/page mappings, evaluate **query → evidence page** retrieval or evidence reachability under controlled conditions:

- Run a fixed query→Node/page seed retriever baseline with no candidate graph.
- Under an identical seed budget, permit one-hop expansion over the **retained candidate graph** as a diagnostic; cap added nodes/pages and match the final rerank budget.
- Compare page-level `Recall@K`, `all-evidence-complete@K` (all gold pages required), `MRR`/`nDCG` where valid, and *additional gold pages reached* over the seed baseline.
- Break down by six evidence structures and four sources; prioritize Cross-Doc and Doc-Far failure modes.
- Report per-query outcomes and query/document coverage; if only 111/120 are currently mapped, say **111/120**, enumerate the nine omissions, and do not call it a 120-query scored evaluation.
- **Data leakage**: do not use the final 120-query test results to repeatedly optimize thresholds and then present the same queries as an untouched test set. If no external dev set exists, pre-register a stratified dev/test split by document family and report it, or explicitly label the 120-query result as exploratory and reserve a later held-out benchmark.
- Query-level page labels do **not** tell you which Node↔Node edge is true. Keep these two evaluation tracks separate.

### Step E — Failure analysis

Specifically audit:

- Low-cosine but real relationships (analogous to watermelon ↔ bee under pollination context).
- Formula equivalence under variable renaming versus false semantic matches.
- Generic/ubiquitous expressions and hub nodes causing false candidate explosions.
- Cross-document and cross-modal candidates missed by Dense ANN.
- Candidate overlap between routes, both all-pairs overlap and unique rescued positive pairs.
- Whether structural candidates overfit same-document/nearby-page patterns.
- Ranking bottleneck: even valid extra graph candidates may bring no improvement after a fixed reranker, as seen in the earlier 24-query pilot.

## 4. Outputs and reproducibility requirements

All generated artifacts go under `DynamicEdgeGraph/stage1_candidate_pruning/outputs/<run_id>/`, with **no overwrite** of historical data:

| Artifact | Contract |
|---|---|
| `input_audit.json` | Complete input/model/coverage/sha256 and frozen-node eligibility audit |
| `hf_120_coverage.jsonl` | Every one of the 120 HF query IDs, source/type, evidence-page mapping, status/reason |
| `route_candidates/<route>.jsonl` | `source_id`, `target_id`, `route`, `direction`, `rank`, `raw_score`, `model/version`, `run_id` |
| `candidate_union.jsonl` | Canonical unique pairs, route contributions, rank/score by route, score gates passed |
| `threshold_sweep.csv` | Threshold/Top-K/budget grid, observed recall, pruning, timing, route coverage |
| `route_overlap.json` | Pair intersections, unique candidates, unique gold-positive rescues |
| `stage1_metrics.json` | Fixed-universe denominator, selection protocol, metrics, exclusions, resource usage |
| `hf_120_results.jsonl` | Eligible query-by-query page metrics and evidence reachability; never relabel as pairwise edge ground truth |
| `manifest.json` | Git commit, exact model IDs, dataset revisions, seeds, config, source hashes, hardware |
| `reports/summary.md` | Plain-language findings, threshold choice, failure examples, next-stage handoff |

Requirements: deterministic ordering; versioned run IDs; reproducible configs; smoke tests; no leaked credentials; no silent denominator changes; failure logs for unsupported modalities and unavailable inputs.

## 5. Suggested implementation and execution order

**Do not write a monolithic script. Execute in these milestones and stop on failed validation.**

1. Create `DynamicEdgeGraph/` and `stage1_candidate_pruning/`, READMEs, `.gitignore`, simple config schema.
2. **Audit-only pass**: locate/inspect frozen embeddings, candidate artifacts, prior acceptance/review labels, and HF subset data. Generate `input_audit.json` and all-120-query coverage table. Do not launch large GPU jobs yet.
3. Implement a **small CPU/GPU smoke** with 100–300 eligible Nodes, Dense ANN and BM25; verify deterministic pair ID, score gates and routing union; add unit tests.
4. Run **frozen-corpus full-universe** Dense-only, BM25, and route-union comparisons using existing embeddings and GPU where beneficial.
5. Add audited structure/formula route(s) only if they provide genuinely new candidates or independently verified positives.
6. Sweep thresholds with declared development labels and matched candidate budgets; choose an operating point and validate independently.
7. If mapping is ready, run the independent 120-query downstream analysis on its compatible corpus. Otherwise provide a **coverage/blocker report**, not fabricated scores.
8. Write `reports/summary.md` and a frozen candidate-pair handoff contract for a future Stage 2. Do **not** build dynamic Edge embeddings in this phase.

Provide a command-line interface similar to:

```bash
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.audit_inputs --config DynamicEdgeGraph/stage1_candidate_pruning/configs/pilot.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.retrieve_candidates --config DynamicEdgeGraph/stage1_candidate_pruning/configs/pilot.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.sweep_thresholds --config DynamicEdgeGraph/stage1_candidate_pruning/configs/pilot.yaml
python -m DynamicEdgeGraph.stage1_candidate_pruning.src.evaluate --config DynamicEdgeGraph/stage1_candidate_pruning/configs/pilot.yaml
```

These commands are **target interfaces to implement**, not claims that the scripts already exist. Decide whether to use modules, directly invoked scripts or a CLI after inspecting repo packaging; update READMEs to match the implemented entry points.

## 6. Definition of Done for Stage 1

- [ ] New root directory + Stage 1 subdirectory created; no existing pipeline files or frozen artifacts changed.
- [ ] Frozen-node count, embedding dimensions/revisions, and all dataset IDs audited and recorded.
- [ ] Official 120-query dataset discovered/loaded safely; all 120 IDs covered by a mapping audit, with failures explicit.
- [ ] At least Dense and Sparse retrieval routes tested, **without any new model training**.
- [ ] Retrieval is candidate-bounded; no full `N × N` similarity materialization.
- [ ] Per-route thresholds and a union strategy evaluated; Top-K retrieval ceiling distinguished from threshold recall.
- [ ] Candidate count/pruning/observed edge-positive recall/route novelty and cost reported with exact denominators.
- [ ] Downstream HF page-evidence evaluation reported only on compatible query/node universes, with honest eligibility counts and no pairwise-label conflation.
- [ ] Deterministic candidate JSONL + manifest + human-readable report produced.
- [ ] No Dynamic Edge Embedding, QKV training, GNN training, or LLM verification implemented in Stage 1.

## 7. Future-work boundary (planning only; do not implement now)

**Stage 2: Dynamic Edge Embeddings with Frozen Nodes.** Given Stage 1 candidates, learn an edge relation representation `e_ij^(context)` that can change with admissible context while the original `h_i`, `h_j` remain fixed. Possible edge-centric attention/message passing is out of scope here. Stage 1 must only hand off stable candidate IDs, retrieval provenance, scores, source evidence references, and audit manifests.

---

**Implementation instruction to agent:** Inspect the latest actual workspace and dataset schemas first; preserve all original artifacts; create the requested directory structure; implement Stage 1 incrementally with tests and auditable metrics. If a supposed 120-query test item cannot map to this node corpus, report it as unmapped rather than guessing. Stop after Stage 1.