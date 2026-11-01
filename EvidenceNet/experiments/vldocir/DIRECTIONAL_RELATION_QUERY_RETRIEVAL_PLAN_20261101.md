# Directional Relation Representation × Query Retrieval Pilot

Date: 2026-11-01  
Status: **implementation and evaluation plan, not implemented or measured**  
Target branch: `feature/evidence-edges`  
Scope: VL-DocIR 24-query / 518-page **development pilot**; preserve frozen assets.  
Goal: test whether **how we represent an existing, evidence-grounded relation** improves query-time *edge choice, new evidence discovery, final retrieval ranking, and evidence efficiency*, without requiring online generative LLM judgments.

## 0. The actual research question

Given two existing EvidenceNodes A and B and a supported relationship between them, should the retriever store (1) a fixed relation type, (2) an open textual description, (3) a **directional, target-oriented retrieval description**, or (4) a hybrid representation? Which representation makes the relation usable when an **unseen query** arrives?

This is **not** a request to generate more edges, reclassify all nodes, train PairRE, or optimize Qwen's sufficiency prompt. **Freeze the same graph and endpoints** for the primary comparison. If all arms fail because a relevant target is unreachable, report a graph-coverage limitation instead of inventing a representation gain.

Two distinct questions must be measured:

- **Representation quality**: given the same seed and real outgoing routes, does a query select a useful edge/target?
- **End-to-end utility**: does that selection find additional *verifiable source evidence* or improve final page ranking, sufficiency, or tokens against a no-edge budget-matched baseline?

A good edge may have zero marginal utility for a particular query. Never force navigation on an already sufficient case to manufacture a benefit.

## 1. Current code and frozen context (verify again before implementation)

Entry points and materials, relative to repository root:

| Path | Role |
| --- | --- |
| `EvidenceNet/scripts/run_vldocir_edge_embedding.py` | Prior frozen edge embedding stages (`prepare/describe/embed/retrieve/report`), matched retrieval arms and reranker; reuse encoder, hashing and evaluation helpers where compatible |
| `EvidenceNet/scripts/run_query_semantic_edge_v2.py` | Query-side adaptive selection/navigation; currently includes online Qwen assessments. Do **not** silently claim the new method is LLM-free if calling it |
| `EvidenceNet/scripts/query_semantic_edge_policy_v2.py` and `query_semantic_edge_core.py` | Query state / selected evidence / route protocol; reuse stable schemas, avoid monkey-patching legacy behavior |
| `EvidenceNet/scripts/vldocir_reading_backbone.py` | NEXT/PREVIOUS importer and validation; code existing **does not prove deployed reading layer is loaded** |
| `EvidenceNet/experiments/vldocir/EDGE_EMBEDDING_HANDOFF_20261025.md` | Original edge-index constraints and data location |
| `EvidenceNet/experiments/vldocir/QUERY_SEMANTIC_EDGE_R4_RESULTS_20261031.md` | Federer r4: both arms stopped before navigation, not a relation-representation test |
| `EvidenceNet/experiments/vldocir/EDGE_CONSTRUCTION_PLAN_AFTER_HF_20261101.md` | H0/H1/N comparison, graph coverage, node localization limitations |
| `migration/vldocir-edge-20261022/results/graph/related.jsonl` | Historical G0 related proposals; 213 total, 187 semantic-routed in original frozen configuration (verify manifest, do not assume manually audited gold) |
| `migration/vldocir-edge-20261022/results/nodes.jsonl` | Original nodes and source anchors |
| `EvidenceNet/output/vldocir_colnomic_7b_20261016/` | H0 ColNomic scores (check exact paths and hashes) |

Snapshot facts for interpretation, **not** expected new results: H0 ColNomic Recall@5 79.17%, Recall@10 91.67%, AP@5 65.83% over 24 development questions. These are **page-level** results; no claim about final answer correctness. Prior semantic navigation results did not demonstrate new evidence benefit. Old semantic-only trace reported `reading_layer: not imported: upstream reading_ready=false`. Re-check **the exact current run manifest** rather than assuming structure either loaded or absent. Current reading importer documents page-local flows and does not synthesize cross-page/singleton links.

## 2. Experiment hypothesis and controls

- H1: A directional **target contribution** text is a more actionable edge-retrieval key than generic `RELATED` or an undirected description.
- H2: Combining typed coarse family + directional description may improve retrieval robustness, but can also lose rare/open relationships.
- H3: Any improvement must survive the identical graph, seed list, query encoder, candidate exposure budget and final reranker. Improvement in route ranking alone is **not** improvement in final evidence.
- H4: Structural reading edges may be useful for grounding, but must be reported **separately** from semantic edges.

Primary study: **freeze node IDs, edge IDs, endpoints, anchor text, underlying graph, seed retrieval and source evidence. Vary only edge representation and how it is encoded/scored**. Make same-model/normalization comparisons first. If adding new structurally grounded edges later, assign a new graph version and a separate factorial experiment.

### Primary arms

| ID | Relation representation used for online route ranking | Notes |
| --- | --- | --- |
| R0 | No semantic graph: budget-matched dense expansion | Fair no-edge control, same source reading / reranker |
| R1 | Type-only: coarse, evidence-grounded type string, direction where intrinsically supported | Do not force all relationships into arbitrary fine taxonomy; unknown → `RELATED` |
| R2 | Existing open relation description | Current baseline; preserve exact frozen description text and hash |
| R3 | **Directional target-oriented description** (`A→B` and `B→A`) | Main hypothesis |
| R4 | Hybrid type + directional description, same encoder and route budget | Compare to R3, not just R1 |
| R5 (diagnostic) | Endpoint/pair text embedding only | Checks whether new “relation” gain is just target lexical similarity |

If current G0 relation descriptions are poor, do **not** give R3 extra facts or privileged context. Both representations must derive from the same supported source anchors. Free descriptions can be regenerated in an explicitly versioned **secondary** comparison if desired; mark that both prompting and representation changed.

### Structural layer: separate switch

Run semantic graph with `reading=off` for primary arm isolation. Optionally repeat R0/R2/R3/R4 with **the same manifest-verified** reading graph on/off. Reading NEXT/PREVIOUS are positional navigation hints, not semantic evidence relations. Only call it `reading=on` when the imported edge manifest, counts, endpoints, and actual query trace prove it. No silent fallback.

## 3. Offline relation representation (no evaluation query or gold visible)

**Do not rebuild the nodes or graph for the primary pilot.** For each existing eligible semantic edge, produce two *directed retrieval records* tied to the same immutable undirected edge identity. These are two navigation views, **not** two newly verified factual edges.

Minimal JSONL record (example is illustrative, not a claimed corpus fact):

```json
{
  "edge_id": "edge_123",
  "source_node_id": "A",
  "target_node_id": "B",
  "direction": "A_to_B",
  "relation_family": "EXPLANATION",
  "shared_subject": "phonon population decay in the same experiment",
  "known_source_contribution": "A reports the observed decay",
  "target_contribution": "B describes a mechanism proposed for that decay",
  "directional_retrieval_text": "From the reported phonon population decay, find the explanation and mechanism discussed in the linked passage.",
  "relation_statement": "B proposes a mechanism explaining A's observation.",
  "qualifiers": ["same experimental setting", "mechanism is proposed, not proven"],
  "source_anchor_ids": ["a-span-1"],
  "target_anchor_ids": ["b-span-2"],
  "verifier_status": "proposal",
  "parent_edge_sha256": "...",
  "representation_version": "directional_relation_v1"
}
```

Exact schema can be adapted to existing IDs; do not invent actual source spans, relations or `verified` status. A/B reversed must be generated with swapped **known/target contributions** and an appropriately reversed navigation prompt, **not** by copying forward text or asserting reverse causation. Coarse type must not replace original open relation statement.

**Generation contract:**
1. Input only the frozen, provenance-linked source and target anchors plus the existing grounded relation description and necessary bounded context. Never include queries, gold, qrels, gold-page IDs, evaluation annotations, or known answers.
2. Relation description must retain entities, properties, temporal/experimental scope, modality, uncertainty, and directional asymmetry. Do not hallucinate measurements or physical causality.
3. For a vague/unsupported existing edge, mark `unknown` / `insufficient_anchor` instead of fabricating target contribution. Preserve it in the comparison accounting and report skipped edges.
4. Encode **directed retrieval text separately** from optional type, target content, or concatenated hybrid; cache vector with exact encoder/revision, instruction prefix, normalized embedding policy, source/prompt/config SHA and input text hash.
5. Queries are encoded online using the **same compatible encoder space** as edge vectors. Do not dot-product prior 0.6B query embeddings against 8B relation vectors; do not equate a scoring prompt change with representation quality.
6. The description is only a *navigation hint*. It cannot be passed to a final answer model as if it were original evidence.
7. Store a `relation_representation_manifest.json` with graph version, eligible/created/skipped counts, type distribution, direction coverage, model revisions and full hashes. Never overwrite prior artifacts.

Proposed new isolated files (names may be adapted if a reusable module already exists):
- `EvidenceNet/scripts/prepare_directional_relation_views.py`
- `EvidenceNet/scripts/encode_directional_relation_views.py`
- `EvidenceNet/scripts/run_directional_relation_retrieval.py`
- `EvidenceNet/tests/test_directional_relation_retrieval.py`

New outputs: `EvidenceNet/output/directional_relation_pilot_v1_20261101/`; treat existing baselines and snapshots as read-only. No GPU job claims before actual submission and result validation.

## 4. Online query path: exact proposed flow

```text
Natural-language query q
  ├─ Encode q (same compatible embedding space)
  ├─ Frozen no-edge seed retrieval → Top10 actual EvidenceNodes (preserve all ranks)
  ├─ [optional] deterministic query facets, no generative LLM in primary arm
  └─ State S = evidence actually read; unresolved needs are optional diagnostics
           ↓
For EVERY seed node s in Top10:
  enumerate real adjacent semantic edge(s) and directional s→t views
  [optional separate reading neighbor list]
           ↓
rank reachable (s, edge, t) ROUTES by matching query to directed edge view
  plus explicitly logged controls (query↔target score, seed rank, etc.)
  no gold / learned answer in route score
           ↓
fixed route exposure budget and deterministic tie-break
           ↓
read target t's SOURCE anchors + necessary bounded original context
  count actual exposed nodes, route descriptions, anchor tokens
           ↓
apply SAME downstream no-edge/edge source ranking + packer/reranker
  no unconditional edge bonus, no replacing source with generated relation text
           ↓
final page ranking, selected original spans and per-query trace
```

**Important**: For the primary embedding-only arm, no online calls to Qwen `requirement assessment`, `marginal support`, `selected_set_audit`, or `navigation` for route/stop decisions. A deterministic fixed exploration budget is simpler and tests edge representation directly. Existing Qwen-assisted approach may be reported as a **separate reference arm**, with its full online token cost. Do not silently reuse `run_query_semantic_edge_v2.py` with hidden Qwen calls and label it embedding-only.

### 4.1 Retrieval/scoring definitions

Start with **the simplest single-vector score**:

```python
route_score(q, s, e, t) = cosine(query_vector, directed_edge_view_vector[s, e, t])
```

This is a hypothesis, **not** proof that natural-language questions and retrieval-directed statements occupy the same embedding distribution. Test query prompts: plain question vs identical-task instruction used for all R1–R4. If comparing prompts, run them as a separately labeled factor.

Optional ablation: combine directional relation matching with a target node score, but make it explicit:
```
score = alpha * normalized_relation_score + (1 - alpha) * normalized_target_score
```
Pre-register alpha on a **separate tuning split**, and report pure relation (`alpha=1`) and pure target (`alpha=0`). Do not tune coefficients against the 24 repeatedly inspected development query outcomes and call that generalization.

For multi-constraint queries, try a **separate** deterministic facet method only if useful: compare the full query vs 2–N rule-extracted facets; no facet-aware method should receive gold or additional manual hints, and give all compared arms the same facet representation. Node identity/year/unit constraints should be validated in the **original source**, not assumed satisfied by embedding similarity.

### 4.2 Navigation details and stopping

- Seed set: fixed Top10 **nodes** (not Top10 pages). Every seed has route-proposal eligibility, including rank10.
- Only actual adjacency from the frozen edge list qualifies in the primary navigation test. Global edge embedding search that introduces an unrelated edge is a **different** arm (`global_edge_search`), never quietly mixed with graph walking.
- Permit targets outside seed set; log original dense rank or `not_in_candidate_pool`. Deduplicate target reading while retaining all proposed source-edge paths.
- Primary: one hop, deterministic route budget(s), e.g. `max_routes_scored=all_adjacent`, `max_new_targets=5/10`; report all actual counts. Secondary: two hops, hard bounds on traversals, cycles, degree/hubs, score evaluations and source tokens.
- Do **not** stop because Qwen declares seed sufficient in the embedding-only primary arm; use fixed budget so each representation gets equal opportunity. Report the unnecessary overhead for already-sufficient seed cases. Adaptive stopping is a secondary, separately measured learned/deterministic policy.
- Reading layer is a distinct flag and consumes the same accounted exposure budget; never assume `NEXT` means the target answers the query.
- Under **equal target exposures** and **equal reader text/visual budgets**, allow common reranker to choose among seen source anchors. Keep route ranking and final evidence ranking separate.
- If a target is not backed by accessible original span/table/crop, mark `unavailable_source`, do not infer facts from generated descriptions.
- For negative facts, specific dates, subjects, variables, axes, units, experimental conditions and figure/table identity, retain necessary original context; don't truncate mid-token/row.
- Online cost accounting: encoder compute, route-score operations, source nodes/anchor tokens, reranker compute, **all** online LLM calls where applicable, final reader tokens and latency. A shorter final packet alone is not lower total cost.

### 4.3 Example query case (illustrative only)

Query: `What mechanism explains the observed phonon decay?`

- Seed A contains the measured decay. It is related to B, which contains a grounded proposed mechanism.
- R1 type text `EXPLAINS`; R2 open description may be vague; R3 A→B view explicitly says `find the proposed mechanism accounting for the observed decay`.
- Online query encoder compares with A→B view; if selected, system reads B's **original** source evidence and preserves the term `proposed`.
- Reverse direction B→A says `find the observed phenomenon the mechanism was proposed to explain`, rather than reusing the forward statement.
- If B repeats A or changes subject/experimental condition, the route is logged as redundant or wrong after independent evidence review; do not declare improvement just because B was visited.

## 5. Evaluation: do not confuse route, page and reader evidence

**First implement a representation-isolation test** (offline route ranking without full Qwen reader): create independently reviewed per-query/seed route labels *only for evaluation* on a small blinded subset. Labels: `direct_new_support`, `necessary_context`, `useful_bridge`, `redundant`, `unrelated_or_wrong`, `unknown`. Review both visited and unvisited candidates. These labels are never written into the retrieval index.

Report (a) eligible query-seed pairs and no-route cases, (b) route Recall/MRR/nDCG@K on **reviewed** examples, (c) destination exposure and useful-route precision, and (d) absent-target oracle reachability for a fixed 1/2 hop budget. Keep `unknown` explicit and note incomplete labels.

**Then end-to-end frozen retrieval**:
- Page Recall@5/@10, AP@5/@10, nDCG@5/@10, RecallAll if applicable, fixed page aggregation/tie-break. Use exact existing evaluation functions and freeze result input.
- Evidence-level: independently checked required facts/constraints preserved, citations/source spans actually included, redundancy, evidence sufficiency, abstention where assessed; **no answer correctness claim until an actual common reader runs**.
- Reader input text tokens at 512/1024/2048/4096 when feasible; visual input separately counted. Also online total tokens/compute, not only final evidence length.
- Graph-specific: fraction of new targets outside seed Top10, new gold pages genuinely reached, new necessary original spans, route-to-target-to-reader retention rate, and harmed queries.
- Report all 24 queries (failures and not-exercised included) and paired differences; a 13-query subset cannot be treated as the full benchmark.
- No claims of outperforming the official 388,548-page dataset from this 518-page local corpus. Treat the 24 often-debugged questions as development only; use a separate frozen, unseen evaluation split for generalization.
- H0 is strong (21/24 already had all gold pages in Top10); report ceiling effects and **not just** gold page recall. Correct page retrieval is not sufficient evidence localization.

**Fairness:** same graph, same seeds, same edge exposure, same target reading limit, same reranker, same evidence packer for R1–R5. Compare R3 not only with R2, but with R0's **additional dense candidates at matched exposure budget**. Every arm should receive comparable original modality availability. Do not preferentially grant a multi-node locator to graph arms when H1 receives one node per page.

## 6. Preflight / debugging checklist

1. Validate all actual directed records `(s,e,t)` refer to real frozen adjacency and to correct original anchor hashes; no swapped provenance.
2. Verify reverse text is semantically reversed and does not fabricate inverse causality; inspect hard negatives: wrong year, different entity, different observable, same generic formula under different assumptions, table missing identity.
3. Verify no evaluation query/gold appears in offline generation input, model cache or representation vector store.
4. Prove that the main R1–R5 online execution is **Qwen-free** for route/stop decisions via call counters, not just flags.
5. Prove `reading=on` from manifest + actual enumerated routes, or report disabled/unavailable. Existing importer code alone is not evidence of deployed loading.
6. Score all edges touching each Top10 seed; assert that rank10, multi-path and out-of-seed targets are handled.
7. Assert repeat/cycle/hub budget, deterministic ordering, correct direction and per-route dedup, no gold-dependent decisions.
8. Unit-test zero adjacency, all seeds sufficient, reversed asymmetric relation, wrong-year match, redundant target, wrong-subject formula, graph-with-bridge, missing original anchor and mixed structural/semantic graph.
9. Ensure R0 candidate expansion and R1–R5 target exposure and rerank budgets are counted identically.
10. Re-run a tiny CPU dry run and persist `manifest.json`, `edges_with_views.jsonl`, `route_scores.jsonl`, `routes_visited.jsonl`, `final_rankings.jsonl`, `per_query_results.jsonl` and `aggregate.json` with hashes. No fictitious GPU job ID or results.

## 7. Decision rules / what a negative result means

| Outcome | Interpretation / next action |
| --- | --- |
| R3 improves evaluated route ranking and final evidence vs R2/R0 | Directional descriptions have demonstrated *conditional* usefulness; validate on held-out queries/corpus |
| R3 improves route ranking but not final evidence | Bottleneck is target evidence, page-to-node localization, shared reranker/packer, or graph ceiling; inspect route→reader losses |
| No representation helps, but oracle reachable useful targets exist | Investigate encoder/query–relation alignment or learned query-route scorer, **then** consider model training |
| No useful target reachable | Frozen graph or initial seeds cannot support gains; change graph only in a new experiment, not by post-hoc gold edges |
| R3 ≈ target-only R5 | Benefit may come from target semantic similarity rather than relation representation |
| R3 loses to R2 or typed R1 | Keep the stronger empirical representation; do not force directional approach |
| Pages equal but reader evidence improves at lower cost | Potential evidence localization/efficiency contribution; do not claim page-recall gain |
| More final evidence tokens or online work for same quality | No demonstrated efficiency gain; report honestly |

## 8. Ordered implementation tasks for Codex

**Task A — Read-only audit (before coding):** inspect the current `feature/evidence-edges` files and output schemas. Report exact graph/reading manifest state, available frozen vectors/anchors, existing embedding instruction and page score aggregation. If a required artifact exists only on Horeka, record missing locally; do not guess.

**Task B — Offline directional views:** add isolated, provenance-preserving converter and unit tests. Generate R1/R2/R3/R4/R5 representations from the **same** existing semantic edges. Keep each `direction` separately addressable; preserve `unknown` cases and manifest hashes.

**Task C — Encode:** reuse Qwen3-Embedding-8B interface where applicable. Assert compatible query/edge preprocessing, dimensionality, normalization and model revision. Cache and hash vectors; do not re-embed the entire corpus per query.

**Task D — Query retrieval:** implement actual seed adjacency enumeration + directional route scores and budget-matched R0 dense expansion. Keep old query runner unmodified; log deterministic path records and full candidate exposure.

**Task E — Matched downstream evaluation:** connect to existing frozen reranker and source selector or implement a minimal shared adapter used by all arms. Do **not** call Qwen online in primary arms. Where a baseline is Qwen-assisted, label and cost it separately.

**Task F — Audit and results:** execute CPU smoke first; review a few asymmetric, redundant, wrong-condition and 2-hop mechanisms without using gold to construct edges. Only then submit the properly versioned GPU experiment. Evaluate all development questions, provide per-query wins/losses, differences vs R0/R2/R5, token/latency, route traces, failure/unknown counts, and a list of what was not measured.

**Acceptance criterion:** another engineer can reproduce graph version → source/target anchors → exact directional view and vector → query score → traversed route → newly exposed original span → final ranking/packet, without any gold contamination or hidden online Qwen call. An unchanged or negative retrieval outcome is valid; the goal is a decisive controlled comparison, not a predetermined win.

## 9. Suggested follow-on (not part of v1)

Only if R3 shows promise, examine learnable relation-aware scoring or light distillation; only if graph reachability is inadequate, improve offline edge discovery (grounded attribution, complementary facts, structural references). Keep those modifications separate from this relation-**representation** experiment.
