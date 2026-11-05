# EvidenceNet：Query 如何真正利用 Edge？——独立研究审查任务

> **用途**：将本文件作为一个全新 Codex 对话的起始上下文和任务要求。  
> **研究项目**：硕士论文，长文档、多模态 Evidence Retrieval / Evidence Graph。  
> **项目路径**：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project`  
> **参考分支**：`feature/evidence-edges`（以当前 `git status` 和实际分支为准）  
> **核心问题**：**当已有一个 Query 和一组已构建的 Edge 时，应该如何利用 Edge，才能在可控成本下找到 Dense Retrieval 原本遗漏、且真正有助于回答 Query 的证据？**

---

## 一、请先理解任务重点

这次不是要求你沿着上一轮实验结论继续增加 Edge、优化候选生成、改进 Pair Allocation，或者训练更好的 Edge Classifier。之前的讨论多次从「Query 怎样使用 Edge」偏移到了「Edge 怎样产生」，这次需要纠正研究重心。

**本任务的核心产出是一个以 Query 为中心的 Edge 使用方案（retrieval-time mechanism）**，包括机制、假设、反例、与已有方法的差异、可验证的实验设计；若证据充足，再实现最小可运行的离线 Replay。请独立评价既有方案，不要把当前实验报告的建议当成必须遵循的路线。

请明确区分：

1. **Edge Construction**：离线发现/生成候选关系。
2. **Edge Reliability / Validity**：关系在证据、实体、条件、方向上是否可信。
3. **Query-conditioned Edge Utility**：给定 Query 和当前已检索证据，沿哪条边到达哪个 Target，是否有增量信息价值。
4. **Candidate Admission**：在有限预算下，是否应把这个 Target 纳入后续检索/重排。
5. **Retrieval Outcome**：是否真正改进 Gold Evidence Coverage、定位、排序或答案质量。

尤其要避免把 **「Edge 存在 / Edge 可信」等同于「对当前 Query 有用」**，以及把 **「新进候选集」等同于「获得新证据」**。

## 二、项目中已有两种 Edge 来源——都必须检查

目前项目中有 **两条 Edge 生成途径**：

- **Qwen 路线**：使用 Qwen / LLM 对节点间关系进行语义判断、生成或验证的 Edge。
- **KG 路线**：项目现有 KG / Evidence Graph 相关流程生成或挖掘的 Edge。

这只是上层区分。**不要假定两者的数据格式、关系 taxonomy、方向性、置信度、anchor、覆盖率、验证状态或可导航性相同。** 请通过实际代码、输出与文档查明：

- 两条路线分别在什么脚本中构建？输出在哪里？
- Edge 的 schema、端点、方向、类型、分数、局部 evidence anchor、source provenance、review 状态分别是什么？
- 哪些是仅 model-accepted、哪些经过独立审核、哪些真正 `allowed_for_navigation=true`？
- 两条来源是否可能互补、重叠、冲突？目前检索代码实际使用了哪一条，是否遗漏了另一条？
- 如果一条路线产生的对象仅是 **未验证 candidate pair**，不要直接称其为 verified edge。

**设计 Retrieval 机制时，以这两种已有 Edge 来源为输入，不要默认需要重新构建第三条 Edge 生产管线。** 若无法判断两者的精确含义，请明确列出待查证的 repo 文件，而不是编造实现细节。

## 三、已经完成的 Query–Edge 实验与主要发现

以下为此前实验的**已报告结果**，请逐项回到产物和代码核查，不能只依据本说明复述。尤其需要识别不同报告之间的评估口径、阶段和上限假设。

### A. 早期 Retrieval Pilot：24 Queries、多个 Retrieval Arms

- 约 24-query pilot，对比多个检索 arm；经过 BGE reranker 后，曾观察到各 arm 的 Top-10 结果/指标相同，没有证明 Graph 的额外收益。
- 更早的图扩展机会诊断：7/24 Query 存在一跳目标；大量目标页原本就在 Dense Top-10 内，导致「候选新颖」与「证据新颖」不一致。
- 需要审查：实验中到底用了哪种 Edge 来源、Seed Top-K、扩展时机、候选合并方式、BGE 重排前后的差异、去重与预算逻辑。不要直接把「reranker 后无提升」推断为「Edge 不可能提升检索」。

### B. Job 119397：Single Admitted Retrieval Route Audit

产物：

- `EvidenceNet/output/kg_retrieval_admission_job_119397/routes.jsonl`
- `EvidenceNet/output/kg_retrieval_admission_job_119397/per_query.jsonl`
- `EvidenceNet/output/kg_retrieval_admission_job_119397/summary.json`

已报告：24 Queries、8 条 model-accepted Edges、1 条 reachable route、1 个 novel admitted target；**没有执行 reranker**。

唯一新增候选的具体问题：

- Query：*How does the proxy voting work for the election of directors if the authority to vote is withheld for one or more nominees?*
- Source 节点是含多个议案的表格，Dense Rank 10；Query 相关的是董事选举行。
- Edge 实际依据的是**审计师批准**行，把 Query 带到另一份文档的 KPMG 审计师批准段落。
- Target Dense Rank 211，被放入候选 Rank 11，挤掉原 Rank 20 候选；但它不回答董事选举 / withheld authority 的问题。
- 同一 Target 页面上另一个正确讨论董事选举的节点已在 Dense Rank 9。
- 原有 Query 的较好证据已在 Dense Rank 1/5 等位置，Gold page 原本已命中。
- 后续 Job 119422 发现该 Edge 涉及跨文档实体/事件身份未解析、弃权票作用可能矛盾，标记为 `CONTRADICTION_REVIEW_REQUIRED` 且 `allowed_for_navigation=false`。

**机制启示**：

1. Node 可能是混合主题；Query 与 Node 某部分相关，不代表 Edge 所依据的局部片段与 Query 相关。
2. Graph Candidate 不能因固定预留 slot 而无条件挤掉更好的 Dense Candidate。
3. Query–Edge 关系应关注 **source-side evidence anchor、target-side evidence、条件/关系类型和当前信息缺口**，不应仅用 `sim(query, node)`。

### C. Graph Pipeline Diagnosis：Reliability 与 Coverage

产物：

- `EvidenceNet/output/kg_graph_pipeline_diagnosis_20261104/REPORT.md`

已报告：

- Job 119397 直接读 8 条 model-accepted edges，没有使用 Job 119422 的独立审计信息。
- **8/8** 已接受边都被标记为 `allowed_for_navigation=false`；因此在正确 reliability gate 下，当前这批 edge 的 navigable 数量是 **0**。
- 有些 `ORIGINAL_TABLE_ROW` anchor 实际跨越多个语义独立的行，不能当作精确的 query-relevant anchor。
- 24 Queries 对应 240 个唯一 Top-10 Seed；这 8 条边合计仅 16 个 endpoint，其中只有一个 Seed 与 endpoint 相交。
- 扩大到 Top-20 也只出现两个 Query occurrence，且是同一条边；Graph slot 容量不是目前的主要瓶颈。

**注意**：这些结果针对当时被使用的特定 8 条 model-accepted edges，**不可未经核实推广为项目中 Qwen 与 KG 两种来源的全部 Edge 都不可信、全部不可用**。请重新盘点完整可用 Graph。

### D. Graph Retrieval Oracle Feasibility Study（v3）

产物：

- `EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/REPORT.md`
- `EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/query_coverage_matrix.jsonl`
- `EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/summary.json`
- `EvidenceNet/scripts/analyze_graph_retrieval_oracle_feasibility.py`

已报告：

| 条件 | Page-level 完整 Query Coverage | 更严格的 bbox-supported Node Coverage |
|---|---:|---:|
| Dense Top-10 | 17/24 | 11/24 |
| Dense Top-20 | 18/24 | 13/24 |
| 当前 Structure-only 上限 | 17/24 | 需查原报告 |
| 当前 Verified Semantic Graph 上限 | 无 Page-level 增益 | 需查原报告 |
| Gold-aware Oracle Semantic Edge | **23/24** | **19/24** |

- Gold 是 `page + element bounding box`，不能把 Gold page 上所有节点一概当作 Gold Node。
- 7 个 Top-10 不完整 Query 的失败类别：3 个已存在潜在 seed→Gold target Pair、但被全局 1,088 对分配丢弃；3 个未在现有 P1/P2 / noisy graph / legacy 候选中生成对应关系；1 个 Gold headline box 不在 Node Generation 覆盖范围。
- 当前 reading structure graph 只在两个文档中验证了 42 条 NEXT/PREVIOUS；zero gain 主要受 graph coverage 限制。
- **Gold-aware Oracle 只是上限，不是实际可达到的算法结果，更不是无条件证明两节点必然具有可验证语义关系。**

**机制启示**：理论上有证据补充空间，但有可能首先需要正确选择「什么时候利用 Edge」以及「哪些 Query 根本无需 Graph」。

### E. Coverage-aware Candidate Allocation Replay（v2）

产物：

- `EvidenceNet/output/coverage_aware_candidate_allocation_v2_20261105/REPORT.md`
- `EvidenceNet/output/coverage_aware_candidate_allocation_v2_20261105/summary.json`
- `EvidenceNet/output/coverage_aware_candidate_allocation_v2_20261105/allocation_protocol.json`
- `EvidenceNet/output/coverage_aware_candidate_allocation_v2_20261105/posthoc_gold_diagnostics.jsonl`
- `EvidenceNet/scripts/replay_coverage_aware_candidate_allocation.py`

在每条 P1/P2 lane 的 1,088 个 canonical pair 预算下，已报告：

| 策略 | P1 Source / Target | P2 Source / Target | 相对 A0 替换 Pair（P1 / P2） | 关键缺失 Gold 恢复 |
|---|---:|---:|---:|---:|
| A0 Global | 656 / 653 | 659 / 655 | 0 / 0 | 0/4 |
| A1 Source-local | 1088 / 834 | 1088 / 836 | 432 / 429 | 0/4 |
| A2 Hybrid | 880 / 738 | 884 / 742 | 224 / 225 | 0/4 |
| A3 Lane-aware | 832 / 706 | 833 / 706 | 188 / 188 | 0/4 |

- A1/A2 的 bbox-localized candidate coverage 从 7/41 到 9/41，但新增覆盖属于本来已在 Dense Top-10 内的证据。
- 缺失的 4 个 Gold item、3 个 Query 仍为 0/4；这些 Pair 在各自 Source 内局部排名 2–9，因此「每个 Source 保留一个」不足以恢复它们。
- 冻结候选缺少 pair-specific member span / table row / precise anchor；不要仅凭页面距离断言关系质量。
- 这轮验证了 **候选分配** 的变化，但并未验证新增 Pair 是否真实可信或是否使 Query Retrieval 变好。

### F. 讨论过但未确认完成的实验：Query-conditioned Recovery

此前提出的探索方向：在 Query-time 从 P1/P2 **分配时丢弃的候选 Pair** 中检索潜在目标，比较 query-agnostic 与 query-conditioned ranking；使用冻结 Query/Node embeddings、原始 Pair Score、局部 rank 等，不借助 Gold 排序。

**目前只有任务设想，没有在本上下文中得到已完成的 Replay 结果。** 请先搜索仓库确定是否有新产物；若没有，不得将其写成已证实的实验结论。

## 四、请重新审视的真正研究问题

请不要仅问「怎样造出更多 Edge」。请从以下问题重新设计检索机制。

### 1. Query 何时应该利用 Edge？

- Dense Top-K 已充分覆盖答案时，Graph 是否应该 abstain？
- Query 需要多条相互补充的证据时，系统如何识别“目前缺什么”？
- 对于没有可达 Edge 的 Query，应该走什么 fallback？
- 是先 Dense 后按需扩展、混合并行检索，还是多轮 evidence-state-guided traversal？

### 2. Query 如何选择一条 Edge？

- Seed node 相关性是否足以启动 traversal？（KPMG 反例显示不够。）
- 可否用 relation type、source/target local evidence span、query sub-question、已有 evidence state 判断 edge 的适用性？
- 仅计算 Query–Edge embedding similarity 是否会退化成 Dense Retrieval 的复制品？如何避免？
- 对 `SUPPORTS` / `EXPLAINS` / `CONTRADICTS` / `CONTINUES` 等不同关系，是否需要不同的选择规则？**实际 taxonomy 以代码为准**。
- 两种来源（Qwen、KG）的边是否应该分 lane、分 calibrator 或分 retrieval policy？
- 如果 endpoint Node 的边来自具体表格行/局部 span，如何避免整个混合主题 Node 的错误激活？

### 3. Query 如何使用 Target，而不只是“把 Target 加入候选集”？

- Target 应提供何种 **marginal evidence utility**：补充缺失条件、解释、引用、比较、纠错、跨模态定义？
- Target 本已在 Dense Top-10 / Top-20 时，图是否依然可能提供有效的 **evidence linking / provenance / answer composition** 价值？如何单独评估，避免把它误记为 Recall Gain？
- Graph Expansion 是取代 Dense slot、扩大候选池，还是进入统一 reranking？必须明确计算成本和公平预算。
- 是否允许某个 Query 最终从图中选 **0 个** 候选？（应考虑。）
- 多跳是否有必要？如果有，如何抑制 semantic drift、环路与过长路径？

### 4. 在现有图很稀疏的情况下，什么能真实验证？

- 首先**分别盘点 Qwen 和 KG 两类 Edge 的真实数量、endpoint coverage、可导航边及 overlap**。
- 区分没有边、边不可达、边不可信、边与 Query 无关、目标不新颖、目标未通过重排这几类不同失败原因。
- 如果可靠边为零，Query-conditioned scoring 的实际效果不能被验证；请提出**不造假、不把 oracle 当实际算法**的可行方法，例如：固定人工复核的微型正/负路径集合，或仅做候选排序能力和理论上限验证。
- 保留已报告的 24 Query 作为诊断集；如果长期用它们迭代，应为最终评测保留独立 holdout。

## 五、希望你比较的检索方案（可以推翻/补充）

至少比较以下概念方案，并给出各自所需数据、预计新增计算开销、主要失败方式、预期可验证性：

| 方案 | 关键决策 |
|---|---|
| R0：Dense only | 完全不使用 Edge，作为主基线 |
| R1：Static graph expansion | Dense seeds 的所有 eligible neighbors，作为简单图基线 |
| R2：Query–Edge scoring | Query 与关系/anchor 联合评分后扩展 |
| R3：Evidence-state / missing-information guided | 根据已检索证据还缺什么，选择能补充缺口的 Target |
| R4：Dual-source edge policy | 比较 Qwen 和 KG 两类边分别使用、联合使用、经统一 reliability gate 后使用 |
| R5（可选）：Discarded-pair recovery | 从历史候选池在线重新捞回未验证 Pair；注意它是候选恢复，不等同已构建 Edge 的 Retrieval |

**不要为了做更多 arm 而做更多 arm。** 请明确你最终推荐的是哪一种机制，以及为何它对「Query 如何利用 Edge」提供比现有方案更强的可证伪假设。

## 六、严格实验原则

1. **先盘点再设计**：检查仓库实际数据，不要仅基于上述摘要推断可用性。
2. **保持冻结对照**：6,520-node universe、Dense Ranking、24 Query 与 Gold 标注不变；新实验写入单独目录，不覆盖旧结果。
3. **无 Gold 泄漏**：Query-time ranking、阈值、候选挑选不得读取 Gold；Oracle 只做离线评估上限。
4. **精确定位**：Page-level 与 bbox-supported region-level 分开报告；不能把同页节点全部算作 Gold。
5. **可靠性先于导航**：`allowed_for_navigation=false` 的边不能被当作 production-valid edge；如果设计用于探索未验证 Pair，必须单独标为 exploratory candidate，不得混同 verified graph。
6. **公平候选与算力预算**：报告每 Query 检索额外 node/pair 数、是否挤掉 Dense 候选、是否运行 reranker、LLM/GPU/CPU 成本。
7. **把 Retrieval Utility 与 Edge Quality 分开评价**：可靠但无关的 Edge、相关但不可信的 Edge、可靠且有增量价值的 Edge，是不同类别。
8. **先诊断、再实现**：除非已有必要数据且能确认实验公平可复现，暂时不要修改生产流水线或直接投大规模训练。

## 七、请按以下顺序开展工作

**第一阶段：Repository / Artifact Audit（必须先做）**

- `git status` / 当前分支 / 最新提交；不覆盖未提交的变更。
- 通过 `rg` / `find` 追踪 **Qwen Edge**、**KG Edge** 两个来源及其被 Retrieval 消费的代码路径。
- 阅读所有相关 Query–Edge 旧实验产物，确认哪些已实现、哪些只是 proposal。
- 建立一张 **Edge Inventory**：来源、数量、taxonomy、方向、置信度、anchors、可靠性、可导航标记、endpoint coverage、实际 consumer。
- 建立一张 **Query–Edge Failure Matrix**：Query→Seeds→Eligible Edges→Selected Edges→New Targets→Valid Evidence→Reranked Evidence 的各阶段数量；没有数据的阶段标注未知。

**第二阶段：独立方案审查（核心任务）**

- 明确指出以前的方案为什么没有让 Edge 产生 Retrieval Gain。
- 提出 2–3 个真正以 Query 为中心的机制，不是新的 Edge Construction 流水线。
- 为每个机制给出最小形式化定义或伪代码：输入 `q`、当前证据状态 `S(q)`、eligible graph `G`，输出一组有序的 `(edge, target, reason)`，允许空集。
- 明确区分 `edge validity` 与 `edge utility(q,S)`；若用 embedding、关系类型或 LLM，分别说明何时需要、如何成本受控及失败模式。
- 判断 **Qwen Edge 和 KG Edge 是否值得分别建模、分别遍历或联合重排**，由真实 schema 和证据决定。

**第三阶段：最小验证计划**

- 优先给出一个 **CPU-only / frozen-data Replay**，明确能够回答什么与不能回答什么。
- 预注册比较组、预算、阈值与成功判据，避免在 24 Query 上反复以 Gold 调参。
- 报告至少：useful-edge selection、novel bbox-supported evidence gain、harmful displacement、abstention quality、edge-source breakdown、latency/budget。
- 若根本没有足够的 eligible Edge，诚实说明不可评测范围，并提出一个**极小规模、明确隔离的人工校验测试集**的构建计划；**不要把构造更多边作为当前主要工作**。

## 八、交付要求

请优先输出一份中文 Markdown 报告，例如：

`EvidenceNet/output/query_edge_utilization_review_20261105/REPORT.md`

报告必须包含：

1. **Executive Conclusion**：你认为怎样利用 Edge，给出明确方案，而不是泛泛地说「增加图覆盖率」。
2. **Evidence-backed Inventory**：Qwen / KG 两种来源如何被存储与使用，引用真实 repo 路径。
3. **Experiment Reconciliation**：各已完成 Query–Edge 实验实际验证了什么、没有验证什么，关键指标及口径差异。
4. **Root Cause Analysis**：为什么 Edge 目前没有改善 Query Retrieval；区分 edge supply、selection、utility、admission、evaluation。
5. **Proposed Retrieval Algorithm**：数据流、打分或规则、abstain、候选预算、与 Dense/Reranker 的接口，必要时给出伪代码。
6. **Ablation / Evaluation Plan**：区分两类 Edge、query-conditioned 与 query-agnostic、使用/不使用 anchors、固定预算与额外成本。
7. **Decision Points**：哪些观察会否定该方案，哪些结果才值得投入 LLM/GPU 或训练。
8. **Uncertainties**：未能访问的文件、未证实的机制、假设及其影响。

**当前回合的优先任务是读代码、审视证据和提出以 Query 利用 Edge 为中心的新方案。** 不要自动进入 Edge 生成、Verification 大批处理、重新训练或者重写生产 Pipeline。若你认为真正的瓶颈在别处，可以指出，但必须仍然回答：**在已有 Edge 的前提下，Query 应该怎样选择、利用、或拒绝这些 Edge？**

---

### 最后请围绕这一句话给出答案

> **我们不是想证明图里可以存在多少条关系，而是想验证：给定一个具体 Query 和当前已经找到的证据，Edge 是否能提供一条有条件、有依据、可度量的路径，把检索引向 Dense Retrieval 没有充分提供的答案证据。**