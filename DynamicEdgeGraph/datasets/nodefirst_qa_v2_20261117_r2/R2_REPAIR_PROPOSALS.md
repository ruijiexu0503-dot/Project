# R2 repair proposals for PR #3 REVISE records

This file documents the non-destructive disposition of all 13 records marked `REVISE` in the PR #3 independent audit. The machine-readable proposals are in `r2_repair_proposals.jsonl`; no r1 or Pilot file is modified.

## Outcome

- `REVISED_CANDIDATE`: 8 records — `011`, `012`, `013`, `020`, `025`, `030`, `041`, `045`.
- `REMOVE_RESAMPLE`: 5 records — `019`, `031`, `038`, `043`, `044`.

Every retained proposal supplies a revised question and answer, a reasoning type, an explicit integrative-reasoning judgment, atomic answer claims, evidence indices, exact source spans, and node-deletion results. These are repair proposals, not automatic Gold acceptance: the parent r2 build must preserve the existing deterministic Source/Mapping Gate and run a fresh independent semantic review and duplicate check.

## Decision rule

A record was retained only when the supplied nodes support a scientifically meaningful contrast, transition, mechanism-to-implementation relation, or controlled multi-level comparison. Merely asking for one fact from each node was not treated as evidence necessity.

Records were moved to `REMOVE_RESAMPLE` when repair would require an unstated bridge: ringdown-to-waveform-averaging (`019`), generic data-processing inequality-to-specific GW statistic (`031`), cross-domain obstacle analogy (`038`), an artificial event-validation dossier (`043`), or an undocumented three-paper validation chain (`044`).

## Integration notes

1. Match records by the complete `draft_id`, never by the numeric suffix alone.
2. For `REVISED_CANDIDATE`, copy only the proposed semantic fields into a new r2 record while retaining original canonical node IDs and provenance.
3. Do not promote a proposal unless Source Integrity, Canonical Mapping, independent semantic review, necessity ablation, and deterministic duplicate checks all pass.
4. Treat `REMOVE_RESAMPLE` as excluded from r2 Gold; replacement sampling must start from canonical nodes and undergo the same automated gates.
