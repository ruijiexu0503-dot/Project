# Full-node text–multimodal diagnostic, V2

## Completed result: GPU 80263

H100 dev completed in **9m10s**, exit 0, all model parameters on CUDA with
no CPU offload. All 40 responses passed the owned-ID schema. The native
frozen 20/20 reference score is TP20/TN20. Under the separate pre-prediction
scope review below, primary resolved results are **TP20/TN19, FP0/FN0**,
plus one scope-ambiguous case. This is a small, reused development collection,
with many explicit identity swaps; it is not a measured corpus-wide zero
error rate, a held-out generalization result or a retrieval improvement.
Unnamed cross-document mechanism/application links remain insufficiently
covered, despite being permitted by the verifier interface.

Link decisions and generated explanations must be evaluated separately.
Source review marked **11 responses for prose/scope repair or narrowing**;
these are not eleven false links. Issues include naming a sensor as a
dataset, calling `moussen` a project, transferring a masterplan theme between
endpoints, assuming Camp Nou from FC Barcelona imagery without an explicit
source name, importing a table's 10 m resolution into the prose endpoint,
calling a rendering a completed building, and denying an actually present
Fig.2 explanation. Minor context wording and mechanism/cultural scope notes
are included in those eleven flags. Raw responses remain intact; corrections
appear separately in `source_review.json` and the case browser.

The accepted A006 image link is preserved as same-subject RELATED. Previously
missing same-stadium links for A008, A009, A010 and A013 were recovered in the
default node composition. Separate source-reviewed additions produce **8
visual links** (3 feature-level ILLUSTRATES + 5 same-subject RELATED), versus
the previous 4. The merged A010+A011 variant has 7 links because it contains
one fewer text node. No new reading edges or node compositions were invented.
The existing experiment files and production graph were not overwritten.

Artifacts in `EvidenceNet/output/text_multimodal_edges_v2_20261015/`:

- `reviewed_summary.json`: resolved counts and original native summary.
- `source_review.json`: verdicts, prose issues and scope notes for every case.
- `clad_link_completion/*.jsonl`: additions per node-comparison condition.
- `node_viewer/index.html`: standalone graph with actual members, original
  crops/descriptions, old reading edges and reviewed added relationships.
- `viewer/index.html`: all 40 full-node pairs with sources, predictions,
  provisional references and filters for the 11 prose/scope flags.

Chromium verified all 40 case pages/images and reference filters. Final
checks verified the four graph variants (8/8/7/8 visual links), new A013
connections, symmetric RELATED, no discarded-edge marker and no page errors.
Frozen dataset/inference-source hashes still match after review.

## Frozen design and submission

2026-10-15. User requested a careful recheck of current links, additional
text–multimodal hard negatives and another experiment. GPU job **80263**:
one GPU, one hour maximum; allowed H100 dev/H200 partitions. This is a
fixed-pair diagnostic, not a retrieval evaluation or production switch.

## Current graph review

All four currently reviewed CLAD links remain valid at their explicit scope:
three ILLUSTRATES feature links, plus V001/A006 symmetric RELATED for the
same Al-Ahly stadium. The image need not show every assertion of a paragraph
to establish a useful object/navigation relationship. Rendering-based links
do not establish material composition, dates, future use or economic effects.

The article-first default graph lacks possible same-stadium navigation
links for A008 (introduction), A009 (architects/project), A010 (design-source
fragment) and A013 (future clubs). The variant merging A010+A011 already
links that merged node, leaving the other three missing. These are omissions
relative to the clarified scope, not newly measured errors under V3's old
narrow illustration prompt. Existing NEXT chains match the source and do
not cross article boundaries. Full audit is in the new package below.

## Reusable cases

Folder: `data/benchmarks/text_multimodal_edges_v2_20261015/`.

- **40 unique endpoint pairs: 20 LINK, 20 NO_LINK**.
- 35 full evidence nodes, 14 byte-preserved visual/table crops, five documents.
- Nine CLAD positives cover original full-node membership, same-object
  navigation and the alternative merged continuation node. Ten negatives
  swap stadium identity, including an FC Barcelona-marked stadium image.
- Eight existing text/figure/table positives are retained from source-reviewed
  EuroSAT, FUSU and STTN cases. Five remote-sensing negatives combine different
  datasets, acquisition content or architectures despite topical similarity.
- Three DLR positives cover AHEAD rescue and RIDGE eye-examination/navigation.
  Five DLR negatives mix GNSS anti-jamming, AHEAD and RIDGE: common institution,
  vehicle, patient or medical appearance does not establish a specific link.

Many pairs reuse assets; balance is over pairs, not independent images or
documents. CLAD supplies a substantial development fraction. References are
assistant source-reviewed and frozen before inference, not independent gold.
The previous narrow A006/future-use negatives are **not** copied as negatives.

`nodes.jsonl` retains original full-node members and eligibility; `cases.jsonl`
stores references/rationales separately. `inputs.jsonl` contains label-blind,
opaque-ID model tasks. All crops are copied byte-for-byte into `assets/`.
`assets.json`, `protocol.json` and `manifest.json` preserve provenance and hashes.
`current_graph_audit.json` records existing links and source-level omissions.

## Scope ambiguity identified before its prediction

Before prediction of `REL_a6d3739205dff699` existed, further source review
found that EuroSAT prose and the FUSU construction figure explicitly share
Sentinel-2 imagery / 10 m acquisition resolution. They are different datasets,
but a specific shared acquisition-mission navigation link may be legitimate.
This pair is therefore recorded separately as UNCERTAIN in
`reference_scope_review.json`; it is not forced to be a hard negative.
The original frozen 20/20 references and native model report remain intact.
Reviewed primary binary scores use **20 positives, 19 clear negatives**,
with this one scope-ambiguous pair separate. The independent review ledger
records that no prediction for this pair existed when the ambiguity was
identified. This addresses reference validity without tuning labels to outputs.

## Verifier and controls

The task separates edge existence from claim entailment. LINK can use either
SAME_SPECIFIC_SUBJECT or CONTENT_CORRESPONDENCE; shared named entities are
not mandatory for genuine method/feature/definition correspondences.
NO_LINK and UNCERTAIN are explicit. No forced support/illustration tag is
used to decide whether an edge may exist.

Full original evidence nodes are endpoints. Internal text windows/HTML rows
only supply source-owned anchor IDs. Model responses select IDs rather than
copying/reformatting source quotes. Original crops plus frozen Qwen descriptions
remain visible; captions/table text stay inside their real node. Endpoint
presentation is hash-counterbalanced. Context sources are separately keyed
and can resolve identity only; they cannot replace either endpoint's anchors
or supply absent facts. Original CLAD titles resolve `the ground`; a real
RIDGE antecedent resolves `this study`.

Qwen3.5-35B-A3B, GPU bfloat16, thinking disabled, greedy decoding, 650-token
ceiling, two attempts. An internal 50-minute inference limit leaves time for
checkpoint/report writes. Actual parameter placement is recorded. Invalid
outputs and UNCERTAIN decisions are reported separately from semantic FP/FN.
Greedy decoding is not assumed to guarantee bitwise reproducibility.

Artifacts: `EvidenceNet/output/text_multimodal_edges_v2_20261015/` contains
raw predictions, execution provenance, summary and per-case reference review.
Source review of both accepted and rejected cases remains necessary.

```bash
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_text_multimodal_diagnostic_v2.py prepare
sbatch current/slurm/evidence_nodes/text_multimodal_v2_gpu_1h.sbatch
```

22 relevant tests passed, including context/endpoint separation, wrong-ID
rejection, nonidentity content correspondences, abstention/invalid accounting,
original-modality retention and the earlier article/RELATED regressions.
Preparation and shell syntax checks passed. The twelve selected reused
visuals were reviewed as a contact sheet; CLAD crops were previously checked
directly, and the table keeps its original row provenance.
