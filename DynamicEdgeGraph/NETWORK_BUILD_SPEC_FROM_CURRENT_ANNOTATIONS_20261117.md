# 网络搭建任务书：基于现有标注的动态 Edge 检索网络

日期：2026-11-17。交付对象：后续实现模型。当前阶段：先补齐网络、数据接口与验证，等待数据集准备完成后启动真实训练。

本文根据当日工作区中的标注、网络源码与数据报告编写。本次只交付 Markdown，没有修改实现代码、执行模型测试或启动训练。下文的接口与验收项是实现要求，不是已完成结果。

## 1. 任务目标与完成边界

实现一个最终只返回有序 Top-K 节点的检索网络。目标情形是：某个相关节点在 Dense 中排第 40，但可以从初始检索节点经过一条或多条合法边到达；系统在有限预算内发现它，再判断它对当前问题和已选结果的新增价值，使其有机会进入 Top-5。

默认架构为：

**冻结基础编码器 → 可训练节点投影 → 有向基础 Edge 向量 → Query / 已选集合条件化的动态 Edge 向量 → 目标级统一排序 → 逐步选择互补的 Top-K。**

多跳候选由独立搜索控制器提供。网络不负责生成最终答案，也不需要先学习一条唯一正确路径。第一版使用小型 MLP 模块，不添加 RL、全库深层 GNN、路径 Transformer 或必经 clustering。

本阶段的交付是“网络可接入训练”，不是“已经训练成功”。必须分别报告：

| 状态 | 含义 |
|---|---|
| NETWORK_READY | 模块、接口、合成测试、梯度、保存加载和预算接入通过验收 |
| DATA_READY_FOR_FIT | 真实输入、划分、候选、有效正负监督、表示与图达到训练条件 |
| TRAINING_COMPLETED | 后续真实训练实际完成，有曲线、有效样本和 checkpoint |
| RETRIEVAL_GAIN_VERIFIED | 后续独立评价验证了收益与成本，且完成必要消融 |

现在可以完成第一项并生成第二项的缺口报告。缺少真实向量或负例时，仍应完成不依赖这些资产的模块；不得用“等数据”代替网络搭建，也不得填造数据来宣布训练就绪。

本任务书细化并更新[上一版实现任务书](IMPLEMENTATION_HANDOFF_DYNAMIC_EDGE_SMALL_DATA_20261114.md)中的网络搭建部分。真实训练与实验仍分阶段进行；若旧文档的资产状态与本文不同，以重新核对后的实际文件为准。

## 2. 当前真实资产：从这些文件出发

### 2.1 最新 Node-first 标注已存在

主输入：[r3 自动审核导出](datasets/nodefirst_qa_v3_20261117/qa_gold_auto_accepted_r3.jsonl)。

核对依据：[导出汇总](datasets/nodefirst_qa_v3_20261117/gold_export_summary_r3.json)、[确定性验证汇总](datasets/nodefirst_qa_v3_20261117/deterministic_validation_summary_r3.json)、[独立模型二次审阅](datasets/nodefirst_qa_v3_20261117/INDEPENDENT_REVIEW_R3_PASS2.md)。

| 项目 | 2026-11-17 核实状态 |
|---|---|
| Query | 17 条：4 single_node、4 cross_page、9 cross_document |
| 节点证据 | 31 次引用；26 个不同 canonical node；14 个文档 |
| 每题所需节点 | 4 题为 1 个，12 题为 2 个，1 题为 3 个 |
| Claim / span | 50 个 claim、122 个精确证据片段 |
| Claim 支持集合 | 37 个 claim 引用 1 个节点，12 个引用 2 个，1 个引用 3 个 |
| 审核状态 | 17 条 FINAL_ACCEPT_AUTOMATIC；来源为模型审核与确定性检查，不称人工 Gold |
| 必要性 | 导出记录均有 Gold 节点删除后的不完整性审核 |
| 模态 | 当前均为文字证据：27 次 legacy TEXT 引用，4 次新 PDF PARA 引用 |
| 数据划分 | 目录没有正式 train/dev/test manifest，记录没有 split 字段 |
| 当前缺少 | 显式负例、完整替代证据组合、路径/桥接动作标签、独立 A/E 分类标签 |

仅按同题共现文档连通，已经形成 7 组，query 数为 7、3、3、1、1、1、1；文档版本/家族合并尚可能继续减少独立组数。17 个问题不是 17 个完全独立场景。这批材料经历多轮审阅并参与模型设计，默认作为开发与接口诊断集，不随机拆成正式泛化测试。

旧 eligibility 清单是早期状态；r3 有后续逐记录来源和映射审核。适配器应记录有效审计链，不能用旧全局 blocked 覆盖后续已通过记录，也不能因 17 条通过而把全库内容都认定为已审核监督。

### 2.2 已有网络骨架，应增量补齐

代码目录：[dynamic_retrieval](dynamic_retrieval/README.md)。

| 文件 | 已有内容 | 本任务主要补齐 |
|---|---|---|
| [model.py](dynamic_retrieval/src/model.py) | 256 维投影、状态编码、F/G 动态边、route mean、统一 R | 明确输入 schema、candidate mask、分视图、无效输入处理、可复现消融 |
| [losses.py](dynamic_retrieval/src/losses.py) | 逐正例对负例的排序损失 | 正负互斥、温度/有限值校验、按 query 聚合状态、标签来源和空监督处理 |
| [search.py](dynamic_retrieval/src/search.py) | 基础两跳遍历和三种预算 | 独立预算实例、Dense 混合、重复 route 更新、集合选择、准确计费 |
| [build_graph.py](dynamic_retrieval/src/build_graph.py) | 同文档语义近邻与相邻页候选 | 可替换图适配器；不能在网络中硬编码只允许同文档 |
| [test_core.py](dynamic_retrieval/tests/test_core.py) | 3 项基础测试源码 | 扩展为本文列出的行为验收；文件存在不代表测试已通过 |

当前没有完整的 build_states / trainer / retrieve / evaluate 接入链。不要另建一个脱离已有工程的平行项目，也不要直接把初版骨架命名为完整系统。

### 2.3 VL-DocIR mini 是独立数据分支

[当前 P0 目录](dynamic_retrieval/runs/p0_vldocir_mini_20261115/DATA_READINESS.md)已有 128/32/64 的 query 清单、51,471 个 canonical nodes、51,441 个可编码文字视图；406/413 条 evidence 精确映射。主监督与输出仍为 page-level weak supervision。

当前视图仍是 DOCUMENT_CONTEXT + CONTENT 的拼接表示；部分 content 来源为 metadata 的 text_sample，不能宣称已使用完整正文。已提交的 embedding 作业日志记录过缺少 numpy 的失败；本次未发现完成的向量与图产物。执行者应重新检查最新状态，不沿用 README 中“已提交作业”作为完成证据。

两套数据不得混用 ID、向量或 qrels：

- Node-first r3：本任务首要适配对象，主输出单位为 node。
- VL-DocIR mini：保留独立 page 适配器；页级标签不复制成页内所有节点正例。

## 3. 当前监督能训练什么

**没有逐 Edge 标签，也可以训练 Edge embedding。** 目标节点排序损失经过目标特征、route 聚合、G、F 反向传播，更新边向量生成网络。这是目标级监督下的间接学习；多条路线对应同一目标时，无法仅凭该标签认定每条路线都是正确语义关系。

| 监督目标 | 现有数据是否支持 | 初版决定 |
|---|---|---|
| Query → 已审核相关 node | 支持正例；负例不完整 | 主排序目标，负例就绪后训练 |
| 已选 T 后尚缺哪些必要节点 | 支持当前审核组合内的必要性 | 构造条件状态；不能把其他 Gold 当负例 |
| 完整 Gold 集合相对删节点集合更充分 | 有对应模型审核 | 可做诊断；主训练先不用独立集合损失 |
| 单个 node 完整回答多节点问题 | 通常不成立 | 禁止给每个 Gold node 复制“完整可回答”标签 |
| Claim 的局部支持 | 单节点支持关系与联合支持集合有记录 | 保留结构；不能把 joint entailment 逐节点复制 |
| A/E 的完整正负类别 | 尚缺 | 接口预留，loss 与下游使用默认关闭 |
| 哪个桥接动作值得扩展 | 尚缺 | X loss 关闭，先使用确定性调度 |
| 语义关系类别/唯一正确路径 | 不支持 | 不拿 reasoning_type 或聚类 ID 当标签 |

现有 integrative_reasoning.label 有遗留占位状态；最新准入应看有效审核链，不能直接把这个字段作为 relation 分类标签。跨文档或联合证据问题也不自动等于图上必须走两跳的问题。

## 4. 必须先固定的数据隔离与身份契约

### 4.1 推理输入与监督文件分离

推理模型可以读取：

- 问题文本或冻结 query embedding。
- 实际候选节点的规范内容表示、可用 context、类型与来源位置。
- 合法图邻接、候选来源和运行时已知的路径深度。
- 已选择结果 T、已经访问的候选、预算剩余量。

以下信息只在训练适配器或离线评价器使用：

- gold_answer_draft、answer_claims、Gold IDs、Gold spans。
- necessity_reason、node_deletion_results、评审结论与正确性理由。
- 标注生成时的 seed、候选生成/修复痕迹和人工或模型给出的目标位置。

**特别重要：当前 17/17 条记录的 seed.canonical_node_id 都属于 Gold。它是标注采样起点，绝不能用作检索时的初始节点。** 运行时 seeds 必须由 query 的独立 Dense 检索得到。合成图测试可以指定人工 seed；真实候选实验不能借用标注 seed。

answer_claims 中的 claim_text 已含答案信息。它可以构造训练标签，不能直接作为学生网络的“query 子问题”输入。以后若引入 query-only 分解器，必须有独立接口与成本记录。

### 4.2 规范数据对象

实现版本化 schema，至少提供以下对象，字段可用 dataclass 或其他项目惯例表达：

| 对象 | 必须字段或约束 |
|---|---|
| QueryInput | query_id、question、namespace、允许的 query view；不含标签 |
| NodeRecord | namespace + canonical_node_id、document/page、content/context 来源、node_type、content hash、表示可用性 |
| EdgeRecord | source_id、target_id、去重后的 provenance、来源内 rank、结构属性、graph_version |
| RepresentationManifest | 编码器及 revision、维度、view 模式、token/truncation 策略、ID→row 映射与 hash |
| RetrievalState | query_id、selected_ids、visited_ids、frontier、独立 path 记录、state_version、预算账目 |
| SupervisionRecord | query_id、正例节点、可信负例、unknown、审核等级、证据组、标签粒度与来源 |
| TrainingState | query_id、state_id、可见 T、实际候选、P/N mask、aux mask、采样来源 |

完整 canonical ID 联结，禁止按行号、数字后缀、字符串近似或向量近似猜测映射。r2/r3 版本 ID 与原节点 ID 各有作用，不能互换。

从原 canonical node 读取输入，使用 r3 的 source_json 与内容 hash 核对来源。Gold span 用于审核可见性，不能为了让正例容易学习而只给正例截取 Gold 片段；正负节点遵守相同输入策略。

### 4.3 保留 AND / OR，而非扁平化证据

当前 r3 每题可保存一个 audited sufficient bundle，并记录其节点删除审核。对 joint claim，支持节点集合表示联合支持；不能将集合拆成多个独立完整支持标签。

未来允许多个替代 bundle 时，schema 必须显式表达“任一 bundle 足够”与“bundle 内多个节点共同需要”。旧的 Gold 并集减 T 逻辑仅适用于明确的必要节点集合，不能强迫检索所有替代证据的并集。没有正确标注时拒绝生成该类条件监督，保留普通相关性标签。

## 5. 冻结输入表示与 content/context 分路

第一版冻结基础文本/视觉编码器，只训练小型网络。向量维度从 manifest 读取，不写死原始维度；默认投影输出 d=256。

支持两个明确模式：

| 模式 | 输入与含义 |
|---|---|
| split_views | content 与 context 独立编码，独立 mask；可以做 content-only 对照 |
| joint_legacy | 仅有原先拼接后的向量；整体作为一个兼容输入，context 通道关闭 |

不能把 joint 向量从中间切开，声称得到 content/context。当前没有独立 context 时保留缺失，不从 Gold 或答案补写上下文。

默认双视图设计：

- Query 与 content 来自同一兼容基础编码器时共享投影 P；若不兼容，必须有明确的适配器与新实验配置，不能直接做跨空间 cosine。
- context 使用独立投影 Pctx，初始只进入目标排序分支，不直接混进基础 edge 的内容端点。
- F 的端点默认使用 content 投影，降低共同文档标题直接支配边表示的机会；这只是可检验的设计选择，不保证自动学到关系。
- 无 context 的投影结果在投影后按 mask 清零；不能认为输入全零经过带 bias 的层仍等于“缺失”。
- context 分支必须可关闭。比较是否缓解文档主题偏置时，需在相同内容、候选和数据下做消融。

视觉/表格接口保留 representation_kind 与 availability。当前 17 条文字标签无法验收视觉理解；没有可用视觉表示的纯视觉节点不得伪装为正常文字节点。适配器记录 unavailable 及原因，按预先声明规则处理，评价保留分母与排除报告。

现有 embedding 截断可能漏掉证据。读取策略、原文范围和实际 token 范围必须记录；网络无法保证从已经丢失的信息中恢复事实。可见性审核只在监督/评价侧使用，不成为在线识别 Gold 的特征。

## 6. 张量接口：实现时不得自行猜测

符号：B 为本批状态数，C 为每状态候选数上限，S 为已选数量上限，R 为每目标 route 上限，d=256。B 不等于独立 query 数；同题多个状态必须有 query_group_id。

下表是模型逻辑接口；实现可用去重节点表加索引 gather 避免内存复制，但对外行为必须等价。

| 输入 | Shape | 约束 |
|---|---|---|
| query_embedding | [B,Dq] | 无答案；与 manifest 一致 |
| selected_content | [B,S,Dc] | T 中节点；不是全部 visited |
| selected_mask | [B,S] | bool；空集合合法 |
| target_content | [B,C,Dc] | 候选去重；不含已选节点 |
| target_context | [B,C,Dctx] | 缺失值有独立 mask |
| context_mask | [B,C] | bool；legacy 模式全 false |
| candidate_mask | [B,C] | bool；padding 不参与选择、loss 或计费 |
| source_content | [B,C,R,Dc] | 每条合法有向 route 的源节点 |
| route_features | [B,C,R,12] | 见第 7 节；不是任意四个数字 |
| route_mask | [B,C,R] | bool；无 route 可以全 false |
| dense_similarity / dense_similarity_mask | [B,C] / [B,C] | 同一冻结兼容空间的 query-content cosine 与可用性 |
| selected_fraction | [B,1] | 已选数量 / output_K，超界应报错 |

供 loss 使用但不得传入模型特征路径的张量：

- positive_mask、negative_mask：[B,C]。
- query_group_id、state_id、监督来源/权重。
- 可选 A/E 分类标签与各自 mask。
- 监督端的必要节点集合、claim 支持集合、可见性与审核记录。

基本校验：

1. P 与 N 不重叠，且均为有效候选；已选节点不能再进入候选或 P/N。
2. route 有效意味着 target 有效、端点存在、source 已由合法过程获得。
3. 有效输入有限；全 padding、无 context、无 route、空 T 都有定义。
4. mask 后的垃圾值不得影响结果。使用 gather/where 或等价安全实现，不能依赖 NaN×0。
5. S 的 padding 规模变化不改变同一 T 的结果。不要沿用 count_embedding 截断到 20 的隐式限制。

输出契约：

| 输出 | Shape / 含义 |
|---|---|
| scores | [B,C]；用于 loss 的有效项必须有限 |
| candidate_mask | 原 mask；选择阶段再对无效项屏蔽 |
| e0、dynamic_edge | [B,C,R,d]，按需返回诊断；无效项固定为零 |
| pooled_edge | [B,C,d] |
| state | [B,d] |
| has_route | [B,C] |
| work_counts | 实际 target 打分数、F/G route 计算数、缓存命中数 |
| aux_status | 各 head 为 disabled 或有效标签版本；不能将随机输出当置信度 |

大批量运行默认不把全部 edge 向量写盘，只保存可重放的 ID、版本和必要统计；诊断模式再导出向量。

## 7. 唯一默认网络的逐层定义

本节固定初版，不要求实现者同时尝试多套 Transformer/GNN。两层 MLP 统一采用“线性 → GELU → dropout 0.1 → 线性”，隐层 512；必要位置使用 LayerNorm。配置与实际参数量写入 manifest。

### 7.1 节点投影与状态编码

\[
z_q=\mathrm{LN}(P h_q),\qquad z_v=\mathrm{LN}(P h_v^{content}).
\]

context 为：

\[
x_v=m^{ctx}_v\,\mathrm{LN}(P_{ctx}h_v^{context}).
\]

T 非空时取其 content 投影的 masked mean；T 为空时使用可学习的 EMPTY 向量：

\[
\bar z_T=\begin{cases}\mathrm{mean}_{u\in T}z_u,&T\ne\varnothing\\
z_{\mathrm{EMPTY}},&T=\varnothing,\end{cases}
\qquad
c_t=\mathrm{LN}\bigl(\mathrm{MLP}_{state}[z_q;\bar z_T;|T|/K]\bigr).
\]

state 输入维度为 2d+1，输出 d。不输入已覆盖 claim 的 Gold mask。T 是当前已选结果集合；visited 是访问集合；path 是发现路径，三者独立存储。初版状态池化是低成本起点，不宣称能精确表示所有逻辑条件。

### 7.2 有向基础边 F

\[
e^0_{u\to v}=F_\phi([z_u;z_v;z_v-z_u;z_u\odot z_v;m_{uv}]).
\]

F 输入 4d+12，输出 d；端点顺序不可交换。没有 per-node/per-edge/per-document ID 查表参数；ID 仅用于索引、去重与日志。

route_features 的 12 维固定如下；来源只能依据实际可用内容和候选规则：

| 维度 | 字段 | 编码 |
|---|---|---|
| 0–4 | semantic、lexical/entity、structural、explicit_reference、other 五类来源 | multi-hot；候选 provenance，不是已证明语义关系 |
| 5 | same_document | 0/1 |
| 6 | same_page | 0/1 |
| 7 | 同文档有符号页差 | clip(delta_page,-8,8)/8 |
| 8 | 页差可用 | 0/1；跨文档或页序缺失时为 0 |
| 9 | 来源内 rank | 1/rank；缺失为 0 |
| 10 | rank 可用 | 0/1 |
| 11 | 当前发现深度 | 有合法轨迹时为 depth / configured_max_hops；未知为 -1 |

同一端点由多个来源召回时合并 provenance；rank 按预先固定的来源优先级选择对应 rank，不能根据 Gold 选来源。图版本、特征词表与该策略一起冻结。未知来源进入 other 并计数；不伪造不存在的 entity/reference 信息。

深度只能来自保存的合法检索轨迹；固定候选训练缺轨迹时使用 -1，teacher-forced T 不重写、伪造或利用 Gold 推断深度。启用图分支时 configured_max_hops 必须大于等于 1；取 0 表示关闭图分支，不执行深度归一化。

第 11 维与运行时路径深度有关，因此含该特征的 e0 缓存必须绑定 route 特征签名，而不能只绑定端点。节点通过更短路径被发现时，深度变更也需失效重算。

### 7.3 动态 Edge 更新 G

\[
e^t_{u\to v}=\mathrm{LN}\left(e^0_{u\to v}+
G_\psi([e^0_{u\to v};c_t;e^0_{u\to v}\odot W_c c_t])\right).
\]

G 输入 3d，输出 d；Wc 为 d→d 线性映射。

必须同时满足：

- 训练时 F、G、P、state、排序头能更新，不能把 e0 长期当成 detached 常量。
- 推理时模型权重固定，但同一条边可随 q/T 重新生成 d 维向量。
- 不能仅给固定 edge embedding 乘一个标量，然后声称已实现本节。
- q/T 改变时向量“能变化”是机制测试；变化有用需要后续真实实验验证。

本模型不编码完整路径序列。它对当前可见的有向边进行条件化，多跳依赖搜索器逐次发现节点；不要将它描述为已经学会了整条路径推理。

### 7.4 去重与 route 聚合

对每个目标先按 canonical 有向端点去重，再按来源轮转、来源内 rank 与稳定 ID 选择最多 R=3 条不同来源节点的 route。精确复制边不产生新投票；不能先截到 3 条再去重。

只有已经合法访问的 source 可贡献 route；不能读取尚未遍历的全库入边来免费丰富一个目标。无 route 的 Dense 候选合法。

\[
\bar e_v^t=\frac{1}{|\mathcal R_v|}
\sum_{r\in\mathcal R_v}e_r^t.
\]

无 route 时 pooled_edge 为零，has_route=0。mean 配合去重可防止精确复制边直接增加权重，但不保证对任意 degree、切块或候选组成差异无偏。保留按 degree 与来源数分层的后续诊断接口。

禁止把跨 edge softmax 概率质量求和作为页面/节点排名分数。

### 7.5 统一目标分数 R

排序隐向量：

\[
f_v=[z_q;c_t;z_v;\bar e_v^t;
z_q\odot z_v;c_t\odot z_v;x_v;
\mathrm{has\_route};\mathrm{context\_mask};
\mathrm{dense\_sim};\mathrm{dense\_sim\_mask}].
\]

维度为 7d+4。用“线性(7d+4→512) → GELU → dropout → 线性(512→1)”产生有限标量 s_v。其隐层 a_v 可供后续辅助 head 共享。

Dense 与 Edge 候选都经过同一 R，没有两个独立 softmax 后直接比较概率的步骤。同一评分请求内，相同目标多路发现后聚合成一次目标打分，不在结果中重复出现；T 或 route 集合变化后的重评分另行计费。原始 Dense 排名仅用于诊断/保护项选择，默认不作为记忆答案位置的模型输入。

相似度只是一个可关闭特征。监督目标要求模型学习“相对可信干扰项，这个目标是否提供尚缺信息”；F/G 使 source→target 与 q/T 的关系有机会影响排名。能否真正利用该通道由消融验证。

## 8. 损失、状态构造与缺标签行为

### 8.1 主损失

对同一 q/T 的有效状态，P 为已审核、尚缺且实际进入候选的必要正例，N 为可信负例或明确标记的弱负例：

\[
\mathcal L_{\mathrm{rank}}(q,T)=
\frac{1}{|P|}\sum_{p\in P}
\log\left(1+\sum_{n\in N}
\exp((s_n-s_p)/\tau)\right),\qquad \tau=1.
\]

逐正例计算，再按状态、原 query 层级平均，防止同题派生状态多或边多的 query 主导训练。不能把其他正例放进该正例的负分母。

实现要求：

- 稳定计算 log-sum-exp；temperature 必须为正。
- P/N/candidate mask 一致，互斥校验失败时明确报错。
- 无 P 或无 N 时返回可微零并统计原因，不生成 NO_EXPAND 或 stop 标签。
- 全批无有效状态时不进行 optimizer/scheduler step；整个数据集均无有效状态时阻止 fit。
- 所有 padding 的 score/loss 数值安全；选择器用的负无穷 mask 不直接乘入 loss。
- 不跨 query 随便使用其他题 Gold 当负例；需确认对当前问题确实不相关，或标为弱假设。

### 8.2 负例来源

当前 r3 主要提供正例。必须报告每个候选是 positive、reviewed_negative、assumed_negative 或 unknown。未标记不自动等于 negative。

后续优先补充这几类负例：主题相近但不支持、同实体错误属性、同数值错误条件、只提到标题、重复已选信息而不补全问题。记录审核方式和可见内容。

weak assumed-negative 模式只能作为显式配置，单列样本数量、抽查错误与结果；不与可信负例混称。构造负例不修改检索图，也不向推理进程传 Gold。

### 8.3 条件状态

当前每题先准备少量状态，默认目标约 4 个：

1. 空 T 或真实 Dense 保护项形成的状态。
2. 已有部分必要证据，缺少其余证据。
3. 含可信干扰项的已选集合。
4. 独立冻结检索过程产生的可重放状态。

对于审核的“所有节点必要”组合，在这些有依据的状态下可用 P=(G−T)∩C。未来出现替代 bundle 时切换到对应的组规则，不沿用简单并集。

训练中给模型看已选 Gold 节点的内容属于 teacher-forced 状态构造，必须标记；模型输入不附加“它是 Gold”的特征。开发评价应包含真实 rollout 状态，防止只在理想历史上学习。

候选池由推理允许的策略产生。为梯度诊断注入正例允许单独命名为 oracle-injected diagnostic；不能作为正常候选覆盖或检索提升结果。图不可达/未提议的正例另行统计。

### 8.4 A/E 与集合监督：先搭接口，不伪造标签

共享排序隐层 a_v 预留两个可选小 head：

- A head：[B,C,3]，类别为对当前需求“无新增支持 / 部分新增支持 / 与 T 共同足够”。这需要对应 q/T/v 的审核；未标记为 unknown。
- E head：[B,C,4]，类别为“有明确相关支持 / 有相关条件冲突 / 仅主题提及 / 可见内容不足”。类别需有独立操作定义与样例，缺失标签不等于内容不足。

默认 enable_A=false、enable_E=false，权重均为零；不参与最终打分。启用后使用各自 masked CE，主要通过共享表示影响 R；不把原始 A/E 概率任意加到 Dense 分数上。若后续直接融合 logits，必须单独配置和校准验证。

当前已知 Gold 组合及删节点测试可给特定集合的充分/不完整监督，但不能直接为任意 q/T/v 填满上述类别。37 个单节点支持 claim 与 13 个联合支持 claim 要分别保留；联合支持不能复制为每个节点都完整蕴含 claim。

若后续只可靠得到一个“支持相关性”标签，就先用一个 support 辅助目标，不强造两个同义 head。集合偏好 loss 另作可选模块，需有同容量的有效完整/不完整集合；仅完整集合对删一项集合存在大小捷径，初版只做诊断、不默认训练。

可扩展总损失为：

\[
\mathcal L=\mathcal L_{\mathrm{rank}}
+\lambda_A\mathcal L_A+\lambda_E\mathcal L_E
+\lambda_{set}\mathcal L_{set}+\lambda_X\mathcal L_X.
\]

默认只有第一项启用。X 尚无路径/动作收益监督，本阶段只定义接口，不实例化随机探索打分器去控制搜索。

## 9. 图、预算与网络的接入契约

### 9.1 图是可替换的候选来源

网络接受合法有向 edge，不限定其必须同文档。现有 build_graph.py 仅生成文档内边，不能直接用来证明跨文档 edge 补召回有效。

本阶段交付 graph adapter 和小型跨文档人工图测试。真实跨文档边后续复用 Stage 1 或新的固定候选策略，例如确实存在的引用/实体锚点、内容近邻等；记录来源与预算。不能为连接 Gold 直接补边，不能从 claim 的联合支持关系倒推出测试图边。

冻结候选拓扑与训练动态向量是两个独立决定。第一轮允许固定图，F/G 仍必须学习。拓扑根本没有目标时，改排序网络无法保证补回。

### 9.2 固定预算与输出数量分开

保留上一版默认起点，均可配置：

| 项目 | 默认 |
|---|---:|
| 输出节点 K | 5 |
| 保护的 Dense 节点 | 2 |
| 初始图搜索 seeds | Dense 前 2 个不同节点 |
| 最大不同访问节点 | 20，包含 seeds |
| 最大 target 评分次数 | 120 |
| 最大动态 route 评分次数 | 400 |
| 每目标最多 route | 3 |
| 一次扩展最多新邻居 | 3 |
| 最大跳数 | 2 |

保护 Dense 2 是当前可解释起点，必须参数化为 0…K；不是不可修改的理论要求。剩余 3 个返回名额在 Dense 与 Edge 候选间统一竞争，可以全来自 Edge。搜索预算不等于输出名额；低 R 的桥接 A 可以被访问与展开但不返回。

默认调度先复用上一版的确定性 Dense-next 与 frontier 交替，任一侧耗尽则使用另一侧。只有初始 seeds 默认作为图根；新 Dense 候选不自动无限新增深度 0 根。按根轮转、浅层优先、稳定规则扩展；不以低 R/A/E 直接封死桥节点。

搜索期间 T_search 固定为实际取得的 Dense 保护集合；visited、frontier 和新发现候选不自动并入 T。最终集合选择从同一保护集合开始，随后每选入一个目标才更新 T。该默认约定让搜索与返回阶段共享清晰的状态含义。

本阶段不把 R 当成完整探索价值 X。真正动态选择“继续 Dense 还是扩展哪个分支”需要后续控制器实验或动作监督，不能由统一返回分自动保证。

### 9.3 模型返回工作量，控制器执行前预留预算

每次实际执行 R 都计 target score，每次对一条有效 route 实际执行 G 都计 route update；即使 q/T 未变，重复计算也要计费。只有命中正确缓存且没有执行对应计算时，才不计该项计算次数。T 或 route 集合变化需要重新判断缓存有效性。F 计算次数与 e0 缓存命中另行报告。batch 中打 20 个目标不是 1 次目标评分。

优先 pack 有效 route 再执行 F/G，避免 padding 路线也执行网络却按 mask 后的数量计费。候选 padding 同理。若实现采用 dense padding，必须额外报告真实张量计算量，不能宣称与逻辑预算完全一致。

控制器先请求 work estimate，确认可执行再运行；模型报告实际 counts，与估计核对。在线内容重编码或图片读取另有 token/图像/call 额度，不能隐藏在一次 score 内。

预留最终集合选择费用：保守上界 K×20=100 次目标评分、100×3=300 次 route 更新；保护 2 项时可以推导更紧上界，但必须统一记录策略。搜索只能使用扣除预留后的余额。模型没有预算时，不允许先算完再截断结果。

若预算不足以继续评分，返回合法的已有排序/选择结果，记录 fallback 与不足原因；不能把未算候选填上伪分数。预算异常不得影响下一 query。

### 9.4 最终集合选择

初始化 T 为保护的 Dense 节点；在剩余候选上调用 R(q,T,v,routes)，选一项、更新 T 和 state_version、重算下一轮分数，直到 K 或候选/可用预算耗尽。

保护项在前，其余按选择顺序返回；同 node 只出现一次。返回分数附带评分时的 state_version，它是条件分数，不与其他选择步的分数重新全局排序。最后重新按混合状态分数排序会破坏原选择语义。

K 小于问题所需节点数时报告容量受限，不通过把多个 node 打包成一个 ID 偷增返回预算。page 模式必须另用 page adapter 和配置单位，不混入 node 指标。

## 10. 缓存、梯度与 checkpoint

训练时只缓存冻结 encoder 输出。P、F、G、state、R 的参数参与更新；不可把可训练投影结果或旧 e0 跨 optimizer step 当不变特征使用。

推理缓存必须区分：

| 缓存 | 失效条件 |
|---|---|
| 原始 h | 编码器、视图、token 策略、内容 hash 变化 |
| 投影 z | 上述条件或 projection checkpoint 变化 |
| e0 | 端点/特征签名、图版本、模型 checkpoint 变化 |
| 动态 et / target score | 额外依赖 query hash、T/state_version、route 集合、context 模式 |

同一 query 的 T 改变后旧 et/score 默认失效。训练 dropout 与推理 eval 模式明确区分；重放验收在 eval 下进行。

checkpoint 包含：模型权重、网络/schema 版本、维度、视图模式、route 特征词表、所有开关、编码器/图/数据 hash、优化器与 scheduler 状态（真实训练时）、随机种子和依赖版本。加载失败必须明确报错，不能静默跳过维度不匹配的层。

梯度验收用至少一条有效 route、一个有效 P/N 的合成 batch：检查 P、F、G、state、R 的有限梯度与一次测试更新；没有 route 的 batch 中 F/G 无梯度是正常情况，不能误判。

## 11. 对已有实现的具体整改清单

这些是源码审查发现的待验收风险，不代表本次已运行复现：

1. model.forward 增加 candidate_mask 与完整输入校验；补 route_feature 语义和分视图接口。
2. 当前先算所有 padded routes 再 mask，需改为有效计算或准确报告两种成本。
3. state count 当前截到 20，升级为显式数量特征与配置校验。
4. losses 校验 P/N 互斥、temperature、padding、finite 值；按 query 归一化多状态。
5. search.traverse 的默认 Budget 对象不能跨调用共享；每个 query 建独立账目。
6. 邻接中重复 target 在访问瞬间再校验，避免先建列表后重复访问与计费。
7. 已访问目标的新合法 route 可在上限内合并；重评分需要预算，不能全部丢弃或免费重算。
8. 拒绝负预算、负 charge；预算预留、缩批、seed 去重均需测试。
9. score callback 的实际工作不能假定永远是一 target 一 route，改为可审计协议。
10. 用明确来源顺序/来源内 rank 代替 provenance 字符串排序。
11. 增加独立训练状态、checkpoint、retrieval 与 evaluation 入口；不让推理加载 qrels。
12. 新版 readiness 分开记录 node、view、vector、graph、label、split；修正旧报告中的阶段混淆，保存旧输出不覆盖。

## 12. 文件组织与交付接口

继续使用 dynamic_retrieval/。实现模型可以按工程习惯调整文件拆分，但必须覆盖：

| 模块 | 责任 |
|---|---|
| schema / adapters | r3 与 VL-DocIR 分别适配；身份、来源和 label policy |
| feature_store / collator | manifest 校验、分视图、mask、节点去重与批处理 |
| model | P、state、F、G、route pooling、R、可选 A/E |
| losses | 主排序、query 级聚合、可选 masked aux；未知监督不自动取零 |
| build_states | 只从训练标签构造状态与 P/N；保存来源 |
| graph_adapter / search | 去重邻接、预算工作量、有限多跳与 Dense 调度 |
| select_results | T 更新、互补选择、输出顺序、来源与成本 |
| trainer | readiness gate、dry-run、checkpoint；本阶段不启动真实 fit |
| retrieve | 仅 query/corpus/graph/checkpoint/config，无 Gold 参数 |
| evaluate | 读取冻结结果后再联结私有 qrels |

建议版本名为 network_v2_build_20261117，不覆盖旧 run。至少提供三个配置：

- network_synthetic：小型人工向量/图，可独立测试。
- nodefirst_r3_build_only：真实 schema 与源映射，只做输入/监督审计，不正式训练。
- nodefirst_fit_template：等待 split、vectors、graph、negative labels 等满足后使用。

build-only 不应偷偷下载模型、提交 GPU 训练或启动真实 fit。实现者应给出真正完成后的命令文档；本文不提前虚构可运行命令。

## 13. 验收测试矩阵

测试重点是影响研究结论的行为；使用人工数值与小图，避免依赖未完成真实数据。一次合成 batch 的 backward/optimizer 更新仅用于工程验收，不记作数据集训练结果。

| 编号 | 用例 | 必须满足 |
|---|---|---|
| T01 | 兼容/错误维度、ID、namespace | 正常输入通过；不匹配明确失败，不猜映射 |
| T02 | 空 T、单节点 T、padding 改变 | 输出有限；同有效集合结果一致 |
| T03 | 无 route / context | 目标仍可打分；缺失通道无 bias 残留 |
| T04 | 无效位置放极端值或 NaN | 不污染有效输出与梯度；有效输入 NaN 报错 |
| T05 | candidate padding | 不参与 loss、返回或工作量计数 |
| T06 | 有向 u→v 与 v→u | 输入顺序被保留；不被 adapter 无意排序成无向边 |
| T07 | 改 q / 改 T | eval 下可重复；动态通道具有可达依赖，不能全部 detach |
| T08 | 梯度与测试更新 | 有效 route batch 中 P/F/G/state/R 可更新，checkpoint 重放一致 |
| T09 | 精确复制 canonical edge | 去重后 route 集合、评分、选择和预算不变 |
| T10 | 多个合法 routes / R 上限 | 先去重再截断；来源策略稳定，无 Gold 参与 |
| T11 | 提高任一正例相对负例分数 | 相应排序损失下降；其他正例不是负例 |
| T12 | P/N 重叠、空 P/N、全无效批 | 非法标签失败；空监督跳过并计数，不学习 stop |
| T13 | 同题状态数不均 | query 级归一化符合约定 |
| T14 | 必要组与替代 bundle | 不强迫召回所有替代节点；不复制 joint entailment |
| T15 | qrels / answer / annotation seed | 推理对象与入口拒绝这些字段；生成 seed 来自 Dense |
| T16 | 两个 query 连续检索 | 预算、缓存、visited 不跨 query 污染 |
| T17 | seed→A→G，A 返回分低 | 合法预算内 A 仍可展开；G 可进入候选 |
| T18 | 环、重复 seed/target、新 route | 不无限访问；新 route 合并和重评分正确计费 |
| T19 | 预算 0/边界/负数/缩批 | 不先计算再判断；负额度拒绝；预留生效 |
| T20 | T 更新后的重评分 | 缓存失效，目标/route 费用再次计入 |
| T21 | 最终选择互补性 | 使用新 T 重算；结构测试可用固定可控 scorer，不冒称模型学会 |
| T22 | Dense 与 Edge 都发现同目标 | 只占一个输出名额；route 可保留来源 |
| T23 | node/page 单位 | 各用自身标签与预算；不把整页节点都变成正例 |
| T24 | 关闭辅助 head | 输出 disabled，不输出随机置信度参与排序 |
| T25 | 导出/加载及恢复 | 版本冲突报错，eval 排序与数值在容差内一致 |
| T26 | no-edge 消融 | route 向量、特征和 availability 信号一起屏蔽 |

T07/T17/T21 是机制可实现性，不代替真实语义正确性。当前 r3 可以校验标签结构和源映射，不能据此直接宣称模型理解了证据。

测试报告注明实际运行环境、命令、通过/失败/未运行；不能把“写了测试文件”记作通过。

## 14. 数据接入前后的分阶段任务

### B0：只读审计与接口冻结

重新检查工作区指令和已有修改；记录 r3、源码、表示 manifest 的 hash。输出 NETWORK_GAP_REPORT.md 和 INPUT_CONTRACT.md，明确真实标签可用性与需要等待的资产。

不要覆盖既有 baseline、Stage 1、旧 Pilot、r1/r2/r3 标注或旧实验输出。其他人的未完成修改保持原样。

### B1：网络与 loss 搭建

在已有骨架上补齐第 5–8 节。实现合成 collator、有效 route packing、前向/反向、checkpoint、no-edge/context 消融。先通过 T01–T15 与 T24–T26。

交付参数清单、模块输入/输出 shape、所有冻结与可训练参数、梯度检查结果。A/E/X 默认关闭；不存在“只有名字没有监督”的完成声明。

### B2：控制器与集合选择接入

完成图 adapter、Dense/frontier 调度、预算协议与最终条件选择，运行 T16–T23。用人工跨文档两跳图验证接口，不使用真实 Gold 补边。

### B3：现有标注 dry-run

适配 17 条 r3，核对 31 个 evidence 引用、50 个 claim、122 个 span、canonical 来源与标签掩码。若文件更新，以新快照统计并说明差异。

输出实际有效状态数、缺负例数、表示可用率、证据可见性、未就绪资产。没有真实向量时完成源/schema/label 检查即可；不能给真实样本填随机向量后称为模型可用。

### B4：构建交付，等待数据

完成 NETWORK_BUILD_REPORT.md、TEST_REPORT.md、DATA_REQUIREMENTS.md、REPRODUCE.md、配置模板及 schema version。报告 NETWORK_READY 是否成立，以及 DATA_READY_FOR_FIT 的每项状态。

**本轮搭建任务到此结束，不主动启动真实训练。** 用户后续明确开始训练且数据条件满足后，再进行 8–16 个 train query 的拟合诊断、固定候选训练与预算检索实验。

## 15. 真实训练启动条件与最小数据交接清单

必须满足：

1. 冻结 corpus / canonical node / view / vector / graph 版本，query 与 node 编码协议兼容。
2. 独立的 train/dev/test 文档家族或共题文档组件划分；同题改写、版本修复、共享证据不跨 split。
3. 正例、可信/弱负例、unknown 分开，存在 P/N 均非空的有效训练状态。
4. runtime seeds 由 Dense 产生；标注 seed 与 Gold 未进入候选发现输入。
5. r3 与 VL-DocIR 标签粒度不混用；视觉不可用和截断范围明确。
6. 评价集不用于选择构图边、网络超参或训练状态；旧 24-query Pilot 与当前反复审阅的 17 条明确标为诊断数据。
7. 所有必须的工程验收通过，结果与模型 checkpoint 能重放。

数据准备方交接表：

| 必须交接 | 内容 |
|---|---|
| corpus manifest | namespace、文档家族、节点与来源 hash、完整非 Gold 候选语料 |
| split manifest | 组件划分、暴露/重复排除记录；不是随机节点切分 |
| query inputs | question 与 query_id；不含答案 |
| labels private | 相关节点、审核来源、可信/弱负例、unknown、必要/替代组 |
| features | query/content/context 的向量、ID 映射、模型与截断协议 |
| graph | 去重有向边、来源、构图配置；不按 Gold 加边 |
| optional aux | 只有审核定义清晰时才交 A/E 或动作标签，否则显式 absent |

规模建议沿用“先 8–16 题检查训练链，再用更大且独立划分的小数据验证”。17 条现有数据足以帮助搭接口，不足以证明迁移性；扩展后的样本量由有效问题/文档组件数和学习曲线决定，不把同题 routes 数当样本量。

## 16. 为后续实验预留的对照与输出

本阶段搭好配置，不启动实验：

| 对照 | 排除的混淆 |
|---|---|
| 冻结 Dense bypass | 验证原排名重放 |
| 学习的 q/T-target，无 edge | 收益是否来自普通监督排序 |
| 可训练静态 edge | 与 query/T 动态更新区分 |
| q-conditioned edge | 与 q+T-conditioned edge 区分 |
| content-only 与 split content/context | 文档主题与内容关系的影响 |
| 同候选下 source/route 打乱 | Edge 通道是否使用正确源信息；仅离线诊断 |
| 同预算一跳/两跳 | 额外候选与深度带来的作用 |
| 后续 A/E 开关 | 独立辅助监督是否有用 |

no-edge 学习对照不自动等于原 Dense；只有 bypass 才要求恢复冻结 baseline。静态 edge 对照仍可在 R 读取 query；其含义是边向量自身不按 q/T 更新。

结果接口记录 query_id、target_id、rank、选择步、state_version、条件 score、原 Dense rank、发现来源、合法 parent/path、hop、route IDs、实际输入视图、预算账目、模型和数据版本。

后续评价同时报告 Recall/RecallAll/nDCG@5/10、新增相关节点与丢失节点、低 Dense 排名目标恢复、候选可达/访问/入选三层、必要集合完整率、degree 与成本。未知替代证据不能直接当不相关；联合支持组不能只命中一个就算完整。

如果目标 Dense rank40 本就在同一个固定 Top100 候选池里，提升是排序收益；若原池只有 Top10，沿边发现目标才是候选补召回。两个结果分别记录，不混称。

## 17. 给实现模型的执行指令

请在 DynamicEdgeGraph/dynamic_retrieval 中执行本文 B0–B4，依据现有 r3 标注补齐网络与接入契约。保留已有骨架、旧结果和其他人的修改。先搭冻结 encoder 上的 256 维可训练 F/G 动态 Edge 网络、统一条件排序、正确的多正例 loss、预算控制器与集合选择，并用合成数据完成必要工程验收。

当前只有 17 条已自动审核的文字标注，没有正式独立 split、完整负例和路径监督。真实数据 dry-run 应如实报告这些缺口。标注中的 seed 不能作为检索 seed；答案、claim 和 Gold spans 不能进入推理特征。A/E/X 无相应标签时保持关闭。

不要为本任务启动真实训练、批量重编码、额外下载或修改原标注。完成网络与验证后交付可复现报告、数据需求清单和训练配置模板。真实拟合与评价属于后续训练阶段：实际 readiness 通过且已有训练授权时执行，不为已授权步骤重复请求确认。
