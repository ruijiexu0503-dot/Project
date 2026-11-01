# Edge construction：离线候选、核验和结构上下文

更新：2026-11-01。[66 个脚本索引](SCRIPTS.md) 按 pipeline、候选、核验、描述 embedding、结构/node 上下文、公式、诊断与历史实验分组。

## 范围与入口

整体系统从文件解析和 node generation 开始。`run_evidence_edge_pipeline.py` 本身是 **post-node** 入口，不能把它单独称为文件到图的完整实现。上游适配入口包括 `parse_vldocir_pages.py`、`prepare_vldocir_nodes.py`、`run_vldocir_nodes.py`；是否满足某个实验的全部前置条件，应检查该实验 manifest。

- 主建边流程：`run_evidence_edge_pipeline.py`，VL-DocIR 适配为 `run_vldocir_edge_pipeline.py` / `prepare_vldocir_edge_adapter.py`。
- 候选：`run_hierarchical_edge_retrieval.py`、分配修复和 line-aware 视图；候选召回与最终接受必须分开统计。
- 核验：`run_routed_edge_context.py`、身份门控、分层/原文 grounding 等实验。目录中存在实现不代表所有模块都串入当前默认流程。
- 关系描述与 embedding：`bounded_edge_descriptions.py`、`sentence_edge_descriptions.py`、`edge_embedding_records.py`、`run_vldocir_edge_embedding.py`。
- 阅读顺序：`vldocir_reading_backbone.py` 和修复脚本。NEXT 可以提供反向 PREVIOUS 导航，但只能由实际 reading assignment 建立，不能按 node ID 猜顺序。
- 公式：`06_formula/` 收集上下文、检索视图、结构与语义对照脚本。

现有参考文献连接应保留独立类别；不能把共享引用、同实体、阅读顺序和语义支持当成同一种证据关系。图片到文字与文字到图片都可能有用途，导航反向可用不代表因果或支持关系自动反向成立。

## 当前证据与尚未解决的问题

HF 对照尚未证明现有边能改善最终证据选择。前序查询冻结图只有 187 条语义边、321 个端点且未加载阅读顺序；KG 准备审计的另一份输入有 213 条旧 RELATED、366 个端点。两者图范围不同，不能混用统计。

KG 审计的 7291 个 node 中仅 5.02% 被旧 RELATED 覆盖；reading assignment 只覆盖 9 个 node。拥有 NEXT 实现不等于实验里所有 node 都有 NEXT。优先确认结构边覆盖和加载，再评价走边策略。

纯文本的同主题、相同模板、不同主体/条件仍容易被错连。添加整段上下文也可能稀释锚点或引入其他对象。现有身份门控、原文引用和描述约束是修复手段，不能宣称错误已清零。

公式不能只比较字母，也不能只做符号重命名：必须保留变量角色、假设、单位和适用条件。常用基础公式相同不等于两篇文章有有用的证据连接。公式上下文实验与结构语义实验应分别查看，不将局部结果推广为所有公式有效。

Dolphin 的换行可用于版面边界和细粒度候选视图，但不是天然句子边界；必须处理 soft wrap，避免把跨行句子截断。行级召回应保留到原 node 和原文位置的映射。

## 下一步建设目标

按 [基于 HF 的调整计划](docs/vldocir/EDGE_CONSTRUCTION_PLAN_AFTER_HF_20261101.md) 优先补结构、归属、身份和互补证据连接，而不是继续增加泛同主题边。

离线候选可以让每个 node 都参与召回，但仍由同一个 verifier 决定是否建边；不强制每个 node 至少一条语义边，不做无界全量两两连接。关系描述可以开放，但必须短、具体、有两端原文依据，保留主体与条件差异。

输出至少能追踪两端 node、来源位置、关系/描述、方向或反向导航语义、核验依据和版本。Query 使用端再判断该边对当前问题是否有增量价值。

## 文档入口

- [现有 pipeline 交接](../../EDGE_PIPELINE_HANDOFF.md)
- [离线 pipeline 对照](docs/vldocir/PIPELINE_COMPARISON_20261025.md)
- [自由描述 edge embedding](docs/vldocir/EDGE_EMBEDDING_HANDOFF_20261025.md)
- [描述限制](docs/vldocir/BOUNDED_EDGE_DESCRIPTIONS_20261028.md)、[一句话描述](docs/vldocir/SENTENCE_EDGE_DESCRIPTIONS_20261028.md)
- [阅读顺序接入](docs/vldocir/READING_ORDER_EDGE_INTEGRATION_HANDOFF_20261031.md)
- [公式上下文诊断](docs/own_corpus_edges/FORMULA_CONTEXT_DIAGNOSIS_20261026.md)、[公式结构语义](docs/own_corpus_edges/FORMULA_STRUCTURE_SEMANTICS_20261027.md)
- [行级与多模态实验](docs/own_corpus_edges/LINE_AWARE_AND_ALL_NODE_MM_RESULTS_20261017.md)

原命令、依赖及部署保留方式见 [总说明](../README.md)。
