# Indexed source anchors and content verification v3

V2 completed on 49 pages / 550 nodes with 14 source-reference edges and 17
model-accepted RELATED_CONTEXT edges. Source/crop inspection found four clear
logo/furniture or concept-confusion errors, five broad topic links, duplicate
caption extraction, and uncertain property identity. Twenty-five model ACCEPT
responses failed anchoring; eleven could pass grounding after whitespace-only
quote repair, which would not itself validate their semantics.

V3 reuses the exact same 120-pair verification queue, candidate pairs, BGE scores,
nodes, article assignments and reading edges. No old model decisions are copied.
This isolates verifier changes; it does not measure global candidate recall or
independent retrieval quality. Previous audit labels are used only in the final
comparison, never in prompts or acceptance rules.

Changes:

- TEXT anchors select endpoint-specific span and member IDs. Display whitespace
  is normalized, while quotes and offsets bind to immutable raw source spans.
  Parser padding is omitted from presentation without modifying original nodes.
- A separate member eligibility snapshot excludes primary logo descriptions and
  thin navigation banners, as well as the existing furniture roles. These hints
  only exclude; generated descriptions never justify positive edges. Original
  nodes/crops remain in the viewer. Mixed nodes retain eligible content members.
- Acceptance requires a concrete relation basis and CONTENT at both endpoints.
  Visual logo observations and pixel-mask/localization contradictions fail a
  final deterministic gate. DIRECT_COMPARISON requires an explicit source span;
  visual juxtaposition of different task examples is insufficient.
- Every proposed ACCEPT passes a second model critic using the same original
  sources/crops. Only CONFIRM produces a final RELATED_CONTEXT edge. This is a
  correlated model review, not independent human validation. Existing explicit
  REFERENCES edges remain subject to member eligibility.
- Invalid schema/anchor responses receive at most one correction attempt.
  Source/member IDs, original quote offsets and crop hashes are stored. Final
  reporting rejects stale pairs and requires both anchoring and critic approval.

The experiment lives in `EvidenceNet/output/node_context_edges_v3_20261011`.
Prepared input checks passed for all 313 source-span occurrences in the queue.
Nine pairs are blocked because an endpoint contains only excluded furniture.
All 169 repository tests passed, including span isolation, repeated-quote offset
preservation, logo gates, concept contradictions and critic requirements.

Submitted GPU verifier: **67457**; afterany CPU reporting: **67459**. The latter
can render a partial result, but an incomplete verification stays incomplete.
No production pipeline, frozen retrieval baseline or previous output is changed.

Early preflight jobs 67454/67455 were cancelled after observing a missing required
reason field. The response schema and correction instruction were made explicit.
Their partial decisions are archived under `preflight_attempt` and do not count
toward the final replay.

```bash
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/verify_node_context_v3.py prepare --output EvidenceNet/output/node_context_edges_v3_20261011
sbatch current/slurm/edge_generation/verify_node_context_v3_gpu.sbatch
# Set --dependency=afterany:ACTUAL_GPU_JOB_ID when submitting the report.
sbatch current/slurm/edge_generation/report_node_context_v3_cpu.sbatch
```

Final outputs include `verification_manifest.json`, `verifier_comparison.json`,
`verifier_regression_cases.jsonl`, previous error/omission regression files,
`semantic_edges.jsonl`, and `index.html`. The comparison separately checks the
four clear V2 errors, five broad-topic links and six previously plausible pairs.
Numbers are experimental regression results, not precision/recall estimates.
