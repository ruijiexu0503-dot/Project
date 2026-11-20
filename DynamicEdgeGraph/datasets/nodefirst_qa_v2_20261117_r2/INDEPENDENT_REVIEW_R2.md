# Independent model review — r2

This review independently evaluated the 30 r2 candidates from their questions, answers, evidence, duplicate retrieval, shortcut retrieval, and the r1 mapping/source-integrity audits as gate facts. It did not use PR3 dispositions or earlier model-review verdicts.

## Outcome

- Strict model pass: 28
- Strict model fail: 2
- Exact historical duplicates: 0
- Retrieved single-node shortcuts: 0

Category results:

- cross_document PASS: 10
- cross_page FAIL: 2
- cross_page PASS: 9
- single_node PASS: 9

## Strict pseudo-multihop findings

- nodefirst_v2_r1::020 fails integrative reasoning. Both nodes are literally necessary only because the question asks for two glossary entries; no joint inference is required.
- nodefirst_v2_r1::021 fails integrative reasoning. It juxtaposes two intervention lists without a common condition, comparison axis, or interaction supported by the sources.

## Retrieval and gate findings

All 30 candidates have no exact historical duplicate and no automatic lexical shortcut block. The largest similarities are low and were inspected as non-answering alternatives. All cited pilot evidence passes the supplied automatic canonical-mapping and source-integrity gates. These facts do not override the two semantic pseudo-multihop failures.

## Deletion-ablation interpretation

Every cited node is required to satisfy the literal wording of its question, and no answer remains complete after deletion of a Gold node. For 020 and 021 this is insufficient: the literal necessity was manufactured by parallel-list wording, so integrative_reasoning_pass is false and model_review_pass is false.
