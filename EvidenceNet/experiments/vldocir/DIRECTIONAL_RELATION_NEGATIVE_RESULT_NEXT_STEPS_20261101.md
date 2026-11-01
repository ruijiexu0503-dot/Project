# Directional Relation Pilot — Negative Result Diagnosis and Next Experiments

Date: 2026-11-01  
Status: **plan only; no code changes or GPU jobs made by this document**  
Branch: `feature/evidence-edges`  
Parent plan: `DIRECTIONAL_RELATION_QUERY_RETRIEVAL_PLAN_20261101.md`  
Reported experiment: `directional_relation_v1_20261101`, HoreKa job `5222005` (user-provided result summary; verify actual run artifacts before producing new quantitative conclusions).

## Goal / decision

The first directional-representation experiment produced **identical page relevance aggregates for R0–R5**. Do **not** immediately add edge descriptions, tweak Qwen prompts, train a new representation, or increase graph edge count to chase improvement. First answer:

1. Did the fixed one-hop graph contain meaningful **route competition**?
2. Was any independently useful target **reachable** but **mis-ranked**?
3. Did the final shared BGE reranker erase meaningful route/candidate differences?
4. Does the reported reading-order coverage problem reflect missing article assignments, failed mapping to final EvidenceNodes, or only a narrow audited subset?
5. Is the old graph simply concentrated on node pairs already easy to retrieve densely?

Do not confuse graph reachability with correctness, graph traversal with useful evidence, and identical page metrics with identical evidence content.

## 1. Frozen facts to reproduce and audit

User-reported run:

- 24 development queries, 518-page corpus.
- Frozen G0 semantic graph: 187 edges, 374 directed views; reading layer **off**.
- Frozen dense Top10 node seeds; one-hop; max **5 new targets** per query.
- Qwen3-Embedding-8B (4096 dimensions) for route vectors; BGE common final reranker.
- R0 no-graph budget-matched dense expansion; R1 type; R2 open; R3 directional; R4 hybrid; R5 target-only.
- Online generative LLM calls: **zero**; no answer reader.
- Only 7/24 queries had usable one-hop targets; each graph arm selected 12 graph targets + 108 dense fallback targets across 120 slots.
- R1–R5 selected the same *sets*; order differed on one Ce 4f query.
- All arms identical aggregate page ranking metrics after reranking: Recall@5 83.33%, Recall@10 89.58%, AP@5 66.70%, nDCG@10 77.39%. They are **not answer accuracy**.
- Reported audited reading assignments: 9 / 7,291 nodes = 0.123%; verify the denominator/scope and exact upstream manifests rather than treating this as all possible document reading order.
- Route labels and oracle reachability assessments were **unavailable**.

The above numbers are reported results, not fresh validation by this document. Check `status.json`, `aggregate.json`, `per_query_results.jsonl`, `route_scores.jsonl`, `routes_visited.jsonl`, `candidate_exposures.jsonl`, `final_rankings.jsonl`, `relation_representation_manifest.json`, `embedding_manifest.json` and `reranker_execution.json` in the actual run output. Preserve manifest hashes and avoid overwriting.

## 2. P0 — read-only audit; zero new embedding jobs

### A. Competition / selection capacity

For **each query and each seed node**, compute from the frozen graph:
- number of real outgoing directed routes;
- number of unique non-seed target IDs, duplicate targets through multiple edges and existing seed overlaps;
- how many are already inside frozen dense Top20/TopK;
- whether the route exposure budget `K=5` was binding;
- original dense rank of each target; `not_in_pool` if absent;
- how many graph target slots were filled by dense fallback;
- score spread, exact ties, representation-specific ordering, and target set overlap (R1–R5).

Aggregate at query level: `N_unique_new_targets`, `N_routes`, `N_targets_outside_dense20`, `budget_binding`, and `actual_route_competition`. Define competition as **at least two distinct eligible non-seed targets, with selection cutoff able to exclude at least one**; distinguish “multiple route scores but same target” from genuine target-choice competition.

**If `N_unique_new_targets <= K`, all graph targets may be taken regardless of their order.** Thus identical R1–R5 sets say little about representation quality. Report the fraction of eligible queries where a genuinely different subset was *possible*.

### B. Offline replay from saved scores

Using the **saved scores and fixed candidate inventory**, deterministically replay route Top1 / Top2 / Top5 (optionally Top10 only where available) with the *same tie-break and no new source/encoder calls*. No route should be invented when the candidate is absent. Log selected targets and overlap by representation.

Separate:
1. route ranking differences;
2. selected target-set differences;
3. source anchors actually exposed;
4. shared final reranker page-order differences;
5. gold metric differences, evaluated afterward.

If scores/candidate lists are missing, report the blocker; do not silently fabricate replay.

### C. Compare with no-graph dense retrieval

Use unchanged R0: additional dense targets under **equal exposure and final source budget**. For each graph target, log:
- earliest dense rank;
- already seen via seed, fallback or BGE candidate pool;
- truly new page/source span;
- whether graph access was redundant at the candidate level.

A route whose target was already in dense Top20 may still supply useful cross-node context, but **must not** be counted as a new dense-missed discovery.

### D. Stagewise failure table

Produce a 24-query table with:
`qid, seed_count, unique_adjacent_targets, route_count, no_route_reason, budget_binding, R1_R5_set_same, R1_R5_order_same, new_targets_vs_R0, changed_BGE_pages, gold_page_gain, needs_human_review`.

This is a **diagnostic**, not a new benchmark. Report all unsuccessful/unknown cases, not just the seven navigated queries.

## 3. P1 — audit the reading-order data, do not force-enable

Existing `EvidenceNet/scripts/vldocir_reading_backbone.py` imports verified NEXT and creates reverse PREVIOUS when `reading_ready` and `ready_for_downstream` are true. Its current single-document limitation is **page-local flow**, not automatically full document order.

Investigate actual upstream files and IDs:
- `article_graph_manifest.json`: exact `reading_ready`, `ready_for_downstream`, processed document count and input hashes.
- `article_assignments.jsonl`, `reading_edges.jsonl`: output row count, unique node IDs, document/page spread.
- raw parser block/member order vs final node ID coverage; many-to-one node membership and filtered blocks.
- How the reported `9/7291` coverage was computed: full corpus? one pilot document? only qualified audited nodes? Avoid confusing these.
- Exclusions by invalid article order, incomplete page flow, missing or skipped nodes, cross-page gaps.

Deliver a coverage funnel `raw ordered blocks → mapped members → final EvidenceNodes → qualified assignments → NEXT edges → actually imported routes`. List reasons for missing coverage. Do not set `reading_ready=true` manually or invent NEXT from UUID/page numeric order. If actual graph imports differ from the old run, clearly version the reading-enabled test separately.

## 4. P2 — blind route utility annotation (small, targeted)

Before testing another embedding representation, obtain a *small independently reviewed* set of query/seed/real-outgoing-target examples from the **seven exercised queries** and a representative sample from the non-navigated 17. Include all outgoing candidates where feasible, both selected and unselected, and stratify by route type and dense rank.

For each route, provide **original** query and source/target anchors with subject, date, equation variables, table header/unit and image availability as applicable; **hide arm identity, embedding score and gold labels from annotators**.

Label:
- `direct_new_support`: new necessary original answer evidence;
- `necessary_context`: provenance/identity/unit/condition that makes known evidence interpretable;
- `useful_bridge`: may lead to required evidence through a real downstream edge, not sufficient alone;
- `redundant`: repeats already available evidence;
- `wrong_subject_or_condition`: apparent relation but wrong entity/year/observable/assumption;
- `unrelated`;
- `unknown`.

Track independent reviewer agreement/ambiguity and provenance. Do **not** assign labels from the same Qwen generator's relation description without independent check. Labels are **evaluation only**; never feed them to offline representation generation or online retrieval.

Report route precision@K, MRR/nDCG where complete labels permit; clearly distinguish candidate-list incompleteness and unknown. Include an upper-bound oracle reachable utility assessment, **never an oracle online selector**.

## 5. P3 — only then choose one of three research branches

**Case A: useful targets exist and representation differs under a binding cutoff.** Investigate relation scoring. Compare R1/R2/R3/R4/R5 at Top1/2 and tested budgets with blind labels. If R3 gains route ranking but not final output, inspect source→BGE handoff, page aggregation and packet selection. Consider query–relation prompt alignment *after* demonstrating a failure mode.

**Case B: useful targets reachable, but all methods choose them.** Representation may not be bottleneck; test better target-side evidence localization or downstream packer and token efficiency. Avoid pointless training.

**Case C: few/no useful targets reachable, especially outside dense Top20.** Freeze a **new graph version** and study complementary/source-grounding/reference candidate generation separately from representation, using unsupervised criteria on raw documents. Never patch graph using evaluation gold or hard-coded known questions. Compare old vs new graph under frozen query scorer.

## 6. Acceptance and file outputs

Prefer simple CPU/pandas/NumPy scripts on frozen `route_scores` and source manifests. Avoid a new HoreKa GPU run until the diagnostic identifies a binding bottleneck. Do not modify historical outputs.

Suggested new locations:
- `EvidenceNet/scripts/audit_directional_relation_opportunity.py`
- `EvidenceNet/tests/test_directional_relation_opportunity.py`
- `EvidenceNet/output/directional_relation_opportunity_audit_v1_20261101/`

Artifacts:
- `audit_manifest.json` with source hashes and run versions;
- `per_query_competition.jsonl`;
- `per_route_rank_comparison.jsonl`;
- `topk_replay.jsonl`;
- `dense_overlap.jsonl`;
- `reading_order_coverage_funnel.json` (or explicit `unavailable` reason);
- `human_route_review_template.jsonl`;
- `aggregate_audit.json` and a concise `RESULTS.md`.

**Definition of done:** We can explain precisely *why* representations led to the same final metrics, identify whether real useful routes were available, separate graph coverage from query scorer and BGE losses, and identify the **one next justified experiment**. Negative results are valid. Do not claim any new measured outcomes, job IDs or source paths without verification.

## 7. Codex instruction

> Read this plan and the completed `directional_relation_v1_20261101` artifacts. First produce the read-only 24-query competition and fallback audit, followed by offline Top1/2/5 replay and mapping of graph targets to original dense ranks and final BGE exposures. Independently verify the meaning of 9/7291 reading assignments from manifests. Keep the original run and fixed graph intact. Produce reproducible audit scripts/tests and output manifests. Do not start new GPU jobs or implement another edge representation until the diagnosis shows a choice bottleneck. When the artifacts are unavailable locally, state exactly which files are required and stop rather than invent metrics.
