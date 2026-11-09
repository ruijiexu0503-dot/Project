# Stage 1 Git submission boundary

Commit the implementation and reproducibility contract, not local data products.

## Include

- `STAGE1_MULTI_ROUTE_CANDIDATE_PRUNING.md` and `README.md`
- `.gitignore` and this guide
- `configs/` (threshold policies and reproducible run parameters)
- `scripts/` (Slurm launchers)
- `src/` (node/view construction, frozen-embedding adapters, bounded retrieval,
  BGE audit, cross-scoring, pruning, analysis)
- `tests/`

## Keep local / do not submit

- `outputs/`: candidate JSONL files, SQLite databases, frozen matrices, charts,
  reports, and experiment manifests
- `.cache/`: downloaded VL-DocIR records and rendered inputs
- `.ann_deps/`: locally installed FAISS/NumPy runtime (~188 MB)
- `logs/`, `*.out`, `*.err`, `__pycache__/`

The source/configuration commit is sufficient to reproduce a run when the local
dataset/model caches and Slurm account are available. Outputs have immutable Run
IDs and should be archived outside Git if they must be shared.

## Suggested staging command

```bash
git add DynamicEdgeGraph/stage1_candidate_pruning/.gitignore \
  DynamicEdgeGraph/stage1_candidate_pruning/GIT_SUBMISSION_GUIDE.md \
  DynamicEdgeGraph/stage1_candidate_pruning/README.md \
  DynamicEdgeGraph/stage1_candidate_pruning/configs \
  DynamicEdgeGraph/stage1_candidate_pruning/scripts \
  DynamicEdgeGraph/stage1_candidate_pruning/src \
  DynamicEdgeGraph/stage1_candidate_pruning/tests
```

Before committing, inspect only this scope with:

```bash
git status --short DynamicEdgeGraph/stage1_candidate_pruning
git diff --cached --stat
```

Do not stage unrelated `EvidenceNet/` files or the root `.gitignore` change
unless those changes are independently intended.
