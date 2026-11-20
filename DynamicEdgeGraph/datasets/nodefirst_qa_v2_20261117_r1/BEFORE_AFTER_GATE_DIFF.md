# Gold Gate before/after report

## Outcome

| Measure | Previous Pilot gate | Automated r1 gate |
|---|---:|---:|
| Input Pilot drafts | 50 | 50 |
| FINAL_ACCEPT | 0 | 38 |
| Acceptance over original Pilot | 0% | 76% |
| Candidates reaching new model review | 50 | 41 |
| Model-review pass among r1 candidates | — | 38/41 (92.7%) |
| Balanced release | 0 | 30 |

The 30-record release has exactly 6 Single-node, 9 Cross-page, and 15 Cross-document records: 20%/30%/50%.

## Removed over-strict blockers

The prior gate treated missing uniform manual PDF verification and legacy HYBRID_SHADOW status as corpus-wide blockers. r1 replaces that policy with per-Node deterministic checks.

- All 550 legacy canonical IDs pass automatic identity and document/page linkage checks.
- 545 legacy Nodes pass Source Integrity. Five severe repeated-symbol/OCR Nodes fail individually; none is used by this Pilot.
- All 99 evidence references in the original Pilot pass Source Integrity.
- The 10 new-periodical Evidence Units were deterministically materialized as canonical Nodes and all mappings pass.
- No manual per-record approval is required.

All 9 former CONTENT_PASS_MAPPING_PENDING records now pass automatic mapping and become FINAL_ACCEPT_AUTOMATIC.

All 24 former PILOT_ONLY_BLOCKED_CONTENT_PASS records pass per-Node mapping, Source Integrity, and the new independent review, and become FINAL_ACCEPT_AUTOMATIC. Their previous block was policy-based rather than a content defect.

## Real content and necessity failures

Three r1 candidates fail for semantic reasons rather than source-policy reasons:

- 009: the question incorrectly treats a downstream spinoff benefit as a second vehicle role.
- 017: one efficiency Node is redundant, so the Evidence Set is not minimal.
- 022: the bridge from artificial-language approximations to a Markov source lacks an intermediate evidence Node.

Nine original Cross-document groups are rejected before r1 review and require new companion sampling: 033, 035, 037, 040, 042, 046, 047, 048, and 049.

## Cross-document necessity

- Previous result: 12/25 passed, or 48%.
- Repaired candidates: 16/25, or 64% of the original quota positions.
- New independent model review: all 16 repaired/retained candidates pass deletion ablation.

Direct shortcut handling:

- 026: repaired by requiring both the initial search SNR and later analysis SNR plus its explanation.
- 028: repaired by separating ringdown physics from the actual inspiral/post-inspiral consistency test.
- 032: repaired by separating likelihood-based reconstructed location from observed timing/amplitude/phase geometry.
- 040: rejected; the mutual-information Node already answers the question without the generic entropy Node.

Draft 038 was also repaired by giving both searches a concrete shared comparison axis: the physical effect that invalidates a standard detection regime and the replacement strategy.

## Export policy

qa_gold_auto_accepted_pool_r1.jsonl contains every record that passes all automated gates. qa_gold_balanced_export_r1.jsonl is the largest deterministic subset preserving 20%/30%/50% exactly. Quota gaps are filled only by generating new evidence-first candidates; necessity and answer-grounding standards are not relaxed.
