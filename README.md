# EvidenceNet project guide

**当前入口：[精选结果与对应 pipeline](current/README.md)。**
2026-10-09 的代码目录与提交检查说明见 [代码导航](current/CODE_MAP.md)。
正在评估的 VL-DocIR 接入见 [实验说明](EvidenceNet/experiments/vldocir/README.md)。
这里汇总了实际指标、保留理由、HoReKa2 运行入口与验证限制。
历史实验已集中归档到 `_archive/2026-10-04/` 并加入 `.gitignore`；
精选结果及其依赖仍在原包目录，已跟踪文件的映射见
[本地归档记录说明](current/archives/README.md)。
2026-10-04 已补齐解析产物和本地依赖的忽略规则，并将7份被替代的探索脚本移入
`_archive/2026-10-04-superseded-scripts/`；恢复方法和Git状态说明见
[清理记录](current/GIT_CLEANUP.md)。

This repository contains the parsing, EvidenceNode construction, document-internal
graph, and cross-document discovery work. The pipeline is evolving, so the
documentation distinguishes deployed behavior from validated shadow experiments.

Start here:

- [`PIPELINE_CURRENT.md`](PIPELINE_CURRENT.md) — operational baseline versus
  current shadow branches and their validation limits.
- [`PIPELINE_STEPS.md`](PIPELINE_STEPS.md) — current end-to-end pipeline, real
  entrypoints, inputs, outputs, and production/shadow boundaries.
- [`PIPELINE_DECISIONS.md`](PIPELINE_DECISIONS.md) — append-only design decision
  log. Add a record whenever a policy is accepted, replaced, or frozen.
- [`EvidenceNet/README.md`](EvidenceNet/README.md) — EvidenceNet CLI usage.
- [`EvidenceNet/docs/structure_detection/README.md`](EvidenceNet/docs/structure_detection/README.md)
  — document-level single-work versus multi-item routing.
- [`parsing/experiments/dolphin_v2_pilot/README.md`](parsing/experiments/dolphin_v2_pilot/README.md)
  — isolated Dolphin-v2 parser evaluation.
- [`OfflineCitationGraph/README.md`](OfflineCitationGraph/README.md) — offline,
  incremental scholarly citation graph.
- [`EdgeGeneration/README.md`](EdgeGeneration/README.md) —
  non-citation cross-document discovery pilot.

## Status vocabulary

| Status | Meaning |
|---|---|
| `ACTIVE` | Executable stable path or an explicitly gated production interface. |
| `SHADOW` | Produces isolated audit output; it must not overwrite production. |
| `EVALUATING` | Comparison is in progress and no winner is selected. |
| `FROZEN` | Result is retained for provenance but is not being tuned. |
| `LEGACY` | Reproducible historical path; not a current default. |

An output directory is not evidence that its method is active. The command,
configuration, model, input root, and decision-log entry together define a run.

## Safe update rule

When changing the pipeline:

1. Add or update a decision in `PIPELINE_DECISIONS.md`.
2. Update the affected step and status in `PIPELINE_STEPS.md`.
3. Keep experimental output isolated and record its provenance.
4. Promote a shadow method only after an explicit before/after audit.
5. Never silently replace source geometry, original pages, ground truth, or
   production graph artifacts.
