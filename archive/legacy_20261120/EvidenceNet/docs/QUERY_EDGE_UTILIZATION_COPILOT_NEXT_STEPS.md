# EvidenceNet — Copilot 下一阶段任务：让 Query 真正利用已有 Edge

> **用途**：在 VS Code / HoreKa2 开启一个新的 GitHub Copilot Chat 对话后，直接阅读并执行此任务。  
> **仓库**：`ruijiexu0503-dot/Project`  
> **目标分支**：`feature/evidence-edges`（以实际 `git status` / `git rev-parse HEAD` 为准）  
> **日期**：2026-11-05  
> **首要研究问题**：**在固定的 Dense Retrieval 结果及现有 Qwen、KG、Reading Edge 下，如何让 Query 在真正缺乏答案证据时选择有用的 Edge，并在无收益时拒绝扩展？**

## 0. 任务边界：不要再次跑偏

**本轮研究的是 Query–Edge Utilization，而不是 Edge Construction。**

- 不要生成更多 Edge、重新训练 KG/Embedding、调 P1/P2 候选分配器或修改建图逻辑。
- 不要把 `Edge Validity`（关系是否成立）、`Query Applicability`（关系是否适合本 Query）、`Marginal Evidence Utility`（Target 是否补充答案缺口）混为一个概念。
- 不要把新 Target / 新 Page、`selected`、`inspect` 当成证据召回增益，也不要把 AI 初审标签说成独立人工 Gold。
- 现有 `denied` Edge 不能导航；`unknown` Edge 只能用于隔离的研究性检查，不能因模型选中或 AI 复核而自动晋升为 `allowed_for_navigation`。
- 不修改生产检索、Navigation 或原始冻结实验结果。先完成数据审计与最小 CPU-only 验证，再提出可测试的 Query-time 策略。

## 1. 已有实验与重要事实（请回到实际产物复核）

### Edge 的两条主要来源

1. **Qwen**：原有的 LLM/Qwen 关系生成与审查流程。原始 Qwen Edge 213 条，其中 role-semantic lane 187 条；目前语义可靠性大多为 `unknown`，不能直接视为可导航正例。
2. **KG**：KG 新挖掘出的 Edge 8 条，均被后续审计 `allowed_for_navigation=false`；另外 KG noisy 213 条与 Qwen 原有 213 对重复，**属于同一 provenance，不能当成独立第二票支持**。

此外还有 Reading/Structure Edge 42 条记录（其中 32 条位于当前 universe 并可供结构性使用）；结构连续性并不意味着语义证据支持。必须尊重 `direction`、`anchor` 与 `eligibility`。

### 冻结实验背景

- Frozen universe：6,520 nodes；24 queries；源导航文件每个 query 含 7,288 原始排序节点。过滤后 7/24 个 query 的 Top-10 发生变化。
- 最早 24-query retrieval pilot：经过 BGE reranker 后多个 arm 的最终 Top-10 没有测出收益。
- Job 119397 的唯一 KG-new 新候选为 KPMG 审计师议案，对董事选举 Query 不相关。该 Edge 后来被审核禁止导航。
- Oracle Feasibility：Dense Top-10 page-complete 17/24，Dense Top-20 为 18/24；Gold-aware Oracle 可到 23/24，但它**仅是理论上限**，不能当作真实图检索结果。
- 旧 Qwen Edge 在历史导航中：33 条 oriented route occurrences、涉及 12 个 query、15 个 novel target occurrences、6 个 novel page occurrences；这些是 **reachability/novelty 统计，不是 useful evidence**。
- Query–Edge Utilization Phase-1 Replay：

| Arm | selected route occurrences | queries with selection | new targets outside Dense20 |
|---|---:|---:|---:|
| `R1_static` | 25 | 12/24 | 8 |
| `R2_target_only` | 25 | 12/24 | 4 |
| `R2_anchor_proxy` | 20 | 9/24 | 2 |

上述三个 arm **都尚未经过有独立正例的 Query–Edge Utility 评估**。`R2_target_only` 依赖 Query→Target 相似度；`R2_anchor_proxy` 依赖 Query 与方向化 Source/Target Anchor 的局部词汇重叠；它们还不能证明 Target 补足答案。

### 刚完成的盲审材料准备

`EvidenceNet/scripts/review_query_edge_utility.py prepare` 已在 HoreKa2 成功运行：

- 可审查的 `(query, oriented route)`：**34** 条（跨 arm 合并去重后，不是 34 个不同 Edge）。
- 首轮固定抽样：**12** 条，涵盖 **10 个 Query**，分层为 `denied_control=1`、`qwen_existing=3`、`qwen_new_node=4`、`qwen_new_page=4`。
- 原始结果目录：`EvidenceNet/output/query_edge_utility_manual_review_v1_20261105/`，包含 `review_cards.jsonl`、`annotation_template.jsonl`、`selection_summary.json`、`audit_only/private_index.jsonl`。
- 对这 12 条材料已有一次 **ChatGPT AI 辅助探索性初审**：关系可信 10/12、Query 适用 4/12、**没有确认边际答案收益（0/12）**。这是非独立、部分样本存在先验接触且 Dense Top-10 摘要截断的快速评阅；**不是人工 Gold，也不能用于训练、证明 Precision/Recall 或反过来指导盲审抽样**。
- 典型负例：利益冲突声明跳到别的研究的声明、Federer 2004 引文跳到另一条 2004 引文、董事选举 Query 跳到 KPMG 审计、科学文章背景/方法互联却不回答 Query 所问的特定数值/条件。

## 2. 首先检查项目和数据（不要仅相信本文件）

从仓库根目录开始：

```bash
pwd
git branch --show-current
git status --short
git rev-parse HEAD
python EvidenceNet/tests/test_review_query_edge_utility.py
```

重点检查：

- `EvidenceNet/docs/QUERY_EDGE_RETRIEVAL_REVIEW_BRIEF.md`（早期独立审查任务书）
- `EvidenceNet/scripts/prepare_query_edge_utilization_replay.py`（RouteRecord、三态 eligibility、R1/R2 算法与 frozen replay）
- `EvidenceNet/scripts/review_query_edge_utility.py`（`consolidate`、`sample_routes`、`review_card`、`evaluate`）
- `EvidenceNet/tests/test_review_query_edge_utility.py`
- `EvidenceNet/output/query_edge_utilization_replay_v1_20261105/route_decisions.jsonl`
- `EvidenceNet/output/query_edge_utility_manual_review_v1_20261105/review_cards.jsonl`
- `EvidenceNet/output/query_edge_utility_manual_review_v1_20261105/audit_only/private_index.jsonl`（**仅用于对账和后验评价，不得放入盲审包**）
- `EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/`（Gold 只用于最后的独立 post-hoc 分析）

如果本地 Git 未包含 `EvidenceNet/output/` 中的实验数据，请优先使用 HoreKa2 持久目录里的现有文件。不要因为 Git 忽略了输出文件就误判为数据缺失；不要覆盖已经生成的实验目录。

## 3. 第一项编码任务：审查尚未抽中的 22 条路线

请编写一个**独立 CPU-only 脚本及对应测试**，建议：

- `EvidenceNet/scripts/audit_remaining_query_edge_routes.py`
- `EvidenceNet/tests/test_audit_remaining_query_edge_routes.py`
- 新输出：`EvidenceNet/output/query_edge_utility_remaining_review_v1_20261105/`

具体步骤：

1. 使用已有 `consolidate(...)` 和冻结 `route_decisions.jsonl`，按 `(question_id, oriented route_id)` 确认全部 **34** 条记录；不要按 arm 重复计数。确认去重键和方向不混淆。
2. 读取第一轮 `review_cards.jsonl` 的 12 个 `sample_id`，从 34 条中**集合差分**出尚未抽中的路线；正常应为 **22** 条。若数量不同，停止并诊断数据版本、sample ID 或去重不一致，不要硬编码 22。
3. 为剩余路线生成**盲审材料**：Query、定向 Source/Target Anchor 及上下文、Edge Relation/Conditions、Frozen Dense Top-10 证据摘要、Target 原始 Rank、可比较的 Dense Candidate（如有）。**不得**在盲审材料中展示 Gold、R1/R2 动作、eligibility、route source class、先前 AI 的判断。
4. 单独生成 `audit_only/private_index.jsonl`，记录真实 query/edge/target IDs、source provenance（Qwen/KG/Reading）、eligibility、三种 arm 的 action、novelty，供事后对账。
5. 不要使用 Gold 或初审结论来排序/选择路线；剩余 22 条应做 **census（全部列出）**，保证无遗漏。输出样本数、query 数、source/stratum 分布、sha256/版本信息和测试结果。
6. 禁止修改第一轮 12 条样本、旧 Route Decisions、原始审计产物；用全新输出目录，防止 `prepare` 覆盖已有文件。

**验收：** 原 12 + 新 22 = 全部 34 条唯一路线；ID 无重复、方向正确；相同输入重复运行确定性一致；盲审包不泄漏 Gold / actions / eligibility；至少覆盖空路径、重复路线、双向边、缺失数据或不匹配版本的测试。

## 4. 第二项任务：把研究问题真正改成 Query Utility

对所有可审查路线，在不看 Gold 或私有 action 的条件下，进行**明确标注为 `AI-assisted exploratory review` 的分析**（Copilot 不是独立人类审查员）：

- `relation_validity`: `valid / invalid / uncertain`
- `query_applicability`: `yes / no / uncertain`
- `marginal_utility`: `yes / no / uncertain`
- `opportunity_cost`: `prefer_target / prefer_dense / equivalent / not_applicable / uncertain`

尤其必须判断：

1. Query 包含哪些**答案需求槽位**（实体、指标、条件、时间、对比对象、所问数值或关系）？
2. Dense Top-10 实际支持了哪些槽位、又缺少哪些？摘录可能截断；不能凭截断文本断言缺失。
3. Edge 的**方向化 Source Anchor** 是否位于与 Query 相关的**同一行/同一局部 span**？不能用混合表格中另一个议案的语义触发该 Edge。
4. Target Anchor 是否**直接填补缺失的答案槽位**，还是只解释术语、提及同一论文/项目、重复已知证据？
5. 如果 Target 进入固定候选预算，它是否比被挤掉的候选更值得保留？如缺少该对照，标注 `not_applicable` / `uncertain`，不猜测。
6. 存在跨文档实体/实验身份、时间条件或公式符号不确定性时，优先 `uncertain`，不要虚构关系有效性。

**严禁宣称 Copilot 生成的判断是盲人工 Gold**。可以生成独立的 `provisional_copilot_labels.jsonl` 和含逐条理由的 Markdown；它们是研究假设和辅助审核数据，不能自动变为 `labels.jsonl`、训练标签或 `allowed_for_navigation`。

如果找不到正例，请完整报告“在当前 34 条可达路线及所见证据中未确认正例”，不要为了得到正例强行放宽定义。

## 5. 第三项任务：设计真正的 Query-time Edge 使用机制

本任务的**最终目标不是完成 22 条审核，而是提出可以测试的 Query 利用 Edge 的算法**。基于真实案例，回答：

- 为什么 R1 的“有邻居就扩展”不够？
- 为什么 R2 Target Similarity 不是边际答案效用？
- 为什么 Anchor Lexical Proxy 可能出现 false rejection 或 false acceptance？
- **给定 Query + 当前 Dense 证据状态，什么条件下应该走一条已存在的 Edge、跳过它或停止扩展？**

至少提出一个可实现的 **Evidence-slot / Evidence-state-conditioned Query–Edge Traversal** 最小设计：

1. 从 Query 提取可核验的答案槽位/约束（可以先用透明规则或离线准备，不假装有独立真实 state label）。
2. 由 Dense Top-10 的局部证据构建每个槽位的 `supported / partial / missing / unknown` 状态；不能仅靠 Query 与 Target 余弦相似度来判定完整性。
3. 对候选 Edge 先应用 **eligibility gate**（`denied → reject`，`unknown → inspection only`），再判断方向化 Source Anchor 与缺失槽位是否匹配。
4. 根据关系类型、Target Anchor 与缺失槽位的兼容性，判断 Target 的**潜在增量价值**；无法确定时保留 `uncertain/abstain`。
5. 与 R1/R2 使用同样的 1-hop、最多 6 条检查路径、最多 3 个新增 Target 的预算；允许零扩展。
6. 当 Dense 已完整覆盖问题时停机；未覆盖但没有可靠且有用的 Edge 时，也要允许停机，不强行扩展。

先输出**具体伪代码、完整状态 schema、Failure Modes 和可运行的最低成本实验协议**。仅在真实审查数据给出可区分的正负机会时，才实现 CPU-only 的 R3 研究原型；否则明确不可识别之处和需要的最小人工标注量，不要用主观合成例子宣称检索提升。

**比较应在同一 Query/Route 集合上进行**，记录 Query-level 的候选增益、拒绝原因、False Rejection、零扩展理由、与 Dense Top-20 的重复及 opportunity cost。指标要区分“研究性 AI 初审”与“人工独立验证”；未有正例时 useful-route recall 必须为 N/A。

## 6. Gold 后验分析：只能在前面冻结后进行

一旦 Route 样本、判断与设计规则冻结，才单独读 Oracle/Gold 文件：

- 验证 Query 存在未被 Dense Top-10 覆盖的 Gold Page/Region 的情况；不要把同页所有 Node 都当 Gold。
- 交叉统计可达 Qwen/KG/Reading Route 是否真的到达**缺失的 Gold Region**；严格区分 `page-level`、`bbox-supported node`、`answer-semantic support` 三层。
- Gold 只用于**后验机会诊断与评价**，不能调整抽样、算法阈值或生成路线。
- 若没有独立正例、或者缺失页面与任何现有 Edge 不连通，请报告该样本下的可识别上限，不要自动把任务转成增加 Edge 数量。

## 7. 本轮交付及验收

期望 Copilot **实际编写并测试**新代码（而不只是提出建议）。请交付：

1. `audit_remaining_query_edge_routes.py` + `test_audit_remaining_query_edge_routes.py`；
2. 新的独立输出目录：22 条盲审卡、空标签模板、私有对账索引、选择摘要、输入哈希和复现说明；
3. `QUERY_EDGE_UTILITY_ANALYSIS.md`：逐类失败机制、若有则包含正例、R1/R2 的表现边界和 Query–Edge Utilization 研究判断；
4. `R3_EVIDENCE_STATE_DESIGN.md`：不是 Edge Construction，而是 **Query-time 决策算法**、伪代码、状态定义、评估协议与停机条件；
5. 测试通过证明；记录 `git rev-parse HEAD`、真实输入文件 sha256，明确运行过哪些程序、哪些指标没有计算。

可选：如果可访问完整局部证据、具备足够案例且有安全的研究性标签，再提供隔离的 CPU-only R3 原型，**绝不**修改生产 Navigation。

## 8. 执行顺序

1. 阅读代码、核对文件与版本；只读诊断。
2. 实现 22 条剩余路线的完整盲审 census 和测试。
3. 报告全部 34 条的 Query–Edge Utility 机会与负例；单列 AI 初审的不确定性。
4. 针对真实证据设计 R3；必要时做受控、有限的 CPU-only 对照。
5. 最后才进行 Gold post-hoc 检查，并出具可追溯报告。

**请不要因为“现有 Edge 效果不好”就把任务又转成 Edge 生成/Allocator 调参。真正需要解决的是：何时、为何以及如何让 Query 利用已有 Edge。**