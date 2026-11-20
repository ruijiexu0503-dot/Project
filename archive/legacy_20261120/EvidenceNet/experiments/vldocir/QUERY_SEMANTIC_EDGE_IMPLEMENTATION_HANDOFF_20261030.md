# Query 如何使用语义 Edge：背景、现状与代码实现交接

更新时间：2026-10-30。面向接手代码实现的模型或开发者。

**文档状态：实现方案，尚未实现或验证本文的新算法。** 本文核实了现有代码和冻结结果，明确了下一版应修复的问题及实验要求。不要把建议、示意例子或建议配置当成已经取得的实验结果。编写本文没有提交新任务。

## 1. 用户真正希望实现什么

完整 EvidenceNet 流程是：

```text
原始文件/网页/PDF
  → Dolphin 解析、版面与阅读顺序
  → EvidenceNode 生成（文字、表格、图片、公式及必要上下文）
  → 离线候选 pair 召回与关系核验
  → 稀疏语义 edge + 原文锚点 + 关系描述 + 离线 embedding
  → query 检索 Top10 实际 node
  → 从这些 node 沿有用的 edge 查找证据
  → 核验并组合原始证据
  → 输出充分、精准、尽量短的来源片段
```

用户的核心设想：初始排名第 10 的 node 可能是入口，沿它的 edge 能找到初始排名很靠后的真正证据，并使该证据进入最终优先结果。**Edge 自己具有语义，query 应该利用“为什么 A 连到 B”，而不只是利用邻接关系。**

明确约束：

- Node、edge、edge 描述与向量提前离线建立；在线允许编码 query/子需求，不允许为每个 query 重建语料或全图 embedding。
- 关系描述采用开放自然语言，不要求全部归入固定关系类别。用户此前提出一句话描述，以减少冗长、泛化和语义稀释。
- 以 Top10 **实际 EvidenceNode** 为入口，所有 10 个都能提出路线；不能只从排名第一或已选入最终文本的节点扩展。
- 图保持稀疏。用户接受“每个 node 召回候选、核验通过才建边”，不要求每个 node 必须有边，更不要求全量 N² 建边。
- 搜索路径需要可追踪：从哪个 seed、沿哪条边、为什么访问、访问后是否有收益、最后保留了什么。
- 本阶段到文本证据选择即可，不必运行最终回答 LLM。评估输入是否充分、精准、少噪声及少 tokens。
- 后续与 VL-DocIR/HF 对照；同 query、同检索库、相同指标才可比较。
- 旧输入、预测、部署包和结果保持冻结，新方法使用新目录、新版本与新 manifest。

本轮先复用已有 node/图隔离查询阶段问题。**这不意味着完整 pipeline 删除了 node generation。** 原始文件到图的端到端重跑应作为后续独立实验。

## 2. 为什么需要这次修改

应把三个判断分开：

1. **关系是否真实：** A 与 B 的原文是否支持这条关系？主要在离线建边阶段核验。
2. **路线是否有用：** 对当前 query 和已有证据，沿 A→B 能补充什么？在线决定。
3. **证据是否充分：** 最终选出的原文能否共同满足问题？在线来源核验与选择决定。

离线关系成立，不代表它对每个 query 都有用。导航有用，也不代表目标节点单独就能回答问题。Query 与 edge 向量相似，更不证明原文事实成立。

当前实现曾在几个阶段丢失这些区别：

- 二元 `covers` 把部分支持当成完整覆盖，具体年份/数值等必要证据被跳过。
- Bridge 不直接回答问题，因而没有 coverage gain，既不能继续走，也不能贡献最终选择。
- 旧 edge embedding 方案用边引入页面候选，最终仍对 query–page 独立排序，丢失了关系解释与联合支持。
- 新 adaptive v2 虽有带状态的导航框架，却没有接入已生成的关系描述。
- “证据够回答”与“证据已经足够短、直接”被当成同一个停止条件。

目标是让 query 评价完整路线：

> 已经找到 A，依据有来源的关系 R 去 B，能补充哪项证据或必要上下文？访问后，哪些原文需要共同保留？

## 3. 已有结果：哪些能下结论，哪些不能

### 3.1 数据与图的范围

- 当前开发 pilot：24 个 query、518 页；已有节点文件含 7,291 个 node，历史编码覆盖数量与原始节点数存在差别，重用时以 manifest/ID 校验为准。
- 旧核验导出 213 条 RELATED proposal，其中本轮冻结使用 187 条语义 proposal；17 条 reference review 和 9 条 administrative review 单独分流。
- 187 条是模型关系提议，不是 187 条人工确认的金标。
- 冻结语义图较稀疏。旧一跳实验仅 7/24 题得到 12 个 Top10 外的 query–node 候选；新版两跳范围仅 1 题有额外第二跳节点，最大范围为 16 个 node。
- 当前查询实验未导入 NEXT/PREVIOUS 阅读顺序层，上游记录为 `reading_ready=false`。不能把本轮称为完整阅读顺序图实验，也不能把待处理 NEXT 提议直接当成已验证边。
- 24 题被反复检查，只适合作为开发回归集，不能宣称 held-out 泛化效果。

### 3.2 重要实验摘要

| 实验 | 已核实结果 | 可以说明什么 |
|---|---|---|
| 旧 span selection：Top10 5218190，固定池 5218191 后由 5218364 续完 | 两组最终各 24/24；固定池 Q1/Q2 在 24×4 预算共 96 个结果上文本完全相同；Top10 各 arm 也相同 | 当时的边使用机制没有改变最终输入；不等于所有语义边方法无效 |
| 固定池 1024 tokens：Q0 排序 vs Q1/Q2 覆盖选择 | 平均文本 776.75→369.875 tokens；宏平均 gold 来源页覆盖 79.17%→60.42%；gold 页对命中 30/40→21/40 | 输入变短并不自动意味着降噪，可能删掉必要证据；这些是事后来源页指标，不是官方 Recall@k/AP 或答案正确率 |
| Adaptive v1：5219198/5219199 | 未完整通过支持协议；出现重复需求、额外需求及字面字段校验问题 | 为 v2 提供工程修复依据，不能当作完整导航效果实验 |
| Adaptive v2 fixed：5219501，A2063G | 25m42s，退出 2，`partial_validation`；1024 预算选 837 tokens，含 2019=75.2、2024.1–3=81.4 的表格 | 修复了一项真实选择遗漏，但不是 edge 带来的增益；仍有 17 个 packet–requirement 校验未完成 |
| Adaptive v2 navigation：5219502，Ce4f | 10m03s，退出 2，`partial_validation`；1024 预算选 998 tokens；初始 seed 被判充分，`selected_sources_sufficient`，没有 navigation 调用 | 不能用于断言语义导航有效或无效；3 个不同 packet–requirement 未完成，跨 arm 重复报告为 9 条 |

现有两个 v2 job 都保存了选择结果，不是 GPU 启动失败或这次因超时未生成结果。Job 结束也不等于实验通过校验。

### 3.3 真实错误例子

- **A2063G：** 旧选择只留总体 76.6% 和上升趋势，丢掉问题要求的两个年份具体率。表格本来在候选里；这是选择问题，不能记为 edge 救回。V2 已在 1024 预算保留表格。
- **Federer 2004/2005：** 单赛季表格及相邻年份导航文字被误当成两个赛季的完整结果，明确的 2004、2005 正文被排除。原候选具备证据，预算也放得下。
- **Graf：** 仅 Barcelona 银牌片段被误判覆盖完整奖牌及年份，遗漏金/铜牌和 1988 年原文。
- **Ce4f：** 需要区分材料、轨道及属性归属；不能将同句中的 V3d/O2p 延展态属性错归给 Ce4f。最新 seed 已有较充分原文，不应为了表现边有用强行宣称救回。

Packet ID 是实验内标识，不同版本可能改变；跨版本用 node/member/source hash 对照，不要靠 P013/P015 等短 ID 直接拼接。

### 3.4 HF 对照的真实范围

已有同一 24-query/518-page 库上的 ColNomic-7B 原图检索结果，可以复用。它不是作者官方全库逐题结果，不是 Ctx/Rerank/Ensemble，也没有评价最后给 LLM 的段落输入。

| 问题 | 本地 ColNomic gold 页排名 | 旧无 edge `hybrid_visual` gold 页排名 |
|---|---|---|
| Federer 2004/2005 | 6、4 | 1、12 |
| A2063G | 1 | 2 |
| Graf | 1、2 | 1、3 |
| Ce4f | 2、5 | 1、2 |

这些是页面排名，不能当成 Top10 node 排名。来源、复算与 AP@5 见 [ColNomic 诊断记录](COLNOMIC_DIAGNOSTIC_CASES_20261030.md)。后续需要查官方定义时使用 [VL-DocIR 数据集](https://huggingface.co/datasets/anonymous-8421/VL-DocIR) 和 [ColNomic 模型](https://huggingface.co/nomic-ai/colnomic-embed-multimodal-7b) 的当时版本；本文不替代官方评测协议。

## 4. 已核实的实现问题：先修复再比较

### 4.1 V2 没有接入已生成的关系描述

冻结文件：

```text
migration/query_adaptive_v2_smoke_5219501_5219502_20261030/results/edges.jsonl
```

2026-10-30 实际统计：187 条，全部 `relation_description.status=PENDING`、描述正文为空；`relation_type` 全部为 null。开放关系本身不要求固定 type，**关键问题是描述为空**。

`run_query_adaptive_evidence_v2.py::prepare()` 读取 `DIAG/edge_records.jsonl`，直接复制 `relation_description`，没有关联 `description_predictions.jsonl`。

旧 `run_vldocir_edge_embedding.py::_encoding_rows()` 已实现按 edge ID、input hash 关联描述并编码；不能说过去从未实现 edge embedding。接手者应复用/提取其校验逻辑，不能只把字段名加到 prompt 就认为语义已接入。

已有描述资产：

| 文件 | 实际状态 | 使用要求 |
|---|---|---|
| `migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/description_predictions.jsonl` | 187 条；186 条 valid DESCRIBED，1 条 valid INSUFFICIENT | 可作为 legacy 描述回归输入；valid 表示通过协议，不表示语义真值已核验 |
| `migration/horeka_verified_results_20261028_2MN9rZZ0/bounded/description_predictions.jsonl` | 153 条；29 条 valid DESCRIBED，124 条 invalid | 不是完成的 187 条新版描述集，不能当成完整替换，也不能静默混用多个描述策略 |

新预检必须输出描述覆盖、版本、缺失/失败/INSUFFICIENT 数量及实际送入编码/导航的比例。语义 arm 遇到全空描述应立即失败，不能跑完后仍标为“semantic edge”。部分不足时采用预先声明的 endpoint fallback，并明确标记；同时报告完整样本与有效描述子集结果。

### 4.2 背景观察与支持事实的协议冲突

V2 的失败重试均出现 `status=missing` 却填写非空 `facts`。模型把“文中提到研究时期，但没有分年数值”放入 facts，验证器将 facts 解释为正向支持。

建议新协议明确区分：

- `support_facts`：带原文 span ID 的直接或部分支持；
- `observations`：背景、范围不符、缺失原因、导航线索，不产生答案 coverage gain；
- `missing`：仍缺少什么；
- `validation_state`：有效/未知/失败，独立于证据的 missing/partial/sufficient。

不要把 missing 自动升级 partial，也不要把异常吞掉后当成“确定没有证据”。保留 raw output；若迁移旧输出，必须保存明确的规范化记录，不覆盖原结果。

### 4.3 充分性审查不稳定

A2063G 在 1024 预算被判充分；2048/4096 仍保留同一数据表，却因“2024.1–3 没有明确写 first quarter”被降为 partial。

需要允许来源可核实的等价表达，并保存规范化依据。日历年第一季度与 1–3 月可等价，财政季度等例外不能无条件套用。数字、单位、主体、统计口径不能被模糊匹配替换。

更大预算不应仅因加入无关上下文而丢掉已有支持结论，但若新来源真实揭示矛盾，应记录冲突，不能机械强制充分性单调。

### 4.4 输入 tokens 与 prompt 上限检查错误

`Broker.call()` 使用 `len(tokenizer.apply_chat_template(...))`。实际 Horeka tokenizer 返回带 `input_ids`/`attention_mask` 的 BatchEncoding，len 为 2，导致固定组 89 次生成计 178 输入 tokens、导航组 31 次计 62。

必须按实际 input_ids 长度计数，覆盖 list、Mapping/BatchEncoding、tensor 及批量维度；同时修复 24576 prompt 长度检查。计数应与实际传给模型的 chat template、特殊 token、thinking 配置一致，避免重复套模板。

最终证据文本 tokens 由另一个 encode 路径计算，不能因此否定 837/998 的文本计数。历史成本文件保持原样；如重算，输出带版本的新审计文件。

## 5. 建议的新架构

```text
离线：两端原文 + 必要上下文
       → 关系核验/描述 → 稀疏图 + 来源锚点 + edge 向量

在线：query → query-only 最小证据需求 → 原始 node Top10
                                              ↓
                              已有证据、未满足需求、所有 seed 的邻边
                                              ↓
                         query/需求匹配 edge 语义 → 路线优先级
                                              ↓
                             访问目标原文，有限预算内继续下一跳
                                              ↓
                         单段支持 + 有来源的跨段联合支持核验
                                              ↓
                          最小充分原文组合、来源、路径及成本记录
```

### 5.1 离线 edge 表示

建议采用“一句具体关系 + 结构化来源约束”，而不是把两个长段落全部复述一遍。

- 关系句说明共同对象、双方不同角色，以及实际连接依据。
- 句子短，但不能为满足字数限制删掉否定词、不同年份、不同材料或测量口径。
- 实体、年份、单位、scope 等属性是来源约束，不是重新引入固定关系类别。
- 附双方原文 span/member ID、offset、source hash、描述模型与 prompt/profile hash。
- 保留 limitations/uncertainty；没有充分关系依据时输出 INSUFFICIENT，不强编句子。
- A→B 与 B→A 可以保存不同导航视角：去找具体数据、去找定义或身份上下文等。这表示导航用途，不自动表示因果方向。双方原文不支持的用途不能凭空生成。

以下仅为**建议数据契约**，不是当前文件已具有的完整 schema：

```json
{
  "edge_id": "stable-id",
  "source_node_id": "A",
  "target_node_id": "B",
  "description": {
    "status": "DESCRIBED",
    "text": "A reports an overall trend; B provides year-specific measurements from the same study.",
    "limitations": "",
    "profile": "versioned-profile",
    "input_sha256": "...",
    "prompt_sha256": "..."
  },
  "anchors": [
    {"node_id": "A", "member_id": "...", "start": 0, "end": 20, "source_sha256": "..."},
    {"node_id": "B", "member_id": "...", "start": 10, "end": 40, "source_sha256": "..."}
  ],
  "navigation_views": [
    {"from": "A", "to": "B", "text": "Find the year-specific measurements."},
    {"from": "B", "to": "A", "text": "Find the study-level interpretation."}
  ]
}
```

示例假定原文支持该关系，不代表当前图中已经有这条边。读取旧数据时应明确适配字段，不直接假设旧 JSON 符合此 schema。

### 5.2 Embedding：分清关系与端点信息

最低实现要求：

1. 保留 endpoint-only 表示作为对照。
2. 为关系句与必要的端点身份/角色建立离线表示；避免长端点文本淹没关系句。
3. 保存实际编码文本、模型 revision、query instruction、tokenizer、pooling、维度、归一化方式及 hash。
4. 在线 query 与 edge 向量必须使用兼容的 embedding 模型和预处理。不能直接将历史 0.6B query 向量与 8B edge 向量点乘。
5. 如采用 relation-only 与 pair+relation 两种表示，分别命名并记录，不在同一实验内无记录地替换。

第一版建议复用旧 pair+relation 编码路径完成正确接线，冻结为一个配置；“更短的独立关系表示”另作表示消融。新导航视角文本与旧 AB/BA 文本排列不是同一个概念，需要区分。

### 5.3 Query 规划

- 只给 query，冻结最少、非冗余的原子需求；规划器不能看到 gold、候选答案或未来目标原文。
- 对两个年份/材料分别保留所需证据及身份约束；比较关系需要联合检查，但不重复要求已收集的同一数值。
- 不为问题添加其未要求的方法、光谱、因果解释等任务。
- 需求状态是 missing/partial/sufficient/unknown 等明确状态；unknown 是校验未知，不是负证据。
- 初始 query 及 query-derived 需求可在线编码。后续如使用剩余缺口文本编码，要记录其来源和内容，不允许臆造目标答案。

### 5.4 从 Top10 出发的语义导航

保留所有 Top10 seed 的扩展资格。路线以 `(source_node, edge_id, target_node)` 为单位。

廉价筛选后，再对有限候选判断：

> 给定 query、尚缺的需求、当前原文支持、关系描述和两端原文锚点，沿这条边能补什么？

建议路线输出：

- `action`: follow/reject；
- `expected_requirement_ids`: 预期帮助哪项需求；
- `expected_gain`: 直接证据、必要上下文或有依据的下一跳线索；
- `source_anchor_ids`: 为什么有这个预期；
- `constraint_checks`: 实体、时间、单位、属性归属等；
- `reason` 与 uncertainty。

这些是导航决策字段，不是限制离线关系类型的固定 taxonomy。预期收益与访问后验证的实际收益必须分开记录。

约束：

- 向量相似度是筛选信号，不直接当真实性、coverage 或最终排名加分。
- 目标已有直接证据与“值得走过去核查”是不同条件；bridge 可以暂时没有答案支持。
- Bridge 需要可核查的下一步依据，不能靠模型想象未存在的边。
- 只有 shared entity/topic 不足以放行。年份不同、主体不同、背景重复应记录具体原因。
- 已访问节点不重复读取；但到达同一目标的不同来源路径可具有不同解释价值，应保留 route provenance，不因 node 去重丢失联合支持依据。
- 全局 edge 检索入口若需要试验，另设 arm；不要与 Top10 局部导航混合后把收益都归因于边语义。

第一版建议最多 2 跳，节点暴露预算沿用可配置上限 40，保留现有 512/1024/2048/4096 最终输入预算。这些是开发起点，不是最优参数结论。超过预算应记录被截断的路线及原因，不静默跳过。

### 5.5 关系参与联合证据排序

旧做法的缺口：边将 B 召回后，如果只独立计算 query–B 分数，A 提供的主体/年份/解释信息可能再次丢失。

应显式检查小规模证据组合：

```text
来源 A 的必要上下文 + 来源 B 的目标内容
  → 是否共同满足一项需求？
  → 是否存在主体/年份/单位冲突？
  → 哪些原文可以删除，哪些必须保留？
```

- 独立支持与联合支持分别记录。
- 联合核验必须引用所有必要原文，不能把生成的关系句作为事实证据。
- 每组必须检查带来的新增支持及代价，不能因为有边就整体加分。
- 未连接的两个原文仍可能共同回答问题，无边组也要具备基本的多来源组合能力；不能故意削弱 baseline。
- 组合数量受预算约束，优先检查实际访问过的路线与共同需求，避免在线 N² 组合。
- 若实施评分公式，先冻结权重并保留各分项；没有验证前不要声称某组系数有效。可先采用“有效支持→新增需求/必要上下文→原文成本→确定性 tie-break”的可审计排序。

### 5.6 最终原文选择与压缩

搜索访问集合与最终证据集合分离。Bridge 可以用于导航但不进入最后文本；若其提供不可缺少的身份/范围信息，则保留对应最短原文。

现有 v2 最终仍选择 whole packets，span ID 主要用于引用校验。不能将它称为已实现精确 span 压缩。

分两步实现，避免混淆收益：

1. 先固定 whole-packet 表示，验证语义边是否改变访问和正确支持；
2. 再加 span/table-aware 选择，所有对照组使用相同压缩器。

压缩要求：

- 输出原文，不用生成的摘要替代证据。
- 保留引用 offset 与 source hash；非连续片段明确分开，不拼成看似连续的原句。
- 表格保留必要标题、表头、单位、行标与数据单元格；不能只选孤立数值。
- 文本保留必要指代、否定、年份、对象及限定词。
- 图片/公式若需要视觉才能判断，应显式记录该能力范围；本轮纯文本 packet 不等于完整多模态验证。
- 最终集合重新核验，压缩后缺少约束时补回原文或报告不足。

### 5.7 停止条件

分开评估两个目标：

- **找齐证据：** 没有足够来源时沿有依据的路径探索，直到充分、无可走路线或预算耗尽。
- **精简证据：** 已充分后，可选地使用小预算寻找同样充分但更短、更直接的替代来源。

默认先实现第一种，精简探索作为单独开关与消融。不要强迫每题走边，更不能用是否走边本身衡量成功。充分性仍有 unknown 时不得假装已完整解决。

## 6. 实验设计：分开验证每个变化

### 6.1 第一阶段：修复接线与运行可靠性

- 修复描述关联、来源/hash 校验、tokens 计数与缺证据协议。
- 冻结新版本输入，确认非空关系实际出现在导航请求/编码文本中。
- 复跑 A2063G 与 Ce4f 做来源选择回归。
- 增加可控的小型合成图测试导航逻辑：例如 rank10→目标、桥接两跳、错误年份、循环、双路径到同节点。合成测试只证明代码行为，不计入真实检索指标。
- 如果真实图下没有可收益路线，明确报告不可达，不根据 gold 临时加边。

### 6.2 第二阶段：固定图和表示，测试边语义

建议分组如下；具体预算在运行前写入配置：

| Arm | 访问/导航 | 最终支持核验 | 用途 |
|---|---|---|---|
| A：无边 dense | 相同 seed10，按原始 dense 次序扩展至匹配暴露量 | 相同单段及基本多来源核验 | 对照增加普通检索预算 |
| B：endpoint 导航 | 同一图、seed 和路线预算；不提供生成的关系描述 | 相同基础核验 | 对照“仅邻接+端点信息” |
| C：semantic 导航 | B 的输入基础上加入有效关系描述/向量 | 与 B 相同 | C−B 隔离关系语义对访问的作用 |
| D：semantic + 路径联合核验 | 与 C 冻结相同访问结果 | 额外核验实际路径提出的来源组合 | D−C 检验保留关系上下文是否改善选择 |

注意：B 可能从两端原文本身推断关系，因此 C−B 是显式离线描述的增量，不是“有无任何关系理解”。为隔离编码作用，可再做固定访问集合的 description on/off 核验，但须另名。

公平性要求：

- 相同 query、语料、seed、模型、最终预算、输出粒度和 gold 定义。
- 目标锚点即使只展示给导航模型、最后被拒绝，也算信息暴露。匹配实际暴露的不同节点数，并另外报告 tokens/调用成本；相同节点数不等于相同成本。
- 不把全量候选一次展示给某 arm，再称它只访问了选中节点。
- 缓存只能复用真正完全相同的输入；含不同上下文的模型调用不能共享“评估结果”。
- 查询失败不能从分母中静默删除；分别报告全体覆盖、完成率与完整子集质量。
- 一句话描述策略、长描述策略、扩大图、NEXT、实体节点、全局 edge 入口、换 embedding 模型应各自做消融，避免一次全部更换而无法解释收益。

### 6.3 需要报告的指标

1. **运行完整性：** 处理数、完成数、未知/失败数、各阶段重试、描述覆盖与 fallback。
2. **可达上界：** gold 来源页/独立标注证据是否在初始 seed、允许跳数内、全图中；区分无边可达与排序未选。
3. **导航收益：** 新访问目标、核验后新增证据、错误主题/年份路线；哪些证据是 dense 基线没有选到而沿边找到的。
4. **排序收益：** 固定页级映射及 tie-break 后的 Recall@5/10、AP@5/10、nDCG 等；保存每题排名。若未产生页面排名，不冒用 AP 指标。
5. **文本证据质量：** 必要事实及约束是否保留、充分题数、错误支持、冗余与不相关原文。页面 qrels 不足以自动证明段落准确，需要独立审查或人工标注。
6. **输入与总成本：** 最终文本 tokens，导航/核验输入输出 tokens，模型调用与生成耗时，冷运行与缓存命中成本分开。
7. **压缩收益：** 在同等证据充分性下比较 tokens，不能只报告平均文本变短。

已读的 24 题继续作为回归；新标注测试单独存放，冻结后再运行。没有最终回答模型时，不报告答案准确率提升。

## 7. 必须保存的搜索路径与输出

每个 query 至少保存：

```text
query 原文、query-only 需求及版本
seed10 与原始 node rank
每个 hop 的 frontier、预算及候选截断理由
source/edge/target ID、实际关系描述及版本、原文锚点
query-edge 分数、来源/目标分数及其模型配置
路线决策、预期补充需求、采用/拒绝理由
访问后的原文支持判定、实际新增支持、矛盾/未知状态
所有暴露节点、访问节点、最终选中节点/片段
联合支持的 source span IDs
最终原文与 tokens、每阶段成本和缓存情况
停止理由、异常、raw model outputs、输入与配置 hash
```

路径可视化要能区分“模型预计有帮助”与“读完确实有帮助”。显示 seed 的初始排名与最终证据位置，支持打开原文，展示被拒绝路线；不要只画最终成功路径。

建议新输出结构（尚未实现）：

```text
output/query_semantic_edge_v1_<date>/
  manifest.json
  edges_with_descriptions.jsonl
  embedding_manifest.json
  prepared_queries.jsonl
  calls/<query_id>/...
  predictions/<arm>/<query_id>.json
  traces/<arm>/<query_id>.json
  selected.jsonl
  metrics.json
  status.json
  diagnostics/index.html
```

## 8. 代码与数据入口

以下路径相对 Project 根目录。优先阅读现有实现，再决定提取公共模块还是新增版本文件。

| 路径 | 用途 |
|---|---|
| `EvidenceNet/scripts/run_query_adaptive_evidence_v2.py` | 当前 prepare/check/infer/report、请求缓存、导航循环、任务断点；描述接线和 tokens bug 在这里 |
| `EvidenceNet/scripts/query_evidence_policy_v2.py` | Query-only plan、assessment、来源核验、frontier、whole-packet pack |
| `EvidenceNet/scripts/run_vldocir_edge_embedding.py` | 已有描述关联/hash 检查、离线 edge embedding、query-edge 评分；不要重复造不兼容格式 |
| `EvidenceNet/scripts/build_reader_anchor_ablation.py` | ROOT/SOURCE/DIAG/MODEL/BUDGETS、packet 渲染及来源基础 |
| `EvidenceNet/scripts/run_span_evidence_selection.py` | span ID/原文映射与历史选择流程 |
| `EvidenceNet/scripts/run_query_evidence_selection.py` | 模型/tokenizer、prepared 校验、通用 IO |
| `EvidenceNet/evidence_graph/llm_client.py` | 模型调用与实际 chat 模板处理，修 token 计数时需对齐 |
| `EvidenceNet/tests/test_query_adaptive_v2.py` | v2 回归测试入口；检查其他关联测试，不因旧测试通过就默认新语义正确 |
| `migration/vldocir-edge-20261022/results/nodes.jsonl` | 原 node/member/source 数据 |
| `migration/vldocir-edge-20261022/results/search/query_window_scores.npy` | 旧冻结 node 检索所用 window 分数；历史 query encoder 为 0.6B，不能与 8B edge 向量混用 |
| `migration/vldocir_trace_inputs_20261023/` | 查询、来源单元、windows 和评估 gold；gold 只供独立 evaluator 使用 |
| `migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/` | 187 条图、legacy 描述等输入资产 |
| `migration/span_results_5218364_20261030/query_span_selection_20261030/` | 24 题固定候选与完整旧结果 |
| `migration/span_results_5218190_20261030/top10_span_navigation_20261030/` | 24 题初始 seed/ranking/历史导航输入 |
| `migration/query_adaptive_v2_smoke_5219501_5219502_20261030/` | 最新冻结结果、请求、日志与 SHA；诊断不需要再次 SSH |
| `EvidenceNet/output/span_edge_audit_20261030/` | 历史失败例子、页级代理指标、ColNomic 逐例对照 |
| `EvidenceNet/output/vldocir_colnomic_7b_20261016/` | 本地 ColNomic 同库评分 |
| `EvidenceNet/output/vldocir_colnomic_horeka_20261016/` | 第二份同库 ColNomic 评分；不能拼接不同 run 的最好结果 |
| `migration/horeka-query-adaptive-v2-20261030/` | 最近部署脚本参考；新版本使用新目录，不改旧部署 |

建议阅读顺序：本文 → [最新 v2 smoke 结果](QUERY_ADAPTIVE_V2_SMOKE_RESULTS_20261030.md) → [query 使用审计](QUERY_USAGE_DETAILED_AUDIT_20261030.md) → [原 edge embedding 交接](EDGE_EMBEDDING_HANDOFF_20261025.md) → 相关脚本。

其他参考：[完整 span 结果](SPAN_EDGE_RESULTS_20261030.md)、[v2 修复说明](QUERY_ADAPTIVE_V2_REPAIR_20261030.md)、[一句话描述策略](SENTENCE_EDGE_DESCRIPTIONS_20261028.md)、[bounded 描述策略](BOUNDED_EDGE_DESCRIPTIONS_20261028.md)。旧文档保留历史状态，遇到冲突以本文明确核实的状态及冻结原始文件为准。

## 9. 推荐实施顺序与验收

### P0：正确性与数据接线

- 检查仓库现有改动及适用 AGENTS.md，保留用户和其他版本文件。
- 建立新版本；关联描述时验证 ID、input hash、profile/prompt hash，拒绝重复、错配和静默过期缓存。
- 修复 token 计数/长度保护；在实际 tokenizer 环境验证。
- 分离支持、背景观察和校验未知；修复已知季度等价与属性归属回归。
- 预检证明导航请求包含有效描述，manifest 记录其来源。

### P1：语义导航

- 实现所有 Top10 seed 的路线候选、query/缺口匹配、有限跳数与预算。
- 记录完整路径、被拒绝候选、实际暴露及 fallback。
- 先做可控图逻辑测试，再跑真实 smoke；没有收益也应如实输出。

### P2：联合支持与精准输入

- 在固定访问结果上测试来源组合核验，避免与导航变化混淆。
- 先 whole-packet 后 span/table-aware 压缩；各 arm 同等能力。
- 输出可点击原文的逐例诊断可视化。

### P3：完整对照

- 完成 24 题回归并保留失败分母，再用单独冻结的新样本验证。
- 统一页面排名协议后复用 ColNomic 分数比较；全库扩展另做资源与覆盖规划。
- 若语义导航受图覆盖限制，另开建图覆盖实验，禁止按 gold 补边制造召回提升。

最低有意义的测试：

1. 非空描述确实影响准备输入；全 PENDING 的 semantic arm 预检失败。
2. 描述 input hash 错配、重复 edge、无效 source offsets 被拒绝。
3. BatchEncoding/tensor/list token 长度正确；超限 prompt 在推理前阻止。
4. `missing + observations` 合法但不产生支持；校验失败保存 unknown。
5. Rank10 seed 能提出路线；bridge 可继续第二跳而不强制进入最终证据。
6. 错年/错实体/仅同主题边不因相似度高就获得最终支持。
7. 多路径到同一目标只读取一次，但不丢失必要来源组合。
8. 联合支持必须有全部必要原文；移除关键表头/年份后不能仍判充分。
9. 两端没有描述时对照行为一致；描述缺失不能冒充 semantic 成功。
10. 预算、暴露计数、循环终止、断点恢复、缓存身份和重复提交保护正确。

不要求断言“真实实验必须提高指标”；验收应保证方法确实运行、来源可靠、比较公平、结果能解释。

## 10. Horeka 部署与任务执行注意事项

本地 Project：

```text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
```

Horeka 用户名始终是 **dv3352**，Project：

```text
/hkfs/home/project/hk-project-p0025545/dv3352/Project
```

最近 v2 远端目录：

```text
/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs/query-adaptive-v2-20261030
```

- 用户偏好尽快开始，曾使用 `dev_accelerated`、4 GPU、45 分钟；这是旧配置，不保证当前分区可用或立即开跑，应查看实际调度数据。
- 最新模型路径为 `external/models/Qwen3.5-35B-A3B`；检查实际部署配置，不把它与 embedding 模型混为一谈。
- 本环境此前能直接读取 `/hkfs` 下结果；先尝试本地可读路径，不要反复要求用户登录。
- SSH 共享连接属于建立它的主机；hk2n1989 与 hk2n1990 的 `/tmp` socket 不一定共享。用户在另一个终端已登录，不代表当前进程一定可复用。
- 密码/OTP 只由用户在终端输入，不要求发送聊天。不要把历史 OTP 写入脚本。
- 新代码和预检先完成，再部署带 SHA 的新包；拿到真实 `SUBMITTED` JobID 才说已提交。
- 旧 `submit_smoke.sh` 有幂等保护，已记住 5219501/5219502，再执行通常返回 EXISTING；它不是新版本重跑命令。新版本使用新目录，避免覆盖旧 job_id/intent。
- 软时间预算需给加载、保存和退出留余量；缓存按真实模型配置和完整输入标识，修 prompt/schema 后不得复用旧“valid”结果跳过新验证。
- 报告区分 Slurm 完成、程序处理完成、协议完成、质量指标；不要将它们合并为“实验成功”。

## 11. 可以直接交给下一模型的任务说明

> 请先阅读本交接文档与适用的仓库说明，检查实际文件和现有工作区改动。实现一个新的、独立版本的 query-semantic-edge 实验：先修复描述没有接入、token 计数和支持/背景协议，再实现从所有 Top10 node 出发的语义路线排序与有来源的联合证据核验。复用已有离线描述、图、embedding 代码和冻结候选，保留旧实验不变。不要按 gold 生成 edge，不要假定当前 187 条描述已接入或已人工核验。先完成可复现的本地预检/测试与真实小样本回归，再按本项目已有授权和可用环境准备/提交对照任务；只有实际取得 JobID 才报告提交成功。产出代码、版本化 manifest、完整路径记录、来源可追踪的最终文本、真实成本和逐例可视化。当前只做到证据选择，不运行最终回答 LLM。分别报告导航召回、联合支持、文本充分性、压缩和页级指标，不能用更少 tokens 代替质量提升。

接手后如调整方案，记录改变、理由及实验版本；本文的建议参数可以在实验前修改并冻结，但已核实的历史结果不能重写。
