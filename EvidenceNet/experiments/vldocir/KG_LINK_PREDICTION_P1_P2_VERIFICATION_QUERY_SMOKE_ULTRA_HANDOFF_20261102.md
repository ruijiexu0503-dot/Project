# KG Link Prediction — P1/P2 verification, bounded query smoke, ULTRA feasibility

Date: 2026-11-02  
Branch: `feature/evidence-edges`  
Status: **Codex implementation handoff, not proof that any new job has run**

## Objective

The user's research goal is to **make evidence edges improve retrieval**, specifically by discovering *correct, complementary evidence links missed by current text-only candidate generation*. Stop re-demonstrating that the old sparse edges do not improve retrieval. This iteration should (1) determine whether P1/P2 differences contain genuine new evidence links, (2) confirm newly accepted edges can be traversed in a small query smoke, and (3) prepare the first real knowledge-graph link-prediction baseline (ULTRA). **Do not** conflate candidate novelty, verified relation correctness, and retrieval gain.

## Frozen facts reported by completed P0 and P1/P2 runs

- Source: Hugging Face VL-DocIR development pilot: 32 docs / 518 pages / 7,291 EvidenceNodes; 7,288 have `members[].text`; 6,520 have frozen embedding views and form the first fair comparison universe.
- Baseline `node_candidates.jsonl`: 1,088 *unique node pairs*; retain original hashing/provenance. Absence means not selected by the *budgeted* baseline, **not** absent from every ANN neighbor list.
- Semantic observation graph: 213 `RELATED_OPEN`, all noisy/model-proposed, **not** human ground truth; already-observed edges excluded from novel proposal counts.
- Validated v5 reading: 21 NEXT + 21 PREVIOUS, 42 traversable directed links, in train split only. Neither all 7,291 nodes nor valid/test have comprehensive verified reading coverage. Do not invent edges by page order.
- P1 text-only: 1,088 pairs, 112 overlap original baseline, 976 outside it.
- P2 text+graph: 1,088 pairs, 111 overlap original baseline, 977 outside it.
- P1∩P2 = 1,086; P1-only=2; P2-only=2; union=1,090 unique pairs. Connected source nodes=386/6,520; 373 connected sources' local TopK changed, zero isolated sources changed. Typed directed adjacency entries reported: NEXT 16, PREVIOUS 16, RELATED_OPEN 426 (inspect the run's definition; do not silently equate entries with unique original edges).
- 72 blind-review pair scaffold entries remain **unlabeled**. No valid candidate precision/recall or retrieval improvement claims yet.

These are **user-provided Codex run summaries**. Locate the actual local run artifacts, source commit and experiment protocol first; if inconsistent, report instead of silently recalculating from fabricated inputs.

## Phase 1 — Diagnose budget bottleneck using existing P1/P2 outputs (CPU/read only)

1. Locate actual frozen v2 preparation protocol, P1/P2 candidate outputs, rankings/scores, source eligibility, hash manifests and baseline pairs. Validate the stated 1,088 / 1,086 / 2 / 2 / 1,090 counts.
2. Produce exact IDs and original evidence excerpts for the two P2-only and two P1-only pairs. Distinguish unordered pair equality from directional source→target, preserve canonical pair keys and dedupe correctly.
3. For the 373 locally changed connected sources, quantify how many **different targets** graph propagation introduced into local Top20 (vs mere reranking), which ones failed global budget admission, and why (score threshold, allocator, source quotas, observed-edge exclusion, or candidate union). Do not guess the reason from aggregate overlap.
4. Audit train/valid/test leakage: reading v5 currently train-only, document split must remain frozen; no eval query or gold page in graph construction.
5. Save a compact source-level diagnostic. No new embedding, no model calls.

## Phase 2 — Bounded, original-evidence verification

Goal: determine whether graph-sensitive candidates can become **source-grounded, complementary** accepted edges.

- **First** review the four disjoint P1/P2 pairs (2+2), plus a stratified small sample from shared pairs and **locally changed-but-globally-excluded** P2 candidates. Make selection deterministic from frozen artifacts (not gold queries). Keep an equal-budget Text-only control selection where comparable.
- Reuse the existing original-evidence verifier, anchor/provenance requirements, and error logging; if running it needs LLM/GPU or external calls, prepare the batch/config and explain cost/commands first rather than auto-submitting an expensive job. Do not automatically label pairs using proposer similarity/graph scores.
- For every reviewed pair, store both source excerpts/locations, validity verdict, directionality, relation description, target contribution, `novel_to_frozen_1088`, proposer memberships and rejection reason. Unreviewed pairs are **unknown**, not negatives.
- Validate four P1/P2-disjoint pairs; do **not** automatically verify the full 1,090 union. If independent human labels remain unavailable, report verifier-accepted proposals as **model-reviewed, not human gold**.

## Phase 3 — Small query integration smoke, NOT full retrieval evaluation

Proceed only with a versioned, accepted-and-provenance-backed edge subgraph from Phase 2. The purpose is to verify code integration, **not** claim metric improvement.

- Wire accepted new semantic edges into the already-existing query navigation interface, without overwriting the baseline 213 noisy observations, v5 reading edges or frozen query data. Preserve `edge_source`, `edge_version`, relation description, anchors and navigation direction.
- Use a few existing development queries whose *initial seed nodes can reach an accepted new edge*; determine reachability algorithmically from the new graph, **not** select edges or generate descriptions using query gold. If no such queries, report `no reachable smoke query`, do not invent a success case.
- At identical frozen seeds, locator, route budget and reranker, capture actual `seed → edge → target → source page/excerpt` traces. Run at most the minimal CPU-supported smoke needed to confirm import, traversal and evidence attribution. If any LLM/GPU is required, produce runnable configuration but do not auto-launch.
- Keep no-new-edge control and new-edge version separate. Report qualitative reachability and logs, not Recall/AP/nDCG gain from a handpicked subset.

## Phase 4 — ULTRA readiness / official smoke

- Check the currently available **official** ULTRA repository, dependencies, checkpoint licensing/location and reproducible official minimal inference/smoke instructions. Do not claim availability of weights without verifying actual files/download methods.
- Explain mapping of EvidenceNode IDs, relation vocabulary and observed-edge split to ULTRA-compatible KG tuples. Report the critical mismatch: ULTRA is **structure-only**, does not consume our `members[].text`, and observed `RELATED_OPEN` is noisy rather than gold; its relation prediction is not a free-text relation generator.
- Ensure candidate tail selection is constrained to the same 6,520-node eligible universe, exact source set, split/filter rules and fixed budget, and that predictions from **outside the original candidate pool** are distinguished from reranking old proposals. Do not allow train/valid/test leakage via inverse/duplicate observed edges.
- Run only the lightweight official example/smoke if locally feasible without substantial downloads/training; otherwise produce exact reproducible commands/config and report blockers. **Do not run full EvidenceNet ULTRA inference or GPU training in this handoff** without a later decision.
- If structural graph is too sparse for meaningful structure-only transfer, report it as a property of this input graph and articulate the next **text-attributed graph proposer** route. Do not overclaim general KG theory is disproven.

## Deliverable

Produce a brief `REPORT.md` with:
1. exact paths and input hashes;
2. validated P1/P2 candidate overlap and reason for global-budget convergence;
3. audited four disjoint pairs and small verification selection with accepted/rejected/unreviewed statuses;
4. any completed query smoke traces, or specific reason it cannot run;
5. ULTRA official smoke readiness, interface mapping and resource requirements;
6. **decision gate**: (a) novel verified complementary endpoints exist? (b) actual query path can traverse them? (c) is ULTRA adaptation feasible on sparse/noisy structure?

Version outputs under a **new** `EvidenceNet/output/kg_link_prediction_p1_p2_followup_v1_20261102/` directory. Preserve earlier experiment outputs, hashes, 32-doc VL-DocIR universe and 6,520-node fair subset.

## Must not do

- No re-download, PDF parsing, OCR, node generation, re-embedding, old-pipeline rerun, large-scale KG training or complete 24-query benchmark.
- No silent promotion of 213 noisy edges, 72 unlabeled blind pairs or absent edges into gold/negative labels.
- No automatically connecting all reading nodes or representing the train-only reading edges as held-out support.
- No full 1,090-pair verifier run or expensive GPU/LLM job without a separately authorized execution plan.
- No retrospective use of evaluation queries/gold to create edges.

## Direct Codex instruction

> Implement this as a staged, versioned follow-up of the **already completed** VL-DocIR v2 P1/P2 candidate runs. First analyze why 373 local graph-influenced TopK changes resulted in only two P2-only globally budgeted pairs. Then select the 2 P2-only, 2 P1-only and small controlled candidate samples for source-grounded verification; create a bounded query integration smoke for accepted edges. Investigate official ULTRA smoke and EvidenceNet compatibility without automatically running heavy KG inference/training. Treat existing model-proposed semantic edges as noisy context; report exact existing artifacts and results, never invented precision or retrieval gains. Preserve all frozen data and avoid full benchmark reruns.
