# Independent semantic review — r1

The review used qa_candidates_r1.jsonl evidence, duplicate_audit_r1.jsonl, and source/mapping audits. It did not use prior independent reviews, pre-review hints, or inherited decisions.

## Outcome

- Model review pass: 38
- Model review fail: 3
- Exact/normalized duplicate blocks: 0

Category decisions:

- cross_document PASS: 16
- cross_page FAIL: 2
- cross_page PASS: 13
- single_node FAIL: 1
- single_node PASS: 9

## Repaired cross-document ablations

- 026: PASS. Removing the first node loses the initial SNR about 24; removing the second loses 25.1 and the finer-sampling explanation.
- 028: PASS. Removing the first node loses the final-mass/spin control of ringdown frequency and decay time; removing the second loses the actual consistency tests.
- 032: PASS. Removing the first node loses the likelihood-maximum definition; removing the second loses the time-delay ring and amplitude/phase geometry constraints.
- 038: PASS. Each node supplies a distinct physical failure of a standard detection regime and its replacement strategy. The shared comparison is explicit rather than a keyword-only pairing.

## Remaining semantic failures

- 009: question conflates a vehicle function with a downstream spinoff benefit.
- 017: one efficiency node is redundant under deletion ablation.
- 022: the cited evidence omits the transition from artificial-language approximation to the Markov-source representation.

All 41 candidates pass the deterministic duplicate gate and automatic source/mapping audit. These automatic gates do not replace the three semantic failures above.
