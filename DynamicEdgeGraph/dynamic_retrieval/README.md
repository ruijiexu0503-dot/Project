# Dynamic Retrieval

The build-stage network is `network_v2_build_20261117`. It implements the
frozen-representation side of the query/state-conditioned directed-edge design;
it has no node, document, or edge ID parameters and never accepts qrels or answer
fields.

Implemented network pieces:

- shared query/content projection P and separate masked context projection Pctx;
- explicit empty selected-set state and `selected_count / output_K` feature;
- 12-D directed route schema, packed F/G computation, mean route pooling;
- one target scorer for Dense-only and Edge-discovered candidates;
- candidate/context/route/Dense masks with masked-NaN isolation;
- complete no-edge and context ablations;
- per-positive ranking loss with state-then-query aggregation;
- disabled-by-default A/E interfaces and strict versioned checkpoints.
- opt-in A-head gain training on Gold completion states; non-Gold candidates
  remain unknown rather than being assigned a false “no gain” label.

The network stage does not run a real fit. Search/controller work, r3 dry-run,
and real-data readiness remain separate stages. See `NETWORK_BUILD_REPORT.md`.

## Local synthetic verification

```bash
module load PyTorch/2.9.1-foss-2024a
python -m unittest discover -s dynamic_retrieval/tests -p 'test_*.py' -v
```

The synthetic configuration is `configs/network_synthetic.json`. No command in
this build-only stage downloads a model, requests a GPU, or submits a job.

The Gold-200 pilot can train the existing A head with the `gold_completion_v1`
policy. It labels a remaining Gold node as:

- `1` when it adds support but the selected set is still incomplete;
- `2` when adding it completes the current Gold set.

Dense non-Gold candidates are marked unknown and excluded from A-head cross
entropy. The launch template enables this auxiliary target with:

```bash
sbatch DynamicEdgeGraph/dynamic_retrieval/horeka_train_gold200.sbatch
```

The older `runs/p0_vldocir_mini_20261115` remains an isolated page-level data
branch. Its IDs, vectors, and labels are not inputs to this network verification.
