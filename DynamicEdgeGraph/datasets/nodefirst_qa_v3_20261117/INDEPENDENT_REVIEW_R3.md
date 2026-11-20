# Independent model review — r3

This is a fresh review of r3 candidates, claim spans, duplicate retrieval, shortcut retrieval, and r1 mapping/source gate facts. PR4 dispositions and earlier r2 review verdicts were not used as truth.

## Outcome

- Strict model pass: 12
- Strict model fail: 5
- Exact duplicate blocks: 0
- Single-node shortcuts found: 0

Category results:

- cross_document FAIL: 2
- cross_document PASS: 7
- cross_page FAIL: 3
- cross_page PASS: 1
- single_node PASS: 4

## Claim-span audit

All 133 spans pass mechanical checks for evidence index, canonical node, exact text membership, and character offsets. Five candidates fail semantic claim-span entailment:

- 011: storage-transition claim spans omit spinning reserve and the future/expected qualifier.
- 012: spans omit the expected storage replacement relation and the asserted ML-to-storage link.
- 013: spans support bipartite unique matching but not the Hungarian identifier.
- 034: spans support permutation-invariant bipartite matching but not the Hungarian identifier.
- 045: spans support several GR tests but omit coherent residual strain asserted in c3 and the integrative claim.

## Strict review of repaired 029

029 passes. Its matched-filter claim is grounded by the modeled compact-binary waveform and signal-versus-noise span. Its generic-search claim is grounded by the no-specific-waveform and coincident time-frequency excess-power span. The comparison uses one explicit axis, waveform assumption and detection representation; both nodes are necessary and no retrieved single node answers both sides.

## Retrieval and gates

No candidate has an exact historical duplicate or retrieved single-node shortcut. Every multi-node shortcut search was executed. Supplied automatic canonical mapping and source-integrity gates pass for all cited pilot evidence.
