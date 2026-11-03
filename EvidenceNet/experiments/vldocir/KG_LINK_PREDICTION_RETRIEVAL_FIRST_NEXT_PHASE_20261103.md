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



---

# PART II — Standalone implementation handoff for a NEW agent session

**Updated 2026-11-03.** This is the operational continuation of Parts 0–5, which remain the research requirements. The reader may be GitHub Copilot, Codex, another agent, or a human engineer. **Assume no access to prior chats.** Do not equate "a script exists" with "an experiment is finished"; everything labeled reported must be checked against local files.

## 6. Executive instruction: where to start

We are researching retrieval augmentation through an Evidence Graph for **long-document multimodal retrieval (VL-DocIR)**. The goal is not higher KG edge counts, standalone link-prediction metrics or simply exposing a new node. A good new edge must connect **original, independently grounded, complementary evidence**; under the **same frozen retrieval budget**, a relevant query should activate the correct target, retain it after reranking and evidence selection, and improve actual page/node retrieval.

**First action: inspect and audit existing LOCAL scripts, artifacts and dirty Git changes; read this entire file. Do not start from an empty pipeline. Do not run GPU jobs or broad reprocessing. Return a concise state matrix and propose ONE bounded next step.**

Repository: \`ruijiexu0503-dot/Project\`; working branch \`feature/evidence-edges\`. On HoreKa2, user-reported main project path: \`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project\`. Earlier VS Code session metadata recorded \`/home/ka_anthropomatik/ka_dv3352/Project\`. **Verify whether these resolve to the same worktree**; never infer path equivalence. The current authoritative version of this plan is the GitHub branch file, which may not yet exist locally.

## 7. Research background and evidence chain

- Documents are parsed into EvidenceNodes with original page, document, modality and source-window anchors. The graph adds reading continuity and candidate semantic relations. Most non-textual elements have textual descriptions/context (e.g. \`members[].text\`), but retaining **original image/table/formula evidence** is essential.
- Two distinct notions must never be conflated:
  1. **Offline edge feasibility:** can a graph/KG method propose and verify an A→B relation that text-only ANN candidates miss?
  2. **Query-time retrieval utility:** does the query need the *additional information in B* and does B survive the same bounded candidate/rerank/selector process to improve retrieval?
- Example negative control from prior smoke: a query about **director-election voting and withheld proxy authority** received a graph target about **auditor-ratification voting**. Although "proxy" overlaps, this is the wrong decision object. It does **not** count as a successful retrieval. Retrieval must be **query-scope aware**.
- For formulas: semantically equivalent relations with renamed symbols should not be missed solely due to surface names; generic formula templates must not create edges across unrelated papers/assumptions. Check symbol meaning, units, conditions, quantity definitions and source context.

## 8. Known experiment state (REPORTED; verify locally)

| Item | Reported result | Interpretation / caveat |
|---|---|---|
| VL-DocIR frozen corpus | 32 documents; 518 pages; 7,291 EvidenceNodes | Do not re-parse |
| Text availability | 7,288 nodes with \`members[].text\` | Text attribution is feasible but not automatically grounded |
| Frozen embedding universe | 6,520 eligible nodes; 768 outside it | Use 6,520 for fair primary comparisons |
| Baseline proposal | 1,088 globally budgeted candidate pairs; per-source TopK=20 | Check frozen manifests for exact filters and source list |
| Existing graph | 213 automatically observed \`RELATED_OPEN\` links; validated reading v5 subset has 21 NEXT + 21 PREVIOUS (42 traversable directed edges) | Noisy observations are not human gold; validated reading subset is train-only |
| P1 vs P2 | 1,088 pairs each; 1,086 overlap | Heuristic P2 added almost no global differentiation |
| P2 local novelty | 373 connected sources reordered; 499 unique local canonical pairs, zero admitted under global cutoff; max local-only score 0.799447 vs cutoff 0.875060 | Not evidence of new globally useful KG target endpoints |
| Bounded verifier | 20 pairs → 8 model-\`EVIDENCE_LINK\`, 12 model-\`NO_LINK\`; 7/8 model-accepted outside frozen 1,088 pool | Nonrandom small sample; **0 human adjudications**; no precision claim |
| One query smoke | Previously rank-211 target reachable | No actual reranker/selector run, wrong auditor/director scope; negative control |
| ULTRA | 6,520-node mapping prepared; official minimal smoke blocked by unavailable dependency and checkpoint | ULTRA structure-only; no official run/metrics, not trained on \`members[].text\` |

The old 24-query retrieval pilot reportedly gave identical BGE-reranked Top10 results across six initial graph arms; 7/24 queries had one-hop target opportunity, and 10/12 graph targets were already in baseline Top10. Treat this as *motivation* to seek actual novel evidence and query-specific routing, not as proof all KG methods fail. Exact split/runs must be verified.

## 9. Local code to inspect FIRST, including uncommitted work

User-shared \`git status --short\` on HoreKa2 (snapshot, not guaranteed current):

**Modified tracked:**
\`\`\`text
EvidenceNet/evidence_graph/hybrid_article_clustering.py
EvidenceNet/experiments/vldocir/KG_LINK_PREDICTION_RESEARCH_PLAN_20261101.md
EvidenceNet/scripts/repair_vldocir_single_work_reading.py
EvidenceNet/scripts/run_document_cross_page_qwen.py
EvidenceNet/scripts/run_hybrid_article_clustering.py
EvidenceNet/scripts/run_vldocir_pipeline_comparison.py
EvidenceNet/scripts/vldocir_reading_backbone.py
EvidenceNet/tests/test_hybrid_article_clustering.py
\`\`\`

**Untracked (potentially important new implementations, not disposable):**
\`\`\`text
EvidenceNet/scripts/check_vldocir_reading_integration.py
EvidenceNet/scripts/prepare_kg_link_prediction_p1_p2_followup.py
EvidenceNet/scripts/prepare_kg_link_prediction_v2.py
EvidenceNet/scripts/run_kg_link_prediction_bounded_verifier.py
EvidenceNet/scripts/run_kg_link_prediction_p1_p2.py
EvidenceNet/tests/test_kg_link_prediction_bounded_verifier.py
EvidenceNet/tests/test_kg_link_prediction_p1_p2.py
EvidenceNet/tests/test_kg_link_prediction_p1_p2_followup.py
EvidenceNet/tests/test_kg_link_prediction_v2.py
EvidenceNet/tests/test_vldocir_reading_integration.py
\`\`\`

Inspect \`prepare_kg_link_prediction_v2.py\`, \`run_kg_link_prediction_p1_p2.py\`, \`prepare_kg_link_prediction_p1_p2_followup.py\`, \`run_kg_link_prediction_bounded_verifier.py\` and their corresponding tests before changing candidate generation. Read actual retrieval entrypoints (e.g. \`run_vldocir_pipeline_comparison.py\`) and determine where seed retrieval, graph expansion, reranker, selector and page-level evaluator really occur. **Do not hallucinate interfaces or file paths**. \`EvidenceNet/output\` is merely a likely location; discover actual manifests and output paths by code search.

## 10. Preservation and authorization policy

- Keep all **628 GB reported** of HoreKa2 \`Project\` data in place. No project migration, archive, deletion, recursive copy or restart of document processing is part of this task.
- Local Git is dirty. **No \`reset --hard\`, \`clean\`, \`stash\`, \`pull\`, \`checkout\`, \`rebase\`, committing or pushing** without explicit user request. Reading \`git status/diff/show\` is fine. Do not modify the files above until audited.
- Do not restart Parsing/OCR/Docling/MinerU, Node Generation, embedding production or large-scale article segmentation. Reuse frozen, versioned assets.
- No heavyweight pip/conda setup, new model checkpoint download, GPU/Slurm submission, wide LLM batch, or long-running benchmark without a separate scope/cost explanation and user approval.
- The current failure of Codex/Copilot UI on HoreKa2 is **not** a reason to erase \`~/.codex\`, replace VS Code server, or rewrite research assets. A fresh agent can work from this document without prior chat history.
- Every evidence or training input must respect splits. No evaluation-question/gold leakage into offline edge selection or edge-description generation. Unobserved edge ≠ negative class.

## 11. First pass: READ-ONLY reconnaissance checklist

Run only safe inspection commands, replacing paths only after checking they exist:

\`\`\`bash
pwd
git rev-parse --show-toplevel
git branch --show-current
git status --short
git diff --stat
rg -n 'kg_link_prediction|ultra_readiness|EVIDENCE_LINK|RELATED_OPEN|candidate.*budget|rerank|query.*trace' EvidenceNet/scripts EvidenceNet/experiments EvidenceNet/tests
sed -n '1,240p' EvidenceNet/scripts/prepare_kg_link_prediction_v2.py
sed -n '1,260p' EvidenceNet/scripts/run_kg_link_prediction_p1_p2.py
sed -n '1,260p' EvidenceNet/scripts/run_kg_link_prediction_bounded_verifier.py
\`\`\`

Then **find actual experiment directories/manifest names** from script defaults and CLI args. Enumerate without rerunning:
- frozen VL-DocIR node/source and 6,520 frozen-view manifest;
- P0 audited corpus/splits and node-page mappings;
- P1/P2 candidate JSONL, overlap and local/global budget reports;
- bounded 20-pair verifier input, output and decision provenance;
- v5 reading-flow check results for 42 navigable edges;
- ULTRA readiness JSON and any pinned dependency/checkpoint configuration;
- 24-query retrieval pilot and single-query negative-control smoke;
- exact retrieval pipeline modules for reranking, selection and metrics.

**Required first output:**

| Stage | Exact code path/function | Exact existing result/manifest path | Verified? | Gaps | Smallest safe next action |
|---|---|---|---|---|---|
| P0 frozen inputs | ... | ... | yes/no/unknown | ... | ... |
| P1 text proposal | ... | ... | ... | ... | ... |
| P2 heuristic graph proposal | ... | ... | ... | ... | ... |
| bounded verifier | ... | ... | ... | ... | ... |
| ULTRA feasibility | ... | ... | ... | ... | ... |
| query-time navigation | ... | ... | ... | ... | ... |
| reranker / selector | ... | ... | ... | ... | ... |
| held-out evaluation | ... | ... | ... | ... | ... |

If the agent cannot access the filesystem, it should request **specific outputs** (e.g. manifest list or code snippets) rather than guess. Distinguish \`reported\`, \`verified\`, \`not yet run\`, \`blocked\`.

## 12. Fixed experimental contract BEFORE code changes

Create or verify a frozen manifest with the following actual local values:
- document and node versions, canonical IDs, node-to-page mapping, modality anchors, source windows;
- frozen embedding files/models, normalization, hashes, 6,520 eligibility;
- split assignment and isolation of train-only reading graph;
- same proposed source-node set, allowed target set, self-/same-page/exclusion rules and canonical pair definition;
- per-source TopK, global candidate budget, tie-breaking and seed;
- independent edge layers: validated reading continuity, noisy \`RELATED_OPEN\`, model-verified semantic edges, human-reviewed semantic edges; preserve provenance/direction;
- query set, dense seed rankings, reranker model/version, total candidate/page/visit/token budgets, evaluator and gold definition;
- output manifest, job/resource/config version, logging schema and full ranking files.

**Fairness:** global proposal budget is not the same as final page budget; keep both fixed. Do not compare P1/P2 scores on inconsistent filters. A new candidate that was already in dense Top10 is not novel retrieved evidence. Page gold and specific original support node are not interchangeable.

## 13. Phased coding work with STOP/GO gates

### Task A — audit existing P0/P1/P2 and verifier (cheap CPU, smallest first)
Verify frozen 6,520 universe, reported P1/P2 1,088 pair counts/1,086 overlap, local-only 499 and zero global admission, 20 verifier decisions. Produce a compact reproducible audit with artifact links/paths; investigate any discrepancy without overwriting previous outputs. Prefer extending current scripts/tests over building a parallel framework.

**Gate A:** all baselines and provenance sufficiently reproducible, or report precise blocker. No new large experiments.

### Task B — instrument retrieval pipeline (priority for actual scientific conclusion)
Trace the genuine path \`query → dense seeds → edge activation → target reached → query-scope gate → budget admission → reranker → selector → final original evidence/page rank\`. For each query, record a structured row with:
\`query_id, seed_node_id, edge_id, edge_layer, relation, source_node_id, target_node_id, target_doc_id, target_page_id, target_modality, provenance, verifier_status, target_contribution, query_scope_score, scope_decision, reached, novelty_to_dense, global_budget_admitted, drop_reason, reranker_rank, final_selected_node, final_selected_page, gold_page_match, grounded_support, latency_ms\`.
Use \`null\` for not measured, not fabricated booleans. Baseline instrumentation should NOT change baseline ranking. Start with one small deterministic query and lightweight tests; avoid claiming retrieval improvement before the full ranking/selector runs.

**Gate B:** prove complete trace from seed to final selection (or isolate exact missing function).

### Task C — scope-aware filtering + negative control
Encode retrieval contribution for candidate edges OFFLINE from original source/target windows, not from evaluation queries. At query time compare query subneed/decision-object/entity/conditions with contribution using existing frozen text views and/or a light existing scorer; support \`match / mismatch / abstain\`. Explicitly test the known \`director election withheld proxy authority\` query against \`auditor ratification\` target (should not be falsely accepted). Also include a valid complementary example to avoid indiscriminate suppression.

**Gate C:** negative control handled without destroying the genuine-positive case. A one-query fixture is **not** benchmark evidence.

### Task D — genuine link prediction feasibility (resource gated)
Check \`ultra_readiness.json\`, official pinned ULTRA environment/checkpoint/smoke first. Structure-only ULTRA is a separate mechanism from the existing P2 heuristic. Do not call the heuristic a trained KG method. Ask approval before installing/checkpoint transfer/GPU. If official smoke is blocked, record the blocker + precise scoped commands and design a separate **text-attributed graph proposer**, using node textual descriptions and graph neighborhoods, for later comparison. Evaluate novel **endpoints outside text-only local Top20** under matching source/target conditions and global budgets; count isolated-source coverage.

**Gate D:** official smoke and credible new candidates, or an explicitly blocked feasibility report. Do not inflate noisy links or assume absent edges are negatives.

### Task E — grounded verification & directional contribution
Create fixed, blinded, stratified candidate set: text controls, genuine KG-only endpoints, formulas, figures, tables, similar terms but different decision object/company/condition, cross-/same-document. Verify both original modality anchors and full source windows; separate \`model_accepted\`, \`human_reviewed\`, \`uncertain\`, \`rejected\`. A valid relation may be redundant; require **what new evidence B contributes to A**. Record direction, type, original anchors, identity/condition checks, provenance and uncertainty. No gold/query peek.

**Gate E:** at least one credible complementary new link, not just a model-marked \`EVIDENCE_LINK\`, before full retrieval test.

### Task F — matched end-to-end retrieval evaluation
With SAME frozen queries, seeds, page/candidate/visit/token budgets and reranker, compare \`R0\` dense/no-edge, \`R-old\` original graph, \`R-text\` verified text-only proposals, \`R-KG\` verified *genuinely novel* KG proposals, optionally \`R-KG+scope\` with query-scope gate. Report query-by-query changes in complete page rankings, Recall/AP/nDCG@5/10, exact supporting original nodes, wins/losses/no-ops, contamination and latency. Explain where each failed edge was lost (proposal, evidence verification, wrong scope, budget, reranker, selector). Use held-out queries/documents for any generalization statement.

**Gate F:** real fixed-budget improvement or an honest negative result, never "reachability = success".

## 14. Conceptual edge record (adapt to EXISTING code schema)

\`\`\`json
{
  "source_node_id": "stable original node ID",
  "target_node_id": "stable original node ID",
  "relation_type": "grounded typed relation",
  "direction": "A_to_B",
  "proposal_method": "P1_text | P2_heuristic | ULTRA_structure | text_attributed_graph",
  "source_anchor": {"doc_id":"...", "page_id":"...", "modality":"..."},
  "target_anchor": {"doc_id":"...", "page_id":"...", "modality":"..."},
  "target_contribution": "what B adds, independent of query/test gold",
  "identity_conditions": [],
  "proposer_score": null,
  "model_verification": "pending",
  "human_review": "unreviewed",
  "confidence_note": null,
  "status": "experimental_only"
}
\`\`\`

Graph edge existence, edge source grounding, complementary contribution and query-time helpfulness are **four different labels**. Do not collapse them. Preserve original evidence nodes, not just model-generated summaries.

## 15. Minimal tests and failure reasons

Tests must cover: deterministic canonical pairs; split/eligibility filtering; constant source/target and budgets; directed edges and distinct graph layers; no automatic promotion of \`RELATED_OPEN\` or model-only accepted edges to human gold; no-edge baseline unchanged; accepted complementary edge routed with trace; wrong decision object rejected/abstained; budget-preserving replacement; reranker/selector stage present before success claim; formula equivalence with renamed variables *and* generic-formula false positives.

Use explicit failure codes: \`no_graph_coverage\`, \`no_novel_target\`, \`unsupported_edge\`, \`redundant_evidence\`, \`identity_or_conditions_mismatch\`, \`query_scope_mismatch\`, \`abstained\`, \`global_budget_dropped\`, \`reranker_dropped\`, \`selector_dropped\`, \`already_in_dense\`, \`gold_definition_mismatch\`, \`missing_dependency_or_checkpoint\`. Never classify a stage not executed as unsuccessful.

Use new, non-overwriting versioned outputs under existing conventions, e.g. \`EvidenceNet/output/kg_link_prediction_retrieval_first_v1_20261103/\` only if appropriate for current repository. At minimum preserve status matrix, immutable manifest, candidate/verifier provenance, query traces, complete page rankings, command/test logs, and \`REPORT.md\` answering the five questions in Part I Section 4.

## 16. Exact instructions for a new Copilot/agent chat

> Read the entire \`EvidenceNet/experiments/vldocir/KG_LINK_PREDICTION_RETRIEVAL_FIRST_NEXT_PHASE_20261103.md\` from branch \`feature/evidence-edges\`, including Part II. This file is the authoritative research handoff; do not presume access to previous conversations.
>
> Work on HoreKa2's existing project, whose 628 GB of data and many uncommitted Python scripts are important. Do not delete, move, reset, stash, pull or overwrite anything. Do not redo parsing, OCR, node generation, embeddings or prior experiments.
>
> Goal: **verified, novel evidence links that improve actual original-evidence retrieval on the SAME fixed budget, after query-scope filtering, global allocation, reranking and final selection.**
>
> Your first turn is **READ-ONLY**: inspect local project identity, dirty Git status, P0/P1/P2/verifier/reading code, frozen manifests, ULTRA readiness and the real retrieval/reranker/selector entrypoints. Return (1) exact paths examined, (2) verified vs reported vs unknown status matrix, (3) one smallest retrieval-first next implementation step, (4) exact proposed files/tests, and (5) any resource/approval requirements.
>
> Do not edit files or run experiments until I authorize the chosen next step. Do not mistake model-only verification, an extra reachable target, or a local candidate score change for measured retrieval improvement.
