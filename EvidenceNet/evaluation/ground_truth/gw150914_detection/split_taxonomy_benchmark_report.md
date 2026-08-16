# Split-taxonomy benchmark report

This report defines a benchmark derivative only. No production graph, candidate generation, ranking, retrieval, or model output was changed or run.

## Frozen inputs

- Original strict/high-confidence GT: 28 unique oracle pairs; SHA-256 `83b082a0e196c964cbfd565690898a1cac8fe346801317cab2c711ab31d19064`.
- The original fine-grained label and all original annotation fields are retained in each derived row.
- Oracle inputs are a label-blind copy of the existing 28 strict tasks, so context and pair orientation remain frozen.

## Taxonomy decision

- Document membership and order are node metadata: `document_id`, `page`, `section`, `reading_order`, and optionally `next_node_id`.
- `REFERENCES` is a discourse edge requiring an explicit, localizable cue. It is independent of semantic function.
- Semantic edges are `SUPPORTS`, `EXPLAINS_OR_ELABORATES`, `MODIFIES`, and symmetric `CONTRASTS_WITH`.
- `CONTINUES` is optional and only means continuation across a physical layout interruption; it never means ordinary next-in-order.
- `CAPTION_OF` and `PART_OF` are not added to this taxonomy under the current merged-node/membership-metadata design.

## Current implementation audit (read-only)

The current production builder creates `NEXT` for every adjacent evidence-node pair and optionally creates the inverse `PREVIOUS`. Those edges encode order, so the new design represents them with `reading_order`/`next_node_id` metadata. The current `CONTINUES_TO` heuristic is selective rather than universal, but it only checks adjacent nodes and can miss continuation around an inserted figure. It also flags equation-to-prose adjacency such as EV-14/EV-15, which is not automatically a physical-region continuation under the new definition. Production code remains unchanged.

## Class distribution

Original fine-grained labels:

- CONTRASTS_WITH: 1
- DEPENDS_ON: 1
- ELABORATES: 18
- EXPLAINS: 3
- QUALIFIES: 1
- SUPPORTS: 4

Semantic evaluation set: 27 resolved; 1 unresolved.

- SUPPORTS: 4
- EXPLAINS_OR_ELABORATES: 21
- MODIFIES: 1
- CONTRASTS_WITH: 1

Reference labels (independent denominator of all 28 pairs):

- REFERENCES=true: 6
- REFERENCES=false: 22

Cross-dimension distribution:

- Resolved semantic edge + REFERENCES=true: 5
- Resolved semantic edge + REFERENCES=false: 22
- Unresolved semantic dimension + REFERENCES=true: 1
- Unresolved semantic dimension + REFERENCES=false: 0

## Explicit REFERENCES

- `gw150914_detection_EV_000007` -> `gw150914_detection_EV_000010`; cue **shown in Fig. 1**; semantic=EXPLAINS_OR_ELABORATES. EV-7 explicitly points to the Figure 1 evidence node EV-10.
- `gw150914_detection_EV_000015` -> `gw150914_detection_EV_000014`; cue **where f and f-dot are the observed frequency and its time derivative**; semantic=UNRESOLVED. The equation-variable continuation in EV-15 explicitly and locally refers back to the equation in EV-14.
- `gw150914_detection_EV_000017` -> `gw150914_detection_EV_000010`; cue **without the filtering used for Fig. 1**; semantic=CONTRASTS_WITH. EV-17 explicitly identifies Figure 1 (EV-10) as the filtered comparison target.
- `gw150914_detection_EV_000018` -> `gw150914_detection_EV_000020`; cue **(see Fig. 3)**; semantic=EXPLAINS_OR_ELABORATES. EV-18 explicitly directs the reader to the Figure 3 evidence node EV-20.
- `gw150914_detection_EV_000022` -> `gw150914_detection_EV_000019`; cue **These interferometry techniques**; semantic=EXPLAINS_OR_ELABORATES. The plural anaphor explicitly refers to the detector-enhancement techniques begun in EV-19.
- `gw150914_detection_EV_000022` -> `gw150914_detection_EV_000021`; cue **These interferometry techniques**; semantic=EXPLAINS_OR_ELABORATES. The plural anaphor explicitly refers to the immediately preceding continuation of the optical techniques in EV-21.

## Unresolved semantic cases

- `gw150914_detection_EV_000014` / `gw150914_detection_EV_000015`; original=DEPENDS_ON. This is computational use of the chirp-mass equation. The equation is neither a scope modifier nor a condition/constraint on the statement, so DEPENDS_ON is not forced into MODIFIES.

## CONTINUES audit (not a current model task)

These four pairs show physical-region continuation. They remain outside the requested semantic/reference metrics and do not create production edges:

- `gw150914_detection_EV_000007` -> `gw150914_detection_EV_000011`; **Occurring within the 10-ms intersite | propagation time**. One sentence continues across a page/layout interruption and intervening Figure 1 material.
- `gw150914_detection_EV_000016` -> `gw150914_detection_EV_000018`; **a single Advanced LIGO | detector**. One noun phrase continues across an intervening physical figure region.
- `gw150914_detection_EV_000019` -> `gw150914_detection_EV_000021`; **mirror at the output optimizes | the gravitational-wave signal extraction**. One sentence continues across a page/layout interruption and an intervening Figure 3 region.
- `gw150914_detection_EV_000024` -> `gw150914_detection_EV_000025`; **radio-frequency oscillator. | [64]. Additionally**. The same calibration paragraph continues across a page boundary; the displaced citation opens the second fragment.

## Benchmark scoring contract

For every known-related oracle pair, semantic classification and reference detection are independent outputs. Semantic direction is scored by role, never by A/B presentation order; `CONTRASTS_WITH` is symmetric. Reference existence is scored on all resolved reference labels, and reference direction is scored only on positive-reference cases. Semantic exact metrics exclude semantic `UNRESOLVED`. Joint counts—both correct, semantic only, reference only, both wrong—use pairs whose two relevant dimensions are resolved.

No 35B/397B inference has been launched for this derivative benchmark.
