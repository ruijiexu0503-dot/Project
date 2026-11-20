# DynamicEdgeGraph：Clustering 审查与 Query-conditioned 研究建议

日期：2026-11-10。范围：只读检查任务书、代码和已有产物，补充数学推导与下一步实验方案；本次只新增本文，不修改代码、不启动训练或 GPU 作业。

审查基于当前工作区，Git HEAD 为 `6cb4b4e`；Stage 2 目录尚有未跟踪文件，不能仅凭该 commit 复现本文看到的全部内容。下文区分已核实事实、数学推导和未运行的建议。

## 1. 我的判断

**“两个 node 在某个 query 下可能有联系”的直觉合理，但更准确的研究对象是：在当前问题和已有证据下，这个 pair 是否值得联合读取。** 这很适合用 query-conditioned scoring / attention 表达。Query 可以改变比较维度、相关性和证据用途，不能凭空使支持、因果等事实关系成立。

你现在的 clustering **作为 E0 几何诊断是合理的，作为已经发现了关系类型的模型则证据不足**。主要问题不在 K-means 算错，而在于：

1. 输入是冻结 node embedding 的代数组合，尚未验证其中有跨主题可复用的关系信息。
2. 当前 hard clustering 不含 query，不能直接表达同一 pair 随 query 改变的用途。
3. Stage 1 永久删除的 pair，后续 clustering / attention 无法通过改变权重恢复。
4. 已有评估主要检查代数性质和聚类构成，尚未检验 pair 对回答问题的增量价值。

**建议保留当前 E0 和 Stage 1 工作点，先验证“候选够不够”和“pair 比只看 target 多提供了什么”，再判断 clustering 是否值得成为必需模块。** 下一步优先做小型诊断与消融，不立即扩大聚类或训练复杂 QKV。

## 2. 当前实际完成了什么

这里以代码和已落盘产物为准，不能把设计稿中的功能当作已实现。

| 项目 | 已核实状态 | 能说明什么 |
|---|---|---|
| 全量 Stage 1 Balanced v1 | 1,495,665 个无向候选 pair；有封装与 readiness 审计产物 | 候选数据已形成；不代表关系真实或高关系召回 |
| 当前 Stage 2 数据 | `pilot_e0_stage1_v1`；7,291 个原始 node，7,288 个可用向量，32 个文档 | 独立 Pilot，不能直接套用全量实验结论 |
| 当前候选抽样 | 五路 Top-100 union 共 950,871 对，均匀 reservoir 抽 5,000 对 | **不是 Balanced ABC 筛选后的样本** |
| 边表示 | 同一个 Qwen3 1024 维空间；10,000 条双向表示；已有 mid/diff/middiff/concat | 多路候选检索已用上，但边表示还是单编码器视图 |
| 已完成的聚类 | mid 与 middiff；各一次 `K=32, seed=17` spherical K-means | 无 K/seed 稳定性比较、soft membership 或 query 条件化 |
| 正反边同簇率 | mid 100%；middiff 49.5% | 端点交换的几何敏感度，不是方向准确率 |
| 审核数据 | 160 对 review sheet，均为 `UNREVIEWED` | 尚不能评价语义关系准确率或独立 query utility |

证据：[pair manifest](stage2_edge_construction/outputs/pilot_e0_stage1_v1/pair_manifest.json)、[数据审计](stage2_edge_construction/outputs/pilot_e0_stage1_v1/data_inventory.md)、[build metrics](stage2_edge_construction/outputs/pilot_e0_stage1_v1/build_metrics.json)、[mid 报告](stage2_edge_construction/outputs/pilot_e0_stage1_v1/clustering/mid_k32_seed17/report.md)、[middiff 报告](stage2_edge_construction/outputs/pilot_e0_stage1_v1/clustering/middiff_k32_seed17/report.md)。这些输出位于 Git 忽略目录，以本地文件为准。

任务说明有版本差异：

- [11 月 8 日设计稿](STAGE2_DIRECTED_MULTI_VIEW_DYNAMIC_EDGE_DESIGN.md) §6 把聚类定义为可选的 soft relation prototypes，并设想后续 edge-to-edge attention。
- [11 月 9 日任务书](../docs/stage2_codex_handoff.md) 第 19–23 行把 Stage 2 定为 query-independent edge construction，把 query-conditioned 使用放在 Stage 3。
- 当前 [Stage 2 README](stage2_edge_construction/README.md) 第 5–16 行仍主要描述早期数据不足和 local-window 路径。最新 Pilot 已有兼容的 7,288 行向量及五路候选，但仍未严格迁移 Balanced ABC。

如果现在概括为“Stage 1 路由，Stage 2 clustering”，应补充：**clustering 负责组织或压缩 pair 表示，query-conditioned 使用负责本次任务中的选择。** 两者不能由一次离线聚类同时完成；是否沿用 Stage 3 这个名称是接口命名问题。本文按你这次提出的研究方向讨论，不把旧任务书的阶段命名当作不能调整的限制。

## 3. 对现有 clustering 的具体审查

### 3.1 E0 保留端点信息，但没有自动提取关系

[representations.py](stage2_edge_construction/src/representations.py) 第 9–20 行实现：

\[
m_{ij}=\frac{h_i+h_j}{2},\qquad \Delta_{ij}=h_j-h_i,\qquad e_{ij}=[m_{ij};\Delta_{ij}].
\]

MidDiff 可以还原两个端点，这是有用的基线性质；但可逆变换不会自动产生“支持、比较、补充条件”等关系知识。两对 node 具有相同关系模式，却来自不同学科时，E0 未必接近；同一篇文章内没有直接关系的段落，却可能因为共同主题而接近。

目前最准确的名称是 **pair embedding clustering**。只有验证“跨文档、跨主题的相同关系模式能聚到一起”，才能进一步称为 relation prototypes。

### 3.2 MidDiff 有隐含尺度偏置，整体 L2 不能消除

当前 node 向量范数实测约为 1，因此令 \(s=h_i^\top h_j\)，有：

\[
\|m\|^2=\frac{1+s}{2},\qquad \|\Delta\|^2=2(1-s).
\]

默认 `[m; Δ]` 没有控制两个部分的相对能量或距离贡献。例如 \(s=0.8\) 时，两块能量为 0.9 和 0.4；\(s=0.2\) 时为 0.6 和 1.6。对整体做 L2 只统一总长度，不改变块间比例。

当前样本中，差值块占总平方范数的比例中位数为 **51.58%**；**55.58%** 的 pair 中差值块能量大于 midpoint 块。这是几何事实，不是关系效果优劣。

一个有用的控制表示是：

\[
e^{\mathrm{orth}}_{ij}=\left[\sqrt2 m_{ij};\frac{\Delta_{ij}}{\sqrt2}\right]
=\left[\frac{h_i+h_j}{\sqrt2};\frac{h_j-h_i}{\sqrt2}\right].
\]

它是 `[h_i; h_j]` 的正交变换，保留内积、欧氏距离和余弦几何。在相同初始化行、相同算法和精确计算下，两者聚类应等价，实际允许浮点误差。因此，普通 MidDiff 与 concat 聚类不同，首先说明**距离度量改变了**，不能直接说 MidDiff 学到了更强关系。

建议下一轮小实验比较 concat、当前 MidDiff 与一个明确的块权重变体。若分别单位化两个块，必须处理近零差值，避免把微小数值扰动放大成强方向信号。

### 3.3 “文档熵”没有测量具体文档身份

[cluster_edges.py](stage2_edge_construction/src/cluster_edges.py) 第 52–59 行只区分 `same_document / cross_document`，`document_entropy_bits` 是这两个状态的二元熵，**没有统计具体 document ID**，无法判断一个簇是否被一篇文章主导。模态熵同样仅区分同模态／跨模态，无法区分 TEXT→TABLE 与 IMAGE→TEXT。

读取已有 labels 和 edge metadata，只读重算得到：

| 指标 | mid | middiff |
|---|---:|---:|
| 按簇大小加权的最大 source-document 占比 | 69.44% | 55.28% |
| 按簇大小加权的最大无向 document-pair 占比 | 61.26% | 48.34% |
| 保持簇大小与文档频率的置换参考：第一项均值 | 11.47% | 11.24% |

第一项为 \(C_{doc}=\sum_k\max_d n_{kd}/N\)，其中 \(n_{kd}\) 是簇 k 内 source 文档 d 的边数；第二项把 d 换成无向文档对 ID。全局最大 source 文档仅占 10.06%。MidDiff 的 cluster 17 和 26 分别有 236、393 条边，source 文档各自 100% 来自一个文档。

全样本涉及 5,273 个 node，同文档 pair 占 **72.62%**、跨模态占 **12.44%**。置换参考固定 labels，随机重分配 5,000 对的 metadata，正反方向同步置换，seed 为 20261110，共 200 次。这控制了总体文档频率和反向配对，**未完全控制共享 node、图结构和采样依赖，因此只作探索性参考，不给显著性结论**。

这些结果表明存在强文档集中信号，但不能据此断言“所有簇都是主题簇”或“关系无效”。下一步补具体 document ID、文档族／领域、完整有向模态对、node 复用度，以及跨主题的独立关系评估。更少文档集中也不自动等于更好的关系表示。

上述统计只读取 `edge_metadata.jsonl`、`edge_embeddings_{mid,diff}.npy` 和两组 `labels.npy / centroids.npy`；未保存新数组或改写实验结果。

### 3.4 hard K-means 无法完整表达一个 pair 的多种用途

当前代码逐行 L2，然后点积分配、单位化均值更新中心，是合理的 spherical K-means 基线。mid / middiff 分别在 **23 / 45** 轮收敛；现有标签与最终中心的最近分配一致。此次未发现未收敛导致的结果错误。

但每条边被强制归入一个簇：没有多重成员、未适配原型状态或 query 输入。一个 pair 同时适合“比较实验”和“补充条件”时，一个 cluster ID 不够表达。

后续可试 top-m soft membership，同时保留原 pair 信息。Soft membership 也不是关系概率；softmax 会为离群 pair 分配总计为 1 的权重，需保留距离／不确定状态，允许所有原型都不适用。

聚类还存在两个不同目标：

- **关系原型：** 希望复用关系模式，主要评价跨主题语义和下游效用。
- **计算路由：** 用簇减少评分对象，主要评价召回／成本曲线。

若只把 cluster 得分加到排序里，最终仍遍历全部边，不会自动节省计算。若用 cluster 硬筛候选，则又引入一层漏召回；两种方案应分开评价。

### 3.5 抽样与评估尚不足以证明关系聚类有效

[prepare_stage1_pilot_pairs.py](stage2_edge_construction/src/prepare_stage1_pilot_pairs.py) 第 10–29 行是 union 内的均匀 pair reservoir。它适合估计该 union 的几何，但不保证少数模态、互补关系、低相似度有用 pair 或每个 node 都被充分覆盖。

只审核保留 pair，无法估计 Stage 1 漏掉多少有用 pair。现有 160 对表可复用，但需独立候选外评估池。`NO_RELATION` 应解释为“在给定证据范围内未发现所评估的关系”，不能解释成“对所有未来 query 永远没有用途”。

正反同簇率主要受表示设计影响：mid 必然相同，diff 必然反号，都不是语义方向测试。下一轮需同时包含方向性关系和对称关系，审核两端实际角色，不能以更低的反向同簇率作为目标。

### 3.6 实现边界：应记录，但不是首要研究瓶颈

- **确认的统计问题：** [build_edges.py](stage2_edge_construction/src/build_edges.py) 第 23–28 行只在输出归一化开启时统计零向量。当前 `build_metrics.json` 中 diff 的 `zero_output_rows=0` 不是真实数量；[metrics.json](stage2_edge_construction/outputs/pilot_e0_stage1_v1/metrics.json) 和实际数组都有 **6 条零差值有向边，即 3 个不同 node pair**。已运行的 mid/middiff 不因此失效，未来 diff 聚类应处理零向量。
- **规模风险：** [cluster_edges.py](stage2_edge_construction/src/cluster_edges.py) 第 84–90 行虽 mmap 读取，随后归一化仍生成完整浮点矩阵，元数据也全量读取；适合 10,000 边，不能据此认为已支持百万边流式聚类。
- **验证不足：** [evaluate_edges.py](stage2_edge_construction/src/evaluate_edges.py) 第 17–18 行只检查 MidDiff 还原结果有限，未与原始端点逐项比较；不能单凭该字段声称已测还原精度。

本次仅记录，不修改实现。

## 4. Attention 类比具体成立在哪里

### 4.1 分开离线表示、query 适用性与增量用途

建议使用三个概念：

\[
e^0_{ij}=g(x_i,x_j),\qquad s_{ij}(q)=f(q,x_i,x_j,e^0_{ij}),\qquad U_{ij}(q,S).
\]

其中 \(e^0\) 是可复用的 pair 表示，\(s\) 是 query 下的适用分数，\(U\) 是相对于当前证据集合 S 的增量用途。

例如，假设 A、B 分别给出两个模型的实验结果：比较模型时值得共同读取；只问 A 的参数量时 B 可能无关；S 已含 B 的同一结果时再次读取可能无增益。这些变化不要求事实关系随 query 改变。

S 很关键：**query relevance 不等于补充了缺失证据**。同一事实换一段文字，可能得到高 attention，却没有新信息。项目的 [Query–Edge Utilization 说明](../EvidenceNet/docs/QUERY_EDGE_UTILIZATION_COPILOT_NEXT_STEPS.md) 也区分 validity、applicability 和 marginal utility；本文借用概念，不将旧图结果当作当前 DynamicEdgeGraph 的实测结果。

### 4.2 用户 query 必须明确进入计算

可研究的形式是：

\[
u_i=F(q,h_i,S),\quad k_{ij}=K(e^0_{ij}),\quad
\alpha_{ij}=\operatorname{softmax}_{j\in C_i(q)\cup\{\varnothing\}}
\left(\frac{u_i^\top k_{ij}}{\sqrt d}\right).
\]

\(\varnothing\) 表示可以不扩展，也可另设停止／拒绝机制，具体需校准与评估。V 可以携带 pair 状态或 target 证据信息；原始 node 与来源仍保留。高维边状态、标量路由分数和读取原文是三个不同对象。

标准 attention 的 Q 是匹配 K 的查询向量，不自动等于用户问题。原设计稿中由 edge 自身产生 Q，只使它依赖 pair 或图上下文；不输入用户 q 就没有用户问题条件性。[Attention Is All You Need](https://arxiv.org/html/1706.03762v7) §3.2 给出 Q/K/V 的定义，这里的用户 q 区分是针对本项目的应用分析。

Attention 权重是候选内部的相对分配，不是“关系成立概率”。所有候选都无用时，普通 softmax 仍会分配总计为 1 的权重。新投影、门控或 QKV 必须有训练目标，随机初始化模块不能因为连接冻结 encoder 就被视为学会了关系。

### 4.3 加上 QKV 仍可能退化成 target 检索

假设 Q 仅来自用户 q，K 是 E0 的线性投影，使用未做 pair-dependent 归一化的 mid/diff/middiff/concat，则点积分数均可写为：

\[
s(q,i,j)=a(q)^\top h_i+b(q)^\top h_j.
\]

固定 source i，在邻居 j 内排序或 softmax 时，第一项为常数，排序只取决于 target 和候选 mask，没有建模 source 与 target 的联合条件关系。若端点均单位化，concat 的整体范数恒定，该结论在其 L2 后仍成立。

**边界：** mid/diff/middiff 若逐 pair L2，分母依赖 pair，严格可分解结论不再直接成立，但几何尺度调制也不证明关系语义。跨不同 source 全局排序时，source 项不会全部抵消。以上是数学推导，不是当前已实现 attention 的实测结果。

下一步至少做 source 替换测试，但不能只看原始分数是否变化，因为可分解模型的 source 项也会改变。应固定 q、相同 target 候选集和候选 mask，比较替换 source 后的 target 相对排序；人工案例需包含“换 source 后应优先选择另一个 target”的情况。也可检查：

\[
D=s(q,i_1,j_1)-s(q,i_1,j_2)-s(q,i_2,j_1)+s(q,i_2,j_2).
\]

可分解模型的 D 为 0；逐 pair 归一化模型的 D 非零也只证明数值交互，仍需语义判断。可探索 source-conditioned Q、乘积／双线性交互、小型非线性 scorer 或联合读取 q/source/target，先证明优于 target-only。也不能直接将 1024 维 query 与 2048 维 MidDiff 做余弦；投影后的空间对齐需要目标与验证。

### 4.4 Stage 1 应是预算约束，不是对所有未来 query 的否定

若静态保留集合为 \(C_0\)，后续只操作其中的边，则 \((i,j)\notin C_0\) 时，改变 clustering / attention 权重无法恢复它。对固定候选内的 pair 选择任务，在相同标注定义下，最终 useful-pair recall 不会超过候选 recall；这不意味着最终答案只能通过某一个固定 pair 获得。

全量 Balanced 的 92.17% 是 eligible node coverage；按全部 canonical nodes 算为 **85.40%**，另有 **8,166** 个 eligible node 孤立。一个 node 有任意一条边就算覆盖，不代表 query 需要的边存在。根据 [工作点 CSV](stage1_candidate_pruning/outputs/vldocir-abc-score-support-pruning-20261109/normalized_abc_search_126279/recommended_operating_points.csv)，Balanced 保留有效五路 union 的 **6.19%**；4.33% 使用了包含失效 BGE 的旧六路 union 作分母。

[search_abc_normalized.py](stage1_candidate_pruning/src/search_abc_normalized.py) 第 200–206 行主要按接近 150 万边的规模参考选择 Balanced，没有按独立语义或 query utility recall 选优。这是工程工作点，“高召回”仍需验证。

如果小样本证明有用 pair 经常在候选外，再单独试受预算约束的补充路径：

\[
C(q)=C_{base}(q)\cup C_{extra}(q).
\]

\(C_{base}(q)\) 是 query seeds 可接触的静态候选，\(C_{extra}(q)\) 是在线检索产生的少量新组合，例如 seed 与 query 检索候选之间的受限 pairing。补充路径需允许静态图孤立 node 从全局索引进入，否则无法恢复它们；新增 pair 仍是待评分候选。

这是未来独立 ablation，不建议现在重调 Stage 1 或按测试题补边。All-pairs 只需在小型文档子集上用作离线诊断，全库不必物化所有组合。

## 5. 下一步按什么顺序做

以下均为待执行方案，非本次已运行实验。先复用 Pilot、向量和审核表，不扩大到全量 150 万 pair。

### 第一步：固定假设与两套评估单位

保留 query-independent 底座，把 clustering 的目标写成可检验问题：**能否在有限读取预算下选到更有用的 pair，或以更少评分成本达到同等效果？** 若另主张发现关系类别，再单独提供跨主题证据。

| 评估单位 | 审核内容 | 用途 |
|---|---|---|
| `(source, target, bounded context)` | 有依据的联系描述、两端角色、出处、未发现／不确定；允许多种描述 | 判断 pair 表示是否有关系信息 |
| `(query, source, target, current evidence)` | 适用性；新增支持／必要背景／冗余／错误条件／未知；相对被替代 dense 候选是否值得读取 | 判断 query-conditioned 使用价值 |

复用现有 160 对表，补“同关系不同主题”和“同主题无所评估关系”的对照。另安排约 30–50 个同 pair 不同 query、固定 q 和 target 候选集后替换 source 的配对案例作机制诊断，后者比较 target 相对排序而非原始分数变化；这是建议规模，不保证统计功效。合成案例能测机制，不能证明真实检索提升。

审核需能访问完整原文、表格标题／单位和图像；当前 700 字符截断仅适合预览，不能将截断造成的信息缺失判成无关系。隐藏 route score、cluster ID、系统预测，部分样本双人复核并保留分歧。AI 判断标为 provisional，不冒充独立人工 gold。

按文档／文档族划分；正反边、近重复内容同组。跨越两个划分的跨文档 pair 另设评估或排除，不能随机按有向边切分而共享端点。选择 K、权重、温度或 scorer 的数据与最终报告数据分离。现有 24-query Pilot 适合作开发诊断，不能自动支持泛化结论。

### 第二步：先检查 Stage 1 留下多少机会

冻结候选政策，对每个评估 query 记录：

- Dense seeds 是否已充分；还缺什么证据。
- 有用 target／组合哪些在静态候选中，哪些需要补充。
- 实际可达的不同 target 数、与 dense Top-K 重复量、预算是否真的排除了候选。
- 失败发生在 node 表示缺失、Top-100 union 未召回、ABC 剪掉、图上不可达，还是后续评分。

评估池至少含未剪枝候选、保留候选、query 的普通 node retrieval 和少量候选外样本，不能只从已有 5,000 对抽样。可在小文档组枚举 pair 并独立审核，得到局部更完整的候选上限。当前 Pilot 没有严格 ABC，因此不能凭它估计全量 ABC 损失；该项只能在匹配的数据／配置中单独审计。

完整标注时报告 useful-pair recall；多系统合并标注池只能报 **pool-relative recall**，明确漏标范围。分层抽样若推总体统计，需保留采样概率并加权。页面 gold 只支持页面召回评价，不能把同一 gold 页内全部 node pair 当正例。

**决策：** 没有有用组合可达时先研究候选；候选充分时才比较评分。若所有候选都在预算内、无论排序如何都全选，数据就无法区分路由方法，应记录这种不可识别性。

### 第三步：完成有限的 clustering 诊断

固定 pair 集，补 concat 与 diff 对照，检查零／近零差值。可先用 `K∈{16,32,64}` 和三个随机种子作敏感性分析，这是起始网格而非最佳参数。

看具体文档／领域集中、模态对、node hub、簇大小、重采样稳定性及跨文档关系近邻；silhouette 仅作几何诊断。每簇审查中心、边界和随机实例，不能只挑最好看的 medoid。

关系原型泛化实验中，中心只在训练文档拟合，在未见文档赋值评价；若只做全库无标签索引，可另报 transductive 设置，不能混成 unseen-document 结论。

**决策：** 主要按文档／主题组织、没有关系迁移或路由效率收益时，就把它保留为诊断／索引工具，不无限调 K 寻找好看的簇。

### 第四步：拆开 pair 与 clustering 的贡献

| 实验 | 候选与评分 | 回答的问题 |
|---|---|---|
| A：target-only | 现有候选内 q→target 评分，另附预算匹配的普通 dense 扩展基线 | 纯节点检索能做到什么 |
| B：pair，无 clustering | 同候选集，显式使用 q/source/target，允许拒绝扩展 | 联合 pair 是否增加价值 |
| C：pair + prototypes | 与 B 相同原始候选池，增加原型上下文或 top-m 原型路由 | clustering 的额外价值 |
| D：候选补充，条件性执行 | 候选审计显示漏召回时，在 B 上加固定预算新组合 | 能否修复静态剪枝 |

先选一个可控的 B，例如小审核集上的固定联合 q/source/target 判断器，或在独立训练标注上学一个小 scorer，明确监督来源。冻结模型的 pooled hidden state 先称 representation probe。不要同时更换候选、编码器、聚类和 reranker，否则无法定位增益。

C 用原型上下文时控制额外模型容量，必要时加等容量无原型对照；C 用簇筛选时记录筛掉的有用 pair。两种 C 分开报告，不混淆语义增益与计算省时。Top-m 也不能被当作永远不可绕过的语义门槛。

公平性包括相同 seeds、可读证据／token 预算、最终 reranker，以及实际评分 pair 数和调用成本；记录离线建模成本。D 改变候选，应独立报告，不把扩大候选的收益归给 clustering。

主要看有用新证据的 precision/recall、相对已有证据的增量、错误／冗余扩展、拒绝扩展和成本。页面 Recall/AP 与答案准确率分开；未跑回答器不报告答案提升。按 query 报告成功／失败与区间，正反 edge 不算独立样本。记录目标集合是否真的变化、差异是否被最终 reranker 抹去。

### 第五步：根据结果决定唯一值得推进的方向

| 结果 | 后续动作 |
|---|---|
| 候选内缺少有用 pair | 做有预算的 query-time 补充，暂缓复杂边模型 |
| 有用 pair 可达，B 不优于 A | 检查联合输入、监督与 source 条件交互，不先加原型 |
| B 优于 A，C 不优于 B 且不省成本 | 保留 pair scorer，clustering 继续可选 |
| C 保持质量且减少成本 | 定位为计算路由，报告召回／成本曲线 |
| C 在独立数据改善证据选择，且排除容量等因素 | 再研究软关系原型、蒸馏或局部 edge attention |
| 缺少可区分机会或标注不足 | 记录不能判断，补独立样本，不把不显著写成证明无效 |

首个交付应是“小型评估集 + 候选机会审计 + A/B/C 对照设计”，不是更大的聚类模型。

## 6. 最相关的三篇一手资料及边界

- [Attention Is All You Need](https://arxiv.org/html/1706.03762v7)：支持 Q/K/V 加权聚合定义，不能据此把 attention 权重解释成事实关系概率。
- [Efficient Content-Based Sparse Attention with Routing Transformers](https://aclanthology.org/2021.tacl-1.4/)：在线聚类组织 attention queries/keys、减少计算范围，适合借鉴聚类作为计算路由。这里的 query 是模型 token query，不等同用户问题；没有证明离线 MidDiff 簇是关系类型。
- [Global Self-Attention as a Replacement for Graph Convolution / EGT](https://arxiv.org/abs/2108.03348)：说明显式高维 edge channels 可与 attention 共存并更新；不直接验证文档 pair 关系，也不意味着当前应采用完整 EGT。

本文的尺度推导、可分解评分分析、候选补充和实验顺序是本项目分析与建议，不是上述论文已替本项目验证的结论。
