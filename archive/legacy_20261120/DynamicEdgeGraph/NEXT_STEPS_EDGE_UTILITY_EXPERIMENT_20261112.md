# DynamicEdgeGraph 下一步任务书：先验证 Edge 的增量选择价值

日期：2026-11-12。状态：**待执行方案**。本次只编写本文，没有修改代码或运行新实验。

## 1. 本轮要回答什么

**给定同一批已读证据和一个额外页面预算，图方法选出的页面，是否比普通检索的下一页更有用？在这个条件下，pair 表示和 prototype 各自有没有额外贡献？**

先把这个问题回答清楚，再研究如何用边替换 Top-5 页面。首轮不继续往旧的正分融合里叠加模型，也不以簇形状、attention 权重变化或 QKV 接口存在作为成功标准。

建议执行顺序：

1. **P0：修复日志并重放旧结果。** 确认能够从日志复现真正的排名。
2. **P1：一个额外页面槽位的对照实验。** 固定候选、seed 和每页代表 route，去掉路径求和与正偏置融合。
3. **P2：根据 P1 决定是否需要关系监督或 prototype。** 不在同一批 24 题上无限调权重。
4. **P3：有选择价值后，再研究 Top-5 替换与证据集合重排。**

P0/P1 可复用现有缓存进行 CPU 实验，无需新 embedding、LLM 调用或 GPU 训练。所有新方法和数字在运行前均为假设。

## 2. 已确认的起点与本轮边界

依据：[现有诊断报告](EDGE_RETRIEVAL_NO_GAIN_DIAGNOSIS_20261111.md)，尤其 §3、§6、§10；[检索评价协议](stage2_edge_construction/RETRIEVAL_EVALUATION_PROTOCOL.md)。2026-11-12 检查时，probe 仍有以下问题：

| 已确认事实 | 对本轮的约束 |
|---|---|
| 原 B/C/D 的 Top-5 新增 3 个 gold occurrence、丢失 12 个 | 必须同时报告 gain、loss 和净变化 |
| 当前 graph bonus 只给非 seed 页，原 Top-10 不加分 | 首轮避免直接复用该融合比较 pair 能力 |
| Value-aware 的 NO_EXPAND 被 max-page normalization 抵消 | 拒绝必须成为实际动作，不能只保存一个概率 |
| 真实 softmax 在所有 seed 候选合并之后执行 | 新实验的归一化范围必须显式记录，不能误称旧版是每 seed softmax |
| Trace 中 attention_weight 是循环末尾残留值 | 从 logits 重建旧权重，新日志保存真正逐边权重 |
| 950,871 对候选的实际路径已覆盖 Top-10 漏掉的 5 个 gold 页 | 优先检查选择价值，不立即扩大 Stage 1、hop 或 seed 数 |
| Prototype 确实进入通道，但未测出有效收益 | 分开检查“参与计算”与“改善检索” |
| 24-query Pilot 已反复开发 | 只能报告开发诊断，不能重新切几题就称全新独立测试 |

保持现有语料、canonical IDs、冻结向量、gold、旧输出和 Stage 1 工作点。当前实验使用 **Pilot 五路 Top-100 union**，不是另一数据空间的全量 Balanced ABC。Clustering 的 5,000 pair 样本也不替代完整候选图。

“安全融合”在本文中指决策链可解释、允许回退、没有已知实现偏置；**不要求用测试 gold 保证每题不掉分**。

## 3. 输入资产：先冻结，再比较

首轮复用：

- 配置：[pilot_e0_stage1_v1.json](stage2_edge_construction/configs/pilot_e0_stage1_v1.json)。
- 冻结 baseline：`EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011/`，包括 queries、gold、node_pages、hybrid_visual scores。
- Node 向量：`DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-pilot-stage1-v1/models/qwen3_0_6b_dense/view_vectors.npy` 及已核验的逐行 ID。
- Candidate union：上述 Stage 1 run 下的 `candidates_top100/analysis/candidate_unions/top100.jsonl`。
- 已缓存的同空间 query vectors、现有 K=32 node/edge centers。
- 旧 B/C/D、protected Top-5、legacy QKV、value-aware 的 metrics、manifest 和 logits。

在新 run manifest 中固定文件哈希、query 顺序、ID 映射、实际源码哈希／Git 状态、参数、tie-break 和输出目录。HEAD 当前为 `6cb4b4e`，但工作区有未提交文件，**仅记 commit 不足以复现**。

当前预期：24 query、518 页、7,288 个可用 node 向量、950,871 无向候选对；原检索每 query 10 个 seed node，总计 240 个 seed occurrence。先逐项核验，数字不一致时解释版本差异，不硬编码来凑计数。

## 4. P0：先让旧实验能够可靠重放

### P0.1 新日志的最低契约

修复位置优先检查 [run_qkv_attention_probe.py](stage2_edge_construction/src/run_qkv_attention_probe.py)。未来修改写入独立版本／新 run 目录，旧产物原样保留。

| 层级 | 必须保存的内容 |
|---|---|
| Edge | query/source/target/page ID、QK logit、V logit、真实 attention、attention×V 贡献、prototype ID |
| 归一化组 | group ID、包含哪些 edge、NO_EXPAND logit、分母、归一化后的权重和 |
| Page | 原始 base 分、page mass、graph correction、最终分、最终 rank、去重前后 edge/target/source 数 |
| Query | 候选数量、实际动作、fallback 原因、seed IDs、完整页面排名和实际成本 |

旧版全 query softmax 与未来分组 softmax 使用不同 `normalization_scope`。`page_score` 不再混指 edge score、page mass 和最终分数。

### P0.2 必须通过的检查

1. 使用保存的 logits 重建旧 softmax/page mass，复现每题 @3/@5/@10 指标；不能直接信任旧 trace 的 `attention_weight`。
2. 每个 attention 组含 null 的权重和为 1；日志中的 edge 权重与实际数组逐项一致。
3. `graph_weight=0` 严格恢复冻结 baseline，包括相同 tie-break。
4. 旧 protected Top-5 精确恢复原前五，仅标作机制控制，不作为有效方法。
5. `context_weight=0` 回到对应无 context 条件；非零 context 检查通道／logit 是否改变，再另外检查排名与效果。
6. 错误 ID、缓存顺序不一致、非有限分数、缺少完整输入应显式失败，不猜测对应关系。

旧数量相关性的参考值：从 logits 重建后，全局 query–page Pearson 为 attention mass **0.893702**、attention×V mass **0.900728**；0.880480 / 0.897420 来自错误日志。新报告应标明全局统计还是逐 query 中位数，不混比。

**P0 验收：** 提供 `REPLAY_VALIDATION.md`，写清复现结果、误差容差和未通过项。P0 未通过时，先修复测量链，不训练复杂 QKV。

## 5. P1：一个额外页面槽位，直接测试边是否会选

### 5.1 为什么采用这个实验

旧方案同时改变了图评分、页面聚合和最终融合，收益与损失纠缠。这里固定已有 Dense Top-10 为证据集合 S，再给所有方法**一个相同的额外页面槽位**：

- Dense 对照：S 加原 baseline 第 11 页，记为 d。
- Graph arm：S 加一个候选页 p，或者保留 d。
- 所有 arm 最终都是 **11 个不同页面**；候选 p 不得已在 S 内，也必须排除 Dense 替代页 d。保留 d 统一由 KEEP_DENSE 动作表示。

这是一项 **固定页面预算的增量检索诊断**。原 Top-10 不变，所以不评价 @3/@5/@10 提升；主评价是第 11 个槽位的选择及 11 页证据集合覆盖。它不意味着最终系统应该永远锁住前十。

11 页预算也不自动等于相同 token／像素／模型成本：首轮明确只匹配页面数，记录页面长度及评分成本；若后续接 reader，应再统一可读 token/视觉预算。

### 5.2 冻结候选与每页代表 route

1. 使用与现有实际检索相同的 10 个 seed page，每页按冻结 q→node 分数选一个 seed node；核验与旧 run 一致。
2. 只使用这些 seed 在原 union 中的合法 one-hop edge；不增加 gold-aware 路线。
3. 按 `(query, source_node_id, target_node_id)` 去重。重复输入同一边不得增加候选数量。
4. 对每个非 seed、且不是 d 的候选页 p，从**至少连到一个当前 seed 的 target nodes**中，按固定 q→target 分数选一个代表 t_p；同分按 node ID。
5. 从实际连到 t_p 的 seed 中，按固定 q→source 分数选一个代表 s_p；同分按 node ID。
6. 所有 arm 共用这一份提前冻结的 `page_representatives`，之后才比较评分。

这样每个页面只有一条 route 参与首轮决策，消除了页面因为重复 edge 或多条路径被直接求和的收益。**它仍可能有 max-selection 偏置：节点更多的页更容易选出一个高分代表；也可能漏掉需要多个 node 才成立的证据。** 首轮如实记录这个局限，不称为完全 degree-invariant。多 target、多 seed 和证据集合聚合留作后续单独消融。

Baseline 第 11 页 d 的代表 t_d 从其可嵌入 nodes 中按相同 q→node 规则选择，不要求它与 seed 有静态图边。若 d 无可用 node，则所有 graph arm 在该题共同回退 d，标记 `REFERENCE_UNSCORABLE`，保留该题，不从分母删除。

### 5.3 以“优于 Dense 替代项”为条件，而不是普遍加正分

对每个候选 p，采用同一个 source s_p，分别计算：

\[
r_A(p)=f_A(q,s_p,t_p)-f_A(q,s_p,t_d).
\]

两项使用同一 scorer、同一 source 和同样的预处理，减少不同 source 自带分数偏移造成的混淆。第二项只是对同预算 Dense 替代项的**反事实评分**，不是认定 `(s_p,t_d)` 存在真实关系；不写回图，不计作新 edge。

设 `NO_GRAPH_REPLACEMENT` 的 margin 为 0：

- 若所有候选 margin ≤ 0，实际执行 KEEP_DENSE，填入 d。
- 否则选 margin 最大的页面填入槽位；同分先倾向保留 d，其余按 page ID。
- d 不参加图候选竞争，避免其图可达代表与全页代表 t_d 不同，造成非零“自比较” margin。
- 不再做跨 edge sum，不除以最大 page mass，不执行 `base + positive_graph_bonus`。

这里的零阈值只表达“当前 scorer 认为候选没有超过其替代项”，不是校准后的真实 utility 门槛。必须报告实际回退率；若从不回退，也要如实报告，不能据此宣称拒绝机制已可靠。

**名称注意：** KEEP_DENSE 表示不采用图替代，但仍读取预算中的第 11 页，不是停止全部检索。真正停止在 10 页的可变预算策略应另设实验，避免预算混淆。

### 5.4 首轮比较三个基础 arm 和一组 V 对照

| Arm | 选择规则 | 要回答的问题 |
|---|---|---|
| R0：Dense-next | 始终选择 d | 相同页面预算的普通检索基线 |
| R1：Target-only | f_T = q 与 target 的余弦；按上述 margin 决策 | 原图候选和新节点视图是否已经足以改善选择 |
| R2：Pair | 使用现有固定 `pair_aware_score`，不加 prototype | source–target 几何比只看 target 多了什么 |
| R3-QK：V 对照 | 使用 exp(z)/2，使用同一 margin 决策 | 控制从 C 分数改为指数形式本身的影响 |
| R3-QKV：Pair + V | 使用下述 exp(z)×V 兼容分，使用同一 margin 决策 | 相对 R3-QK，V 是否有独立选择价值 |

R2 的函数复用 [edge_representation_scoring.py](stage2_edge_construction/src/edge_representation_scoring.py)，权重固定，不用 Pilot gold 搜索。

R3-QKV 建议使用现有 probe 的逐 edge 未归一化贡献：

\[
f_V(q,s,t)=\exp(z(q,s,t))\frac{1+u(q,s,t)}2,
\]

其中 z 是现有 `qk_logit`，u 是现有 `value_logit`，Q/K/V 构造全部保持原定义。它保留 QK 与 V 同时参与，去掉全 query softmax 的共同分母与跨路径求和；在本实验中只是排序分数，不称概率。对候选与 Dense 替代项都使用这一公式。

对应 R3-QK 固定 V 兼容项为 1/2，即 f_QK=exp(z)/2。R3-QKV 与 R2 同时改变了指数变换和 V 项，因此不能直接把两者差异归给 V；V 的独立贡献只看 R3-QKV−R3-QK。两组共用相同候选、source、null margin 和参数。

注意现有 Qvalue·V 不保证数学上位于 [-1,1]；记录实际取值范围，检查有限性，不静默 clipping，不把该标量称为校准置信度。反事实 `(s_p,t_d)` 的值可能超出旧真实边的范围，同样必须记录。若另做 cosine-normalized V，应独立命名，不能在本 arm 中悄悄改变定义。

R1 使用的新 node 表示与冻结 baseline 的窗口级 page score 并非完全同一条打分路径，因此 R1 对 R0 的收益包含候选／表示视图差异；**pair 独立贡献看 R2−R1，V 贡献看 R3-QKV−R3-QK**。不能将 R1−R0 全部归给关系推理。

### 5.5 首轮机制检查

| 检查 | 预期 |
|---|---|
| 精确复制同一 canonical edge | 去重后的代表、分数、决策不变 |
| 调换输入 edge 顺序 | 固定 tie-break 后结果不变 |
| 无合法候选、所有 margin 非正、候选为 d | 实际选择 d；各 arm 均仍输出 11 页 |
| 固定候选，提升 KEEP_DENSE 的比较阈值 | 图替代次数不增加，足够高时全部回退；此项为合成机制检查，不是调优 |
| R3-QKV 的 u 置零 | 分数与决策应严格等于 R3-QK；这是接线检查，真实 V 效用另看检索指标 |
| 固定 q 与相同 target 候选，替换 source | 检查相对排序／差分，不只看原始分数变化 |

将同一原文拆成更多节点的检查，只有可靠 provenance 能判定重复时才要求去重后不变；没有这种映射时记录为待审计，不能声称完整解决切块偏置。

## 6. P1 的评价与交付

### 6.1 主评价

对每个 arm 输出：

- 相对 R0 的 **完整 gold-page 覆盖率 @11** 和 page Recall@11。
- 额外槽位的 gold gains、gold losses、净变化；计算单位为 query–page occurrence。
- KEEP_DENSE 比例、真正换页题数、候选及代表 route 数、每题成本。
- 已在 S 中充分覆盖的题与 S 尚不完整的题分别报告，但总结果始终保留全部 24 题；该分组仅后验评价。
- 如果把新增页固定追加在第 11 位，nDCG@11 仅辅助报告；@5 等于 baseline 是构造结果，不当成果。

Gold 只在动作和输出页集合冻结后进入评估。既有“5 个漏页都可达”只是机会信息，不允许据此手工补路线或只挑这 5 题运行。

### 6.2 页面命中之外，补少量真实用途审核

对各 arm 有不同动作的题，审核 `query + S 的完整原始证据 + graph 页 p + Dense 页 d`。隐藏 arm 名称、分数和 gold；若规模允许，争议题全审，并抽取 KEEP_DENSE 案例检查漏掉的机会。

标记：`新增所需支持 / 必要背景 / 冗余 / 错实体或条件 / 信息不足`，并判断 p 相对 d 是否值得读取。不能把“同 gold 页”直接变成 pair 真关系标签，也不能仅靠截断预览判断已有证据不充分。

记录人工／AI 辅助来源、分歧和未知；没有独立人工标签时，语义效用只报探索性结果。方法分歧样本不是全体随机样本，不能直接用它估计全库 precision。

### 6.3 本轮建议输出

新建独立 run 目录，例如 `stage2_edge_construction/outputs/edge_utility_slot_v1_<run_id>/`，存在则拒绝覆盖。至少包含：

| 文件 | 用途 |
|---|---|
| `input_manifest.json`、`protocol.json` | 固定输入、源码、参数、证据预算和主指标 |
| `page_representatives.jsonl` | 各 arm 共用的候选页、代表 source/target、Dense 替代项 |
| `route_scores.jsonl` | 每个 scorer 的候选分、替代项分、margin、V/QK 分量 |
| `decisions.jsonl` | 实际选中页、回退原因和可追溯 route |
| `page_sets.jsonl` | 每题明确的 11 页最终集合 |
| `per_query_metrics.jsonl`、`summary.json` | gain/loss、覆盖、动作和成本 |
| `MECHANISM_CHECKS.md` | 重复、顺序、回退、V 通道与边界检查 |
| `RESULTS.md` | R0/R1/R2/R3-QK/R3-QKV 对比、失败案例、可支持与不能支持的结论 |

新路径只是建议产物，当前尚未创建或运行。若后续更新 README/benchmark，请把本轮 @11 槽位实验和旧 @5/@10 重排实验分表，不将不同预算的数字混排选优。

## 7. P2：什么结果支持继续做 prototype 或训练

| 观察结果 | 下一步 |
|---|---|
| 实际代表 route 的目标页／span 没有新增证据机会 | 检查代表选择是否过窄，再研究多 target 或 seed/candidate；不从页面可达率直接推断语义覆盖 |
| R1 优于 R0，但 pair/V 对照没有额外收益 | 优先保留简单 target 选择；暂停增加复杂 attention，审查 pair 的监督与输入 |
| R2 对 R1，或 R3-QKV 对 R3-QK 有稳定的开发集增量 | 冻结该机制，在独立数据上验证，然后做一次有／无 prototype 对照 |
| Prototype 只改变 logit，没有质量或成本收益 | 保持为可选模块，不通过反复调 K 追同一 Pilot |
| 各 scorer 的选择都无效，但独立审核能区分有用／无用组合 | 建立少量独立监督，先训练简单 pair scorer，与等容量 target-only 比较 |
| 标注不足或有效机会很少 | 报告无法判断，补独立样本；不把不显著写成证明无效 |

Prototype 第一轮只增加一个 edge-context arm，固定现有 K=32、context weight=0.1，使用同一代表 route、scorer 和 Dense 反事实计算。Node context、多原型温度、复杂局部 edge attention 以后逐项增加，不做一次大网格搜索。

**允许开始小型监督实验，不以零训练先获得正收益为硬前提。** 真正前提是 P0/机制链可靠、有独立可审查的学习目标和数据。学习 query-conditioned utility 时，训练 query 与 gold 可以在训练分区提供监督；gold 不进入静态图，也不进入验证／测试时的候选选择。

当前 24 题全部是开发数据。新的 query 与文档族划分要事先冻结；同 pair 正反方向、重复 query、近重复文档不跨集合泄漏。使用全语料无标签聚类时明确 transductive 设置，不能声称中心从未见过测试文档。

扩大训练前，在预先冻结的验证集上达到事前定义的实际收益，或质量非劣且明确节省成本。报告配对 query 差异及不确定性；文档相关性强时考虑文档族重采样。小样本区间可能很宽，不从一个 query 的改善宣布方法成立。

## 8. P3：有增量价值后，才回到 Top-5

槽位实验只证明“能否挑到更有用的新页”，没有证明“知道替换哪个旧页”。后续单独研究：

1. 在相同 candidate page pool 中联合比较 baseline 与新增页，使用一致的最终评分／集合选择协议。
2. 判断替换的机会成本，特别是比较任务中的两侧证据、条件说明与重复材料。
3. KEEP_BASELINE 作为真实动作；不要在后续归一化中取消拒绝信号。
4. 对有／无 pair 使用相同的融合、证据预算和最终 reranker；这一轮才能报告 RecallAll@5、nDCGAll@5。

如果只能恢复 baseline 而没有独立收益，结论就是尚未显示图增益。不要通过永久锁定 Top-5 宣称方法有效，也不要要求利用测试 gold 逐题保证无损。

## 9. 给未来执行者的完成标准

首轮交付到 P1 为止：

- P0 旧结果可重放，日志真实且含最终 page ranking。
- 新实验的输入、代表 route、同预算 Dense 替代项在各 arm 间完全一致。
- 重复 edge 不导致额外支持；KEEP_DENSE 是实际输出动作。
- R0/R1/R2/R3-QK/R3-QKV 全部运行并保留 24 题，只有后验评价访问 gold。
- 报告覆盖、净 gain/loss、回退、成本与原始证据案例，明确 @11 实验不能证明 @5 提升。
- 根据结果表给出下一条具体分支，而不是自动启动训练、换 encoder 或扩大图。

本任务书的目标是把“边是否值得使用”变成可识别、可复现的问题。它不预设 Edge 一定优于普通检索，也不把一个零训练负结果当作整个研究方向的终点。
