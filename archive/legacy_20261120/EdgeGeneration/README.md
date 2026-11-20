# Edge-generation discovery pilot

Updated 2026-10-09. Current pipeline entrypoints and retained experiments are
indexed in [current/README.md](../current/README.md). `CrossDocumentDiscovery/`
at the repository root is a compatibility link to this directory.

This isolated experiment discovers substantive relationships that are not
explicit citation links. It does not modify EvidenceNet or OfflineCitationGraph.

For moving this work to another checkout, see [MIGRATION.md](MIGRATION.md).
The two exploratory positive examples are recorded in
[docs/related_examples.md](docs/related_examples.md).

The graph families remain separate:

- `CITES`: exact bibliography provenance from OfflineCitationGraph.
- `RELATED`: retrieval candidate accepted only after strict semantic review.

The original September pilot retrieves CERN Courier 2022 EvidenceNodes against section-level
units from the three GW150914 papers. BGE-M3 is candidate retrieval only. A
retrieval score is never sufficient to materialize an edge.

## Indexed candidate pilot (shadow)

`scripts/run_ann_candidate_pilot.py` reuses the 447 BGE-M3 vectors from
`output/typed_anchor_multimag_pilot_v1`, grouped into 62 magazine articles and
three papers. CLAD/DLR cover selected pages only. Article representations are
normalized member-vector means, not newly encoded summaries.

It compares exact and HNSW retrieval, excludes same-article neighbors, combines
local/article/lexical routes using RRF, and sweeps 5/10/20 candidates per article.
The route depth stays fixed at 20 so budgets are comparable. The seven existing
provisional evidence-pair labels are reported individually and are not treated
as exhaustive article-level gold. Synthetic 10k/100k vector tests measure search
scaling only. No LLM is run and no verified graph edge is written.

Install the isolated CPU dependency from the repository root:

```bash
EvidenceNet/.venv_qwen/bin/python -m pip install --target EdgeGeneration/.ann_deps --no-deps faiss-cpu==1.12.0
mkdir -p EdgeGeneration/logs
PYTHONPATH=EdgeGeneration/.ann_deps EvidenceNet/.venv_qwen/bin/python \
  EdgeGeneration/scripts/run_ann_candidate_pilot.py \
  --output EdgeGeneration/output/ann_candidate_local --threads 8 --sizes 10000 100000
```

This CPU benchmark should run in a CPU allocation. The historical ANN Slurm
launcher contains a HoReKa1 partition and absolute checkout path; it requires
migration before use on HoReKa2. The direct command above uses the current checkout.

Outputs appear under the supplied `--output` directory (`EdgeGeneration/output/ann_candidate_local`
in the command above): `report.html`,
`summary.json`, candidate/evidence JSONL, index files with row-ID mappings,
and a versioned candidate SQLite cache. The incremental check tests append,
save/reload and cache idempotency; reverse-neighbor maintenance and a production
ingestion service are not implemented by this pilot. Cache invalidation is
conservative: any input or policy change creates a new dataset version.

The route-union ablation retains each route's top 3/5/10/20 article candidates
without a subsequent fusion cutoff. `union3_review_candidates.jsonl` includes
the best local evidence recovered within those bounded article pairs, allowing
inspection even when a candidate came only from article or lexical retrieval.
These evidence scores are not semantic verification.

First real-data results: [ANN pilot notes](docs/ann_candidate_pilot_2026-09-16.md).

Tests:

```bash
PYTHONPATH=EdgeGeneration/.ann_deps EvidenceNet/.venv_qwen/bin/python -m unittest discover -s EdgeGeneration/tests -p test_ann_candidate_pilot.py
```

## Article-scoped adapter and retrieval evaluation

`scripts/prepare_relation_first_inputs.py` imports component-based relation-first
snapshots and optionally document article membership/reading edges. It writes
addressable units and scoped candidates; it does not perform semantic verification.
See the [article graph contract](../EvidenceNet/experiments/document_article_graph/README.md).

The hybrid-v2 EvidenceNode retrieval comparison is implemented separately in
`EvidenceNet/scripts/retrieve_vldocir.py`. Its page ranking is a retrieval measure,
and does not materialize `RELATED` or intra-article semantic edges.
