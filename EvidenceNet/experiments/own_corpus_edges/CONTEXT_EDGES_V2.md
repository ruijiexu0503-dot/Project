# Evidence-node context edges v2

This pilot uses the same 49 pages and 550 immutable multimodal evidence nodes as
v1. It does not alter the production pipeline or the frozen VL-DocIR baseline.
Generated descriptions remain candidate representations, never source anchors.

The v1 audit found furniture, parser padding, and visual-style similarity among
high-scoring pairs, and explicit figure references below the relevance threshold.
V2 therefore applies member-level furniture eligibility, rejects unusable windows,
cleans retrieval representations while preserving raw spans, counts distinct nodes
in candidate budgets, and adds source-reference and geometry/reading candidates.
The intra-article candidate budget no longer applies a two-per-target-article cap.
Reading adjacency and geometry are candidate routes, not accepted semantic edges.
Nodes and their original members/crops remain available in the viewer even when
their representations are excluded from candidate retrieval.

Unique figure/table/equation references resolve within a known article or the same
unresolved page. Opening caption labels declare a target and never reference a
second caption. Ambiguous references are recorded. Reference ranges, decimal
equation identifiers, external citations, and unresolved article ownership remain
limitations of this conservative resolver; it is not a full citation parser.

BGE scores propose pairs only. A deterministic queue of up to 120 pairs includes
structural routes, scope quotas, and high relevance scores. It does not use the old
audit labels to select candidates or the verification queue. Qwen sees eligible
original text and original crops only, with no generated descriptions or scores.
Accepted RELATED_CONTEXT edges are symmetric and require source-member quotes
or visible crop observations. REFERENCES retains its source-to-target direction.
Model checking is not independent human validation, and no retrieval improvement
is claimed from this graph experiment alone.

Run on HoreKa2:

```bash
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_node_context_edges.py prepare --policy-v2 --output EvidenceNet/output/node_context_edges_v2_20261011
sbatch current/slurm/edge_generation/run_node_context_edges_v2_gpu.sbatch
# Supply the actual preceding job ID using --dependency=afterok:JOB_ID.
sbatch current/slurm/edge_generation/verify_node_context_v2_gpu.sbatch
sbatch current/slurm/edge_generation/report_node_context_v2_cpu.sbatch
```

Outputs include eligibility, raw/cleaned windows, candidate routes, BGE alignments,
proposed edges, the source/crop verification queue and individual decisions, final
semantic edges, graph_data.json, and index.html. Snapshot hashes protect the original
node files and prepared inputs. `compare_node_context_pilot.py` reports recovery of
previously audited error/omission cases separately from quality on unseen samples.
An incomplete verification run stays marked incomplete, even after reranking.

Submitted jobs: 67360 first rerank; 67361 cancelled before starting after discovering
the caption declaration bug; 67362 corrected rerank; 67364 source/crop verification.
Use Slurm accounting and output manifests to check completion rather than treating
submission as a successful result.
