# Concrete event/project coreference v4

V3 removed the four previously identified errors and five broad-topic links, but
retained only three of six plausible v2 links and no cross-document edges. Its
critic rejected specific event and project links by requiring identical claims,
a direct comparison, or distinct entities, although these were intended to be
contextual coreference edges. It also retained an overlapping caption extraction.

V4 keeps the same 120-pair queue, BGE scores, 49 pages, 550 evidence nodes,
reading edges, source span IDs and furniture policy. It reruns every decision;
previous decisions are not copied. Final edges still require an actual source
anchor, eligible content and critic confirmation.

- Both proposal and critic explicitly allow complementary facts about one
  concrete event/project/entity, including observations versus inference or
  project results versus participants. Matching numerical claims, a causal
  relationship and a direct comparison are not required for this basis.
- SAME_NAMED_ENTITY requires a literal shared name/acronym in both selected
  anchors, an entity type and a substantive fact from each endpoint. Generic
  computer-vision task categories, logos, bare names and unresolved identity
  remain excluded. Shared-entity checks are case/whitespace tolerant and use
  word boundaries; aliases without a common anchored identifier remain a
  conservative limitation. Model-provided fact summaries still need semantic
  inspection; they are not independent evidence.
- Same-page caption fragments with the same figure/table label, strongly
  overlapping original member boxes and similar opening text are rejected as
  duplicate extraction. Separated panels and cross-page captions are not
  rejected by this rule. On the fixed queue it detects one pair, PAIR_01285.
- Correction retries now include the prior response and explicit object-shaped
  TEXT-anchor instructions, to address the remaining malformed anchor responses.

Rules are general; neither entity names nor node IDs from the regression audit
are used in acceptance logic. Original nodes/crops and old experiment results
are preserved. No production pipeline or frozen retrieval baseline is modified.

```bash
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/verify_node_context_v3.py prepare --version 4 --source EvidenceNet/output/node_context_edges_v3_20261011 --output EvidenceNet/output/node_context_edges_v4_20261011
sbatch current/slurm/edge_generation/verify_node_context_v4_gpu.sbatch
# Set --dependency=afterany:ACTUAL_GPU_JOB_ID for reporting.
sbatch current/slurm/edge_generation/report_node_context_v4_cpu.sbatch
```

Submitted verifier: **67530** (H200); report: **67532**. The report compares the
same candidate queue and the original v2 audited errors/plausible links. Tests
cover complementary event facts, anchoring the entity at both endpoints,
generic-topic rejection, duplicate caption geometry, and critic requirements
in both v3 and v4. These are regression checks, not an independent retrieval
or precision/recall evaluation. Promotion requires completed results and review.
