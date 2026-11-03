# 将知识图谱链接预测接入 EvidenceNet：研究与实验计划

日期：2026-11-01，更新：2026-11-02。状态：v2、P1/P2、20-pair bounded model verifier 与条件式 query reachability smoke 已完成；没有独立人工标签或 retrieval gain 结论，ULTRA 官方 smoke 因依赖/checkpoint 未缓存而暂停。

本文补充 [基于 HF 对照结果的建边调整计划](EDGE_CONSTRUCTION_PLAN_AFTER_HF_20261101.md)。下文涉及 EvidenceNet 的改造均为我们的设计，不是论文已经验证的结论。

## 1. 要回答的问题

能否利用已有图结构和节点内容，发现当前文本相似度候选召回遗漏的连接，并最终提高固定预算下的证据覆盖？

建议把 KG 模型先接在离线候选发现层：模型提出可能连接，经原文 verifier 核验后才进入证据图。在线仍由 query 决定哪些边值得访问。预测概率不等于原文事实，也不等于对当前 query 有用。

必须区分三个任务：

| 任务 | 输入与输出 | 对当前问题的作用 |
|---|---|---|
| 端点预测 | `(node A, relation, ?)` → 候选 B | 能补充从未被召回的 node pair，优先测试 |
| 关系预测 | `(A, ?, B)` → 候选关系 | 改善已知 pair 的关系判断，单独做不能解决漏召回 |
| query 条件导航 | `(query, A, edge, B, 已选证据)` → 访问/选择 | 判断新增证据价值，不能由前两项的 KG 排名直接替代 |

其中 KG 论文中的 query 通常是缺失一个位置的三元组，并非用户自然语言问题。

## 2. 已核查的研究与实现边界

### TRIX：优先研究结构驱动的候选补充

[论文：TRIX: A More Expressive Model for Zero-shot Domain Transfer in Knowledge Graphs](https://arxiv.org/abs/2502.19512)；[官方代码](https://github.com/yuchengz99/TRIX)。

方法利用关系与实体之间的结构交互，支持跨领域、未见实体和关系上的归纳预测，同时研究端点与关系预测。官方代码包含两种任务的训练与推理入口；本次未确认可直接下载的预训练 checkpoint，不能把仓库里的 checkpoint 参数示例当成已提供权重。

对我们的用途：测试图结构能否产生文本近邻之外的候选。其关系预测是在目标图的候选关系中打分，不是自由生成任意关系句子。把文档片段当作 KG 实体，是需要验证的领域迁移。

### CBLiP：借鉴局部连接结构来判别候选

[论文：Replacing Paths With Connection-Biased Attention for Knowledge Graph Completion](https://www.cs.rpi.edu/~zaki/PaperDir/AAAI25.pdf)；[官方代码](https://github.com/shoron-dutta/CBLiP)。

通过 Transformer、连接偏置注意力和实体角色表示编码局部子图，避免显式路径编码。论文研究归纳式实体预测，以及传导式关系预测；不能据此声称已解决未见关系上的完全归纳迁移。代码分别提供 IEP 和 TRP。

对我们的用途：比较“只看两端内容”和“看两端及周围连接”能否减少错连。加入节点文本、图表说明和公式角色属于我们自己的扩展。当前少量自动生成边不足以支持直接训练可靠模型，需要独立的人工核验训练/验证数据。

### ULTRA：较适合作为第一轮可运行基线

[论文](https://arxiv.org/abs/2310.04562)；[官方代码与权重](https://github.com/DeepGraphLearning/ULTRA)。

ULTRA 支持迁移到新实体/关系词表的知识图谱，仓库提供预训练权重和自定义图推理说明。相较于从零训练，可先用它验证结构迁移是否有信号。代码可用并不表示适配 EvidenceNet 后必然有效。

### FnF-TG：与开放关系描述更贴近，但代码尚未就绪

[论文：Fast-and-Frugal Text-Graph Transformers are Effective Link Predictors](https://aclanthology.org/2025.findings-acl.615/)；[官方仓库](https://github.com/idiap/fnf-tg)。

结合文本描述与一跳邻域，并在完全归纳扩展中用关系文本生成关系表示。这与我们的文本丰富节点和开放关系描述更接近。不过，核查时仓库只有 Coming soon，尚无可运行实现；若实现相近架构，应标为“受 FnF-TG 启发的适配”，不能宣称官方复现。它同样不等于自动生成、验证任意关系描述。

## 3. 现有结果对这条路线的限制

已有诊断见前述建边计划：被冻结的语义图只有 187 条边、321 个端点，相关节点库有 7291 个 node；前序导航没有接入完整 reading layer。187 条也是自动生成的提案，不能全部视为人工金标。

因此必须先完成结构覆盖审计。大量孤立节点、仅由 NEXT 组成的独立链、统一 RELATED 标签，可能不能为纯结构模型提供足够区分信号。这是对我们数据的风险判断，不是上述论文的实验结论。

现有 `scripts/vldocir_reading_backbone.py` 已有受审计图导入及 NEXT/PREVIOUS 构建逻辑；不能重复写一个忽略原始 reading_ready 状态的替代品。当前页面局部流也不能被当作已验证的跨页阅读顺序。先统计实际载入覆盖率，再比较 KG 模型。

H0/H1/N/S 的既有检索结果不能当 KG 训练标签。尤其 H1 每页只取一个 node 的定位限制、S 只有部分题完成，仍需要分开处理。

## 4. 图表示：保留证据节点，也保留开放描述

第一阶段以原 EvidenceNode 为预测端点，保留 node_id、document/page、原文定位和模态。这样新边可以直接落回现有搜索流程。

KG 适配层采用两部分：

- 可验证结构谓词：NEXT、PREVIOUS、CONTAINS、CAPTION_OF 等，只导入已确认的关系；这些属于导航或归属，不自动代表事实支持。
- 原有语义边：保留自由描述、两端锚点和核验状态；结构基线允许使用少量稳定粗标签，文本图模型使用描述表示。

不要给每句自由描述创建互不共享的关系 ID 并期待纯结构模型理解句义。也不要为迎合 KG 模型，强迫所有语义关系重新进入细粒度固定 taxonomy。分别报告粗类型结构版和文本关系版，承认前者可能丢失语义。

第二阶段可增加 Entity 节点及 EvidenceNode→Entity 的有来源 mention 链接。实体消歧必须保留年份、实验条件、作品版本等区别；同名不自动合并。实体层用于候选路由，最终证据仍必须回到原节点和原文，不能把 entity hub 当答案来源。避免同实体节点展开成全连接 clique。

## 5. 接入流程与接口

```text
原文、节点、经核验的结构/语义图
  ├─ 原有 ANN / lexical / identifier 候选
  └─ KG 端点预测候选
          ↓ 合并、去重、按固定预算分配
     同一个原文 verifier
          ↓
     带出处、描述、类型和版本的 accepted edges
          ↓
     冻结的 query 检索 → Top10 入口 → 沿边导航 → 原文片段选择
```

KG 必须有机会提出原 ANN 候选池之外的端点。仅重排原候选池可以降低 verifier 浪费，却不能证明解决了漏召回。

候选记录至少保存：`source_id, target_id, proposed_relation, proposer, model_version, graph_version, raw_score, candidate_scope, is_new_to_baseline`。KG score 单独保存，不冒充 verifier confidence，也不与不同模型的原始分数直接相加。

核验后另存两端各自的原文 anchors、简短关系描述、是否接受及拒绝原因。在线记录 query 相关性、目标新增证据、访问结果；新描述应简短并有来源，但一句话不是正确性的保证。

所有图与边表示离线建立；在线只编码 query、进行评分和必要的原文判断，不按每个 query 重建语料 embedding。

## 6. 第一轮实验设计

先使用已有开发集定位可行性，最终用未参与调参的文档/query 做检验。当前小规模 pilot 的提升不宣称官方全集提升。

| 组别 | 候选方法 | 其余条件 |
|---|---|---|
| A | 现有文本/identifier 召回 | 冻结 verifier、总候选预算、结构图和在线流程 |
| B | 同一候选池 + KG 重排 | 检验核验效率，不声称发现新端点 |
| C | 原候选 + ULTRA 新端点提案 | 固定总核验预算，记录替换了哪些原候选 |
| D | 原候选 + TRIX 新端点提案 | 权重来源和运行可用性核查后执行 |

CBLiP 和文本图扩展放在第二轮，避免一次改候选、表示、训练数据和在线选择而无法归因。若需要训练，把训练成本、训练数据与 zero-shot 实验分开报告。

不构建全部 N² 边。按源节点和关系限制 TopK 提案、设置全局 verifier 预算；若模型需要扫描所有尾实体，另记实际推理成本，不能把保存 TopK 等同于计算也只需 TopK。限制候选范围时公布过滤规则，并同时检查过滤是否排除了正确目标。

### 6.1 建边指标

- 人工核验集上的候选 Recall@K、接受边 precision、相同预算下新增正确 pair 数。
- 将“原池内重排改善”和“原池外新增正确 pair”分开。
- 按纯文本、公式、图表、跨文档、同文档远距分别统计。
- MRR/Hits@K 仅用于明确标签范围的 KG 测试；报告候选空间与过滤协议，不与不同候选范围结果混比。
- 未标注 pair 是未知，不可一律作负例。对模型新发现的候选进行盲审，报告抽样方式。

### 6.2 检索与片段选择指标

在相同 query、检索库、入口、token 与访问预算下，对比无边、原边、增强边。维持 HF 原始页面排名 H0 和同选择器的 H1 对照，并单独检查页内定位。

报告 Recall/AP/nDCG@5、@10（必须有完整页面排名才计算），gold 来源覆盖、最终选择 tokens、原文支持与噪声、耗时和调用成本。页面 gold 命中不能代替片段证据正确，模型自报充分不能当人工金标。

重点逐题追踪：初始入口未命中 → 新边确实使目标可达 → 实际访问目标 → 选中目标原文 → 增加有效证据。对“原本已命中”和“新增访问但无收益”分别计数，不把走边次数当成功指标。

## 7. 数据拆分与泄漏控制

按文档或相关实体组划分训练、开发、测试；不能只随机拆边，使同一事实的相邻片段落入两侧。测试图允许哪些已观察关系必须预先声明。

隐藏测试边时，同时移除其逆边、等价重复边，以及由目标事实直接生成的描述特征；查询 `(A, ?, B)` 时不能把金标关系句子喂给模型。保留合法可观察的上下文，但不能通过编码等价事实泄漏标签。

离线建边不读取检索测试 query 或 gold 页面。当前失败例子只做诊断与开发回归；正式结论需要新的保留集。现有自动边仅作为噪声观测图，不自动充当真值。

## 8. 实现顺序与继续条件

1. 导出带来源和版本的可观察图，审计结构层及孤立节点；复用现有 importer。
2. 建立小规模人工核验 pair 集及按文档拆分，包含相似但不同条件、不同字母同公式、通用公式同形异义等 hard cases。
3. 独立环境运行 ULTRA 官方小例子，再适配 EvidenceNet；核查 TRIX checkpoint，若需训练则单列预算。
4. 运行 A/B/C，统一 verifier 和候选预算；有新增正确端点再运行 D 与在线对照。
5. 若只有补边指标改善而证据不变，检查可达性、导航与选择；若新增候选多为错连，回到文本/实体身份约束，不继续扩大图密度。
6. 若结构模型缺乏有效信号，再实现带文本与关系描述的局部图模型。此时明确标为研究适配，不以论文名称替代复现证据。

最低交付物：配置及输入 hash、候选及拒绝记录、accepted edges、逐题访问路径、最终原文片段与成本、匹配口径的对照报告。验收目标是固定预算下新增可验证证据，而不是增加边数。


## 9. 2026-11-02 — 非文本 EvidenceNode 的文本化前提（待代码核实）

用户补充的重要系统前提：**Formula / Table / Figure 等非 text 模态的 EvidenceNode 通常已经有相关上下文或文本描述**。因此对于离线 KG 候选端点预测，可以优先视为 **text-attributed Evidence Graph**，不必在第一轮为每一种模态额外开发专用编码器。原始模态、原始锚点和 provenance **仍必须保留**，最终 verifier 应回看原始证据；文本摘要可能漏掉公式等价性、数值、坐标轴和实验条件。

**待核实的实现问题（不能擅自认定已统一）**：现有不同模态的 `text_representation` 是否都能通过相同读取接口拿到？字段具体在哪里、哪些为空、描述是否携带必要的变量定义、表头/单位、图注及实验条件？请抽样并统计覆盖率；不要重做描述生成，也不要假定这一步需要新的视觉模型。

**对研究顺序的影响**：
- 将 **text-only candidate proposer** 作为对照，并研究可利用邻域信息的 **text+graph proposer**；衡量结构信息是否带来原文本候选池外、经核验的正确新连接。
- ULTRA / TRIX 仍保留为已有权重及适配条件允许时的 **结构 KG 基线**；它们不自动利用节点文本，不能因为节点有描述就假设模型已消费描述。
- FnF-TG 等文本图方法继续作为方法参考，具体代码与 checkpoint 可用性需另查，不要把未验证论文实现当作即插即用。
- 第一轮应优先预测**端点候选**，而不是强制所有自然语言关系映射到一个细 taxonomy。Verifier 再判定具体关系和目标提供的新证据。
- 继续区分「有真实关系」「在旧候选池之外」「对 query 检索有帮助」三个不同指标。

### 同日 Article / Reading 修复核查对 KG 输入图的影响

以下为**用户提供的 Codex 本地代码/测试核查结论**，本节并未独立复现 HoreKa 测试：
1. Worker isolation **fixed**：真实入口 `run_vldocir_pipeline_comparison.py::reading_worker/run_document` 逐文档隔离；已有测试及 v2/v3 运行证据。
2. Invalid checkpoints **old path unused in fresh workflow**：fresh 入口使用新输出根，恢复由 `RecoveryCalls` 和 `--retry-invalid` 处理；不能混同 `--retry-document`。
3. Single-article cross-page NEXT **still missing in current VLDocIR v3 execution**：single-article continuation 分支仍被跳过；独立 `run_document_cross_page_qwen.py` 尚未接入 v3；两文档只有 9、2 条页内 NEXT，跨页 0。
4. Readiness coupling **fixed / strict importer intentional**：逐文档 partial 不使 worker 中断；严格全图导入仍要求完整验证。
5. Reading graph import→query **unverified end-to-end**：已有各自的单元测试和 collector/retriever 代码，但 v3 尚无 `collect → retrieve` 的已完成整链路运行证据。

**这不阻止研究 KG 候选发现**，但决定 KG 试验输入图的真实可用性：显式标记跨页 NEXT 缺失与 reading import 未验证，不把 v3 page-local 边冒充全阅读图；KG 适配实验可以先使用已校验的局部图并报告限制，不将这些修复议题无条件设为整个 KG 研究的重新启动前提。

### 2026-11-02 后续实测更新：v5 reading 与 KG pilot v2 preparation

上述 v3 限制中的第 3、5 项已由全新 v5 smoke 实测更新：两篇文档的 58 个 EvidenceNode 完成严格 article/reading 验证，导出 21 条 `NEXT` 及其 21 条 `PREVIOUS`；其中 1 条是显式两阶段判定的跨页 `NEXT`。Importer/navigation 检查覆盖 42/42 条 directed edge，Slurm job 以 exit code 0 完成。该结果只验证这 58 个节点，不外推到其余 corpus。

`kg_link_prediction_pilot_v2_20261102` preparation 继续冻结完整 VL-DocIR 范围：32 documents、518 pages、7291 EvidenceNodes。v5 的 58 个节点只是完整图中的 validated reading subset；其余节点不推断 reading edge，缺边不作负例。213 条 `RELATED_OPEN` 保持 noisy observed context，绝不作为 gold。

统一文本直接来自既有 `members[].text`：7288/7291 节点非空，不重新 Parsing、Node Generation 或 OCR。原冻结 embedding views 覆盖 6520 个节点，因此不重新编码时，Text-only、Text+Graph、ULTRA 的主公平比较 universe 固定为这 6520 个共同可见节点；其余 768 个有文本但无冻结 view 的节点和 3 个空文本节点仍保留在完整实体图中，但不进入主比较候选空间。若以后扩到 7288 个文本节点，必须对缺失节点按同一冻结协议补编码并作为单独实验版本。

原 1088 个 `node_candidates.jsonl` pair 被固定为 baseline membership set。后续所谓“新端点”严格指 canonical pair 不在这 1088 个固定预算候选中，并不声称它不在任何可能的 ANN 邻居中。v2 preparation 没有运行候选生成、KG model、embedding 或 verifier；72 个 blind review pair 仍未标注，因此当前不能报告 candidate recall 或 verified precision。

### 2026-11-02 P1/P2 第一轮 Candidate Generation

已在不修改 v2 preparation 和 production Edge Pipeline 的条件下完成 CPU candidate generation。P1 将同一 EvidenceNode 的既有 frozen views 取均值并 L2 normalize，以 node cosine 生成 Text-only 排名。P2 使用完全相同的 6520 source/target universe、document-split filtering、self/observed-`RELATED_OPEN` 排除规则及 TopK=20；仅对具有观测邻域的 source 加入类型化邻居传播分数（`RELATED_OPEN` weight 1.0，`NEXT/PREVIOUS` weight 0.75，最终 graph blend 0.20）。noisy semantic edge 只作 context，不作 gold；无边也不作负例。

CPU smoke 覆盖三类关系并通过接口、过滤和 isolated fallback 检查。完整运行每个 proposer 保存 130400 条定向 Top20 ranking，再使用同一 deterministic canonical-pair 去重规则截取 1088 pair。P1 与 baseline 重合 112，baseline 外 976；P2 与 baseline 重合 111，baseline 外 977。两臂全局预算共享 1086 pair，各有 2 pair 独有。这只是 candidate composition 差异，不是质量提升。

图覆盖必须单独解释：6520 个 source 中只有 386 个在过滤后的 frozen universe 内具有图邻域，6134 个完全孤立。connected sources 中 373 个 Top20 发生变化，共有 502 个 P2 Top20 entrants，平均 P1/P2 Top20 集合重合 18.70/20；isolated sources 的 P2 ranking 被断言逐项等于 P1。全局 P2 budget 中只有 30 个记录以 connected node 为定向 source，因此不能用总体 2-pair 变化掩盖或否定局部图行为，也不能据此声称 retrieval improvement。

完整 rankings、raw scores、逐候选 graph provenance、逐 source graph decisions、时间与输入 hash 位于 `EvidenceNet/output/kg_link_prediction_p1_p2_20261102/`。本轮未运行 Parsing、OCR、Node Generation、Embedding、ULTRA、GPU training 或 verifier。没有独立人工审核标签，故不报告 precision、recall 或 Retrieval improvement。

### 2026-11-02 P1/P2 bounded follow-up

按照 `KG_LINK_PREDICTION_P1_P2_VERIFICATION_QUERY_SMOKE_ULTRA_HANDOFF_20261102.md`，已验证 P1=1088、P2=1088、shared=1086、P1-only=2、P2-only=2、union=1090。373 个 connected changed sources 的 P2 local Top20 共引入 502 个 source→target incidence、450 个不同 target ID、499 个 canonical pair；这些 local entrants 全部进入候选 union，但最高 P2 score 0.799447，低于全局 budget cutoff 0.875060，因此 0 个进入全局 1088 budget。两个 P2-only 全局 pair 原本已在各自 source 的 P1 Top20 中，是 graph reranking 越过全局 cutoff，不是 local Top20 新 entrant。allocator 没有 source quota，瓶颈是全局分数阈值，不是 observed-edge exclusion、candidate union 或 canonical dedupe。

已冻结 20-pair bounded verification selection：4 个 P1/P2 disjoint、4 个 stratified shared control、6 个 locally changed but globally excluded P2 candidate，以及同 source 的 6 个 P1 local-exit control。每项保存原文 excerpt/location、proposer membership、baseline novelty、graph provenance 和空白 verdict/direction/contribution 字段；当前全部为 `unreviewed`，没有自动用相似度或图分数打标签。

因为 `accepted_edges.jsonl` 仍为空，query integration smoke 正确状态为 `BLOCKED_NO_ACCEPTED_VERSIONED_EDGE_SUBGRAPH`；不能为了展示路径而凭空接受边或用 query gold 选边。ULTRA 官方接口已固定到 commit `427966ad8ed60420eef034063d44f3153addff90`，导出 6520-node entity map 与按 split 隔离的 observed context triples，但未 clone、下载 checkpoint、编译 `rspmm`、运行 inference 或训练。ULTRA 是 structure-only，不读取 `members[].text`，当前 eligible context 只覆盖 387/6520 个 endpoint nodes，因此适配在接口上可行、证据上仍受 sparse/noisy graph 限制。

follow-up 的人类可读报告、输入 hash、四个 disjoint pair、source-level budget diagnosis、verification selection、query blocker 和 ULTRA readiness 位于 `EvidenceNet/output/kg_link_prediction_p1_p2_followup_v1_20261102/`。仍不报告 precision、recall 或 retrieval improvement。

### 2026-11-02 Bounded verifier execution preparation

按照 `KG_LINK_PREDICTION_BOUNDED_VERIFIER_ULTRA_SMOKE_HANDOFF_20261102.md`，已为冻结的恰好 20 pair 生成 source-grounded verifier snapshot：54 个覆盖完整 eligible member text 的窗口、40 个 endpoint node crop、16 个仅来自 validated v5 NEXT/PREVIOUS 的 reading-context 条目。推理不使用 diagnostic 中的截断预览；reading context 不能替代 endpoint anchor。输出 schema 强制保存 direction、`target_B_adds`、complementarity、entity/condition constraints、两端 anchors 和 model/human review status。

本地节点没有 GPU；Qwen3.5-35B-A3B 权重约 72GB，沿用现有 4-GPU Horeka verifier 路径。任务上限固定为 20 pair，每 pair 最多 2 次尝试、全任务最多 24 次生成；不允许扩大 selection。部署包位于 `migration/horeka-kg-bounded-verifier-v1-20261102/`，目标输出是 `EvidenceNet/output/kg_link_prediction_bounded_verification_ultra_smoke_v1_20261102/`。当前 `verifier_results.jsonl` 和 model-only accepted subgraph 为空，不能提前陈述 verdict。

若产生 source-anchored model-accepted edges，任务只运行 frozen seed reachability CPU smoke，最多保存 5 条路径；不执行完整 reranker 或 24-query benchmark，也不报告 retrieval metric。若没有 accepted edge 或没有 reachable seed，则显式报告对应状态。

本机已有 PyTorch，但没有 `torch_geometric` 或 ULTRA checkpoint。根据 handoff，不自动安装、下载、编译 `rspmm` 或运行官方数据集；`ultra_smoke_report.json` 记录 pinned commit、官方命令、环境差异和独立授权需求。MIT 仅确认为 repository license，不外推 checkpoint redistribution terms。

### 2026-11-02 Bounded verifier 运行结果

Horeka Job `5223949` 在 `dev_accelerated` 上以 exit code 0 完成，20/20 pair 全部处理，实际 21 次生成调用，未超过 24 次上限。模型 verdict 为 8 `EVIDENCE_LINK`、12 `NO_LINK`、0 invalid/error；其中 7 个 model-accepted pair 位于原冻结 1088 baseline 外。所有 verdict 仍是 `model_reviewed`，独立人工核验数为 0，production graph 未修改。

按 selection group：P1-only 为 2/2 accepted；P2-only 为 0/2 accepted，跨公司 SEC householding 与 clawback 两例均为 `NO_LINK`；shared control 为 3/4 accepted；P2 local entrant 为 2/6 accepted；matched P1 local-exit control 为 1/6 accepted。该小样本不能当 precision/recall，也不足以证明 P2 优于 P1。

条件式 query smoke 找到 1 条 frozen-seed route：director-election voting query 从 seed 通过 model-only edge 到达初始 rank 211 的 target。代码导入和 traversal 成功，但未运行 reranker/selector，`target_selected_by_reranker=null`。该 target 原文讨论 auditor-ratification voting，与 director-election query 存在明显 scope mismatch；这说明 smoke 只证明可遍历，也暴露 model-only edge 可能过宽，不能据此声称 retrieval gain 或自动 promotion。

完整结果、source anchors、model-only subgraph、query trace、execution metadata 和 verifier manifest 位于 `EvidenceNet/output/kg_link_prediction_bounded_verification_ultra_smoke_v1_20261102/`。
