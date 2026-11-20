# Integrated post-node edge pipeline

Updated 2026-10-23. Implementation branch: `feature/evidence-edges`.
Entrypoint: `EvidenceNet/pipeline_steps/step3_b_evidence_edges.py`.
This is reusable orchestration, not promotion of disputed semantic judgments or
a claim of validated production edge precision. Historical experiments stay frozen.

## Selected pipeline

Immutable EvidenceNodes + resolved article membership + per-member eligibility
→ source-addressed text/table/visual-description retrieval views
→ Qwen3-Embedding-8B + BM25 + identifiers, RRF and article routing
→ unique global escape quota + same-document/article original-caption references
→ original endpoint text, captions and image crops for every verifier pair
→ one matched-control Qwen3.5-35B-A3B verifier with resumable checkpoints
→ separate undirected RELATED proposals, review queue and rejected pairs.

Only eligible members enter retrieval. Generated descriptions remain explicitly
retrieval-only; they cannot establish named identity. Raw text/offsets are unchanged.
Unresolved article ownership is reported, not silently assigned. Reference candidates
are not automatically evidence links. Article IDs must be globally document-scoped.

The default does NOT append the experimental text-scope clarification or extra
formula/visual context; the fresh suite did not establish a gain. Experimental
numeric-citation resolution, expanded pointer context and contiguous-reading lanes
also remain separate. Upstream raw/semantic text normalization is unchanged.

## Encoder decision and comparisons

Default for this new edge entrypoint: `qwen3-8b`. Upstream node-generation embedding
is NOT changed: doing so could change immutable node identities. Explicit profiles
also support 0.6B, 4B, GTE-large-en, GTE-Qwen2, BGE-large-en, BGE-en-icl and MXBAI.
The model directory is configurable; switching the profile also switches pooling
and padding. No silent fallback or old-model vector reuse is allowed.

Local matched reports under `EvidenceNet/output/`:

| Encoder | Strong RELATED candidate coverage |
|---|---:|
| Qwen3-Embedding-8B | 16/29 |
| Qwen3-Embedding-4B / 0.6B | 14/29 |
| GTE-large-en-v1.5 / GTE-Qwen2-1.5B-instruct | 14/29 |
| BGE-en-icl | 13/29 |
| BGE-large-en-v1.5 / MXBAI-embed-large-v1 | 12/29 |

Sources: `edge_embedding_model_comparison_horeka_v1_20261020/REPORT.md`,
`edge_embedding_model_comparison_v3_20261020/REPORT.md`,
`edge_embedding_english_models_v1_20261020/REPORT.md`,
`edge_embedding_english_large_v2_20261020/REPORT.md`.
These are development candidate-recall measurements, not final edge precision.
Final candidate counts differ slightly; the newly integrated repaired allocation
has not yet been evaluated jointly with 8B. No explicit final selection memo was
found; 8B is the documented default assumption based on these completed reports.

## Commands

Use a Python environment containing the existing EvidenceNet dependencies.
Inputs use the current `units.jsonl` / `eligibility.json` contract (also called
`corpus_nodes.jsonl` / `corpus_policies.json` in the combined corpus). The existing
asset resolver supports `traffic` and `expanded` source collections; retain their
prepared page images/crops. Other collections need an explicit asset adapter;
missing source images go to preparation_errors, never text-only fallback.

```bash
python EvidenceNet/pipeline_steps/step3_b_evidence_edges.py prepare \
  --nodes <handoff/corpus_nodes.jsonl> --policies <handoff/corpus_policies.json> \
  --embedding-profile qwen3-8b --output <fresh-output>
python EvidenceNet/pipeline_steps/step3_b_evidence_edges.py embed --output <fresh-output> --device cuda
python EvidenceNet/pipeline_steps/step3_b_evidence_edges.py retrieve --output <fresh-output>
python EvidenceNet/pipeline_steps/step3_b_evidence_edges.py prepare-verifier --output <fresh-output>
python EvidenceNet/pipeline_steps/step3_b_evidence_edges.py verify --output <fresh-output> --minutes 52
python EvidenceNet/pipeline_steps/step3_b_evidence_edges.py export --output <fresh-output>
```

Embedding and verification are separate processes so they do not retain GPU memory
simultaneously. The verifier retains the tested four-GPU balanced placement with
26 GiB weights per GPU, 700-token response budget and two attempts. It writes each
unique response atomically and resumes on the next `verify` invocation. No job is
automatically submitted. `--model` selects the verifier; `--embedding-model` on
prepare selects the encoder location. Do not confuse these two models.

## Outputs and safety boundary

- `manifest.json`: frozen configuration, snapshots and source/code hashes.
- `embedding_manifest.json`: profile, tokenizer/config hashes, view row identity,
  execution device and vector hash; stale or foreign caches fail closed.
- `node_candidates.jsonl`: unique fixed-budget candidates, not semantic edges.
- `verifier/`: label-free inputs, source image hashes, preparation failures,
  resumable raw model responses and per-attempt audit.
- `graph/related.jsonl`: model-proposed undirected RELATED edges only.
- `graph/review.jsonl`: missing/invalid responses, preparation errors, navigation
  without checked identity, or direct-complement claims lacking a verified local pointer.
- `graph/rejected.jsonl`: model NO_LINK decisions.

All exported records have `evidence_propagation_allowed: false`. The evidence-vs-
navigation rubric and semantic claim audit are not settled. A missing pointer does
not mean a relation is false: it goes to review. The checks do NOT solve F033's
semantic confusion between same function and same bounded claim. They do prevent
unchecked navigation and unsupported direct-complement branches from automatically
entering the RELATED proposal file. No source graph or frozen labels are rewritten.

Validation covers offline end-to-end orchestration with a mocked encoder/model,
source snapshots, eligibility, cache invalidation, budgets, audit gates and resume.
Fresh integrated GPU accuracy has not been measured.

## 2026-10-23 source-role repair and remaining claim errors

The VL-DocIR adapter now preserves exact parser source-atom roles. Previously it
converted every prose member to generic `text`, including atoms already marked
`reference`. The export stage now audits both endpoints: bibliography/mixed
bibliography goes to reference review, not ordinary semantic RELATED proposals.
Pure original conflict-of-interest/funding/consent/data-availability statements
go to a separate administrative review route. This deliberately narrow grammar
requires complete statements throughout the node; mixed scientific content and
generated visual descriptions do not trigger it. Body text containing citations
is not automatically bibliography. Neither route deletes nodes or creates a
verified citation link, and both may be useful for queries about those subjects.

An independent, lossless split of the frozen VL-DocIR graph is available at
`EvidenceNet/output/edge_role_repaired_v1_20261023/`: 213 original proposals become
187 ordinary proposals, 17 reference-review records and 9 administrative-review
records. Every original edge is retained; original graphs/vectors are untouched.
These counts measure source routing, NOT precision or confirmed false positives.
The reusable export keeps review records in `graph/review.jsonl`, with the
specific route under `source_role_audit`; the derived snapshot splits the routes
into separate files for inspection.

Visual review: `EvidenceNet/output/edge_repair_review_20261023/index.html`.
It separates original endpoint anchors from model explanations and highlights
different predicates being merged, `obtained or waived` losing its alternative,
and similar procedures being called the same study without an identity bridge.
These semantic failures are not solved by source roles alone. A broad RELATED
proposal must not be interpreted as equivalent claims or independent support.

The isolated `query_edge_repair_v2_20261023` diagnostic reuses all document/edge
embeddings and adds query-time gating and BGE reranking, with explicit extra
inference cost. It is separate from offline edge construction. Compare against
dense+BGE, not only old dense scores: only 2/24 pilot queries have a different raw
graph candidate set. No retrieval improvement is claimed before completed scores.

Local validation on 2026-10-21: 63 tests passed across the new orchestration,
encoder profiles, allocation, original identity gate, metadata repair, routed
context, Dolphin soft wraps and hierarchical retrieval. The CLI help and Git
whitespace checks also passed. A real-corpus preparation is available at
`EvidenceNet/output/integrated_edge_pipeline_v1_20261021/`: 1,131 eligible nodes,
2,053 retrieval views, 182 excluded nodes recorded with their IDs. No new
embeddings, GPU verification or integrated graph-quality result has been produced.

That historical prepared snapshot is pinned to its original code. The 2026-10-23
source-role repair changes code hashes: use the archived matching code to resume
that snapshot, or use the prepare command above with a fresh output directory for
the current implementation. Do not rewrite its frozen manifest to bypass checks.
