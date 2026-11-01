# EvidenceNet 按研究任务整理的工作目录

更新：2026-11-01。这里将 **query 使用图**、**离线建立 edge** 和 **知识图谱关系预测** 分开，供继续实现和切换模型使用。

| 工作目录 | 职责 | 入口 |
|---|---|---|
| query | query 拆解、检索种子、沿边导航、证据选择、预算和评价 | [说明](query/README.md)、[32 个脚本](query/SCRIPTS.md) |
| edge_construction | 候选召回、关系核验、描述 embedding、结构边、公式上下文 | [说明](edge_construction/README.md)、[66 个脚本](edge_construction/SCRIPTS.md) |
| knowledge_graph | 独立的 KG 准备、标注、ULTRA/TRIX 候选预测和 entity overlay 研究 | [说明](knowledge_graph/README.md)、[2 个现有脚本](knowledge_graph/SCRIPTS.md) |

## 目录如何使用

这些目录是实际建立的分类工作入口，`scripts/` 中是指向现有源码的**相对符号链接**，不是独立复制的代码。修改链接文件会修改原源码。此次没有移动原脚本，没有改变 pipeline 默认参数或已部署任务。

保留原路径的原因：脚本之间存在同目录 import，测试和 Horeka 部署包已引用 `EvidenceNet/scripts/`。直接搬走会破坏旧实验的复现。历史脚本仍可能是新脚本的依赖，不能因为放在 history 分类中就删除。

运行时继续从 Project 根目录使用原命令，例如 `python EvidenceNet/scripts/run_query_semantic_edge_v2.py --help`。不要把某个分类子目录单独复制到远端当完整运行环境；部署继续使用已有 migration 打包流程，并检查依赖和 SHA。只拷贝符号链接不会携带源码。

`docs/` 中链接的是完整历史文档目录，以保留文档之间的相对引用；每个 README 列出本方向应优先阅读的文档。`results/` 是已有结果的链接，不是新增实验。没有复制测试目录，避免 pytest 重复收集。原测试仍在 `EvidenceNet/tests/`。

[catalog.json](catalog.json) 记录每个分类入口、原路径和整理时的文件 SHA256；它是整理快照，不代替部署 manifest，后续修改源码后 hash 会变化。本次覆盖 100 个相关脚本，并非全仓库迁移；其他解析器、通用模块和旧探索脚本仍在原位置。

## 三个方向的接口

```text
文件 → 解析与 node generation → 离线建边 → 冻结 nodes / edges / 来源与描述
                                      ↑
                        KG proposer → 原文 verifier（研究分支）

query → 检索 TopK seeds → 根据 query 判断已有边的用途
      → 沿边取目标原文 → 选择证据片段 → token 预算 / 检索和证据评价
```

离线图不依赖测试 query 或 gold answer。在线可以对已有边按 query 判断相关性与增量价值，但不能把边的自然语言描述当作原文事实。KG 预测只是候选来源，不能直接当真值。

## 当前结论边界

目前尚未证明 edge 提升了最终证据质量。HF 对照是 24 query / 518 页 pilot，不是官方全集；页面检索、node 定位、导航和最终证据选择必须分别评价。详见三个工作目录，不能把 node similarity 的结果写成有 edge 的结果，也不能把实验计划写成已经实现的功能。
