# KG Link Prediction for Retrieval Improvement — next-stage Codex handoff

Date: 2026-11-03  
Branch: `feature/evidence-edges`  
Status: **plan and implementation instructions; not an executed experiment**

## 0. Non-negotiable research objective

**The reason we create an Evidence Edge is to IMPROVE RETRIEVAL of original, query-relevant evidence.** Discovering a plausible relationship, increasing edge count, maximizing link-prediction Hits@K, or making more graph traversals is **not the end goal**.

The end-to-end hypothesis is:

> Offline KG link prediction finds *source-grounded links* to relevant, complementary evidence that dense retrieval would otherwise miss. When an unseen query arrives, query-aware navigation uses those links to make **the right original evidence** reachable and selected **under the same fixed candidate, page, visit and token budgets**, ultimately improving VL-DocIR retrieval (and, where measured, original-evidence completeness).

Treat **new pair discovery → evidence-supported edge → query-relevant target → budgeted candidate exposure → reranker/selector retention → final retrieval gain** as distinct stages. A success in an upstream stage is not proof of downstream gain.

**Do not restart old negative-result audits as the main task.** Build and test a retrieval-oriented KG method.

## 1. Current measured findings (user-provided Codex results; confirm against local manifests)

Frozen VL-DocIR pilot: 32 docs, 518 pages, 7,291 EvidenceNodes. 7,288 have `members[].text`; 6,520 have frozen views, used for first matched comparison. Baseline global candidate pool: 1,088 pairs. Validated v5 structural subgraph: 21 NEXT + 21 PREVIOUS, 42 traversable directed edges, train-only. Noisy observed `RELATED_OPEN`: 213, not human gold.

P1 text-only and P2 heuristic text+graph each submitted 1,088 globally budgeted pairs, sharing 1,086. P2 changed local TopK for 373 connected sources and introduced 499 unique canonical pairs locally, **none** reaching global cutoff (max 0.799447 < 0.875060); two P2-only final pairs were P1 local Top20 rerankings. **This did not achieve genuinely different globally selected KG endpoints.**

Bounded 20-pair source-grounded LLM verifier: 8 `EVIDENCE_LINK`, 12 `NO_LINK`; of the model-accepted 8, 7 are outside the frozen 1,088-pair pool. **Human-reviewed = 0; accepted means model-accepted, not gold.** Both P2-only global pairs were rejected. Do not treat this nonrandom 20-pair sample as precision/recall.

One query navigation smoke successfully exposed a candidate target at initial rank 211, but **without reranker/selector execution**; the query was about **director-election voting with withheld authority**, while the target anchor concerned **auditor-ratification voting**. This is a *query scope mismatch*, not retrieval improvement.

ULTRA mapping is prepared for the 6,520-node universe, but official minimal smoke has **not run**: dependency + checkpoint absent. ULTRA is **structure-only**, cannot consume `members[].text` as-is, and its predicted relation is not a free-text evidence justification.

## 2. The methodological correction: retrieval-driven, not edge-count-driven

### 2.1 Offline: link proposal and original-evidence grounding

- Keep original VL-DocIR documents, EvidenceNode IDs, modality metadata, source anchors, `members[].text`, previous input/graph versions and hashes. No re-parsing/OCR/node generation/embedding by default.
- Use a **genuine KG link-prediction proposer** as a candidate-source experiment (start with pinned official ULTRA smoke, then narrowly adapted ULTRA if feasible). Do not relabel the existing graph-propagation heuristic as ULTRA or present a graph bonus as a learned KG predictor.
- Because the graph is sparse/noisy, retain a **text-attributed graph candidate alternative** explicitly. Compare text-only vs structure-only vs text+graph *as distinct mechanisms*; do not equate missing structural signal with evidence against graph-informed methods generally.
- Keep `NEXT/PREVIOUS` validated reading, `RELATED_OPEN` noisy semantic observations and verified new edges as **separate graph layers with provenance**. The 213 automatically proposed edges are not supervision gold. Absent edges are unknown, not negatives.
- For new proposed (A,B), verify via full source windows and original modality anchors where necessary: entity identity, document/experiment context, variable conditions, supported relation, direction and **the novel evidence B contributes compared with A**. Reject unsupported cross-company conflations. `EVIDENCE_LINK` does not guarantee complementarity.
- Store reusable **directional target-contribution / information-need description** offline, source-grounded and independent of evaluation query/gold. Do not produce it by peeking at the target evaluation question.

### 2.2 Online: scope-aware edge navigation

- At query time, a *valid relationship* is only a candidate route; it is useful only when its target supports the **specific information need of the query**.
- Explicitly handle `director-election withheld proxy authority` vs `auditor ratification`: both are proxy voting, but target scope/decision object differs. A generic semantic edge score should not force this target into final evidence.
- Reuse current query decomposition / node scoring / edge representations if present; first inspect actual code paths. Design a **query-to-target contribution/condition** compatibility gate or score using available text embeddings and metadata (optional light reranker), with an abstain option. Avoid requiring an online generative LLM to re-judge every edge.
- Preserve a no-edge / dense fallback. No edge may expand the total budget or silently replace a stronger source on the same fixed final page budget.
- Log why each target was reached, accepted/rejected for this query, inserted/dropped by global budget, reranked, and (if available) retained as final original evidence.

## 3. Staged execution, with explicit decision gates

### Phase A — real KG proposer feasibility (small, isolated)

1. Inspect already prepared `ultra_readiness.json` and official pinned ULTRA instructions/checkpoint availability. Report dependency/download/compilation size and permission constraints accurately.
2. **Do not auto-install a new heavyweight Python environment, download checkpoints or submit GPU/Slurm** without a distinct, scoped user approval if resources are required. If approved, perform *official minimal smoke* first. Only after success, a tiny EvidenceNet endpoint-prediction trial with 6,520-node eligible universe, split quarantine and controlled source IDs.
3. Keep identical candidate filters, canonical pair definitions, per-source TopK, global budget and baseline overlap accounting. Show **endpoints introduced outside text-only local TopK**, not merely pairs crossing the last global cutoff. Report coverage by connected vs isolated nodes; score source of every proposal.
4. If ULTRA fails to produce novel credible candidates due to structural sparsity, do not blindly tune/triple graph density. Write the concrete design for a text-attributed link predictor using `members[].text` plus verified/noisy graph neighborhoods, and compare against the frozen text-only baseline.

### Phase B — bounded edge verification and contribution profiling

1. From actual new KG candidates and comparable text-only controls, construct a small **blind, stratified, fixed-budget** set, including different source/target documents, same-object complementarity, misleading shared terms, formulas/tables/figures and low-ANN-rank endpoints when available.
2. Run original-evidence verifier within an explicitly approved call budget; separate `model_accepted`, `human_reviewed`, `uncertain` and `rejected`. If human labels are absent, report only model-verified counts and *do not* claim true precision.
3. Version an accepted candidate-edge subgraph with direction, both anchors, identity constraints, contribution and uncertainty. No production promotion.
4. Gate for Phase C: at least one evidence-grounded new link with an actual complementary target. If absent, go back to candidate proposal rather than launch a retrieval benchmark.

### Phase C — retrieval-oriented integration, not just reachability

1. Take versioned accepted new edges into the **existing** query retrieval pipeline. Freeze corpus, query set, baseline dense seeds, locator, candidate/page/visit/token budgets and reranker. Make evidence-bearing query tasks reproducible and maintain query/gold isolation from offline edge building.
2. Compare at minimum:
   - `R0`: no new semantic edges / unchanged dense baseline;
   - `R-old`: prior noisy/accepted semantic graph as originally used (explicit review status);
   - `R-KG`: verified KG-proposed *new* edges under exactly the same budget;
   - if available `R-text`: verified text-only new edges with the same verifier/edge count or candidate budget to isolate KG contribution;
   - optional `R-KG+scope`: same edges with query-scope navigation gate, ablated against no gate.
3. For each query, keep stage-level traces: `gold page initially in candidates?` → `seed` → `edge direction/description` → `target new to seed?` → `query-scope match?` → `reached` → `survived global budget?` → `reranker rank` → `final source page/node evidence`.
4. **Primary success:** valid previously missed original evidence moves into final fixed-budget retrieval and improves held-out page ranking (Recall/AP/nDCG@5/10 with complete rankings) and/or an independently adjudicated original-evidence coverage metric. Also report query-wise wins/losses, contamination/noise and latency/cost. Distinguish page-level gold from actual selected supporting node.
5. Use pilot development queries for debugging and freeze offline edge construction independent of query gold. Reserve independent documents/queries for any generalization claim. Current v5 structural NEXT are train-only, so no held-out reading improvement claim.
6. The single rank-211 query smoke **cannot be counted as success**: its auditor target mismatches the director-election query; reranker/selector weren't run. Include it as a **negative-control scope case**.

## 4. Minimum output and interpretation

Version outputs in a new root such as `EvidenceNet/output/kg_link_prediction_retrieval_first_v1_20261103/`. Keep immutable input manifests, candidate logs, verifier decisions, provenance-backed edges, execution commands/jobs, query trace, page rankings and reason codes.

Produce `REPORT.md` answering **in this order**:

1. Did the KG proposer produce candidates *outside text-only local TopK* at the same source/target universe and budget?
2. Which are source-grounded and genuinely **complementary**, rather than redundant or cross-company/condition mismatches? By what review level?
3. Could an unseen query reach the target, and **did the target survive budget, reranker and evidence selection**?
4. Did retrieval improve **against frozen baselines under the same budget**, on which specific queries and with what regressions?
5. If not, precisely which stage failed: graph coverage, candidate recall, verifier quality, scope gate, budget allocator, reranker or evidence selection?

Report negative results faithfully; do not optimize to evaluation gold. If Phase A is blocked by dependency/checkpoint, report that blocker and a ready-to-run config, not a fictional Phase C result.

## 5. Concrete Codex instruction

> The user's objective is **RETRIEVAL IMPROVEMENT**, not KG completion or increasing edge count. Start from the frozen VL-DocIR v2 assets and completed P1/P2/bounded-verifier results. Attempt a narrow genuine KG-link-prediction feasibility path (official ULTRA smoke and, if authorized and feasible, small EvidenceNet proposer), while retaining a text-attributed graph route because all modalities have usable `members[].text` for most nodes. Enforce offline provenance and verifier checks. Design query-scope-aware navigation to avoid the known director-election vs auditor-ratification mismatch. Only claim improvement if novel supported edges pass query-specific scope filtering, fixed-budget global candidate selection, reranker/selector and improve held-out retrieval metrics; reachability alone does not count. Use explicit staged gates, preserve all old runs, do not silently download/install/submit expensive jobs, and do not restart the old negative-result analysis as the primary task.
