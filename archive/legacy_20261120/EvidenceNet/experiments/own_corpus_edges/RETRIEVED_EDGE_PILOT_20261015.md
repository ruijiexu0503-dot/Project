# Build edges from naturally retrieved candidates

CPU job **78114**, after successful retrieval job **78100**. This extends the 76411-replay candidate experiment into a bounded graph-building pilot, separate from the forced-pair 58/45-case verifier benchmarks.

Update: 78114 failed before inference because its page-only parser could not read `slide_0020`. The parser now distinguishes PDF pages, slides and standalone images, retaining the CERN legacy PDF-page override. Nine focused tests pass, and all 48 actual inputs were successfully prepared before retry **79541**. The original failed V1 is preserved; the retry output is `EvidenceNet/output/retrieved_evidence_edges_pilot_v2_20261015/`.

Input: `EvidenceNet/output/previous_edge_schemes_current_suite_v1_20261015/hierarchical_candidates.jsonl`, generated on the complete 1,313-node source union. Select up to 48 natural candidates, ranking within scope/material/modality strata and rotating across observed strata with a per-node degree cap of four. No reference labels or curated case IDs are used to select pairs. Missing visual descriptions are recorded and excluded rather than silently replaced by another representation. This is a diagnostic subset, not all retrieved pairs or a representative statistical sample.

Model: Qwen3.5-35B-A3B, CPU bfloat16, deterministic generation, thinking disabled. Ordinary text, captions and parsed tables remain original node members; visual members use existing Qwen descriptions. The independent description/raw/mixed experiment remains separate. Source node IDs and eligible members are preserved, and original crop paths are retained for later source review. Legacy PDF-page overrides match the reusable suite.

Classify SUPPORTS / EXPLAINS_OR_ELABORATES / MODIFIES / CONTRASTS_WITH, with REFERENCES independently. The functional definitions and role-based directions are reused from the current split-taxonomy run. This natural-candidate pilot additionally requires one short owned quote at each semantic endpoint and a relation explanation, with up to 900 generated tokens and two attempts. Quotes bind to source member spans, allowing only whitespace normalization. Visual-description quotes remain explicitly marked `QWEN_VISUAL_DESCRIPTION`; they are not asserted as independently verified image facts. Generated descriptions cannot establish an original-document explicit reference.

Only validated non-rejected decisions create evidence-edge proposals. Invalid outputs, rejections, raw attempts, reasons and provenance remain available. A rejected semantic relation can still produce an independently supported reference edge. CONTRASTS_WITH is symmetric. Existing reading order stays a separate graph; this trial does not regenerate it or turn it into semantic proof.

Article navigation aggregates supporting model edge IDs only when both endpoints have confirmed article identities. Expanded magazine nodes with PAGE_LOCAL_ONLY or UNRESOLVED assignments do not become confirmed article edges. Same-PDF uncertain boundaries are reported as unresolved; article segmentation is not silently inferred from page buckets. Aggregated navigation is not an independently verified article relation.

Output: `EvidenceNet/output/retrieved_evidence_edges_pilot_v1_20261015/`

- `plan.json`: code/dependency hashes frozen before job submission.
- `manifest.json`, `protocol.json`: frozen selected inputs, full candidate/source snapshots, scope counts and original crops.
- `inputs.jsonl`, `nodes.jsonl`, `excluded_nodes.jsonl`: selected pairs, unchanged member content and preparation issues.
- `predictions.jsonl`: all raw attempts and validated results with owned evidence anchors.
- `evidence_edges.jsonl`: proposed semantic and independent reference edges.
- `article_navigation_edges.jsonl`: supporting-edge aggregation for confirmed article identities only.
- `summary.json`, `REPORT.md`: progress, decisions and graph counts. Edge count is not semantic accuracy.

Preparation runs after retrieval completes, freezes the candidate inputs before model inference, and supports strict checkpoint resume. Source and code changes stop execution. Four focused tests passed for owned exact spans, description provenance, semantic direction/anchor ownership, unresolved article boundaries and reference-only edges. Accepted proposals still require original-source review before pipeline adoption.
