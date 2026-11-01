# Top10 node 出发的一跳搜索：源数据与图覆盖审计

审计日期：2026-10-29。只读取现有文件并计算可达性，没有新模型推理、修改节点、增加边或使用gold选择路径。

**范围：24题、518页开发集，以及旧实验冻结的187条语义边子集。不是完整最终pipeline，也不是官方全集。**
以下图稀疏程度不能外推为完整EvidenceNet的图覆盖率。

## 1. 初始检索缓存和映射

项目根目录：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project`。

|内容|相对路径|
|---|---|
|24题及顺序|`migration/vldocir_trace_inputs_20261023/queries.jsonl`|
|窗口与unit映射|`migration/vldocir_trace_inputs_20261023/windows.jsonl`|
|unit与node/page映射|`migration/vldocir_trace_inputs_20261023/units.jsonl`|
|冻结query–window分数|`migration/vldocir-edge-20261022/results/search/query_window_scores.npy`|
|编码与输入校验记录|`migration/vldocir-edge-20261022/results/search/encoding.json`|
|原node与members|`migration/vldocir-edge-20261022/results/nodes.jsonl`|

矩阵形状为24×10301，行对应queries文件顺序。对窗口列wi：

```python
unit = units[windows[wi]["unit_input_line"] - 1]
node_id = unit["unit_id"]
node_score[node_id] = max(all_window_scores_for_that_node)
```

node排序采用`(-score, node_id)`确定性处理并列。encoding.json记录了矩阵SHA256及queries、units、windows等原始输入hash。
其编码模型是Qwen3-Embedding-0.6B；node/edge侧另有8B编码，不应混称为相同encoder。

## 2. 8817个unit与7291个node：差异来源已确认

完整、与冻结编码一致的文本输入目录：

`EvidenceNet/output/vldocir_minimal_inputs_20261016/hybrid_visual/`

核对结果：

- `provenance.jsonl`与上述TRACE的`units.jsonl`逐记录完全一致：8817条。
- `window_provenance.jsonl`与TRACE的`windows.jsonl`逐记录完全一致：10301条。
- `model_inputs.jsonl`的8817条记录提供原编码`content`和`title_context`。
- 1529个TRACE-only unit是单独索引的parser标题，ID形式为`task/structural/D...`；生成逻辑见`EvidenceNet/scripts/retrieve_vldocir.py`中structural heading部分。
- SOURCE中的3个没有编码的node，其member文本为空。
- 对其余7288个共享node，按成员原顺序用换行连接所有非空`member.text`，与canonical `model_inputs.jsonl`的`content`逐字符完全一致：**0个内容差异**。

因此不存在本次发现的共享ID文本漂移。用户要求从Top10 **node**出发时，应首先过滤为实际EvidenceNode ID，再取Top10。
1529个结构标题仍是合法检索unit，但没有自动成为同名EvidenceNode；不得把它们静默当成图节点。
若保留全部8817个unit的原检索方式，应另列对照并说明差异。

初检embedding还包含页面标题上下文，node分数并非只由node正文决定；末端仍需重新检查目标原文。

## 3. 冻结187条语义边的Top10一跳覆盖

边文件：

`migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/edge_records.jsonl`

关键字段为`edge_id`、`source_node_id`、`target_node_id`和`endpoints.A/B.spans`。
本审计将这组RELATED边作为双向导航候选，保留原记录身份；没有把导航方向解释为事实支持方向。

对24题分别以真实node-only排名Top10为入口，遍历所有187条语义边中的直接邻居：

|统计|结果|
|---|---:|
|query–seed出现次数|240|
|有至少一条该子集语义边的query–seed|25|
|去重后的query–邻居出现次数|29|
|初始Top10以外的新query–node|12|
|初始Top20以外的新query–node|7|
|能增加至少一个Top10外node的问题数|7 / 24|

计数按query内去重；同一node出现在不同query中分别计数。它们只是**可达性**，不是相关证据数、救回准确率或最终排名提升。
若错误地从全部8817个unit直接取Top10，结果会变为24个有边seed、11个Top10外新node，说明标题过滤确实影响种子集合。

## 4. 阅读顺序NEXT产物存在，但尚不能作为完整已验证骨架

可读取的远端结果根目录：

`/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs/vldocir-pipeline-compare-20261025/EvidenceNet/output/vldocir_pipeline_comparison_20261025`

在其`articles/`下检查到16个文档目录：

- 共633条原始NEXT，状态均为`QWEN_PAGE_FLOW_PROPOSAL`。
- 633条均为同页连接，所有source/target都存在于旧SOURCE的7291个node中。
- 16份`article_graph_manifest.json`引用文件的SHA256全部一致。
- **16份manifest的`reading_ready`全部为false**；例如`reading_issues.jsonl`含`PAGE_READING_UNRESOLVED`。
- `graphs/`尚无汇总的阅读骨架，未生成已编译PREVIOUS集合。
- 远端`adapted/nodes.jsonl`的7291个ID及members与旧SOURCE完全一致；文件字节差异来自metadata。

`EvidenceNet/scripts/vldocir_reading_backbone.py`要求reading_ready、完整assignment覆盖、端点/文章一致性与DAG检查后，才导出NEXT及其严格逆关系PREVIOUS。

因此正确描述是：**已有部分真实阅读顺序提案，完整验证和导入尚未就绪。**
不能说项目没有NEXT，也不能将633条提案直接当作已验证完整骨架。尤其不能因为某node没有冻结语义边，就断言它在最终pipeline中没有任何可走的边。

## 5. 一跳发现实验的解释边界

1. 所有Top10实际node都有探索资格，不根据gold选取有利seed。
2. 目标允许位于初始候选之外；路径必须来自seed的真实邻接表，而不是全图edge榜。
3. 不沿用旧一跳实验按目标dense分数先截每seed前2个邻居的限制，否则可能提前丢掉弱相似桥接节点。
4. 目标原文用共同评分器重排，不继承seed分数，也不因连边自动加分。
5. 分别记录Top10外新node、Top20外新node、新page、最终证据及其路径。
6. 官方gold是page级，不能将该页全部node标为正确证据。片段正确性、噪声和充分性仍需复核。
7. NEXT同页也可能改善定位；页面Recall不变不代表它对原文定位无作用。
8. 增加相同候选检查数量的dense扩召回对照，区分图贡献与多检查候选的贡献。

本文件是源身份与当前可用子集审计，不是检索提升报告。
