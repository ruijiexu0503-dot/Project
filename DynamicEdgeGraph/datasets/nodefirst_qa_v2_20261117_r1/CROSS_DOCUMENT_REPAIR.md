# Cross-document necessity repair

This analysis preserves the original Pilot and evaluates drafts 026–050 using only their questions, answers, and cited evidence. It does not use the curation pre-review hint.

## Result

- 12 of 25 original groups remain valid without changes.
- 4 groups have evidence-supported repairs and must undergo a new independent model review.
- 9 groups cannot be repaired from their current evidence without weakening necessity; they are rejected and require companion resampling.
- The provisional candidate count rises from 12 to 16 of 25 (48% to 64%) before the new independent review. This is not yet a final pass rate.

## Direct single-document shortcuts

- 026: the parameter-analysis node already explained why its SNR was higher. The repaired question additionally requests the initial search’s numerical SNR, making both documents necessary.
- 028: the GR-test node already described the test. The repaired question additionally asks which physical quantities determine ringdown frequency and decay time, a fact supplied only by the properties node.
- 032: the properties node already contained timing, amplitude, and phase localization. The repaired question separates the maximum-likelihood definition of reconstructed position from the observed ring/geometry constraints.
- 040: the mutual-information node already defined entropy reduction. No strict repair using the generic entropy node was found, so the group is rejected.

## Other failures

- 038 is repairable because both searches have an explicit comparable axis: a physical effect invalidates the standard detection regime and motivates a specific replacement strategy.
- 033, 035, 037, 042, 046, 047, 048, and 049 remain rejected. Their relations are parallel lists, unsupported causal bridges, generic governance transfer, or an overly broad shared label.

The repaired records are in qa_crossdoc_repaired_candidates.jsonl. Rejection and ablation details for all 25 records are in crossdoc_repair_analysis.jsonl.
