# r2 deterministic validation contract

`scripts/validate_r2.py` is the non-model gate that runs after the new independent
model review. It only reads r1 and r2 inputs and writes new r2 validation outputs.
It never modifies the Pilot or r1.

## Required inputs

- `pr3_audit_actions.jsonl`: exactly 22 `KEEP`, 13 `REVISE`, and 3 `REMOVE` rows.
  Every join uses the complete ID such as `nodefirst_v2_r1::011`; numeric suffixes
  and row positions are never accepted as keys.
- One complete r2 candidate JSONL (`qa_candidates_r2.jsonl` by default).
- One new independent model-review JSONL (`qa_independent_reviews_r2.jsonl`).
- `r2_repair_proposals.jsonl` when REVISE decisions exist. A proposal may resolve
  to `REMOVE_RESAMPLE`; that ID must then be absent from r2 candidates.
- Canonical Mapping and Source Integrity audits. r2 audits take precedence; when
  evidence nodes are unchanged, the script reuses the r1 automatic audit rows.
- Duplicate and single-node-shortcut retrieval records, either embedded in each
  review or supplied as separate r2 audit JSONL files.

## Exact Answer Claim Grounding

Every candidate needs non-placeholder `answer_claims`. Each claim contains:

```json
{
  "claim_id": "c1",
  "claim_text": "A concrete atomic answer claim.",
  "supporting_evidence_indices": [0],
  "evidence_spans": [
    {"evidence_index": 0, "span_text": "a literal substring of evidence_text"}
  ]
}
```

`span_text` (also accepted as `evidence_span` or `text`) must be a literal,
non-empty substring of the referenced node. A compact string list is also
accepted when the claim has exactly one supporting evidence index, because its
index is unambiguous; multi-node claims require explicit span objects. Every
support index needs a span, and all Gold nodes must be covered. `Answer
component 1`, `Claim 2`, and similar labels are rejected as placeholders.

For cross-page and cross-document candidates, at least one atomic relational
claim must cite two or more evidence indices. `integrative_reasoning` must also
have a meaningful label; `parallel_list`, `aggregation_only`, and equivalent
labels are blocked. This catches pseudo-multihop questions that merely place
unrelated facts next to one another.

## Necessity, duplicate, and shortcut records

`node_deletion_results` may be in the review or candidate `necessity_test`. It
must have one row for every evidence index. A row passes when it explicitly says
`node_required: true`, `answer_complete_without_node: false`, or uses an outcome
such as `FAIL_WITHOUT_NODE`.

Duplicate and shortcut checks must record execution, not only a final Boolean.
Recommended embedded review fields are:

```json
{
  "duplicate_retrieval": {
    "executed": true,
    "normalized_exact_duplicate": false,
    "duplicate_pass": true,
    "nearest_matches": []
  },
  "shortcut_retrieval": {
    "executed": true,
    "single_node_shortcut_found": false,
    "candidates_checked": []
  }
}
```

For a single-node QA, shortcut retrieval may use `status: "NOT_APPLICABLE"`.
Cross-page and cross-document QA require an executed search with
`single_node_shortcut_found: false`.

## Running

```bash
python3 scripts/validate_r2.py
```

Use `--require-target-distribution` on the release candidate to make an exact
20% Single Node / 30% Cross-page / 50% Cross-document mix a global export gate.
Without the flag, the ratio is still reported but does not obscure record-level
failures while repairs and resampling are in progress.
