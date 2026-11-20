# 为什么当前 Edge 没有带来检索收益：实验与实现审计

日期：2026-11-11。只分析已有实验、代码与报告；本次仅新增本文，没有修改代码、重跑模型、提交作业或覆盖实验结果。

## 1. 结论先行

**这轮主要问题已经能定位到：图检索确实促上了一些漏掉的 gold 页面，但当前融合方式把更多原本正确的页面挤出前列；而 edge、prototype 和 QKV 尚未提供足够可靠的增量评分去抵消这种损失。**

当前不能简单归结为“Stage 1 没召回”“clustering 没学好”或“attention 没用”：

- 这次实际使用完整 Pilot 五路 Top-100 union，950,871 个无向 pair。Baseline Top-10 漏掉的 5 个 gold 页，在实际评分路径里 **5/5 都可达且已评分**。
- 原版 B/C/D 在 Top-5 都新增 3 个 gold 页，却丢失 12 个已有 gold 页，净损失 9 个 query–page occurrence；完整覆盖从 16/24 降到 13/24。
- 在还没有使用 edge 表示的 **target-only B** 中，主要下降就已经发生。C/D 的失败不能全部归因于表示或聚类。
- 保护 baseline Top-5 的版本把 Top-5 排名直接固定，因此“不下降”来自设计保证，也同时失去了在 Top-5 改善的可能。
- 最新 QKV 是**未训练的确定性特征探针**；legacy 版本的 attention/V 没进入最终排名，value-aware 版本虽然消费 V，但取消了 NO_EXPAND 对融合的作用，并引入明显的页面候选边数量偏置。

因此，下一步优先解决**评分如何进入最终排序、如何允许不扩展、如何避免重复路径被当作独立证据**，之后才值得判断训练 edge / clustering 的收益。

## 2. 这次看的是哪些新结果

本报告更新了 [11 月 10 日审查](CLUSTERING_REVIEW_AND_QUERY_CONDITIONED_NEXT_STEPS_20261110.md) 的实验状态：目前已经存在下游检索、prototype context、QKV probe 和 ranking fusion audit，不能再说“只有聚类诊断”。

主实验根目录：`stage2_edge_construction/outputs/pilot_e0_stage1_v1/`。共同范围是 24 个 query、518 页；每类问题 4 个，所以六类 macro 与 query 平均在本 Pilot 上一致。指标均为页面检索指标，没有据此评价最终答案准确率。

| 实际运行 | Recall@5 | RecallAll@5 | nDCGAll@5 | Recall@10 | RecallAll@10 | nDCG@10 |
|---|---:|---:|---:|---:|---:|---:|
| A：冻结 hybrid_visual no-edge | 83.33% | 66.67% | 55.76% | 89.58% | 79.17% | 74.17% |
| B：graph + target-only | 64.58% | 54.17% | 44.29% | 77.08% | 66.67% | 59.18% |
| C：original directed edge | 64.58% | 54.17% | 44.29% | 75.00% | 62.50% | 58.41% |
| D：C + prototype context | 64.58% | 54.17% | 44.29% | 75.00% | 62.50% | 58.44% |
| protected Top-5，B/C | 83.33% | 66.67% | 55.76% | 89.58% | 79.17% | 74.27% |
| QKV value-aware，none/edge | 66.67% | 54.17% | 44.40% | 89.58% | 79.17% | 65.12% |

RecallAll 表示该 query 的全部 gold 页都进入 Top-K。Value-aware 的 node/node_edge 在这些召回指标上相同，nDCG@10 分别为 65.06% / 65.02%，不是所有指标都完全一致。其 Top-10 召回回到 baseline 水平，但排序质量仍明显低于 baseline；protected 版本 nDCG@10 的微小变化也不是 edge 表示的独立收益，因为 B/C 相同。

来源：[原 B/C/D 对比表](stage2_edge_construction/outputs/pilot_e0_stage1_v1/BENCHMARK_COMPARISON.md)、[protected 指标](stage2_edge_construction/outputs/pilot_e0_stage1_v1/query_conditioned_retrieval_protected_top5/pair_aware_metrics.json)、[value-aware manifest](stage2_edge_construction/outputs/pilot_e0_stage1_v1/qkv_attention_probe_value_aware/manifest.json)。现有 BENCHMARK_COMPARISON 尚未收录后两类，单看该表会漏掉最新结果。

这些结果来自反复检查过的开发 Pilot。可用于定位错误，不能把本次后验分析后选择的方法称为独立测试集上的泛化提升。

## 3. 首要原因：当前融合系统性偏向原先排名靠后的页面

### 3.1 实际执行的公式

[run_query_conditioned_edge_retrieval.py](stage2_edge_construction/src/run_query_conditioned_edge_retrieval.py) 第 128–155、184–189 行：

1. 取 baseline Top-10 页，每页选 query 相似度最高的一个 node，共 240 个 seed-node occurrence。
2. 沿固定候选图找邻居。
3. **跳过目标属于任意 seed 页的边。** 当前 24 题都取满 10 个 seed 页，因此 baseline Top-10 页全部没有 graph bonus。
4. 对剩余每页取最大的 graph score，加到该页的 min–max baseline 分数上。

\[
S_{final}(q,p)=S_{base}^{minmax}(q,p)+0.25\,G(q,p).
\]

Target-only 中：

\[
G(q,p)=\max_{i\to j:\ page(j)=p}\frac{1+\cos(q,h_j)}2.
\]

因此，具有 graph 候选的非 seed 页获得：

\[
0.25G=0.125+0.125\max\cos(q,h_j),
\]

而 baseline Top-10 页获得 0。这包含一项**仅因进入 graph 候选而获得的正偏置**。对所有页面加相同常数不会影响排序，但这里常数只加给原 Top-10 之外的页面，所以会改变排序。

代码注释里的“preserve original retrieval”只是排除了重复扩展，并没有保护原有排名。对 target-only 而言，这种变化发生在没有任何 edge 语义参与之前。

### 3.2 已观察到的实际损失

从保存的 page rankings 和 fusion audits 复算：

| Arm / 范围 | 新增 gold 页 occurrence | 丢失 gold 页 occurrence | 净变化 |
|---|---:|---:|---:|
| B / Top-5 | 3 | 12 | −9 |
| C / Top-5 | 3 | 12 | −9 |
| D / Top-5 | 3 | 12 | −9 |
| B / Top-10 | 4 | 10 | −6 |
| C、D / Top-10 | 3 | 10 | −7 |
| protected B/C / Top-10 | 3 | 3 | 0 |
| value-aware 四组 / Top-5 | 1 | 9 | −8 |
| value-aware 四组 / Top-10 | 3 | 3 | 0 |

同一页面出现在不同 query 中按不同 occurrence 计，不能把这些数当作全库去重页面数。现有 [Fusion Audit](stage2_edge_construction/outputs/pilot_e0_stage1_v1/query_conditioned_retrieval/RANKING_FUSION_AUDIT.md) 的“10”是**发生 gold 掉出的 query 数**；逐条累加实际丢了 12 个 gold 页。

B 的 60 个 Top-5 新进入页面 occurrence，原排名全在 11–15，获得的 bonus 约 0.156–0.225；C 的 61 个新进入页面原排名为 11–17，bonus 约 0.162–0.221。原 Top-10 页的 bonus 全部为 0。这不是只有少数异常边偶然出错，而是融合政策持续改变竞争条件。

### 3.3 两个能解释机制的具体例子

**植入装置 headstage/clamp 高度，query `81150ced-33ba-4c21-bfc9-3a96ec899240`：**

- Gold 文档 `044d9da3-6f4a-4dc9-9099-f64bf2245f28` 第 4 页：原 rank 2 → B rank 15。
- 同文档第 3 页：原 rank 5 → B rank 18。
- Top-5 被该文档第 20、7、18、5、10 页占据。它们原先排在 11–15，获得约 0.218–0.225 加分。
- 第 4 页 baseline 归一化分数为 0.995684；晋升后第 5 名页面的 baseline 分数为 0.914000，原差距只有 0.081684，但后者 bonus 为 0.218227，足以反超。

这些晋升页与同一研究相关，不代表它们能替代问题所需的尺寸证据。这里先确认的是页面 gold 排名损失，不把未逐段人工审核的非 gold 页一概认定为语义无用。

**比较两项研究的纳入／排除标准，query `eb28ec1d-f888-4c45-ba3b-d40171a0ccd4`：**

- 第二项研究的 gold 页从 rank 13 → rank 3，说明图确实能促上漏页。
- 第一项研究的 gold 页从 rank 1 → rank 7，同时被挤出 Top-5。
- 这是典型的“补回 B，却丢掉 A”：单页加分没有表达比较任务需要同时保留两侧证据。

也有正向案例：开幕式问题的 gold 页 rank 11 → 5；Federer 2004/2005 问题的 gold 页 rank 12 → 2。但三处 page gain 不足以抵消全体损失，也不能直接等同答案充分性提升。

证据：[B 逐页排名](stage2_edge_construction/outputs/pilot_e0_stage1_v1/query_conditioned_retrieval/target_only_page_rankings.jsonl)、[B 逐题审计](stage2_edge_construction/outputs/pilot_e0_stage1_v1/query_conditioned_retrieval/target_only_fusion_audit.jsonl)。

## 4. 此次不能把主要责任归给 Stage 1 漏召回

之前提出“静态剪枝可能限制后续收益”仍是一般风险，但这轮数据给出了更具体的判断：

- 实际检索扫了完整 **950,871** 对，不是只在 clustering 的 5,000 对样本上走图，也没有应用全量 RepresentativeSubset 的 Balanced ABC。
- 每个 arm 实际评分 **32,220** 条有向候选边，累计 **3,335** 个非 seed query–page exposure，平均每题约 139 页。
- Baseline Top-10 漏掉的 5 个 gold 页，实际 trace 中均存在，说明至少这些缺口没有在本轮 seed 选择／候选图阶段消失。

| Query ID 前缀 | gold 原 rank | B 最终 rank | C 最终 rank | D 最终 rank |
|---|---:|---:|---:|---:|
| 45db14c0 | 11 | 5 | 5 | 5 |
| 4a5f4ed0 | 17 | 10 | 11 | 12 |
| 4ba09a15 | 40 | 27 | 27 | 27 |
| df2f051f | 12 | 2 | 2 | 2 |
| eb28ec1d | 13 | 3 | 3 | 3 |

可见同时存在“促上但抵消其他证据”“仍然没排够高”“edge 通道反而略降名次”。下一步先定位评分与融合，当前没有证据要求立即再扩候选图。

需要保留一个口径区别：[opportunity audit](stage2_edge_construction/src/audit_query_candidate_opportunity.py) 第 37–64 行从 seed 页的**所有 node**出发；实际 retrieval 每页只选**一个 node**。两者的可达上限不能直接等同。本文的 5/5 结论已额外使用实际 edge trace 核验，不是照抄宽松审计中的 100%。而且可达 gold 页不等于到达了该页内正确的证据 node／span。

## 5. 为什么加 edge 表示和 clustering 没有扭转局面

### 5.1 C 目前只是固定的几何打分，没有关系或增量证据学习

[edge_representation_scoring.py](stage2_edge_construction/src/edge_representation_scoring.py) 第 23–28 行：

\[
C=0.50\,target+0.35\,alignment+0.15\,shared.
\]

其中 alignment 比较 `normalize(q−source)` 与 `normalize(target−source)`，shared 比较 q 与 midpoint。系数固定，未根据独立训练数据学习什么关系对什么问题有帮助。

进一步令单位向量间 \(a=q^Th_t\)、\(b=q^Th_s\)、\(c=h_s^Th_t\)，非零分母时：

\[
\cos(q,\widehat m)=\frac{a+b}{\sqrt{2+2c}},\qquad
\cos(\widehat{q-h_s},\widehat{h_t-h_s})=
\frac{a-b-c+1}{\sqrt{2-2b}\sqrt{2-2c}}.
\]

所以当前 C 是三种两两相似度的固定非线性组合。它确实依赖 source，但没有显式学到“这个 target 补了当前答案缺少的哪个条件”。这不证明这种几何永远无用，只说明它的收益必须实测，不能由方向性或 source 替换后分数变化推出。

B 与 C 的 Top-5 **集合在 4/24 题变化，有序列表在 7/24 题变化**，但 Top-5 gold 指标完全相同。不是评分没有动，而是变化没有改善评估中的证据命中。

### 5.2 D 的 prototype 是小扰动，且没有额外关系监督

实际 D 是 `0.90*C + 0.10*prototype_context`，使用 5,000 pair／10,000 directed edge 拟合的 32 个固定原型；原型随后分配给完整的活跃边。它没有运行 query-adaptive clustering，也没有把完整候选边做训练式更新。

C → D 的 3,335 个 graph 页面最终融合分数绝对变化：中位数 **0.001679**、均值 **0.001659**、最大 **0.005269**。相较约 0.16–0.22 的原始 graph bonus，这个改动很小。

实际 Top-5 集合 **24/24 都不变**，只有 2 题内部顺序改变，且没有改变 Top-5 gold 指标。结合此前已观察的文档集中现象，这些原型没有显示出足以改善证据排序的独立信号。

这不是建议直接加大原型权重。加大未经验证的语义信号可能放大同主题偏置；应该先在统一融合下确认原型分数能区分有用与冗余／错误条件的候选。

[Prototype Update Report](stage2_edge_construction/outputs/pilot_e0_stage1_v1/prototype_updates/middiff_k32_seed17_t0.1/PROTOTYPE_UPDATE_REPORT.md) 描述的是采样边的几何变化。完整候选更新 E 仍未评测，不能把 D 的检索结果当作已验证了训练式 dynamic edge updating。

## 6. 最新 QKV 为什么仍没收益

### 6.1 运行的是确定性 probe，训练模块尚未被使用

[run_qkv_attention_probe.py](stage2_edge_construction/src/run_qkv_attention_probe.py) 第 48–68 行用手工拼接的 query、source residual、target、midpoint、difference 构造 Q/K/V，权重固定为 0.50/0.35/0.15，没有训练。

[qkv_edge_attention_model.py](stage2_edge_construction/src/qkv_edge_attention_model.py) 定义了可训练模块，但本次 probe 没有调用它，没有已验证的训练 checkpoint。因此当前结果能评价固定几何启发式，尚不能回答“学习后的 edge-to-edge attention 是否有效”。

### 6.2 legacy 版本的 attention/V 没参与最后的页面排序

旧版 `legacy_max_qk` 用每页最大的 `0.5+0.5*QK` 加分。Softmax、加权 V 和 NO_EXPAND 被计算并记录，但最后排名仍来自 max QK。

无原型版本的 QK 与 C scorer 在代数上等价。对这套实现，加入 softmax 的名字不会增加最终评分能力。不能将其负结果写成“attention 聚合已经试过且无效”。

### 6.3 value-aware 消费 V，但 NO_EXPAND 被归一化抵消

Value-aware 定义页面质量：

\[
m_p=\sum_{e\to p}\alpha_e v_e,
\quad\alpha_e=\frac{\exp z_e}{Z},
\quad G_p=\frac{m_p}{\max_r m_r}.
\]

于是：

\[
G_p=\frac{\sum_{e\to p}\exp(z_e)v_e}
{\max_r\sum_{e\to r}\exp(z_e)v_e}.
\]

这里的 v_e 是 `0.5+0.5*Qvalue·V` 标量兼容分数。Softmax 分母 Z 完全抵消，**包括 NO_EXPAND 对 Z 的贡献**。无论 NO_EXPAND 的概率怎样变化，它都不能通过这条计算路径抑制 graph bonus。当前候选的 V 兼容因子为正，因此每题质量最高的候选页最终固定获得满额 **0.25** 加分。

代码没有执行“选择 NO_EXPAND 则不扩展”的决策。现有 no-expand attention 约为 0.000229–0.014091，但真正的问题不仅是值小，而是没有进入最终决策。相关代码为第 70–85 行。

### 6.4 页面聚合高度受候选边数量影响

同一 target 可以从不同 source 到达，一页也可以有多个 target node。当前对该页所有路径的 attention×V 分数求和，没有将重复 target 或近重复证据视为相关观测。

本次依据保存的 QK/value logits 重新计算真实 softmax 和 page mass，得到：

| Value-aware arm | 每题页面 mass 与候选边条数的 Pearson 相关系数中位数 | mass 最大页也处于边数最大页集合 |
|---|---:|---:|
| none | 0.99454 | 22/24 |
| node | 0.99427 | 21/24 |
| edge | 0.99463 | 22/24 |
| node_edge | 0.99406 | 21/24 |

这是强烈的数量偏置迹象。相关性并不单独证明因果，需要 count-only、按 unique target 去重、mean／max 聚合消融才能分离数量与语义贡献；但它足以说明，不能把当前 mass 增大解释为“获得更多独立证据”。

四组 @3/@5/@10 召回相同，edge 与 none 的全部已保存逐题指标相同；node/node_edge 仅少数题的 nDCG 有微小变化。最明显的变化来自从 max QK 改为 mass 聚合，而不是 edge clustering 带来的改善。

### 6.5 发现了日志错误；它影响分析，不是这次排序下降的直接原因

第 88 行生成 trace 时，`attention_weight` 引用了前面循环最后一个 `weight`，导致同一 query 的所有边都写入同一个 attention 值。四个 value-aware arm 的 24/24 题均有这个现象。Trace 的 `page_score` 也记录了候选的旧 QK score，而不是 value-aware 最终的归一化 page mass。

本文**没有直接使用错误的 logged attention**计算上述相关系数，而是从每条边的 `qk_logit`、`value_logit` 加上 NO_EXPAND logit=0 重建。重建的每题 @3/@5/@10 nDCG 与已保存指标全部一致，因此可以确认本文分析的是实际执行的融合结果。

这项日志错误应先修复，避免后续 attention 可视化产生错误解释；但正确重建后排名仍然下降，不能把无收益全归因于日志。

## 7. Protected Top-5 与旧实验应怎样解读

`protected_baseline_topk=5` 将原前五页按原顺序拼到最终结果前面，再接图重排后的剩余页。因此所有 @3/@5 指标必然等于 baseline，改不了也掉不了。这可以作为损失定位控制，不能作为 Top-5 改善方案。

该版本 @10 新增 3 个 gold occurrence，同时丢 3 个，完整覆盖仍为 19/24。说明仅保护前五没有解决后续竞争的增量收益问题。

旧 EvidenceNet 结果提供背景，但不是这轮失败的同一个原因：

- [11 月 1 日方向关系机会审计](../EvidenceNet/output/directional_relation_opportunity_audit_v1_20261101/RESULTS.md) 只有 12 个 query–target 机会、7 题有可用 target，K=5 对 24 题均不构成竞争，108/120 扩展位由 dense fallback 填充。那轮无法充分检验表示选择能力。
- [11 月 4 日 KG 诊断](../EvidenceNet/output/kg_graph_pipeline_diagnosis_20261104/REPORT.md) 的小图只有一个实际可达路线，且走向与 query 不一致的 auditor 信息。不能把那套稀疏覆盖结论搬到当前 95 万 pair 的候选图。
- [D1 预算匹配报告](../EvidenceNet/output/budget_matched_dense_control_v1_20261106/BUDGET_MATCHED_REPORT.md) 与 [Custom 111-query 报告](../EvidenceNet/output/custom_vldocir_benchmark_v1_20261106/CUSTOM_111_RETRIEVAL_REPORT.md) 观察到部分 query-conditioned retrieval 收益；D1 使用 subquery 扩展，未将 unknown edge 计入正式导航，不能算成 edge 的收益。

另外，当前 DynamicEdgeGraph 代码直接在冻结的 hybrid_visual 页面分数上融合，没有调用历史实验的最终 BGE reranker。因此**不能把这轮负结果归因于 BGE 抹掉收益**。

## 8. 我建议接下来先做什么

以下是下一轮建议，本次均未修改或运行。优先在现有缓存上验证机制，暂不新增大规模模型训练或候选图。

### P0：让结果可核验，并消除已确认的融合问题

1. 修复 trace 的逐边 attention 和实际最终 page score；保存 QKV 最终 page rankings。将新 probe 纳入统一比较表，但保留“untrained”状态。
2. 建立一次完整 replay：必须复现 baseline、原 B/C/D、value-aware 逐题指标及新增／丢失页。关闭 graph 时应严格恢复 baseline。
3. 将“进入候选池”和“最终排序”分开：保留 seed 与新候选可共同参与排序，用共同且明确的打分契约比较。不能一边给旧 Top-10 永久零 bonus，一边给新页普遍正偏置，再把降分全部归于 edge。
4. NO_EXPAND 必须能实际使本题／本轮 graph contribution 为零，且不能在后续按最大值归一化时又消去门控。允许保持 baseline，不应每题强制有一页拿满 graph weight。

这里不要求把所有旧 Top-5 永久锁死。需要避免无依据的替换，同时保留真正有用的新证据进入前五的机会；“保证所有测试题不掉 gold”不能作为使用测试 gold 调参的目标。

### P1：做三组能定位原因的低成本消融

| 对照 | 固定什么 | 判断什么 |
|---|---|---|
| graph 候选常数加分／纯 count-only vs 实际 scorer | 同 seeds、候选、页面融合和预算 | 当前效果有多少只是候选身份或数量造成 |
| unique-target 去重后的 mean／max vs 当前 sum | 同 Q/K/V 和候选 | 重复路径及页面长度是否在主导 |
| target-only vs pair vs prototype | 同已修正融合、拒绝机制、候选预算 | edge 与 clustering 的独立贡献 |

评价同时报告 gain、loss、净变化、RecallAll、nDCGAll 和不扩展次数。对比任务额外记录“补回一侧时是否保住另一侧”，避免只统计新 gold 页而漏掉被挤掉的证据。

这轮的 5 个漏页都已评分，所以优先修评分和融合；仅当更严格的 node/span 审计发现候选确实缺少所需内容时，再研究补召回，不先扩大 Top-K 或 hop。

### P2：机制成立后，才决定训练什么

如果修正后的 pair 仍不优于 target-only，最缺的是**独立的 query–source–target 增量用途信号**。模型需要判断：target 相对当前已保留证据补了什么，是否匹配实体／年份／实验条件，以及替换哪条旧证据更合算。

可以先构建小规模独立标注和训练/验证划分，再比较小型交互 scorer 与几何基线；不要把冻结 node embedding 接上 QKV 接口就视为已学习。Clustering 继续作为可选的原型特征或计算路由，对照无 cluster；只有它在质量或计算成本上有独立收益，才值得增加复杂度。

当前每个 arm 都遍历相同的 32,220 条活跃边，cluster context 并没有减少这部分评分量，因此本轮也不能声称已验证聚类带来的稀疏计算收益。

## 9. 本次分析的证据边界

本报告中的 gain/loss、实际可达性、C/D 分数差、排序变化、QKV 数量相关性来自对现有 JSON/JSONL 的只读复算。未生成新 embedding、关系标签或实验排名文件。文中对源码的定位以本次工作区为准，代码可能包含未提交修改。

已确认的是本 Pilot 上的融合损失、无效 NO_EXPAND、日志缺陷和缺少训练；“新的融合／监督能否让 edge 真正获益”仍需下一轮独立实验，不能从当前诊断直接保证。


## 10. 对所贴 Value-aware 比较结果的进一步核对

本节核对用户贴出的数值与结论，仍不修改代码。比较表的指标与保存的 manifest 一致；需要补上 no-edge 基线，才能判断是否真正有图收益：

| 方法 | RecallAll@5 | Recall@5 | RecallAll@10 | nDCGAll@10 |
|---|---:|---:|---:|---:|
| No-edge | 66.67% | 83.33% | 79.17% | 62.34% |
| 原 C / QKV none | 54.17% | 64.58% | 62.50% | 48.43% |
| Value-aware，无 cluster | 54.17% | 66.67% | 79.17% | 59.73% |

因此，Value-aware 相比原 C 有恢复，但 Top-10 完整覆盖只是回到 no-edge 的 19/24，Top-5 完整覆盖仍是 13/24，低于 no-edge 的 16/24；没有证明 V 带来超过普通检索的收益。

### 10.1 0.880 / 0.897 来自错误的 logged attention

对 `qkv_attention_probe_value_aware/none/edge_attention_trace.jsonl` 的 3,335 个 query–page 分组，分别使用日志权重与从 logits 重建的真实权重复算：

| 统计方式 | edge count 与 attention mass 的全局 Pearson | edge count 与 attention×value mass 的全局 Pearson |
|---|---:|---:|
| 直接使用日志 `attention_weight` | 0.880480 | 0.897420 |
| 从 QK logits + NO_EXPAND 重建 | **0.893702** | **0.900728** |

用户提供的两个相关系数能由错误日志重现，不能直接用来分析真实 attention 分布。数量偏置的判断仍得到正确重建支持，但应更换统计值，并明确这里是将所有 query–page 合并的全局 Pearson。真实逐 query Pearson 的中位数分别为 0.998988 / 0.994537，与全局统计口径不同。单个 query–page 最大 574 条候选 edge 这一计数正确。

### 10.2 当前代码是每 query 一次 softmax

当前 `candidate=[]` 在 query 循环中初始化，所有 seed 的合法边追加完成后，第 70 行才统一 softmax，并加入一个 NO_EXPAND。因此当前实现是“每 query 全部合法 one-hop edge + 一个 NO_EXPAND”，不是每 seed 各做一次 softmax。

Q 向量虽随 source 改变，最终所有候选仍进入同一个归一化分母。后续若改为每 seed 归一化，应明确作为新实验，不能将现有结果按那个机制解释。

### 10.3 两个结论应收窄

- 四种 context 指标接近，支持“本轮没有观察到 prototype 的有效增益”。代码确实将 node/edge prototype 加入 Q 或 edge 通道；指标相同不等于实现没有使用 prototype。
- 高相关支持存在数量偏置，不能单独证明 Top-10 变化全部由 degree 导致，也不能推出所有跨 edge 求和都不合理。多条独立证据的支持可以累积；当前缺少对重复 node、同页切块、多个 seed 指向同一证据的区分。需要 count-only 和去重控制，才能归因。

### 10.4 `(seed,page)` 池化是合理对照，但不自动完全 degree-invariant

如果先对全部 edge softmax 再在页内取 mean，原 softmax 分母仍依赖其他页面的边数；跨 seed 时还可能改变 seed 间的相对权重。对每个 seed-page 算一个分数之后再跨 seed 求和，也仍受命中该页的 seed 数影响。

更清楚的零训练实验契约是：

1. 固定 seed 集合和 seed 权重；先按 target/原始证据身份去重。
2. 在每个 `(seed,page)` 中分别池化匹配分数和 V 内容，输出一个页面候选，而不是直接把路径条数当证据强度。
3. 在唯一页面候选与 NO_EXPAND 之间分配权重，保持该门控对最终贡献有效；不再用最大页面 mass 归一化消去拒绝信号。
4. 以固定 seed 权重聚合，显式决定多个 seed 命中同一证据是否算独立支持。
5. 增加“复制同一 edge / 将同一内容切成更多 node”的扰动检查。如果原始信息未变，页面分数不应仅因重复计数上升；真正不同证据的增加另行评价。

Max、mean、log-mean-exp 等都有信息损失或选择偏置，先作为受控对照，不宣称某个池化公式已经解决关系建模。应区分“对重复计数不敏感”与“忽略所有候选数量”：后者可能丢掉真实的多证据支持。

“QKV 可以零训练运行”在当前固定几何 probe 中成立；它不意味着新定义的可训练投影无需学习，也不意味着这些权重已校准为语义关联或证据充分性的概率。
