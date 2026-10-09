# EvidenceNode boundary v3 focused regression

Result update 2026-10-09: both tasks of 61927 failed. Qwen responses did not
consistently satisfy role coverage / exact boundary quotations; incomplete
decision-chunk provenance then triggered `Stale candidate/decision checkpoint`
during assembly. No v3 result was accepted. The VL-DocIR pilot uses hybrid v2.
The submission and acceptance criteria below document the failed experiment.

Job **61927** runs two frozen v2 source pages (Entropy page 10 and the GW
polarization paper page 6), with embedding+geometry and geometry-only inputs in
separate dev GPU tasks. At submission check, task 0 was RUNNING and task 1 was
PENDING due to the array concurrency limit. Each task has two H100 GPUs and a
14m30s limit. Outputs: `EvidenceNet/output/hybrid_boundary_v3_61927/`.

The baseline EvidenceNodes, full candidate set, scores and page bytes are reused
from v2 job 61078. Source hashes are checked. Only the boundary protocol changes:

- One pair per model call prevents confusion between neighboring pairs.
- Explicit last/first 80-character boundary fields supplement existing context.
- Verbatim boundary quotations must match the supplied strings exactly.
- A boolean `same_sentence` must agree with CONTINUATION/SEPARATE.
- Non-null guards force separation; null does not.
- Reasons are limited to 180 characters. This bounds deliberation but does not
  prove that arbitrary natural-language reasons are semantically consistent.
- Invalid replies are retried once; an invalid page falls back to unmerged
  baseline nodes and fails validation. No automatic promotion.

Eleven local boundary/contract tests pass. They cover invented boundary text,
predicate/label contradictions, string booleans, guard violations, long reasons,
equation punctuation and legitimate cross-caption continuations. Fresh GPU
quality results were not obtained because validation/assembly failed; the runner
would write structural audit and regression evaluation only after assembly.

Acceptance must include recovery of both frozen GW continuations and the
cross-figure Entropy continuation, no known negative regression, and valid
source/decision checks. These are development regressions, not independent GT.

## New-document sample preparation

`EvidenceNet/output/evidence_node_holdout_20261009/manifest.json` freezes nine
pages from nine documents absent from the 49-page regression: two research
papers, ESA, NASA history, Glasgow science, IMF, WIPO and FAO publications.
Selection uses parser layout metadata only, preferring tables and figure-caption
pages with at least two paragraphs. PDF, parser JSON and rendered-image hashes
are retained; rendered dimensions match the original Dolphin run.

These pages have not undergone node inference. Source review and conversion to
the member-asset input contract remain necessary before that experiment. They
are document-disjoint samples, not independently human-annotated ground truth.
Run them only after checking the focused v3 result. Existing production nodes,
graphs and parsing outputs remain unchanged.
