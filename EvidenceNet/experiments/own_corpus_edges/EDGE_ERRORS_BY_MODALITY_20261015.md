# Existing semantic-edge errors by endpoint modality

2026-10-15. User requested comparison of text–text, text–multimodal and
multimodal–multimodal errors. Re-analysis only; no inference, graph updates
or new scheduler jobs. Reading NEXT is not pooled with semantic decisions.

The primary definition uses eligible original members: T has ordinary text
only; M contains an original visual, table or standalone `equ`-role formula.
A visual represented by a generated description remains M. Inline math
does not by itself create a separate modality. Empty evidence is separate.
An alternative convention counting parsed LaTeX formulas as text is also
reported; the main observed risk is unchanged.

## Latest RELATED mixed-input experiment

Use the 58 frozen reference cases from 103 generated predictions. Two cases
have unresolved edge-cutoff labels; one resolved case intentionally has no
eligible evidence and is excluded from the three substantive strata. The
other 45 natural pairs lack complete references and are not scored.

| Pair | Resolved samples | Positive / negative | Wrong connect/reject decision | Wrong among accepted edges |
| --- | ---: | ---: | ---: | ---: |
| T–T | 40 | 20 / 20 | 5/40 = 12.5% | 3/21 = 14.3% |
| T–M | 10 | 10 / 0 | 0/10 | 0/10 |
| M–M | 5 | 1 / 4 | 3/5 = 60% | 3/4 = 75% |

The highest observed RELATED false-edge rate is M–M. This is not a reliable
population ranking: only five M–M cases are resolved, with four negatives;
the T–M group contains no resolved negative at all. The three false M–M
cases reuse the EuroSAT sample-image node, so they are not independent
document/asset samples. These are assistant-reviewed development readings,
not independently adjudicated labels.

With formulas counted as text, T–T is 5/42 wrong (11.9%), with 3/23 accepted
edges false (13.0%); T–M is 0/8, still without negatives; M–M is unchanged.

N04, N21 and N22 are the M–M false positives. Model reasons promote shared
satellite scenes, land-cover categories or computer-vision domain into a
level-2 specific connection. N22's own limitation acknowledges different
datasets, tasks and architectures. T–T false positives N07/N08/N20 similarly
promote shared satellite/data-domain descriptions. T–T false negatives are
P11 and P26 under this protocol's provisional RELATED reference readings.

## Dependence on edge policy

This pattern is not universal across existing algorithms. The previous
concrete-correspondence verifier falsely accepts one of four resolved M–M
negatives and accepts its one positive. The four-function description
protocol rejects all four M–M negatives but misses the positive. Its matched
mixed-representation subset gets all five M–M existence decisions correct,
with one remaining label/direction disagreement. That mixed subset has no
T–T controls under the same prompt/backend and cannot provide a three-way
ranking. Native relation definitions and reference scopes differ; experiments
are never pooled into one error rate.

Existence errors (FP/FN), false-discovery rate (FP/accepted), type/direction
errors, explicit-reference errors and output-format failures are distinct.
In particular, correct edge existence does not validate generated claims,
directions or image descriptions.

The newest CLAD 80131 trial is a separate text–image-only diagnostic. After
user clarification, four accepted proposals are retained as three scoped
ILLUSTRATES edges plus one symmetric RELATED edge. A006's `the ground` refers
to the same Al-Ahly Stadium shown by V001: a useful content-navigation link,
without asserting that the image depicts or proves the entire masterplan.
**The earlier 1/4 (25%) false-edge claim is withdrawn.** The old review is
archived and original model outputs/frozen narrow references remain unchanged.
This is a clarified review criterion, not a newly measured zero error rate.
Another pair is format-pending due
to line-wrap dehyphenation. Its four node conditions share the same visual
decisions and must not be counted as four independent experiments. It has
no T–T/M–M controls and cannot itself rank the three modalities.

The table above retains the original RELATED experiment's frozen definitions.
Its figures are conditional on that protocol and are not error rates under
the user's broader clarified navigation policy; the full 58-case set has
not yet been re-annotated under that policy. Edges sharing one specific
stadium should be distinguished from edges sharing only a generic domain
or visual category across different datasets.

## Reproduction and follow-up

```bash
python EvidenceNet/scripts/audit_edge_errors_by_modality.py
```

Artifacts: `EvidenceNet/output/edge_modality_error_audit_20261015/` contains
`REPORT.md`, both modality conventions in `summary.json`, every scored
case in `cases.jsonl`, and frozen input hashes/definitions in `manifest.json`.
All four re-scored protocols reconcile exactly with their original aggregate
TP/FP/FN/TN counts, including the separately reported empty-evidence case.

Priority: review M–M generic-similarity errors, and add genuine T–M hard
negatives. A balanced follow-up should include positives and difficult
negatives per stratum across independent assets/documents, keep relation
policy fixed, and measure both edge existence and supported subclaim scope.
