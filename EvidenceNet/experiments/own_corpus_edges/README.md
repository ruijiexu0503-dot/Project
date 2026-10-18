# 自有材料的 edge 试跑

下一步实现交接见 [先建立相关文章索引，再定位跨文章 evidence node](ARTICLE_BRIDGE_GRAPH_HANDOFF.md)，
包含当前工程入口、数据结构、实施步骤、已知错例与验收标准；该新方案尚未实现。

最新算法试跑见 [分类型 evidence-node 连边](TYPED_EDGES_V1.md)：原文实体索引、
原图视觉候选和按关系类型核验，49 页试跑已完成；
[结果复核](TYPED_EDGES_V1_REVIEW.md)显示覆盖改善但精度不足，尚未测量检索提升。
后续方法的文献依据与改造建议见 [语义与图方法研究笔记](SEMANTIC_GRAPH_RESEARCH.md)。
已完成 [独立事实提取的固定候选对照](FACT_GROUNDED_EDGES_V1.md)，比较 80 对候选；
[结果复核](FACT_GROUNDED_EDGES_V1_REVIEW.md)显示抽取／协议失败较多，尚不能证明提升。
[逐项修复记录](INCREMENTAL_EDGE_REPAIR.md)保存第一项断行匹配回归结果和文章候选路由方案。
新一轮 [文章候选与 node 上下文对照](ARTICLE_CONTEXT_PILOT_V1.md)固定 64 对节点，
分别检查候选覆盖与加入有来源上下文前后的关系判断。
[结果复核](ARTICLE_CONTEXT_PILOT_V1_REVIEW.md)：两组已完成，背景能帮助个别图号消解，
但仍有错图注、错误类型与候选漏连，尚不接入正式 pipeline。
下文记录最初的 v1 实验。

实验 ID：`own_corpus_edges_v1_20261011`。
使用已有 49 页混合材料的 Hybrid v2 embedding+geometry 节点，共 550 个。
输入为 `EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry` 与对应 prepared 页面。
输出为 `EvidenceNet/output/own_corpus_edges_v1_20261011/`，产物与集群提交器本地保留并忽略。

这轮先建图并检查两端证据，不开展检索消融。输入包含自己的论文、杂志、教材、
幻灯片、报告与单图材料。VL-DocIR 冻结 baseline 是另一个独立实验。

## 运行链

| 任务 | Job | 行为 |
|---|---|---|
| ownership | 66674 | 复用完整可映射的 26 页源阅读流，重新判断其余 23 页分组/flow |
| candidates | 66675 | Qwen3-Embedding-0.6B、阅读近邻、视觉几何近邻及显式 marker 候选 |
| verify | 66676 | 四个分片，最多两个并行；Qwen3.5-35B-A3B 核验实际节点原文/目标 crop |
| report | 66677 | 无论核验是否全部成功，汇总实际结果、问题与可视化 |

原分组可复用必须同时满足源 fragment/visual 文本和几何一致、flow 已接受、
所有当前节点可唯一归属且未跨旧 flow 冲突。拒绝过的提议不算成功分组。
已知论文的文档身份用于跨页文章归属，独立 flow 与跨页 NEXT 仍需单独证据。
杂志未确认的跨页文章归属保持 page-local。

## 输出

`index.html` 可选文档与边类型，点击节点查看原文、成员、原始 crop、生成描述和
页面位置；点击边查看两端、类型、方向、锚点、原图及依据。拒绝、不确定和
格式失败的记录可单独检查。

机器记录包括 `units.jsonl`、`reading_edges.jsonl`、`candidate_pairs.jsonl`、
`decisions/`、`semantic_edges.jsonl`、`article_edges.jsonl`、`issues.jsonl` 和 `summary.json`。
候选预算按 scope 分配并分散到 source pages，最多 380 对；不是全部可能关系。
文章关系仅聚合已有节点证据边，并保留 supporting_edge_ids。

语义允许 SUPPORTS、EXPLAINS_OR_ELABORATES、MODIFIES、CONTRASTS_WITH、
REFERENCES、CAPTION_FOR 和 ILLUSTRATES。存在性、类型、方向和两端锚点一起保存。
生成描述只帮助找候选；不能作为 TEXT 原文锚点。视觉锚点对应实际目标 crop。
模型接受且来源可定位仍须独立源文复核，不能当作已测量的语义精度。

当前 49 页是开发回归材料，已有边界/角色问题（包括 slide headline）会继承到
本轮查看中。缺失分组、跨页映射和无法判断的关系保留问题记录，不自动补造边。
已知跨页仅来源核验后可映射的旧边；稀疏页面采样限制续页覆盖。

## 本地检查与恢复

149 项 EvidenceNet 测试通过，包括来源锚点、分组覆盖、重复 flow、未知文章 scope。
Slurm 语法和生成的 viewer JavaScript 语法检查通过。每次运行检查源节点哈希。

```bash
source current/env.sh
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_own_corpus_edges.py report \
  --output EvidenceNet/output/own_corpus_edges_v1_20261011
```

局部重跑需使用同一输入版本；已有 decision 文件会复用，失败文件需要先归档后
再重试。试跑不修改输入节点或既有 VL-DocIR baseline。
