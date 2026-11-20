# 实现任务书：动态 Edge 表示、固定预算多跳检索与小数据训练

日期：2026-11-14。用途：交给新的 Codex 或其他实现模型，独立完成实现与验证。

**本次交付只有任务书。本文的模型、参数、命令接口和实验均为待实现建议；未在本次会话中启动训练、下载或修改实现代码。** 新会话收到“执行本任务书”后，按阶段完成实现及必要验证，遵守工作区适用指令。无需依赖此前聊天才能理解任务。

## 0. 最终决定与任务边界

实现一个只返回有序 Top-K node/page 的检索系统：

> 初始 Dense 检索 → 沿候选边进行预算内多跳搜索 → 动态生成 query / 已选集合条件下的 edge embedding → 选择互补结果集合 → 输出 Top-K 及检索来源。

必须满足：

1. Edge embedding 是共享网络生成的可训练向量；同一条边允许随 query、已选集合变化。
2. 第一轮可以冻结 node encoder 和候选图，但不冻结 edge encoder。新数据集使用自己的 canonical namespace 和独立图，不能套用不匹配的旧 ID。
3. 搜索预算 B 是硬约束；执行前检查。预算有余量且有合法动作时继续，无需学习 stop。
4. 允许 `seed→A→G`。A 可以仅用于探索，也可能本身是需返回的证据；不要求每个中间节点独自回答问题。
5. 最终 K 个结果要考虑互补性。只找到多节点题中的一个相关目标不算完整覆盖。
6. Similarity 是可用特征。局部 answerability、潜在 evidentiality 可以作为辅助预测/监督，但需要实际标签，不能只命名两个 head 就声称实现。
7. 当前不实现完整回答生成、在线事实认证、RL、全库深层 GNN 或必经 clustering。固定 Dense 2 + Edge 2 保留为对照，最终剩余结果名额允许跨来源竞争。
8. 实现成功和实验提升是不同验收结论。结果为负也必须如实交付；不通过改预算、改 Gold 或挑测试题制造提升。

本任务书是当前实现主入口。旧文件中 VQA 主流程、只竞争 Dense 第 11 页、只用固定 MidDiff、强制一跳、第一轮必须同时训练五个损失等设定，不作为这里的要求。

## 1. 工作区、现有资产与保护范围

项目根：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project`。

开始时读取适用 `AGENTS.md`、检查 git 状态与实际运行环境。本次只读时，已有一处 tracked 修改：`DynamicEdgeGraph/stage1_candidate_pruning/src/vldocir_full_analysis.py`；执行时可能变化，不覆盖、回滚或假定它属于本任务。

建议新增独立目录 `DynamicEdgeGraph/dynamic_retrieval/`，包含 `src/`、`configs/`、`tests/`、`README.md`；新数据适配结果和实验输出单独版本化。不要把新训练器混进原零训练 Probe。

主要可复用线索：

| 路径 | 用途与限制 |
|---|---|
| `DynamicEdgeGraph/stage2_edge_construction/src/node_representations.py` | 现有 content/context 与 node 类型整理逻辑；先核查实际输入 |
| `DynamicEdgeGraph/stage2_edge_construction/src/run_edge_utility_slot.py` | 冻结检索、稳定排序、ID/复现逻辑；旧单槽任务不是本任务 |
| `DynamicEdgeGraph/stage2_edge_construction/src/qkv_edge_attention_model.py` | 现有 sparse attention 接口；当前文件没有完整训练循环 |
| `DynamicEdgeGraph/stage2_edge_construction/outputs/pilot_node_representation_v1/` | 旧 Pilot 分层文本，不代表用户自建语料 |
| `DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-pilot-stage1-v1/` | 旧 Pilot 兼容向量和候选，仅对应它自己的语料与 ID |
| `EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011/` | 冻结 baseline，保留原样 |
| `DynamicEdgeGraph/stage2_edge_construction/outputs/edge_utility_slot_v1_20261112_r2/` | 旧 24-query 结果与 route，作为已暴露诊断资产 |

**不要照搬旧 `marginal_page_retrieval_loss`。** 本次读到的实现对 Gold logits 做 logsumexp，只要求正例总质量大；无 Gold 池会自动转成 NO_EXPAND。前者不保证多个必要目标都学到，后者与桥接探索和固定预算停止不符。保持原函数及结果可复现，在新模块实现新损失。

此前已出现过页面入边数量主导 softmax mass、单代表 route 漏内容、500 字符预览截断、文档主题主导聚类等问题。新实现需记录实际可见内容，不能把没有读到的内容判成不存在。

## 2. 数据现状：本次已核实的事实

### 2.1 用户原有 Node 探究数据已经找到

入口：`DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/`，重点读 `DATASET_INVENTORY.md`、`asset_manifest.json`、`split_manifest.json`、`QUALITY_REPORT.md`、`SPLIT_AUDIT.md`。

来源链已记录为：`relation_first_corpus_shadow_v7_cpu → hybrid_49page_stress_prepared_20261007 → hybrid_node_v2_61078/embedding_geometry → own_corpus_edges_v1_20261011`。源说明位于 `EvidenceNet/experiments/own_corpus_edges/README.md`。

| 项目 | 当前核实状态 |
|---|---|
| 规模 | 25 文档、49 页、550 Hybrid nodes；761 parser atoms、72 visual bundles |
| 节点类型 | 474 TEXT、27 COMPOSITE、45 VISUAL、3 TABLE、1 CAPTION |
| 正式 QA / evidence | questions、answers、Gold evidence 均为 0 |
| 划分 | 全部 development-only，train/test 为空 |
| 资产 | 49 页图像及源 node 文件存在；不等于原始 PDF 已核验 |
| 输入缺口 | context_text 全空；45 个节点 content_text 空，需结合视觉类型处理 |
| 标签限制 | HYBRID_SHADOW_CANDIDATE 与 UNVERIFIED_RETRIEVAL_HINT 不是检索/A/E Gold |
| 其他缺口 | 文档族、页尺寸、旋转、物理页序等字段尚需核实 |

这套材料与 VL-DocIR 独立，可优先用于节点/图/预算回归、少量标注后的训练可行性诊断。它长期用于开发，不能随机拆节点后称为独立测试。空 context 保持缺失；重建时必须有真实来源，不猜标题/章节。

### 2.2 已有带监督的 VL-DocIR 抽样可作为 mini 训练来源

入口：`DynamicEdgeGraph/training_data/vldocir_full_sample_v1_20261112_r1/`。

本次只读核对清单与训练 schema，没有读取测试题目/答案文本来设计模型：

| 划分 | query | 关联文档组件语料 | evidence 条目 |
|---|---:|---:|---:|
| train | 800 | 67 | 1451 |
| dev | 200 | 13 | 422 |
| test | 200 | 14 | 382 |

`sample_manifest.json` 规定同题证据文档归同 split、文档组件不跨 split。训练 evidence 包含 document_id、page_number、html_unique_element_id、html_tag、相对 bbox 等字段，存在精确映射到节点的可能，但必须实际核查。

`raw_asset_manifest.json` 标记 94 个文档全部下载；本次看到 raw 文档记录 94 条、页面记录 1475 条、94 个文本子目录。**这只证明原资产层面的存在与清单状态，不证明兼容 nodes / embeddings / 图已就绪。**

旧 `PIPELINE_READINESS.md` 仍记 PENDING_DOWNLOAD、节点/向量 BLOCKED、训练 FORBIDDEN；与新下载清单不一致。执行者需核对门槛产生原因、实际新产物与日志，在新版本 readiness 中记录已满足项。不能仅将旧布尔值改为 true，或因目录存在就宣称就绪。若是尚缺节点/ID/向量，则完成该 mini 子集对应准备再继续；若存在明确权限/用途限制，按其实际条款处理，不推测授权。

### 2.3 新收集的真实文档尚不是监督数据集

`DynamicEdgeGraph/datasets/real_documents_v1_20261113/README.md` 记录 25 个旧文档引用 + 75 个新增 PDF，共 100 文档清单。`pipeline_to_nodes_v1_20261114/manifest.json` 为 75 个 PDF 的节点管线输入，明确无 benchmark questions / Gold。

管线 manifest 存在不代表全部节点处理成功；README 与后续任务状态可能不同，执行时查实际完成产物。当前不把这 75 个 PDF 当现成训练监督，也不继续批量下载。若用于后续域内训练，先完成输入/标签/新文档族划分。

## 3. 能否先用小数据训练：可以，但分两级

### 3.1 第一级：训练链可行性与过拟合诊断

使用 8–16 个**训练 query**，每题选少量固定合法候选，检查：损失可下降，F/G 参数和梯度确实更新，缺失正例排名可提升，同一 q/T 能重放。不能要求每个真实例子必被模型拟合；若在无矛盾、输入完整的诊断样本上仍完全学不动，先定位数据/梯度/实现问题。

已有 24-query Pilot 可以做代码与机制回归；由于已经反复分析，不作为独立 dev/test 或正式提升结论。用它过拟合时必须明确标为 debug-only。

### 3.2 第二级：小规模学习实验

**建议主路线：从已有 VL-DocIR train/dev/test 划分取一个 mini 子集。** 优先复用已标注 query/evidence，同时只处理子集所需的完整文档组件。建议起点目标为约 128 train、32 dev、64 test query；这些数值是工程规模建议，不是保证学习成功的最低样本量。

先按原 split 和文档族/共享文档组件过滤，再采 query；实际数量可以偏离目标，不能为了凑数把组件切到不同 split。已暴露 Pilot 的 query 与文档族要检查重叠，不能把其已反复检查的案例放进独立测试。优先选取完整、可映射的样本，但选择规则不能依据某个方法是否成功或测试 Dense 排名差距。

样本应覆盖单项、多证据、不同模态/内容结构；训练集可以适度增加困难样本，但 dev/test 保留预先声明的自然分布或明确分层，不能只挑图能到达的 Gold。记录每种类型数量，`multi-page` 不自动等于真正的依赖型 multi-hop。

候选语料保留选中文档组件的全部合法页面/节点及固定干扰语料，不能只留 Gold 页。完整 mini 语料的大小与裁剪规则必须声明；在小语料中提升不等于原 94 文档或更大语料中同样提升。

若 mini 学习曲线和 dev 结果有稳定信号，可增加到约 200–500 个独立训练 query；是否需要更多由错误类型与学习曲线判断。不能把同题生成的 1000 条 routes 当成 1000 个独立训练样本。

### 3.3 如果坚持先用自建 25 文档语料

先新增一小批审核后的 query→相关 node/page 标签，包含互补信息组和可信干扰项，再进行第一级训练。问题可由模型起草，但答案、支持位置、必要性和错条件负例必须有审核记录；未审核草案不叫 Gold。

这套长期开发语料用于 train/dev 诊断；独立测试优先使用新文档族及未参与设计的新问题。无需为了凑一个看似完整的 split，把同篇文档的不同页或同题改写分开。

## 4. P0 必须产出的数据契约

阶段 P0 输出新目录中的 `DATA_READINESS.md`、`source_manifest.json`、`split_manifest.json`、`label_alignment_report.md`、`exclusions.jsonl`、`unit_decision.json`。记录原资产 hash、映射依据、无法映射项，不覆盖原始标注。

### 4.1 身份与标签

- `nodes`：canonical node_id、doc_id、page_id、类型、完整 content、独立 context、源文件/区域位置、表示可用性与缺失 mask。
- `edges`：有向 source/target、候选来源集合、类型/特征与缺失标记；相同端点/关系的重复召回合并 provenance，不重复计票。
- `queries_input`：query_id、query 文本及测试允许信息；不包含 answer、Gold IDs、necessary、评估理由。
- `qrels_private`：训练/评估器读取的相关性、标签粒度、来源、审核状态；测试检索进程不加载。
- 可选 `requirements`、`evidence_bundles`、`aux_labels`：保留未知和 mask，不把缺标注填为负。

### 4.2 Node 与 page 两种粒度不混用

优先核查 html_unique_element_id 与实际 node 源元素的精确映射；多元素组装、一对多、bbox 坐标转换必须有审计。不能用相似度猜一个 node 就称为 Gold node，也不能把整张 Gold 页的节点全标正。

**P0 固定主任务粒度。** 若有可靠 node 标签，后续按 node 训练；否则先做明示的 page-level 弱监督版本。允许页级监督/返回与节点图搜索并存，但配置必须分别命名 `B_node`、`B_route_score`、`K_page`，评价使用页级 qrels；不能把同一个 K 同时解释为 node/page。

page 版本仍可在节点图搜索：把预算内实际访问过的节点组织成目标页面内容包，按固定上限与 mask 聚合后产生一次页面分数，标签与损失定义在该页面包上。尚未访问的页面正文不能免费加入；页内哪条 route 正确仍未知。结果中保留访问节点与 route，不能把页正例复制为各节点强正例。

另记录 Gold 页是否进入候选、Gold 元素是否映射成功、相关元素是否实际进入可见节点包。命中页但没读到标注元素时，只能作为页级弱监督；不能把包标成已包含支持信息，更不能在测试阶段用 Gold 指定应读取的节点。强节点/A/E 标签对此应 mask 或标为未读。

### 4.3 候选图与表示

固定原图意味着保持其版本可复现，不是跨语料硬套 ID。mini 新语料缺图时，按已声明 Stage 1 规则仅从允许文档内容构造独立候选图，记录配置/hash；不能用 Gold answer、Gold 目标或测试性能选择边。

node/query embedding 必须来自同一兼容编码器与处理配置；缺 3 个向量等历史情况需要显式排除与计数，不猜映射。第一版允许使用已有 joint embedding，注明它的 context/截断限制；若重新生成 content/context 视图，作为新的派生版本，保留模型实际可见 token 范围。视觉节点不因文本为空被静默删除，应有支持的视觉视图或明确不可用标记。

## 5. 唯一的默认初版网络

第一版采用**冻结基础 encoder + 256 维小型动态 Edge 模块 + 条件排序头**。这是低成本学习验证版本，不先微调整个大语言/视觉模型。若表示本身缺信息，另做读取更完整内容的诊断，不能把该小模型失败等同于所有动态 edge 方法失败。

### 5.1 可训练部分

1. Query/node 的共享空间投影，输出维度 d=256；原始 embedding 维度由 manifest 读取，不硬编码猜测。
2. 状态编码器：对已选目标的可见表示做 masked mean / 固定池化，再与 query 拼接进小型 MLP；空集合有显式 EMPTY 表示，保留已选数量。
3. 基础 edge encoder F：两层 MLP，使用 source/target 有序输入及交互。
4. 动态更新层 G：两层 MLP，输出 d 维残差。
5. 目标排序头 R。集合、A/E、X 头按后续 gate 添加，不在第一轮无标签强开。

默认小 MLP 隐层可取 512、GELU、dropout=0.1、必要 LayerNorm；这些是固定起点，不作性能保证。记录准确参数量并避免大规模超参遍历。

### 5.2 动态向量公式

原始 embedding h 冻结，z=Pωh 是可训练投影结果；不要把 z detach。m 是方向/来源等有依据的 edge 特征：

\[
e^0_{u\to v}=F_\phi([z_u;z_v;z_v-z_u;z_u\odot z_v;m_{uv}]),
\]

\[
c_t=\operatorname{State}_\psi(z_q,T_t),\qquad
e^t_{u\to v}=\operatorname{LN}(e^0_{u\to v}+G_\psi([e^0_{u\to v};c_t;e^0_{u\to v}\odot Wc_t])).
\]

初版只更新当前实际评分的 routes。训练优化 F/G 与投影、状态、R；测试固定参数，根据 q/T 前向重计算向量。不要用逐 edge ID 查表参数，不用测试答案在线更新权重。

训练 F 时不能始终读旧 detached e0 缓存；部署时可缓存与模型版本匹配的 e0。节点编码缓存可以冻结，动态边输出不能跨 query/state 误复用。

### 5.3 候选聚合与评分

按 canonical target 组织不同合法 routes，默认每目标最多 3 条。选择规则在看 Gold 前固定：不同 source/来源优先，再按固定 provenance 顺序打破平局；不得仅为取最高 query–target cosine 而保留一个代表。对重复端点召回合并来源标记。

默认将受限 routes 的动态向量做 masked mean 后交给 R；无 route 用零向量加 missing mask。R 同时接收 q/state、目标表示和 pooled edge，Dense 与 Edge 输出同一尺度的目标分。这里 mean 只防直接重复计票，不保证任意切块或候选组成完全无偏，要做 degree 分层诊断。

page 版本在同一接口前增加固定上限的已访问 node 内容包池化，记录支持哪些输入；不复制标签到每条 route。预算不足导致可见内容不同的情况要保留日志。

返回分可写为 `R(q,T,target,routes)`。探索用 X 概念保留，但初版不训练。节点表示可冻结；edge 表示必须可学习且随 q/T 变化。不能只给固定向量乘一个标量就称为完成动态向量模块。

## 6. 主损失与训练状态

在同一 q/T 下，P 是尚需取得且实际在候选池中的正例，N 是已确认应排在这些正例之后的干扰/重复项。其他必要正例不进入某个正例的负例分母：

\[
\mathcal L_{rank}=\frac1{|P|}\sum_{p\in P}\log\left(1+\sum_{n\in N}\exp((s_n-s_p)/\tau)\right).
\]

默认 τ=1。使用稳定 log-sum-exp；P/N 为空时跳过该项并计数，不转为 NO_EXPAND。分级标签只对已知偏好的项目对计算，未标注项不自动作为确定负例。

P0 必须报告 `P非空且N非空` 的可训练状态比例及负例来源。只有正例 evidence 时，先在训练划分内审核困难负例，或单独建立 `assumed_negative` 弱监督模式并报告抽查错误率；不得改称确定负例。没有有效训练状态时交付数据缺口，不允许全部跳过 loss 却报告训练完成。优先完成一小批审核状态用于过拟合诊断，再扩展有标记的弱监督训练。

训练状态包括空/seed 集合、部分正例、含干扰项的集合；每题先采少量状态，例如 4 个。状态和 routes 的增加不改变独立 query 数。按 query 再按状态平均，避免大 degree、大候选池或同题派生量支配梯度。

若所有 Gold 都是必要且无替代，可用 `(Gold − T)∩C` 作为 P；否则按已审核信息组或替代组合处理。只有 page Gold 时称为标注页覆盖监督，不声称已学到严格充分性。

固定候选训练先隔离排序能力，候选池由推理允许的过程生成。为调试额外注入 Gold 的样本只能单列 diagnostic，不作为真实候选效果。实际不可达/未提议 Gold 要单列，不能用排序损失掩盖。

梯度必须流经 `L_rank → R → e_t → G → F`。具体更完整公式与标签解释见[损失函数文档](LOSS_FUNCTIONS_FIXED_BUDGET_RETRIEVAL_20261114.md)。

## 7. 训练配置与小样本步骤

先用 8–16 个训练 query 做固定候选过拟合诊断。记录每个模块梯度范数、参数变化、正负分差和正例名次，必要时关闭 dropout 以定位梯度问题；这不是泛化指标。

mini 训练的一个起点：AdamW、学习率 1e-3、weight decay 1e-2、梯度裁剪 1.0、每批约 8 个 query、最多 20 epochs、dev 连续 3 次无改善可停止训练。先用 seed=17 跑通；具备可比较结果后用 3 个预声明随机种子复查，不在小 Pilot 上调大量参数。

这些优化设置只适用于上述小型随机初始化投影/MLP，不直接用于全量大模型微调。若执行者改为 Transformer adapter / LoRA，必须另列配置、参数量、学习率、成本和对照，不静默更换默认模型。

checkpoint 保存 F/G/R/state/projection、编码器标识、输入视图、schema、图与划分 hash、训练进度和配置。选 checkpoint 只看 dev 预声明指标，例如 RecallAll@5 为主、nDCG@5 为次；test 只在冻结配置后运行。

训练“早停”用于优化过程，与在线搜索的硬预算停止是不同机制。

## 8. 固定预算搜索：先使用可重放调度

### 8.1 预算必须能在日志中核算

建议将下列配置作为小规模起点，单列多种成本，不将它们含糊地合并为一个“20”：

| 配置 | 初始值/规则 | 含义 |
|---|---|---|
| `output_k` | 5，主报告另算 @10 时使用单独声明的配置 | 最终不同输出单位数 |
| `dense_keep` | 2 | 沿用用户保护 Dense Top-2 的策略；报告其代价，不声称最优 |
| `seed_count` | 2 | 初始图搜索根；与最终保护数量分开存储 |
| `max_unique_nodes` | 20，包括 seeds | 实际访问/评估不同图节点上限 |
| `max_target_scores` | 120 | 每次 q/T 条件下目标重评分都计入，缓存命中另记 |
| `max_route_updates` | 400 | 每次动态 edge 更新计入；不因同 node 曾访问就免费 |
| `routes_per_target` | 最多 3 | 去重后的合法 route 上限 |
| `neighbors_per_expand` | 最多 3 | 每次提议新邻居数量，剩余量不足就缩批 |
| `max_hops` | 默认 2 用于初始受控验证 | 可配置；运行不学习最佳深度 |

相同 query 下若模型重新计算同一 target 的另一状态或 route，须计入评分/更新次数。向量化 batch 不能让计费从多个候选变成一次；另外记录 batch/模型调用、实际内容 token/图像和延迟。

预留最终集合选择预算。例如 K=5、最多 20 个候选、每候选最多 3 routes，保守预留最多 100 次目标评分、300 次 route 更新给最终选择；搜索阶段只能用剩余的对应额度。实际 K_keep=2 时可少用，不能超支。预留参数必须由配置计算并做合法性检查，不硬编码神秘常数。

若使用 page 输出，`max_unique_nodes` 仍数图节点，`output_k` 数不同页。页内实际读到多少节点、页面包池化成本都记录。若运行使用在线原文/图像编码，还需在配置冻结 token/图像/调用上限；只报告 node 数不足以称同成本。

动作前检查各项余额：可缩批就缩批；没有任何动作能在剩余额度内执行时停止。不要先超预算再截断日志。不能在搜索结束后免费执行未预留的集合评估或 Gold 指导回读。

### 8.2 初版调度规则

用固定规则把搜索与模型学习分开：

1. Dense Top-2 初始化种子和候选；保存原始排名。搜索期状态固定为实际保护的 seeds，避免每到一个候选就重新计算全部状态。
2. 维护 Dense 剩余队列与图 frontier。每个周期依次处理一个未访问 Dense 目标、一个 frontier 的小批邻居；其中一侧耗尽时使用另一侧。
3. 只有初始 seeds 是默认图根；Dense 后续补入项先作为结果候选，不自动无限新增深度 0 的根。改变这一规则属于独立实验，避免根不断增加造成深层节点永远轮不到。
4. Frontier 按不同根轮转，优先较浅深度；同深度可按已得 R 排序，稳定 ID 打破平局。低 R 的节点仍保留合法展开机会，不以 A/E 低分直接删除所有桥接。
5. 每次最多提议 3 个未访问邻居，邻居次序由固定的廉价 route 规则产生；跨不同来源不可直接混排未校准原始分数，优先使用来源内 rank 与明确的交错规则。记录未被展开、被预算截断和已访问者。
6. 重复 node/环路不无限消耗预算；新的可用 route 只在固定上限内更新并计费。模型只读允许访问的内容；没有免费预读整个邻域再选一个。

这不是最终的最优自适应策略，而是验证 R/动态 edge 与两跳机制的固定对照。最终来源名额仍可动态变化：保留 2 Dense 后，其余 3 位可全部来自图。学会 X 后再改变动作优先级，需保持同总预算比较。

### 8.3 多跳与返回是两件事

`seed→A→G` 中，A 可以消耗访问预算但不返回；若问题需要 A 与 G 的内容，二者都可以入选。日志必须分清 A 未提议、未访问、被访问但未展开、G 未提议、G 已访问但未入选。

图上不存在/预算内未发现 Gold 是搜索或候选问题，不把它归咎于最终排序 loss。若 A 没有可见线索，有限预算不能保证找到其后所有目标，不编造全局最优承诺。

## 9. 最终集合选择

候选池固定后，初始 T 为被保护的 Dense 结果。每次用 `R(q,T,v,routes)` 选择一个尚未入选的目标，更新 T，直到 K 或预算允许范围；同一 node/page 只出现一次。模型原始输入 q 始终保留，不让错误的需求摘要完全替代 q。

这使相同 v 在“已有 A”和“已有 A+B”时可以有不同新增价值。初版通过含 T 的条件排序训练实现；不得仅取静态分最高的 K 项却宣称已实现集合条件化。

最终返回顺序固定为保护项在前，其余按逐步选择顺序；指标据此计算。若改变顺序，要作为单独配置，不能只为提高 nDCG 临时排序。

完整证据需要超过 K 个输出单位时，标记容量受限，不能把多个 node 包成一个 ID 偷增预算。也不要求必须返回所有替代证据的并集。少量成对组合/备选集合搜索在后续 P4 添加，不能免费枚举全部组合。

## 10. 何时增加集合、A/E 和探索损失

### 10.1 集合偏好

有审核后的同容量 T+ / T− 时，使用 `L_set=softplus(F(q,T−)−F(q,T+))`。T+ 包含有效必要组合，T− 用重复或干扰项替换一项必要内容；删除后仍有替代支持的集合不能标负。

F 必须读取集合交互；训练与推理成本另计。先比较仅条件 L_rank 与加入 L_set 的效果，不先堆叠全部模块。

### 10.2 A/E

- 局部 A：候选提供哪项需求，允许部分支持；多标签 BCE 或明确的分级分类。
- 潜在 E：任务相关信息是否有支持、条件冲突或内容不足；masked CE。
- 教师可在训练划分使用答案/标注生成监督，学生推理输入不包含答案。未审核模型输出标为 provisional，不称 Gold。
- 未标注采用 mask=0；语义上的“内容不足”是另一类有依据标签。仅有数字/引用/答案字符串不能直接当正例。
- 若只能稳定标注一个“支持相关性”类别，可先合并辅助目标，不强造两个同义 head。

第一轮无标签时不启用 A/E loss。后续至少抽查高相似但缺信息、低相似但支持、同值错实体/条件、仅标题提及、真正桥接这几类样本。

### 10.3 X 探索价值

仅在固定搜索与 R 已跑通后，使用训练集受限后续轨迹标记动作收益。相比下一批 Dense，展开 A 在同剩余预算下是否改善检索结果，可以用于 pairwise X loss。A 不是 Gold 不意味着不该展开。

存在通往 Gold 的路径仅是可达上限/弱标签，未探索分支不是确定失败。多个有效动作可同时为正，不要求唯一路径。当前预算是硬约束，始终不自动加 stop loss 或 RL。

## 11. 实现模块与入口契约

以下是需要新增的模块职责，不代表已经存在：

| 模块 | 输入 | 输出/责任 |
|---|---|---|
| dataset adapter | 原节点、查询、私有 qrels、原 split | canonical manifest、独立推理输入、映射/缺失报告 |
| graph adapter | 合法候选图、provenance | 去重的有向邻接；稳定迭代顺序 |
| feature store | 模型/视图/ID manifest | 同空间 hq/hn、缺失 mask；不带 Gold |
| dynamic edge model | q/T、端点、route | e0、e_t、目标分、诊断张量 |
| training state builder | train 候选及 train labels | q/T/P/N、来源与置信度；只离线使用 |
| trainer | config、状态、feature store | checkpoint、loss/排名/梯度日志 |
| search controller | query、图、模型、硬预算 | 访问轨迹、候选池、预算台账 |
| set selector | 实际候选池、预留预算 | 有序 Top-K、选择原因字段，不生成答案 |
| evaluator | 已冻结结果 + 私有评估 qrels | 指标、分组统计、失败归因 |

至少提供相互分离的入口：`prepare_data`、`build_states`、`train`、`retrieve`、`evaluate`。通过 README 给出实际实现后的可运行命令；命令应支持 config、输出目录、seed、checkpoint 和 split manifest。不要在文档中把尚未实现的命令描述成已执行成功。

`retrieve` 不接收 Gold 路径/answer 参数；评估是独立步骤。结果行至少包含 query_id、target_id、输出粒度、rank、score、Dense 原排名、发现来源、parent/path、hop、实际输入节点、预算快照和模型版本。

日志不需要打印全库内容，但能回指原始内容与配置重放。模型异常/解析问题与“不相关”分开记录，保存必要 raw / error 信息，不静默丢题。

## 12. 分阶段实施与 gate

| 阶段 | 必须完成 | 通过后再做什么 |
|---|---|---|
| P0 数据与环境 | 完成本文第 2–4 节核查、split/单位/负例策略、mini 清单；节点/表示/图就绪 | 才进行真实训练 |
| P1 最小训练链 | 小模型、L_rank、8–16 train query 固定候选诊断、checkpoint 重放 | 固定候选 mini 训练 |
| P2 排序学习 | mini train/dev、静态/动态消融、独立候选覆盖统计 | 接预算搜索 |
| P3 硬预算多跳 | 调度、去重、预算预留、两跳日志、Top-K 返回 | 检查候选/排序各自瓶颈 |
| P4 互补与 A/E | 条件 T 行为审查；有标签才启用集合/A/E 增强 | 冻结方法评估 mini test |
| P5 可选探索学习 | 有足够轨迹且证据表明分配是瓶颈时训练 X | 资源允许再扩训练量/语料 |

Gate 不要求每阶段必须提高指标。失败时交付可复现错误、原因与可执行修复；不通过继续加模型掩盖数据问题。mini 的有效训练状态为零、ID 不可对齐或输入缺失时，先完成能做的数据/实现检查并报告缺口，不伪造训练成功。

### 12.1 抽样与标签冻结

在运行模型前，按原 split、文档族组件、资产可用性元数据与固定 seed 冻结 mini IDs/corpus。保留原 800/200/200 文件不变。记录实际文档组件数，64 个测试 query 并不等于 64 个完全独立文档场景。正式 test 不用于提示、阈值或权重设计。

### 12.2 训练完成的最低证据

不仅有 checkpoint 文件，还应有有效样本数、标签来源、loss 曲线、每模块梯度/参数更新、正例排名变化和重放结果。过拟合诊断与 dev/test 指标分开；loss 下降不等于 edge 机制或泛化成立。

## 13. 必须验证的行为

对会影响实验结论的机制写小型确定性测试，避免仅镜像实现：

1. **身份与泄漏**：错误 ID/不兼容 embedding 明确失败；推理数据不含答案/qrels；同题派生状态不跨 split。
2. **多正例损失**：提高任一尚缺正例相对负例的分数应降低对应损失；其他正例不作为负例；空 P/N 被跳过并计数，不变成 stop 标签。
3. **动态边梯度**：F/G/投影有有限梯度且 optimizer 后参数变化；模型保存/加载后结果可复现；不存在旧缓存使 F 的更新失效。
4. **动态状态**：同 q/T/input 重放一致；不同 q/T 能影响向量。另在审核案例上验证选择变化合理，向量变化本身不算语义验收。
5. **预算**：缩批、搜索/最终选择预留、多 route/多状态重评分计费、预算为零、边耗尽但 Dense 仍有候选等情况不超支。
6. **两跳与循环**：构造不含测试 Gold 的小型人工图，验证 A 低返回分时仍可能展开到后继；避免 A↔B 循环；不同路径不重复返回同目标。
7. **去重与度数**：精确复制同一 canonical edge 不改变聚合/入选；不同独立 routes 的作用另测，不声称对所有 degree 差异不敏感。
8. **输出粒度**：page 模式同页不占多名额，node 模式不混页标签；实际可见节点包与 Gold 元素可见性审计一致。
9. **互补选择**：在明确标注 A/B 与 A 重复项的例子中，已选 A 后 B 的条件价值符合训练目标；真实模型失败时如实报告，不把人为规则覆盖算模型学会。

仅复现旧 Dense 排名的 bypass 模式应与冻结 baseline 一致。新学习模型的“edge 通道关闭”恢复的是匹配的 state–target 学习对照，不自动等于冻结 Dense；不要混淆这两个恢复测试。

## 14. 必须报告的实验

先固定候选做表示消融，再做同预算搜索，避免把候选池变化混进模型比较：

| 对照 | 要回答什么 |
|---|---|
| 冻结 Dense | 原始排名与预算参考 |
| 学习的 q/T–target，无 edge 信息 | 收益是否来自普通监督/集合状态 |
| 可训练但 query-independent edge | 基础端点关系编码的作用 |
| query-conditioned edge | 问题条件化是否有用 |
| query + T-conditioned edge | 已选集合条件化是否改善互补选择 |
| 动态 edge + 有监督的 A/E 或集合项（后续） | 辅助监督的独立价值 |

匹配可见内容、候选、训练机会与尽可能相当的容量；不把大模型/额外读取的收益全部归给 edge。固定 2+2、一跳与两跳属于搜索/配额对照，用同 B 和明确 K 分开报告。

指标：Recall@5/10、RecallAll@5/10、nDCG@5/10；新增相关目标、原相关目标损失；低 Dense 排名目标的恢复；候选可达率、实际进入候选率、可见性；分支/深度/degree 分层；访问/评分/内容/延迟成本。某一题从 40 升到 12 不等于 Top-5 成功。

测试按问题类型、初始是否完整、是否需要多个标注目标分层，并给总体分母；真正 2-hop-only 可达组在结果冻结后离线标注，不在在线选择中使用。报文档组件数及多随机种子波动；小测试估计不包装成跨数据集泛化证明。

## 15. 交付目录和报告清单

新增运行目录使用实际日期/唯一 run ID，不覆盖旧输出。每个 run 至少保存：

- 输入/模型/编码器/图/数据划分 hash 与完整 config。
- 数据 readiness、标签映射、排除原因及有效训练状态统计。
- checkpoint、训练曲线、梯度诊断、实际优化参数列表。
- 每题预算轨迹、候选与 route、最终有序列表、Gold 仅在评估阶段加入的结果。
- `RESULTS.md`：完成了哪些阶段、指标/成本、对照、失败案例与结论边界。
- `REPRODUCE.md`：真实可执行命令、环境/依赖、随机种子、资源需求和已知限制。

不要只交一个总分表。至少能判断失败来自数据、候选不可达、桥接没展开、内容未读、动态向量没更新、排序或集合容量中的哪一项。

## 16. 执行时的优先顺序

首先完成 P0，优先复用既有资产并生成 mini 数据 manifest。随后实现唯一默认小模型与 L_rank，跑训练链诊断和固定候选实验，再接预算搜索。A/E、集合额外 head、X 按标签和瓶颈逐项增加。

实现者若认为必须改变默认架构/粒度/预算，先在报告中说明具体证据、改动和对照，再继续；普通可逆实现选择可自行完成，不为每个步骤反复等待确认。只有实际缺少外部信息或明确权限时，列出已完成部分与具体阻碍。

本任务书不要求本次会话立即执行训练。用户新对话可直接发送：

> 请执行这份任务书。从 P0 核对现有数据与小规模划分开始，保留旧 baseline 和输出。默认使用冻结 encoder、可训练动态 edge、固定硬预算，先完成小样本训练和固定候选验证，再接多跳搜索。不要扩展为答案生成系统；不要把全部辅助损失一次性加上；所有结论提供复现和成本证据。

## 17. 设计依据与参考

本地详细讨论：[动态边与损失](LOSS_FUNCTIONS_FIXED_BUDGET_RETRIEVAL_20261114.md)、[固定预算与多节点选择](ADAPTIVE_BUDGET_MULTIHOP_RETRIEVAL_20261114.md)、[A/E 与检索配额](RETRIEVAL_ONLY_EDGE_RERANKING_ARCHITECTURE_20261114.md)。若旧描述与本任务书的简化默认配置冲突，以本任务书及用户最新指令为准。

[EADPR](https://aclanthology.org/2024.findings-eacl.130/) 提供证据与干扰段落区分的检索监督参考；[SetR](https://aclanthology.org/2025.acl-long.861/) 研究返回集合共同覆盖信息需求。这些工作不提供本文 128/32/64 或 256 维设置的效果保证；本任务书具体架构、预算、样本量和 gate 是针对当前资产提出的工程起点。
