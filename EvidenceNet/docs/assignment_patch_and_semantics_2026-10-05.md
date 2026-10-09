# Assignment repair and semantic audit — 2026-10-05

Follow-up on 2026-10-06: 48023 completed with 5/8 flow repairs; 48027 completed
nine pages with one flow failure. The subsequent prompt-only comparison failed
its review gate and no broader run was submitted. See
[current results and archival](prompt_comparison_and_archive_2026-10-06.md).
The queued-status notes below describe the original 2026-10-05 checkpoint.

Status: implemented, local checks passed, GPU validation queued. These are
opt-in shadow policies, not a claim that all failed pages or semantic edges are fixed.
Frozen regression 46209 and candidate snapshot 46210 remain unchanged.

## Flow repair

`--recovery-policy bounded-v2` extends v1 to missing assignments, invented IDs,
wrong-type IDs, invalid structural roles and invalid continuations. Normalization
removes invalid claims, records each removal, and explicitly enumerates every
unassigned real source ID. Invalid `table` roles become missing-content tasks;
content is never silently reclassified as page furniture.

At most one additional VLM call selects duplicate occurrences and places missing
IDs within existing content items. Exact ID coverage, destination types, flow
membership, insertion anchors and allowed schemas are checked, then the original
full validator runs again. `UNRESOLVED` remains a failure. Repaired pages retain
`needs_review: true`, `semantic_validated: false` and partial status.

Frozen-response preflight over all 49 pages:

| Outcome | Pages |
|---|---:|
| Previously valid flow unchanged and still valid | 41 |
| Failed flow becomes structurally valid without a model call | 2 |
| Requires a model assignment decision | 6 |

The two deterministic repairs are CLAD p63 (unknown fragment ID) and
`gw150914_gr_test` p3 (self-loop continuations). Their audited flow artifacts are
under `EvidenceNet/output/semantic_audit_20261005/deterministic_flow_patches/`.
This is flow-only replay, not materialization of new nodes/edges for those pages.

## Semantic findings

Read the anchor and association basis of all 42 accepted local relations; inspect
full source images for a purposive subset of 23 relations on nine pages. Reviewer
is the assistant, not independent human GT. The remaining 19 have **not** received
full visual review. These counts must not be reported as a precision estimate.

| Source-reviewed outcome | Relations |
|---|---:|
| Supported association, sometimes with evidence limitations | 10 |
| Reject relation | 7 |
| Association needs a better primary anchor | 3 |
| Ambiguous scope/condition; further review needed | 3 |

Concrete failures:

- ML1 p6 and ESS203 slide20: institutional/project logos linked to learning or
  glacier time-lapse photography. The source visuals do not depict those claims.
- CLAD p6: two vertical PHOTO credits accepted as `CAPTION_FOR`.
- CyberPhysical p6: “Blocks represent a function” linked to the physical spring
  diagram instead of the separate function-block diagram.
- NVIDIA p6: a promotional award-belt photo linked to a specific 50x performance
  claim that the photo does not show.
- DLR p12: caption placed beneath the ambulance photo attached to the separate
  large river-vehicle photo, without explicit shared-panel wording.

Anchor problems include `Fig.`, `FIG.`, `7.`, generic headings and DLR p17's funding
sentence selected while the basis describes the eye examination. Exact offsets
do not establish semantic support. The CLAD stadium case is deliberately **not**
called a simple wrong-identity negative: the visible page number 58 and the
contents entry's “some more projects” wording support an editorial association,
although the Barcelona image cannot support a specific Manchester United claim.

Machine-readable per-edge decisions, source paths, hashes and limitations:
`EvidenceNet/output/semantic_audit_20261005/relation_review.json`.

## Implemented semantic safeguards

`--anchor-protocol span-id-v2` keeps figure prefixes, numbered-caption prefixes,
personal titles and initials with their descriptions. Exact original-text offsets
and the maximum chunk length remain enforced. v1 remains available unchanged in
its segmentation behavior for comparison.

The v2 validator rejects bare figure/number markers and short PHOTO-credit-only
primary evidence. This is a narrow content check, **not** an automatic semantic
verifier. Applying these checks and the reviewed-logo map to old anchors flags
8/42 old relations for exclusion/reselection; that number mixes anchor defects
and unsupported relations and is not a semantic error count.

The v2 prompt requires the primary evidence to support the stated association,
explicitly separates attribution from captions, and disallows logo/topic and
promotional-photo/numerical-result associations. Source-reviewed KIT and EIS
roles are added to `EvidenceNet/config/reviews/visual_roles/reviewed_visual_roles_20261005.json`, bound
to page hash, crop hash and geometry. Components remain present; semantic
candidates skip these reviewed logos. Unreviewed visuals remain UNKNOWN.

## Validation and queued experiments

- 40 relevant tests pass: 14 relation-first, 8 v1 recovery, 5 v2 assignment patch,
  9 source grounding, 4 adapter. Python compilation and launcher syntax pass.
- All 49 source pages also run through the local v2 pipeline check without LLM
  inference; see `EvidenceNet/output/semantic_v2_local_check_20261005/summary.json`.
- Job **48023**: two H100s on dev, at most 14m30s, frozen-response repair of the
  eight failures; `_archive/2026-10-09-launchers/current/run_flow_patch_dev.sbatch`. Output:
  `EvidenceNet/output/flow_patch_v2_48023/`.
- Job **48027**: dependent on 48023 finishing, two H100s on dev, at most 14m30s;
  `current/slurm/edge_generation/run_semantic_v2_dev.sbatch`. Ten targeted pages include known defects
  and a positive GW caption control. Output: `EvidenceNet/output/semantic_v2_48027/`.
  Nine unrepaired valid flows can be reused after input/config checks; CLAD p6's
  repaired ownership cannot be reused and its flow is generated again. Its
  comparison therefore does not isolate only the semantic-policy change.
- Last status check: 48023 PENDING (Priority), scheduler estimated 12:50 local;
  48027 PENDING (Dependency). Start estimates are not guarantees. No new GPU
  result or six-page model-repair success rate is available yet.

The ten-page test is a targeted regression, with policies informed by these
failures; it cannot establish generalization. Cross-document candidate semantics
still need the existing independent blind review. No 1048-page run was launched.
