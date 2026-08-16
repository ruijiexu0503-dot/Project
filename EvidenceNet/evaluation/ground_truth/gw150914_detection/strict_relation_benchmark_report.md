# GW150914 strict high-confidence relation benchmark

## Scope

- `full_gold`: 36 broader curated relations in `all_pairs_ground_truth.jsonl`.
- `strict_gold`: 28 relations with high-confidence existence, subtype, and direction.
- `questionable_gold`: 8 plausible relations excluded from exact type+direction evaluation.
- The strict subset is not a complete inventory of all valid document relations.
- Original full-ground-truth SHA-256: `9cea614565779c16d867fa3f12afae22f54e296e7d2375ca2a8a9320c0cf7199`.

## Strict distribution

| Relation | Count |
|---|---:|
| ELABORATES | 18 |
| SUPPORTS | 4 |
| EXPLAINS | 3 |
| QUALIFIES | 1 |
| DEPENDS_ON | 1 |
| CONTRASTS_WITH | 1 |
| **Total** | **28** |

## Evaluation requirements

Type-and-direction experiments must report macro F1, per-relation precision/recall/F1,
confusion matrix, ELABORATES prediction rate, direction accuracy, exact type+direction
accuracy, and an always-ELABORATES baseline. Gold labels, directions, rationales, and
supporting spans must not be exposed in model prompts.

## Integrity checks

- Strict rows are unique and exactly match 28 relations in the historical reference.
- Questionable rows are unique and exactly match 8 relations in the historical reference.
- The sets are disjoint and their union exactly covers all 36 historical gold relations.
- The original ground-truth file was not modified.
