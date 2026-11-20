# Cross-article evidence retrieval diagnostic

The intended graph connects canonical EvidenceNodes in different articles.
Articles own and contextualize evidence; an article-level retrieval score is not
a prerequisite for a local relation and does not create an evidence edge.

## Reused upstream contract

Use existing validated Qwen article ownership and reading order. Namespace
page-local IDs by document and page, and use accepted cross-page continuation
decisions when joining article fragments. Map parsed source IDs to canonical
EvidenceNode source membership explicitly. Ambiguous/missing mappings remain
unresolved, not guessed by text similarity or numerical ID suffixes. Article
profiles help retrieve candidates but are not themselves source evidence.

The current diagnostic still reuses the old 447-vector snapshot to isolate the
retrieval change. It does NOT implement the full Qwen-to-canonical-node adapter.
The snapshot also contains paper sections/pages; candidates involving these
aggregates are marked `requires_atomic_endpoint_resolution` where membership
contains multiple nodes. They are not atomic semantic edges.

## Candidate design

1. Query a persistent evidence ANN index directly, excluding the same article.
2. Overfetch a bounded pool and optionally limit each target article to two hits.
3. Independently use article/local/lexical routing to identify a bounded set of
   articles, then retrieve their evidence. Never use this route as a hard gate
   on direct evidence hits.
4. Deduplicate pairs retrieved in either direction. Retrieval direction is not
   semantic direction. Keep full IDs, article owners, pages and source text.
5. Verify a bounded candidate set with the existing semantic-existence-first
   policy. Provide each endpoint with its owning article/context; require exact
   supporting spans. Similar topic alone is insufficient; uncertain remains
   unresolved. Only verified atomic pairs become graph edges.
6. Derive article-level relations as views over verified evidence links.

For incremental operation, embed each new EvidenceNode once, query the existing
index, append new vectors, and verify newly proposed pairs. Cache verification by
both endpoint content/context versions and model/prompt/taxonomy version. Updating
an article grouping can invalidate same-article exclusion and contextual judgments.
Do not materialize transitive evidence links merely because A connects to B and
B connects to C. Reverse-neighbor refresh remains necessary for recall over time.

## Completed diagnostic

Output: `EdgeGeneration/output/cross_article_evidence_audit_v2/`.

| Policy | Unique candidate unit pairs | Provisional positive pairs retained | Provisional negatives retained |
|---|---:|---:|---:|
| Global top 10 | 3,437 | 3/4 | 1/3 |
| Global top 10, at most 2 per target article | 3,621 | 4/4 | 1/3 |
| Article routing, top 10 per source unit | 3,853 | 3/4 | 2/3 |
| Global top 10 plus routed top 10 | 5,524 | 4/4 | 2/3 |

There are 97,275 possible cross-article unit pairs in this snapshot. The diverse
top-10 candidate set is 3.72% of that, a 96.28% reduction in potential pair
verification workload. This is not a wall-clock speedup or a semantic precision
measurement. Four positives and three negatives are provisional historical labels;
the selected report view is exploratory, not a tuned production default.

The report shows gravitational-wave-related candidate texts. No semantic model
has judged these exported pairs. Before final graph construction, replace the
old ownership snapshot with validated Qwen ownership and paper section targets
with canonical evidence endpoints. Measure held-out evidence-pair recall,
verified edge precision, verification calls per new node, and same-magazine
cross-article coverage, rather than only article-pair coverage.

## Run

```bash
PYTHONPATH=EdgeGeneration/.ann_deps OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  EvidenceNet/.venv_qwen/bin/python EdgeGeneration/scripts/audit_cross_article_evidence.py \
  --output EdgeGeneration/output/cross_article_evidence_audit_v2
```

All nine tests under `EdgeGeneration/tests` exercise retrieval invariants;
the script records source snapshot version and checks the vector-cache hash.
