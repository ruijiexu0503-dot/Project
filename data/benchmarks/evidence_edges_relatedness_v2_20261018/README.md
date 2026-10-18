# Evidence edge relatedness V2: six-case reannotation

This is a non-destructive annotation overlay for six disputed cases from
`evidence_edges_v1_20261014`. It does not modify or supersede the frozen V1
benchmark. The source node IDs and source quotes remain owned by V1.

The graph-facing schema has one model-generated semantic edge type:
`RELATED`. Qwen does not choose a named relation or direction. It predicts an
ordinal relatedness value:

- `0`: no edge; only broad topic or vocabulary overlap;
- `1`: weak retrieval/navigation relation through the same explicit method,
  component, loss family, dataset, object, or project;
- `2`: concrete content relation: one endpoint explains, instantiates,
  qualifies, compares, or directly corresponds to the other.

Values 1 and 2 both create `RELATED` edges. Consumers may use value 2 for
evidence aggregation and value 1 for exploratory retrieval. `NEXT` remains a
separate deterministic reading-order edge. Explicit citations and relation
wording may be stored as metadata; they are not extra choices in the Qwen
classification target.

## Reannotation result

| Case | Relatedness | Review |
|---|---:|---|
| P02 | 2 | The STTN windowed temporal attention is a bounded concrete application of the general Transformer attention behavior. |
| P09 | 2 | The general self-attention operation and its temporal-window application form a concrete general-to-application relation. |
| P10 | 2 | Both address missing positional information, with a grounded fixed-versus-learnable comparison. |
| P11 | 1 | Both explicitly use multi-head attention, but the passages do not make the same specific claim. |
| P12 | 1 | Both explicitly use the L1 loss family for different prediction targets; useful for method navigation, not evidence propagation. |
| P26 | 2 | UMBRELLA's predictive and recommendation-oriented AI system is a concrete instance of the NIST definition. |

The earlier layered verifier's `NO_LINK` decisions for P11, P12, and P26 are
not copied into this overlay. They resulted from a stricter same-subject or
claim-level evidence gate. That gate answers whether an edge can propagate
evidence, while this schema asks whether the pair is useful as a semantic
retrieval connection and records strength separately.

`six_cases.jsonl` is the machine-readable overlay. Original V1 relations are
retained only for provenance and must not be shown to the model.
