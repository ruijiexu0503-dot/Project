# Article bridge pilot v1 — 2026-10-12

Implementation of [the handoff](ARTICLE_BRIDGE_GRAPH_HANDOFF.md). GPU job **69626** completed in 23m11s; CPU report **69627** produced the artifacts. See [the source review](ARTICLE_BRIDGE_PILOT_V1_REVIEW.md): 11 accepted, 21 uncertain, 11 status-policy conflicts and one inspected false rejection. New event-based candidates show limited promise, but the adoption gate is not passed and retrieval improvement is not evaluated.

## Frozen inputs

`EvidenceNet/output/article_bridge_pilot_v1_20261012/` holds the manifest, original evidence nodes, separate article assignment map, source/crop hashes and code snapshots. Existing experiments and the VL-DocIR baseline are unchanged.

11 article units, 218 original nodes (215 eligible), 28 frozen development pairs and 16 fresh pairs selected before pair verification. Fresh samples exclude the previous 320-pair verification queue; they are not independent expert labels. Sources include seven sampled papers (three GW150914 papers, three other gravitational-wave/method papers, DETR) plus AHEAD, UMBRELLA, CERN Open Science and one supervised-learning slide fragment. Page fragments do not imply complete article coverage.

Original page inspection identified AHEAD main text/sidebar as one article fragment. UMBRELLA uses only the upper stroke-treatment article; Open Science uses only the lower-left article on its spread. These reviewed assignments are separate from unchanged original node metadata. Author bio/byline nodes are retained but excluded from subject evidence; existing footer and page-number exclusions remain.

## Implemented stages

1. Independently extract literal EVENT/PROJECT mentions with content roles and exact original text offsets. Canonical keys normalize only case/whitespace; aliases across different names are deliberately unresolved. Invalid records remain visible without discarding valid siblings. No mandatory subject–predicate–object extraction.
2. Resolve unique explicit figure/table references inside the confirmed article. Check the target's original text/crop, keep context anchors separate, and forbid copying context-only measurements into target claims. The GW150914 properties paragraph → Fig.1 posterior plot chain is an explicit regression case. Other anaphora, pure visual identity and general co-membership are not automatically resolved.
3. Build article navigation reasons and subject-to-node maps. Literal anchors support identity candidates; role/kind correctness still needs source audit. Article navigation does not assert paragraph relationships.
4. Compare global dense/lexical node candidates against shared-subject candidates with a global fallback. Both arms have **8 outgoing cross-article targets per eligible node**; subject routing may use up to 4 subject slots and reserves 4 global slots, padding with global candidates when necessary. Missing cached vectors use lexical ranking. 163 reading edges and 180 within-article structural candidate pairs are protected independently, including formulas. Local structural proposals are not automatically accepted semantic edges.
5. Verify the frozen/fresh union once using identical original evidence and rules for both arms. Accepted semantic edges are only `RELATED_VIA_SUBJECT`, preserving two local aspects and separate bindings. Shared-event linkage asserts neither entailment nor equal numerical values. Missing bindings remain UNCERTAIN, not correct negatives. Invalid responses are FORMAT_PENDING.
6. Aggregate model-accepted node edges separately into article evidence edges. Produce a report and HTML viewer that opens article reasons, source-backed bindings, node members, original crops and accepted/rejected/unresolved decisions.

This first version covers specific events/projects; citation navigation, general methods/concepts, cross-name aliases and broader discourse/anaphora resolution remain future work. Generic LIGO noise/thresholds and unrelated CERN articles are development negatives. Several portrait/climate/C3 cases in the handoff are outside this selected corpus and are not claimed fixed.

## Validation and adoption gate

19 relevant tests passed. Two CPU protocol smoke runs exercised empty-index and positive-reference paths, including GW Fig.1 binding, local anchor ownership, equal budgets, formula protection and viewer generation. They used synthetic responses in disposable temporary directories; their outputs are not experiment results. The new marker resolver handles sentence-final `Fig. 1.` without confusing decimal identifiers or resolving ambiguous captions.

Manifest freezes the gate before model results: protected local routes must not be lost, source audit must find zero accepted identity/provenance errors, and valid cross-article recall must improve at the fixed budget before considering adoption. Both accepted and rejected/unresolved sides require source review. These are development diagnostics, not Recall@k/nDCG; a separate frozen-query evaluation is required to assess retrieval quality.

## Run and inspect

```bash
source current/env.sh
# Already prepared and submitted; use a new output directory for a new experiment.
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_article_bridge_pilot.py run
.venv-magazine-exp1/bin/python EvidenceNet/scripts/run_article_bridge_pilot.py report
```

Calls are checkpointed with input/image fingerprints. Resume the same frozen experiment with `run`; changed code, inputs, vectors or source assets fail verification. CPU report runs after any GPU termination so partial decisions/errors remain inspectable. A partial report does not indicate completion.

Outputs: `articles.jsonl`, `subjects.jsonl`, `subject_mentions.jsonl`, `context_bindings.jsonl`, `subject_node_index.jsonl`, `article_navigation_edges.jsonl`, `node_candidates.jsonl`, `routing_selections.jsonl`, `verification_queue.jsonl`, `node_edge_decisions.jsonl`, `semantic_edges.jsonl`, `article_evidence_edges.jsonl`, `summary.json`, `REPORT.md`, `viewer.html`. `index_errors.jsonl` and `reference_issues.jsonl` expose failures/coverage gaps; `calls/` retains prompts, responses, retries and elapsed call times. Slurm files and generated artifacts remain ignored under the existing repository policy.
