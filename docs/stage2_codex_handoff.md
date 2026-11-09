# DynamicEdgeGraph — Stage 2 Directed Edge Embedding 开发任务书

**日期：** 2026-11-09  
**状态：** Stage 1 Balanced 工作配置已选定（全量 Candidate Graph 导出状态待核实）；Stage 2 新 Codex 会话任务书 / 待实验验证  
**目标分支：** `feature/evidence-edges`  
**建议实现位置：** `DynamicEdgeGraph/stage2_edge_construction/`（实际以仓库检查结果为准）
**本次优先级：** 24-query Pilot 的 Stage 2 E0 数据接口、向量表示、方向性测试与可审计输出；不要重跑 Stage 1 阈值搜索。

> **给 Codex 的首要指令：** 请先阅读本任务书、`docs/stage2_edge_construction_literature_notes.md`、`DynamicEdgeGraph/stage1_candidate_pruning/README.md`、`EvidenceNet/experiments/vldocir/README.md` 和 `EvidenceNet/experiments/vldocir/BASELINE.md`，核实 Stage 1 Balanced 工作配置与其导出状态、Pilot 数据/入口是否存在，再制定最小可执行计划并实际实现。不要仅输出概念讨论。对于本文未证实的路径、字段、输入覆盖率和数据映射，请以实际代码与文件为准，明确报告差异，不要猜测或静默补齐。

---

## 1. 研究背景与阶段边界

项目目标是面向长文档、多文档、多模态证据检索，建立能够保留语义信息、关系方向以及节点来源的连续向量图表示。

整体划分：

1. **Stage 1 — Candidate Generation / Pruning：** 使用多模型检索得到 Node Pair 候选，通过多路线一致性、归一化分数累计、单模型高分等 ABC 规则减少候选数量。它不是语义关系判定器。
2. **Stage 2 — Query-independent Directed Edge Construction（当前任务）：** 对候选 `(source_node, target_node)` 构造有方向的高维 Edge Embedding，研究它是否同时保留两端的**共享语义**与**方向性差异/关系**，并在小样本上进行可信的离线评估。
3. **Stage 3 — Query-conditioned Routing（不属于本任务）：** 基于 Query 选择边、进行 Q/K/V 或 Attention 路由，比较图扩展及证据检索效果。

**本阶段禁止将 Query 编入 Edge Embedding，禁止以 Query Gold Evidence 直接生成边，禁止将 Stage 3 的路由/图扩展混进 Stage 2。** Query 仅用于选定现有 Pilot 数据范围、后续评估和误差分析；训练/构建关系时不得看到该 Query 的相关性标签或答案。

**Stage 1 的 Balanced v1 工作配置现已选定。** 当前不是重新选择阈值，也不是让 Stage 2 负责生成全量 Stage 1 候选图。Stage 2 应提供可替换的 Candidate Pair Adapter：先在独立的 24-query Pilot 上运行；未来再接入已导出和校验的 RepresentativeSubset Balanced 图。若全量导出尚未完成，不得阻塞 Pilot 的 E0 开发。

## 2. 已知事实、必须核实的输入

### 2.1 Stage 1 Balanced v1：已选定的工作配置（不是本次运行规模）

Stage 1 已完成归一化 ABC 阈值搜索（100 组配置，Job `126279` 成功完成）。**方法与阈值作为当前 v1 工作配置固定**；这不代表已经完成独立语义关系验证，也不保证全量 Pair 导出文件已经落盘。Codex 应只读核验真实文件、manifest、配置版本与文件哈希。

**输入和候选池：**

- VL-DocIR RepresentativeSubset 有 **112,591 Canonical Nodes**；原始含 BGE 的 Top-100 Union 约 **34,558,320** 个无向去重 Pair。
- 剔除失效的 BGE 路线后，有效五路线（Qwen3、GTE-Qwen、MXBAI、GTE-large、BM25）的完整 Top-100 Union 为 **24,177,794** 个 Pair，**不是 cross-scoring 未完成的部分数据**。
- 四个 Dense 路线在全部 24,177,794 个 Pair 上都有 cross-score；BM25 仅 **7,312,713** 个 Pair（30.25%）有观测分数，其余是 **missing / not observed**，不是零分。
- BGE-en-ICL **仅诊断，不参与任何 A/B/C 判定**。结构边不混入这套语义 Candidate Union。
- 采用 **tie-aware ECDF / midrank** 做归一化；已保存的参考分布和方法版本必须与筛选配置一起保留。不能把不同模型原始得分直接相加；不能在 Pilot 的小样本上随意重新拟合 ECDF 并仍宣称使用相同的全量阈值。

**Balanced v1 ABC（OR）规则：**

| 规则 | 固定定义 |
|---|---|
| A | 五条有效检索路线均召回该 Pair，固定保留 |
| B | 四个 Dense 的 tie-aware ECDF 归一化分数**均值 ≥ 0.9817807** |
| C | **有观测值**的有效路线中 ECDF 最大值 **≥ 0.9951319**；BM25 缺失不作 0 分 |
| Union | `A OR B OR C`，去重，不强制 Top-N 截断 |

**Balanced 已报告统计：**

| 指标 | 结果 |
|---|---:|
| A 单独命中 | 1,096,204 Pair |
| ABC Union | **1,495,665** 个无向候选 Pair |
| 相对原始 34,558,320 Pair 的保留率 | **4.33%** |
| Eligible Node Coverage | **92.17%**（不是全部 Canonical Nodes 的覆盖率） |
| 平均度 / P99 度 | **28.68 / 261** |
| 跨文档候选比例 | **53.86%** |
| 跨模态候选比例 | **12.56%**（按原始模态统计） |

这只是**候选图**，不是已经确认的真实关系图。跨模态候选的绝对数量在 Conservative/Balanced/Broad 三配置间变化很小；可以作为后续诊断背景，**不要为此重新优化 Stage 1**。

**现有 Stage 1 输出入口（均需在 HPC 实际核验）：**

- `DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-abc-score-support-pruning-20261109/normalized_abc_search_126279/`：阈值搜索 CSV、参考分布、推荐配置等。
- `DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-abc-score-support-pruning-20261109/cross_score_reliability_audit_126255/`：cross-score 审计。
- 全量 `Balanced v1` Candidate Pair 导出/封存可能由另一会话进行；**文件是否已存在不得仅凭任务描述假设**。只有完整性、Pair 数量、ID 映射、版本和哈希均验证后，才将其标记为可用的 scale-up 输入。
- Job `126323` 曾被安排生成 Markdown 汇总；是否完成以本地实际文件/作业状态为准，不把待生成报告当作事实来源。

**本次 Stage 2 Codex 的边界：** 不重跑 Stage 1 搜索、不改变上述阈值、不改写 Stage 1 输出，不为了等待 150 万 Pair 导出而延迟 Pilot 开发。此处 1,495,665 是计划复用的全量工作点，**不是 24-query Pilot 的预期边数**。

### 2.2 24-query Pilot（本次 Stage 2 首选输入）

仓库文档记录：

- `EvidenceNet/experiments/vldocir/README.md`
- `EvidenceNet/experiments/vldocir/BASELINE.md`
- 冻结 no-edge baseline ID：`vldocir_no_edge_v1_20261011`
- 24 个 Query，518 页，7,291 个 Evidence Nodes，262 个视觉组件。
- 来源为 arXiv、PubMed、SEC、Wikipedia，每类来源 × 六种问题类型各选一条 Query；属于小规模选定语料实验，不是全量官方 benchmark。
- 六组 no-edge retrieval arms 均已有结果；**`hybrid_visual` 是后续比较的主要冻结 baseline**。
- 基线快照文档所记路径：`EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011/`。实际数据与产物可能被 `.gitignore` 排除，必须在当前 HPC 工作区验证。
- 检索输出也可能位于 `EvidenceNet/output/vldocir_pilot_20261009/retrieval/`；以 manifest 和实际代码为准。

冻结 baseline 的查询、检索库、节点与页面映射、原始图像描述、模型配置、评估协议等均不得修改或覆盖。

可先运行已有校验（路径与 Python 环境需确认）：

```bash
python EvidenceNet/scripts/verify_retrieval_baseline.py \
  EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011 --check-encoder
```

**重要：** 24-query 数据集有页面级检索 Gold Evidence，但这**不等价于 Node–Node 语义关系标签**。不能据此凭空生成正例 Edge，也不能在尚未实现 Stage 3 时宣称 Stage 2 提升了检索指标。

### 2.3 第一项任务：数据资产审计

Codex 应在写模型前执行只读检查，产出 `data_inventory.md`：

- 24-query Pilot 的节点清单、唯一 Node ID、Text / Semantic Text / Caption / Visual Description、文档 ID、页码、原始模态、来源路径；字段可为空但必须显式记录。
- 现有 Embedding 的模型名、向量维度、归一化状态、view→node 映射方式、原始顺序、哈希与可用范围。
- Stage 1 Balanced v1 推荐配置、ECDF 参考分布、无向 Pair 文件和对应 provenance 是否存在；格式、Score/Support、ABC flags、BM25 缺失语义及实际文件哈希。**同时独立统计 Pilot 是否拥有同一套检索路线与兼容的节点向量；不得默认全量 Pair ID 能映射到 Pilot Nodes。**
- 是否存在已经过人工审查的正例、负例、NO_RELATION、阅读顺序/结构边等；区分其来源与可信程度。
- 对于缺失文件、Node ID 冲突、Embedding 行错位、跨数据集混用等问题，**显式失败或隔离**，禁止自动猜对应关系。
- 记录本次可运行的 Pilot 实际 Node、Document、Pair、Embedding 数量；不要拿全量数值冒充 Pilot 数值。

### 2.4 Stage 1 → Stage 2 Candidate Pair 接口（必须区分两套数据）

建立一个统一的、**不携带查询条件**的候选输入接口，至少明确：

- `dataset_id` / `dataset_revision` / `node_id_namespace` / `source_run_id`；
- 无向 `pair_id`、两个端点的 Canonical 或 Pilot Node ID，以及映射到同一冻结 Encoder 的向量行号；
- Pair 来源（`balanced_v1_full` 或 `pilot_local_candidate` 等）、原始文档/页码/模态；
- 可用时存储 Route Support、归一化参考版本、A/B/C 命中信息；不可用时明确 null 或 not_available，不伪造；
- Pair 表、Node 表、Embedding 矩阵的数量、哈希与完整性检查。

**首轮 Pilot 的可行路径分两种：**

1. **严格迁移 Stage 1 v1**：只有当 Pilot 可提供同口径的五条检索路线、同版本 Score 计算、兼容的 ECDF 参考分布和明确的缺失值语义时，才应用已经固定的 A/B/C 数值阈值；记录相对于全量数据的分布漂移与实际保留数量。不可为了达到 150 万的同比例而重调阈值。
2. **Pilot-local 候选集（允许且不阻塞 E0）**：若上述条件不满足，复用 Pilot 中已有检索记录/可复现候选生成与分层抽样，清楚标为 `pilot_local_candidate`。它可以用于对比 Stage 2 Edge 表示，**但不能宣称是严格的 Balanced v1 输出**。Codex 不应为了严格重现全量五路线而重新训练/计算全模型，除非另有明确批准。

Stage 1 的 Pair 是**无向候选对**；Stage 2 应把 `i→j`、`j→i` 作为可区分的两个表示方向，或采用可重建的惰性表示。**生成两个有向表示不意味着两个方向的语义关系均有效**，也不得把这当成已经审核通过的 Edge。

---

## 3. Stage 2 的核心研究问题

### 3.1 不希望仅用一个权重或离散类别表示边

我们希望 Edge 是一个连续向量，能够保留有用的语义关系细节，而不是只有一个相似度 Weight、一个 Relation Type 或一个 Cluster ID。

一条候选 `(i, j)` 可能同时包含：

- **共同信息：** 两个节点讨论相同的方法、事实、对象、实验设置、数据集，或者本质上等价的公式。
- **差异/方向性信息：** 第二个节点在第一个节点基础上新增了什么、补充了什么，或者两者存在怎样的支持、比较、限制、反驳关系。
- **无实质关系：** 两段文字仅主题相近，不能仅因余弦分数高就认为存在语义边。

因此，Stage 2 要研究的是：

> **如何用统一的 Edge Embedding 同时保留两个节点的共享语义以及 source→target 的方向性关系，而不预先把关系压缩成固定分类？**

### 3.2 为什么同时考虑 Midpoint 与 Difference

令 `h_i, h_j ∈ R^d`，**必须来自同一个冻结 Encoder、同一个对齐的向量空间**：

```text
m_ij       = (h_i + h_j) / 2     # midpoint，交换端点后不变
Δ_i→j      = h_j - h_i           # directed difference，反向后符号相反
edge_i→j   = concat(m_ij, Δ_i→j)
```

性质：

- `m_ij = m_ji`；`Δ_j→i = -Δ_i→j`。
- `[m, Δ]` 可逆还原 `h_i = m - Δ/2`、`h_j = m + Δ/2`，保留两端向量的信息。
- 当两个节点非常相似时，`Δ` 可能接近 0，但 `m` 仍能保留共同主题位置。
- **限制：** Midpoint 不等于严格的“共同语义交集”；Difference 不自动等于语义关系/因果/支持/反驳。可逆也不等于提取出了新的关系知识。
- 对于完全相同的向量，避免对零差向量直接做单位化。
- 不允许跨不同 Encoder 直接做向量加减或拼接后当作同空间特征。跨 Encoder 融合必须明确写出各自分支及后续对齐/投影，并作为后续实验。

### 3.3 更进一步的目标：共享部分 + 方向性部分

在第一版 Baseline 之后，探索可学习表示：

```text
s_ij       = f_shared(h_i, h_j, text_i, text_j, optional_context)
r_i→j      = f_directed(h_i, h_j, text_i, text_j, optional_context)
e_i→j      = Project(concat(s_ij, r_i→j))
```

期望：`s_ij ≈ s_ji`（共享成分近似对称）、`r_i→j` 对顺序敏感；**不能强行假设学习到的语义关系一定满足 `r_j→i = -r_i→j`**，因为反向关系可能具有另一种语义而非简单负号。

可探索的实现机制：

- 对称输入特征，如 `mean(h_i,h_j)`、`abs(h_j-h_i)`、`h_i⊙h_j`，用于共享分支。
- 有序输入，如 `[h_i; h_j; h_j-h_i]` 及 `source/target` 明确标记的文本，用于方向分支。
- 使用小型 Projection/MLP 或 Pairwise Cross-Encoder，必要时考虑关系描述蒸馏/对比学习。
- 允许输出包含 `relation_validity / abstain` 的**独立诊断头**，但不要将它与连续 Edge 向量混为一谈。

没有可靠关系标注时，先作为待验证假说，不要声称模型已经学会关系语义。

---

## 4. 第一批 Baseline：必须先实现、无需训练

建议用同一个冻结 Encoder 对 Pilot 的合法节点做实验。默认选择与 Pilot 兼容、映射已验证的 Encoder；不要盲目使用全量 Stage 1 的矩阵。

| 名称 | 表示 | 维度 | 研究目的 |
|---|---|---:|---|
| E0-Diff | `h_j - h_i` | `d` | 只保留向量位移，方向反转 |
| E0-Mid | `(h_i+h_j)/2` | `d` | 只保留共同位置，无方向 |
| E0-MidDiff | `[(h_i+h_j)/2 ; h_j-h_i]` | `2d` | 首选完整无训练 Baseline |
| E0-Concat | `[h_i; h_j]` | `2d` | 有序端点表示，对照 MidDiff |
| E0-Interaction | `[mean; difference; abs(difference); h_i⊙h_j]` | `4d` | 显式共享、差异与交互特征 |

**优先级：** `E0-Diff`、`E0-Mid`、`E0-MidDiff`、`E0-Concat` 必做，Interaction 视成本加入。

请支持配置化的：

- input normalization：对节点向量是否 L2 normalize，分别记录并评估；
- output normalization：对 Edge 是否 normalize，不要把差值为零时产生的 NaN 隐藏；
- dimensions / dtype / file size / throughput；
- source→target 与 target→source 成对输出（或以可重建方式保存），但不要将双向语义有效性视为已确认；
- 端点顺序、稳定 pair_id、文档/页码/原模态 Provenance。

如果只使用未训练的可逆代数变换，不能仅凭 Edge 最近邻相似度好看就宣称优于 Concat，因为 `MidDiff` 与 `Concat` 本质上携带等价的端点信息。比较应着重后续学习器/几何归纳偏置/效率与有标注的关系评估。

---

## 5. 第二批方法：在 E0 跑通后再做

### E1. Pairwise Cross-Encoder（联合阅读两个节点）

- 输入明确区分 `[SOURCE]` 和 `[TARGET]`，提供各节点文本/描述，以及**受限且可追溯**的局部上下文；不加入 Query 或答案。
- 生成有序 Pair 的内部表示，再经过 Projection 得到固定维度的 Edge Embedding。
- 如果使用未训练的 pooled hidden state，必须称为 **representation probe**，不能声称它已经是 Relation Embedding。
- 对输入长度与模型成本设预算，优先小样本试验，不对百万边直接跑 Cross-Encoder。
- 对比 source/target 交换前后的向量变化，以及与 E0 的关系区分能力。

### E2. Shared–Directed Representation Learning（首选研究方向）

- 显式采用共享分支与方向分支，探索对称性/方向性约束。
- 训练数据不足时优先只实现清晰可测的架构和小规模探针；不要靠伪造标签强行训练。
- 可选：使用少量人工审查的关系对、硬负例、带置信度及证据依据的 Teacher 关系描述进行对比或蒸馏。
- 对自然语言关系描述/人工审查中的 `NO_RELATION`、同义改写、跨模态、公式字母替换与主题相近但无关系案例进行独立处理。
- **验证内容：** 是否真的区分共享信息与方向性关系，而不只是学到主题/文本重复。

### E3. Teacher → Student（可选、非第一阶段阻塞项）

- Teacher 对小样本有序 Node Pair 给出：关系描述、方向、可引用的源/目标依据或 `NO_RELATION / UNCERTAIN`。
- 不把 Teacher 输出当人工真值；可审查后用于蒸馏 Student Encoder。
- 独立评估 Teacher 的误连率，避免把 LLM 幻觉大规模蒸馏进图。

已有研究文献与方法适配边界见 `docs/stage2_edge_construction_literature_notes.md`。**Edge Clustering 不是 Stage 2 的必要步骤**：如果开展，只作探索性诊断，检查向量是否按关系而非单纯话题聚合；不得把 Cluster ID 替代连续 Edge Embedding。

---

## 6. 24-query Pilot 上的实验数据设计

### 6.1 Candidate Pair 的选取

优先从 Pilot 的真实 Node 表与合法候选边中选取。**Stage 1 Balanced 数值阈值已固定，但 Pilot 是否可严格迁移仍需验证**：遵循 2.4 节的两种候选输入路径；不能重新拟合 Pilot 本地 ECDF 后直接套用全量阈值，也不能在缺少五条兼容路线时伪造 A/B/C 命中。若采用 Pilot-local Candidate，应如实标注并在 Stage 2 的所有 E0 方法上使用**同一固定 Pair 集**，保证横向可比。

建议分层抽样，先审计是否有足够数量，再决定样本大小：

- 同文档 / 跨文档；同页 / 跨页；同模态 / 跨模态（按原始模态，不按文本化后的类型）；
- 多模型同时支持、单一路线高分、低支持但语义潜在有价值；
- 高相似度重复文本、近重复、主题相近但不相干；
- 公式等价但符号重命名、同公式不同语义、表格与文字互证、图注与正文；
- 结构上相近但语义无关，以及明确的 `NO_RELATION`；
- 多文档证据互补、描述同一对象的不同事实、相互矛盾的陈述。

不要假定 Pilot 一定有 2k～5k 个可审查的优质关系；请先统计，再以实际量确定配置。样本必须记录采样规则、随机种子、候选来源、审查状态与潜在偏差。

### 6.2 数据划分与标签边界

- 24-query 的 Gold Evidence 是**检索标签**，不是边标签。
- 若有既存人工审查 Pair，核对它是否来自同一 Pilot、同一节点 ID 体系；否则仅作为外部材料参考。
- 制作最小、可人工复核的 Pair Review Sheet，允许 `SUPPORTED_RELATION`、`NO_RELATION`、`UNCERTAIN`，并可附加方向、共享语义、关系描述、来源依据及审查者。
- 尽量按文档/文档家族分 Train / Dev / Test，而不是随机 Pair，防止同文档重复内容泄漏。
- 与 Query 的金标准标签严格隔离；不把“都在 Gold Pages 上”当成语义正例。

### 6.3 评估问题与度量

**A. 工程正确性（E0 先做）**

- Midpoint 交换不变，Difference 交换反号；MidDiff 可逆；无 NaN/Inf；稳定 Pair ID；行号/Node ID 完全匹配。
- 相同节点或几乎相同节点时差值接近零，但系统仍保留中点信息。
- 记录输出维度、dtypes、每千条 Pair 耗时、内存及磁盘开销。

**B. 关系语义（需独立审查集）**

- 对人工确认的相似关系，测试 Relation Analogy Retrieval / Nearest-Neighbor 的 Precision@K、MRR 或其他适当指标。
- 方向测试需使用真正的非对称样本；**向量在交换端点后变了，不等于学到了正确方向语义**。
- 主题泄漏测试：跨领域但关系相近是否比同领域但关系不同更接近？
- 明确评估 `NO_RELATION`、近重复模板、公式变量替换等 Hard Negatives。
- 对 E0 不同维度的结果控制比较条件；必要时加入相同输出维度的投影对照，并区分投影是否经过训练。

**C. 24-query 检索可用性（仅作准备/诊断）**

- 可输出某 Query 的 Gold Evidence 节点可达性 / 候选边覆盖情况，但不要调用 Query 生成 Stage 2 Embedding。
- 可以分析哪些 Query 存在图扩展机会，以及正确证据间是否有候选连接。
- 在未实现明确的 Stage 3 策略和固定评估协议前，不把这部分报告成 Stage 2 的检索提升。
- 牢记旧 Pilot 中不同 Retrieval Arms 的 Top-10 表现接近、图扩展空间可能较少，因此**不能只用24条 Query 的 nDCG 判断 Edge Embedding 质量**。

---

## 7. 建议代码结构与数据契约

先检查仓库是否已有相关模块，尽量复用，不要建立与 Stage 1 / EvidenceNet 不兼容的第二套 Node 定义。若新建目录，可参考：

```text
DynamicEdgeGraph/stage2_edge_construction/
├── README.md
├── configs/
│   ├── pilot_e0.yaml
│   ├── pilot_e1.yaml                 # 仅 E0 完成后需要
│   └── subset_balanced_e0.yaml      # 仅未来扩展时启用
├── src/
│   ├── audit_inputs.py              # 资产、映射和覆盖审计
│   ├── prepare_pilot_pairs.py       # 稳定 Pair 表和采样
│   ├── representations.py           # Mid / Diff / Concat 等
│   ├── build_edges.py               # 分批生成 Edge Embedding
│   ├── evaluate_edges.py            # 工程/关系评估
│   └── common.py                    # 配置、路径、IO、ID 契约
├── tests/
│   ├── test_pair_mapping.py
│   ├── test_representations.py
│   └── test_evaluation.py
└── outputs/<run_id>/                # 生成产物不得覆盖 baseline
    ├── input_manifest.json
    ├── data_inventory.md
    ├── pairs.jsonl
    ├── edge_embeddings.npy          # 或分 shard/memmap
    ├── edge_metadata.jsonl
    ├── metrics.json
    └── report.md
```

**接口约定（可以按现有项目风格调整，但必须写清楚）：**

候选 Pair 元数据建议至少包含：

```json
{
  "pair_id": "stable-pair-key",
  "source_node_id": "node-a",
  "target_node_id": "node-b",
  "source_document_id": "doc-a",
  "target_document_id": "doc-b",
  "source_modality": "TEXT",
  "target_modality": "TABLE",
  "candidate_origin": ["pilot_local_candidate"],
  "node_id_namespace": "explicit-dataset-version",
  "dataset_id": "explicit-pilot-dataset",
  "stage1_policy": null
}
```

Edge 输出需记录 `edge_id`、`pair_id`、方向、`embedding_row`、`representation_method`、`encoder_id`、`input_vector_version`、`normalization`、`dtype`、`run_id` 和 Provenance；Pair 若以无向形式输入，转换成双向时须有稳定唯一 key。不要用字符串排序推断语义方向。

输入必须校验 Embedding 行数、Node/View ID 对应、维度一致、哈希或版本信息；不得用 `zip()` 静默截断不等长的 ID/Embedding 列表。

优先批处理与 `numpy.memmap` / shard；不要物化 N×N Pair Matrix、不要为百万 Edge 先生成多份 4d float32 文件。代码须支持 `--max-pairs`、`--seed`、`--dry-run` 或等效选项，便于本地 Smoke Test。

---

## 8. 建议实施顺序：请直接执行，不要只给想法

### Phase 0：确认现状与制定可执行清单

1. 查看 Git 分支与工作区状态，不覆盖/清理现有未提交修改。
2. 阅读上述文档及实际 Pilot 数据；核验 Stage 1 Balanced v1 配置/参考分布/全量导出是否存在，以及 Pilot Node/Embedding/Pair 是否能够安全复用；检查基础评估脚本和旧边代码。
3. 生成 `data_inventory.md`，列出能直接复用的内容、真正缺失的信息、潜在问题，以及最小可跑的 Pilot Pair 集；明确使用严格 ABC 迁移还是 Pilot-local Candidate。**全量导出未完成只记录，不作为 E0 的阻塞项**。
4. 给出简短实施计划（列明将创建/修改的文件），然后继续实现；除非出现明确阻塞，不要停在计划阶段。

### Phase 1：Stage 2 E0 实现（本次的最低完成目标）

1. 完成 Pilot Node/Embedding/Pair 输入 Adapter 和严格校验。
2. 依据 2.4 节选择候选输入路径，构造可复现的固定 Pilot Pair 集/分层样本，保留源字段、IDs 和 Pair 来源；不同 E0 方法不能各自更改 Pair 集。
3. 实现 E0-Diff、Mid、MidDiff、Concat（可选 Interaction）。
4. 同时测试 i→j 和 j→i；验证对称性、反对称性、可逆性与重复节点的安全性。
5. 跑一个小型 CPU Smoke Test，再在可用资源内跑完整 Pilot 的 E0 实验。
6. 产出可供人工审查的样本表、向量、元数据、统计报告以及运行命令。

### Phase 2：可评价关系质量的数据与诊断

1. 检查已有真实人工关系 Pair，如无合格标签，准备小型、分层的 Review Panel，明确状态是 `UNREVIEWED`。
2. 做 Relation Analogy / direction / topic leakage / hard negative 的评估实现；缺少真实标签的指标必须报告为 `not_available`，不能伪造。
3. 输出失败案例，特别是共享事实但差值为零、文本相近却不存在关系、公式字母重命名、多模态互证。

### Phase 3：E1 / E2 研究预研（不要求一开始完成全部训练）

1. E0 结果审计后，决定是否值得实现 Pairwise Cross-Encoder Pilot。
2. 先对同一批 Pair 做小规模可复现比较；明确冻结/训练、输出投影、成本和验证指标。
3. 再提出 Shared–Directed 学习目标与损失函数候选；说明需要何种独立监督/自监督信号，避免无标签状态下的虚假质量结论。
4. 只有 E0 与评价集准备好后，才考虑对比学习/蒸馏/Teacher。

### Phase 4（后续可选）：RepresentativeSubset 扩展验证

1. 在另一 Stage 1 会话导出并完整校验 **Balanced v1 的约 1,495,665 个无向 Pair** 后，使用相同的 Stage 2 Candidate Adapter 接入它们。
2. 先做 E0 的吞吐、存储、数值正确性和模态/文档分层诊断，再决定是否具备扩展 E1/E2 的计算预算。
3. 绝不默认 24-query Pilot 训练或结论能直接泛化到 RepresentativeSubset；记录两套 Node ID 命名空间、模型版本、参考分布和数据漂移。
4. **Phase 4 不是当前首次交付的验收前置条件，也不授权直接启动全量 GPU 推理。**

---

## 9. 运行和版本约束

- 先 CPU / 小样本，尽量用现有冻结 Embedding。**不要在未经说明的情况下提交 GPU Job**；确需 GPU 时，先给出模型、输入量、预计资源、输出及必要性。
- 不修改冻结 no-edge baseline、不改写旧 Pilot 的 Gold Evidence 或源页面、不覆盖 Stage 1 Balanced v1 输出和已保存的 ECDF 参考分布。
- 实验放独立输出目录；包含完整命令、随机种子、Git commit、配置、输入清单及文件哈希。
- 不要大规模改造 `EvidenceNet` 或 `stage1_candidate_pruning`；如需适配，尽量通过 Stage 2 Adapter 实现。
- Git 提交必须仅包含确认要追踪的代码/文档/小型配置和测试，不提交大文件、密钥、权重或受限数据。
- 文档和报告用中文；代码注释、函数名、数据字段保持项目现有风格即可。

## 10. 验收标准与首次回复要求

**最低验收（Phase 0 + Phase 1）：**

- [ ] 已定位 24-query Pilot 真正可用的 Node、Embedding、Pair/检索记录，提交可核验的 `data_inventory.md`；明确与 RepresentativeSubset 的 ID/向量空间是否兼容，并记录 Stage 1 Balanced 导出状态及 Pilot 候选输入模式。
- [ ] Stage 2 E0 四组 Baseline 可通过统一 CLI 重复运行；输入、输出、双向 Edge、原始模态和来源映射完整。
- [ ] 单元测试包含 symmetry/antisymmetry/invertibility/zero-diff/ID mapping/missing input；没有静默错行。
- [ ] 小样本真实运行完成，并给出每种方法的向量维数、Pair 数量、CPU 时间、文件大小和实际输出目录。
- [ ] 有人工可读的抽样对照与错误检查；未标注关系不冒充有效关系。
- [ ] 报告解释 E0 能证明什么、不能证明什么，以及进入 E1/E2 最缺的监督信息是什么。
- [ ] 没有修改 Stage 1 算法/阈值/ECDF 参考分布、冻结 baseline 或 Stage 3 代码；没有将 Pilot-local Candidate 冒充 Balanced v1。

**Codex 首次回复请简短汇报：** Stage 1 Balanced 配置/导出状态、实际找到的 Pilot 文件及数量、严格 ABC 迁移是否可行、可复用模块、最小实施步骤、预计修改的文件。之后直接开始实施 Phase 0 和 Phase 1；遇到具体缺失数据时采用标注清晰的 Pilot-local 候选备用路径，并继续推进能完成的部分。

---

## 11. 相关文件与阅读材料

**项目内：**

- `docs/stage2_edge_construction_literature_notes.md` — Stage 2 Baseline、Relation Learning、Cross-Encoder、Distillation 的文献及适配限制。
- `DynamicEdgeGraph/stage1_candidate_pruning/README.md` — Stage 1 接口与代码入口；Balanced v1 数值以 Job 126279 的推荐配置、CSV 与固定参考分布为准（若本地有更新，先核对 run ID 与文件哈希）。
- `EvidenceNet/experiments/vldocir/README.md` — 24-query Pilot 数据与检索流程。
- `EvidenceNet/experiments/vldocir/BASELINE.md` — 冻结 no-edge baseline 及评估约束。
- `PIPELINE_CURRENT.md` — 实验/生产路径和数据契约边界。

**论文方向（进一步研究，不要求第一轮全部实现）：**

- SCL (TACL 2024): https://aclanthology.org/2024.tacl-1.93/
- Retrieval over Classification (EMNLP 2025): https://aclanthology.org/2025.emnlp-main.943/
- Efficient Document-level Event Relation Extraction (RepL4NLP 2025): https://aclanthology.org/2025.repl4nlp-1.7/
- EP-RSR (NAACL Findings 2025): https://aclanthology.org/2025.findings-naacl.224/
- Distill-RE (AKBC 2026): https://aclanthology.org/2026.akbc-1.25/

**研究原则：** 先把一个可信、可复现、能在 24-query Pilot 上实际运行的 Directed Edge 表示实验做出来；再去讨论更复杂的训练、Clustering、蒸馏或全量部署。不要为了追求复杂架构而跳过数据契约与有效性验证。