# 当前 Slurm 提交器

这些 sbatch 是本机集群的实验启动配置，Git 忽略，磁盘文件保留。
新 checkout 需要根据集群账户、分区和本地环境另行配置提交器。

从仓库根目录执行 `sbatch current/slurm/<group>/<name>.sbatch`。
参数、环境和作业依赖见 [入口说明](../LAUNCHERS.md)。

| 子目录 | 用途 |
|---|---|
| `vldocir/` | 数据集解析、节点准备与生成、检索评测 |
| `hybrid_nodes/` | Hybrid v2 回归运行和评测 |
| `document_graph/` | 文章图语料解析和发布 |
| `evidence_nodes/` | 视觉成员、多模态节点、边界恢复和 span grounding |
| `edge_generation/` | relation-first、语义和窗口候选实验 |

各组服务不同实验，不应按目录顺序直接批量提交。
