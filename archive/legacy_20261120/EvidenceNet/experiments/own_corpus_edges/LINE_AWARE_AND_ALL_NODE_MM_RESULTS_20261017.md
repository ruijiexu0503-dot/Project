# Dolphin line-aware retrieval and all-node multimodal relatedness

Date: 2026-10-17. Both experiments are shadow development diagnostics. Neither
changes the production graph, and neither is a held-out accuracy estimate.

## Completed jobs

| Job | Experiment | State | Runtime | Exit |
|---|---|---|---:|---:|
| 85284 | Dolphin line-aware retrieval | COMPLETED | 10m35s | 0 |
| 85218 | All-node multimodal broad relatedness | COMPLETED | 24m14s | 0 |

## 1. Dolphin line-aware retrieval

The experiment retains all 2,223 existing normalized retrieval views and adds
9,816 source-mapped line views. New views consist of individual non-empty
Dolphin lines and overlapping four-line windows. Literal newlines and line-end
hyphens are retained; no EvidenceNode or source quote is split or rewritten.

At the same 1,301-pair comparison budget:

| Selector | Positive | Hard negative | Uncertain | Navigation positive |
|---|---:|---:|---:|---:|
| Current hierarchical | 10 / 26 | 2 / 27 | 1 / 3 | 2 / 2 |
| Line-aware | **12 / 26** | **2 / 27** | 1 / 3 | 1 / 2 |

The reported run produced 1,367 selected pairs because every selector lane could
fill its quota, but taking the frozen score-sorted prefix of 1,301, 1,200, or
1,000 pairs gives the same 12/26 positives and 2/27 hard negatives. The recall
gain is therefore not explained by the extra 66 pairs.

Final positive-case changes versus the current selector:

- Added: P04, P05, P07, P17, P26.
- Removed: P09, P10, P21.
- Net: +2 positives.

The line views produce useful local matches. Examples include the Graph WaveNet
adaptive-adjacency description in P05, matching dynamic-road-network wording in
P07, and two concise EuroSAT/Sentinel-2 definitions in P17.

The initial pool rises from 24/26 to 25/26 positives by recovering P11; P12 is
still the only positive absent from the initial pool. The much larger initial
pool also contains more hard negatives, so lines improve recall but are not a
semantic decision rule.

P01 and P02 are still missing from the final selection even though they are in
the initial pool. For P01, line views expose the local Graph WaveNet statement
at dense ranks 3/7; for P02, temporal-transformer lines reach ranks 6/15. Their
remaining failure is quota/degree selection, not text visibility. A small,
separately capped line-claim lane is preferable to letting 9,816 views compete
unboundedly with every existing view.

## 2. All-node multimodal broad relatedness

This experiment preserves the broad undirected 0--3 `RELATED` rubric and adds a
source-page node crop to every endpoint with eligible geometry. It covers 144
unique node crops; 102/103 pairs have crops at both endpoints. The one missing
endpoint has no eligible evidence and remains empty.

| Verifier | TP | FN | TN | FP | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Broad mixed representation | 29 | 2 | 19 | 6 | 0.829 | 0.936 |
| Broad all-node multimodal | **31** | **0** | 18 | 7 | 0.816 | **1.000** |
| Strict layered verifier | 28 | 3 | **25** | **0** | **1.000** | 0.903 |

The all-node representation recovers P11 and P26. It also fixes old false
positive N20, but turns N16 and N26 into new false positives, for a net increase
from six to seven false positives.

The failure mechanism is important: N22 infers EuroSAT from similar satellite
appearance even though the FUSU-Net endpoint does not name EuroSAT. N16 links
two unrelated CERN events by institution and month; N26 links distinct traffic
models by broad domain and architecture vocabulary. Original node crops improve
visibility but do not supply the missing identity or claim correspondence.

Three of 103 natural-candidate responses were invalid. All are large table
pairs where the model tried to list dozens of row evidence IDs and exhausted the
420-token output budget. They are not among the 58 evaluated cases. Future
prompts and validation should cap selected anchors per endpoint (for example,
at most three) and ask for the smallest sufficient evidence set.

## Recommended graph policy

The results favor a recall/promotion separation rather than a single mutually
exclusive fine-grained classifier:

1. Use broad multimodal `RELATED(level)` for discovery and navigation recall.
2. Store semantic facets (`SAME_SUBJECT`, `CLAIM_CORRESPONDENCE`,
   `DIRECT_COMPLEMENT`) as optional multi-label metadata; a facet failure must
   not delete the broad discovery edge.
3. Use the strict layered verifier only to set `evidence_eligible=true` for
   semantic aggregation or claim propagation.
4. Keep explicit document reference direction and semantic visual roles as
   separate fields.
5. Add a bounded line-aware retrieval lane with its own quota, node deduplication,
   and degree cap. Do not treat a newline as a sentence or node boundary.

This preserves the recall advantage of broad multimodal nodes while preventing
visual/topic-only links from entering the evidence graph.
