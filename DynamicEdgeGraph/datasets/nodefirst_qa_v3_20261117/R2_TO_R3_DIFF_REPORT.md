# Node-first QA r2 → r3 difference report

Date: 2026-11-17  
PR #4 join key: complete `nodefirst_v2_r1::NNN` `draft_id`  
Manual approval required: no

## Scope and provenance

- Read all three files in PR #4 `EvidenceNet/docs/qa_r2_20_independent_audit_20261117/` at head SHA `11b7f0f6c56385c812bcc7f1a8e78c64a316ff03`.
- Applied the manifest to all 20 r2 balanced Gold records: 16 content PASS and 4 REVISE.
- Preserved r2 Gold, r1, and the original Pilot. Every new artifact is under this r3 directory.
- Reused Source Integrity and Canonical Node Mapping as separate automated gates; no manual approval was introduced.

## Repairs

- PR #4 flagged 14/20 records for claim-span repair. Claim mappings were rebuilt from the corresponding canonical-node `evidence_text`; offsets were recomputed from literal source matches.
- Questions changed for `012`, `029`, and `034`.
- Answers changed for `004`, `012`, `029`, and `034`.
- `029` now compares only the evidence-supported axes: waveform assumptions and detection representations. Unsupported `vetoes` and generic-search noise-background claims were removed.
- `015` was excluded for resampling because the two nodes do not state a grounded socio-technical-risk → RMF-gain bridge.
- `016` was excluded for resampling because the two nodes do not state an explicit responsible-principle → future-evaluation link.
- `041` was excluded for resampling because structural causal notation and empirical causal identification are different domains without a documented bridge in the selected evidence.

## Independent review history

- Pass 1: 12/17 strict pass. Five span-entailment gaps were found in `011`, `012`, `013`, `034`, and `045`.
- The five gaps were repaired by adding the missing `spinning reserve`, expected storage replacement, Hungarian identifier, and coherent residual-strain qualifiers; `012` was also narrowed semantically.
- Pass 2 was a fresh review of all 17 candidates and did not inherit pass-1 decisions.
- Pass 2: 17/17 strict pass; 50/50 claims and 122/122 exact spans passed joint entailment and mechanical source/offset checks.
- Duplicate findings: 0. Single-node shortcuts: 0. All multi-node shortcut searches were executed.

## Automatic final gate

- `GOLD_ELIGIBLE_AUTOMATIC`: 17.
- `EXCLUDED_RESAMPLE`: 3 (`015`, `016`, `041`).
- Gold category distribution: 4 Single Node, 4 Cross-page, 9 Cross-document.
- All 31 selected evidence nodes pass automated Source Integrity and Canonical Mapping.
- All exported records pass claim grounding, node-deletion necessity, duplicate, shortcut, and independent semantic gates.
- The r3 set is intentionally not padded back to 20 with unaudited replacements; resampling remains explicit.

## Output map

- `qa_gold_auto_accepted_r3.jsonl`: 17 automatically accepted r3 Gold records.
- `qa_candidates_r3.jsonl`: 17 repaired candidates before final gate embedding.
- `qa_independent_reviews_r3_pass2.jsonl`: final fresh independent review.
- `claim_span_audit_verified_r3.jsonl`: per-claim exact-span and semantic-entailment results.
- `deterministic_validation_r3.jsonl`: per-record automatic gate decisions.
- `r2_to_r3_diff.jsonl`: complete 20-ID before/after values and dispositions.
- `pr4_disposition_r3.jsonl`: retained versus explicit resampling queue.

