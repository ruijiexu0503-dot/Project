# KG Link Prediction — bounded evidence verification + ULTRA official smoke

Date: 2026-11-02  
Branch: `feature/evidence-edges`  
Status: **next Codex execution handoff; not an executed-result report**

## Goal

Move beyond the completed P1/P2 heuristic graph-propagation diagnosis toward (1) **source-grounded verification of 20 already-selected candidate pairs** and (2) **an official reproducible ULTRA smoke**, as a *structure-only KG link-prediction baseline*. The ultimate research objective remains **new verified and complementary connections missed by the budgeted ANN pool, and eventually retrieval improvement**, not increased edge counts or re-proving old negative results.

No need to regenerate the frozen VL-DocIR corpus, embeddings, P1/P2 rankings or v5 reading graph.

## Ground truth / provenance boundaries

Existing run's reported facts:
- VL-DocIR development pilot: 32 docs / 518 pages / 7291 EvidenceNodes; 7288 text-bearing; 6520 frozen embedding-view fair primary universe.
- Frozen original ANN candidate pool: 1088 canonical pairs.
- P1/P2 each 1088; shared 1086; P1-only 2, P2-only 2, union 1090.
- P2 local entrants: 502 incidences, 450 target IDs, 499 canonical pairs. All 499 missed global cutoff (max 0.799447 < 0.875060). Two P2-only global pairs were P1 local Top20 members promoted in score; **P2 is currently a graph-aware reranking baseline, not demonstrated novel endpoint discovery**.
- 213 `RELATED_OPEN` are noisy model-proposed observations, **not gold**.
- v5 reading graph: 21 NEXT + 21 PREVIOUS validated; confined to train-only partial subgraph, not comprehensive full-corpus reading.
- The deterministic 20-pair batch was prepared but **none has been verified**.
- ULTRA mapping / split-isolated triples already prepared, pinned official repo `427966ad8ed60420eef034063d44f3153addff90`; no checkout/dependency build/checkpoint/inference yet.

Use actual local `EvidenceNet/output/kg_link_prediction_p1_p2_followup_v1_20261102/` reports and manifest hashes as source of truth, and do not assert any new result in advance.

## A. Execute bounded verifier on exactly the prepared 20 pairs

1. Validate checksums and read `verification_selection.jsonl`, `disjoint_pairs_with_evidence.jsonl` and upstream manifests. Keep sample selection unchanged and deterministic (4 disjoint, shared controls, P2 local entrants, matched P1 controls). Never consult gold pages or evaluation queries when deciding pair labels.
2. Reuse project's *existing source-grounded relationship verifier* with the original excerpt + article context + available formula/table/image description, grounding identifiers and document identity. Ensure the actual invocation and model version are logged. Check that input excerpts in the diagnostic are **truncated previews**; verifier must read full bounded original evidence rather than 200-char previews.
3. Obtain approval/check available GPU or LLM gateway quotas as appropriate to the local workflow. **User authorizes this specific 20-pair bounded verification**, not more; if execution would require unusually expensive calls, inaccessible permissions or a new infrastructure install, stop and report the concrete blocker rather than silently starting a broader job. Run no more than 20 pairs and avoid retries that exceed an explicitly logged cap.
4. Each pair: output `source_id,target_id`, canonical pair ID, proposer membership, `novel_to_original_1088`, evidence anchors/excerpts, same/cross-document, entity identity constraints, model verdict (supported/rejected/uncertain), direction, supported relation text, *what target B adds beyond A*, redundancy/complementarity, confidence if calibrated (otherwise score only), model/version and rejection/error reason.
5. For the two P2-only examples in the existing report (cross-document SEC householding and clawback): **verify whether different companies merely repeat similar policy, rather than assuming cross-document mutual factual support**. Do not label as invalid based only on topic similarity; examine full provenance and whether an entity/condition-matched comparative relationship is truly supported.
6. **Model verifier approval is not independent human ground truth.** Save outputs under `model_verified` vs `human_reviewed` statuses, preserve uncertain/unreviewed. Never treat absent edges as negatives. Do not compute gold precision/recall without independent labels.
7. Do not touch production graph or overwrite `accepted_edges.jsonl` from earlier versions. Write accepted model-proposed relations into a new versioned subgraph with provenance, distinguishing `model_accepted` from any actually human confirmed cases.

## B. Minimal query integration smoke, conditional

After step A, **only if** at least one model-accepted relation with source anchors exists:
- Wire a *copy* of the versioned new-edge subgraph into existing navigation/import code (reuse implementation, no replacement of production graph). Keep the no-new-edge control.
- Choose a handful of development queries **solely by reachability from frozen seed IDs**, not by knowledge of gold answers. If no reachable seed, report the limitation, don't manufacture a success case.
- Same seed, query, locator, route budget and reranker across control/augmented run. Record exact `seed → direction/edge → target → original excerpt/page` and whether target entered candidate/selection. This is a **functionality smoke**, not a claim of statistically meaningful retrieval improvement.
- If running the full query pipeline requires heavy LLM/GPU or reranking jobs beyond the bounded smoke, prepare the command/config only and stop. Do not launch 24-query benchmark.

## C. ULTRA independent official smoke

1. Refer to *pinned* official `DeepGraphLearning/ULTRA` revision above; verify current upstream instructions if accessible (do not assume a Python or PyTorch compatibility promise beyond pinned docs). Check repository/license, checkpoint source, checkpoint usage restrictions, OS/CUDA/PyG and `rspmm` compilation prerequisites. MIT repo license does **not automatically establish checkpoint licensing**.
2. Create an isolated environment (do not modify production Python env). Avoid massive or unapproved downloads, compilation or GPU/Slurm jobs. If dependencies and weights are already cached, run **only the official minimal smoke**; otherwise provide runnable setup commands, actual size estimates if known, and ask for authorization before dependency install/checkpoint download/compilation.
3. Check official smoke first: checkpoint loads, minimal official KG inference executes, schema and shape consistent. Record result, command, runtime, device, software versions, checkpoint digest and actual stderr when relevant. Do not imply official smoke means EvidenceNet performance is demonstrated.
4. Inspect the prepared EvidenceNet 6520 entity mapping and split-quarantined `RELATED_OPEN`/NEXT/PREVIOUS triples against ULTRA's expected input semantics. Note **ULTRA is structure-only** and cannot consume `members[].text` without custom extension. Do not use validation/test known links in training context when testing those links, including inverse/duplicate leakage.
5. If official smoke works, implement only a *dry-run adapter/config* for candidate endpoint prediction in the 6520 node eligible universe. Preserve exact filtering, source pool, TopK and 1088-pair budget; don't run full inference or train new model yet.
6. Produce a feasibility judgment (works / blocked dependency / unavailable checkpoint / graph too sparse / other) with concrete evidence, not predicted gains. If pure structure-only is signal-limited, outline a **text-attributed graph** alternative as future work, not another immediate unbounded experiment.

## D. Deliverables / end condition

New root: `EvidenceNet/output/kg_link_prediction_bounded_verification_ultra_smoke_v1_20261102/`

- `REPORT.md`: a short measured status (20-pair selection, # submitted, model-accepted/rejected/uncertain/error, independent human review status, any query smoke routes, ULTRA official smoke state).
- `verifier_results.jsonl` and `verifier_manifest.json`: per-pair provenance, full-source anchors, model configuration, run costs/call caps, hashes; preserve original selection.
- `accepted_new_edges_model_only.jsonl` (possibly empty) with explicit review level and no automatic promotion to production graph.
- `query_smoke_status.json` and conditional trace.
- `ultra_smoke_report.json` and independent adapter notes + reproducible commands (even if blocked).
- Small targeted tests for input schema, dedup, identity/split checks and provenance if code changes; no large suite needed.

**Stop** after bounded verifier / optional query functionality smoke / ULTRA official minimal smoke or feasibility blocker. Do not run full VL-DocIR retrieval, 1090-pair batch verification, bulk KG inference, GPU training, re-embedding or re-parsing. Keep old artifacts immutable. If dependencies/cost cannot be authorized, perform read-only preparation and transparently mark the blocked step.

## Copy-paste Codex instruction

> Continue from the existing P1/P2 follow-up outputs, not from scratch. Verify exactly the prepared 20 pairs using the project's source-grounded verifier, with full evidence and bounded model calls, tracking accepted/rejected/uncertain and whether target evidence truly complements the source. Human labels remain unavailable, so call these model verdicts, not ground truth. Only if versioned accepted edges exist, perform a tiny frozen-seed query navigation smoke. In parallel check pinned official ULTRA checkpoint/dependencies and run its minimal official smoke only if readily available without a major install/download or new GPU allocation; otherwise report the blocker and precise setup needed. Preserve split isolation, all frozen corpora and outputs, and do not automatically broaden experiments.
