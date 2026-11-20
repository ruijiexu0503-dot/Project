# Network build report

Date: 2026-11-18  
Version: `network_v2_build_20261117`  
Scope: network/loss/checkpoint build only; no real training and no job submission

## Status

`B1_NETWORK_IMPLEMENTED`: complete for the requested build-only scope.

The broader task-level `NETWORK_READY` status is intentionally not claimed yet:
B2 search/controller and final set selection are outside this pass. Likewise,
`DATA_READY_FOR_FIT`, `TRAINING_COMPLETED`, and `RETRIEVAL_GAIN_VERIFIED` are not
claimed.

## Implemented contract

`DynamicEdgeRanker` accepts query `[B,D]`, selected content `[B,S,D]`, target
content `[B,C,D]`, context `[B,C,Dctx]`, source content `[B,C,R,D]`, fixed 12-D
route features, Dense similarity, `selected_fraction [B,1]`, and all prescribed
masks. It returns scores `[B,C]`, the original candidate mask, optional e0 and
dynamic edge diagnostics `[B,C,R,d]`, pooled edges `[B,C,d]`, state `[B,d]`,
route availability, auxiliary-head status, and actual packed work counts.

All masked rows are packed before learned projections/MLPs. Thus padding values,
including NaN, do not enter a learned layer. Effective non-finite inputs fail
explicitly. No-edge disables edge vectors, route features, route availability,
and edge work together.

The default trainable modules are P, Pctx, EMPTY, state MLP, F, Wc, G, and R.
A/E heads are absent unless explicitly enabled. For input dimensions D/Dctx,
model dimension d, and hidden width h, the default parameter count is:

`d(D + Dctx) + d^2 + (19d + 22)h + 14d + 1`

An enabled A head adds `3h + 3`; E adds `4h + 4`.

## Loss and checkpoint behavior

The ranking loss validates positive/negative disjointness, candidate membership,
finite effective scores, and positive finite temperature. It averages positives
within state, states within query, then queries. Empty P/N states are counted and
skipped; an all-empty batch returns differentiable zero with
`optimizer_step_allowed=false`.

Checkpoint loading is strict over network version, architecture, the 12 route
features, and every state-dict tensor. Required provenance fields are encoder,
graph, and data hashes plus random seed.

## Verification

Environment: HoreKa module `PyTorch/2.9.1-foss-2024a`, CPU.  
Command:

```bash
python -m unittest discover -s dynamic_retrieval/tests -p 'test_*.py' -v
```

Result: 12 tests passed on 2026-11-18. Covered behaviors include shapes and work
counts, padding invariance, masked-NaN isolation, input rejection, no-route and
no-context behavior, directed endpoint order, q/T-dependent dynamic edges,
no-edge/context ablations, disabled auxiliary heads, loss monotonicity and query
grouping, finite gradients for P/F/G/state/R, one optimizer update, and exact
eval-mode checkpoint replay.

## Deliberately not executed

- no r3 or VL-DocIR vector loading;
- no real candidate construction, fit, retrieval, or evaluation;
- no search-controller or final-set-selection changes;
- no GPU allocation, scheduler submission, download, commit, or remote push.
