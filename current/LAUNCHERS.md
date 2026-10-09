# Slurm 入口

2026-10-09 整理后，本机保留 27 个 sbatch，其中 `current/slurm/` 的 17 个
仅在本地保留并被 Git 忽略；69 个历史/被替代的提交器
移到 `_archive/2026-10-09-launchers/`，按原相对路径存放并沿用归档忽略规则。
它们的 Python driver 和实验结果说明仍保留，移动文件的 SHA-256 不变。

`current/` 的 17 个保留提交器统一放在 `current/slurm/`。
按用途分为 `vldocir/`、`hybrid_nodes/`、`document_graph/`、`evidence_nodes/`
和 `edge_generation/`。从仓库根目录执行
`sbatch current/slurm/<group>/<name>.sbatch`；脚本内部仍使用
`current/env.sh` 和仓库根目录作为环境/工作入口。

## 日常 pipeline

| 用途 | 入口 |
|---|---|
| VL-DocIR 解析试跑 / 完整解析 | `current/slurm/vldocir/run_vldocir_dolphin_smoke_dev.sbatch`、`current/slurm/vldocir/run_vldocir_dolphin_dev.sbatch` |
| VL-DocIR 输入准备 | `current/slurm/vldocir/prepare_vldocir_nodes_cpu.sbatch` |
| VL-DocIR 节点试跑 / 完整节点 | `current/slurm/vldocir/run_vldocir_nodes_dev.sbatch`、`current/slurm/vldocir/run_vldocir_nodes_full.sbatch` |
| VL-DocIR 检索评测 | `current/slurm/vldocir/run_vldocir_retrieval_dev.sbatch` |
| Hybrid v2 冻结 49 页回归与评测 | `current/slurm/hybrid_nodes/run_hybrid_node_v2_dev.sbatch`、`current/slurm/hybrid_nodes/evaluate_hybrid_node_v2.sbatch` |
| Dolphin 文章图语料解析 / 发布 | `current/slurm/document_graph/run_document_graph_dolphin_dev.sbatch`、`current/slurm/document_graph/publish_document_graph_dolphin.sbatch` |
| 跨页判断 | `EvidenceNet/slurm/run_document_cross_page_qwen_dev.sbatch` |

VL-DocIR 依赖关系和需要导出的参数见其实验 README。不要把六个提交器
无依赖地同时运行；这次既有任务链的 IDs 和依赖保持不变。

## 保留的辅助入口

- `current/slurm/` 的 member-asset 35B、multimodal labelled CPU、relation-first v7、
  bounded recovery、span grounding、window candidates、semantic-v2 提交器。
- `parsing/pipeline_steps/step1_run_parsing_pipeline.sbatch`、
  `parsing/run_doc_profile_all.sbatch`、`parsing/src_splitpage/*.sbatch`。
- Dolphin 的原始 parser 对照提交器；两个 PosterGen 提交器。

这些入口服务不同输入契约，不应按文件名拼成一个默认 pipeline。
旧集群的 parsing 辅助入口仍可能需要修改分区/环境；以对应 README 为准。

## 查找和恢复历史提交器

本地清单：`json/launchers_20261009.json`，已忽略，磁盘文件保留。
记录全部保留路径以及原路径、归档位置、原因、SHA-256。

```bash
# 预览并核对全部 69 个本机归档文件，不移动文件。
python current/restore_launchers.py

# 只恢复一个需要重跑的旧实验，不覆盖已有文件。
python current/restore_launchers.py \
  --path current/run_hybrid_boundary_v3_dev.sbatch --apply
```

恢复需要本机 `_archive/` 副本。旧文档中明确指向 `_archive/` 的提交命令
只用于历史复现；这些文件不随新的 Git checkout 下载。
