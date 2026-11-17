# Evidence-first Node-level QA 标注与审核规范（v2）

**适用项目**：DynamicEdgeGraph / EvidenceNet  
**目标**：构建可靠的 Long-document Multimodal Retrieval Gold QA Benchmark，用于评估 Dense、Hybrid、Graph-based Retrieval。  
**生成模型**：Terra 或 Sol；两者执行相同协议。  
**版本日期**：2026-11-17。  
**核心原则**：程序预先抽样证据；模型基于证据生成问题；独立审核 Question / Answer / Evidence / Node Mapping。**不能让生成模型随意挑自己最容易写题的材料，也不能把初始抽取的 Node 自动视作最终 Gold Node。**

> **重要说明**：本文件所列路径、语料规模、处理进度均来自项目方提供的当前数据清单。撰写本规范时没有直接访问 HoreKa2 文件系统、原始 PDF 或 canonical node DB。运行前必须由 Sol/Terra 在实际 HPC 环境核对目录、清单、字段、文件数与页面图的可用性，不得自行假设解析格式。

---

## 0. 给 Sol / Terra 的执行任务（首先阅读）

你负责为 EvidenceNet 构建一版新的、**Evidence-first、node-grounded、可追溯**的 QA Benchmark。**不要对已有 268 条候选草案直接批量修改并当作新 Gold**，也不要从已有答案反推证据。必须从下面定义的两个合格数据源建立独立采样池，记录真实的 seed Node 和候选发现过程。

**最终通过内容和映射审核的样本**，目标类别分布：

- **20% Single-node**：完整答案仅需要 1 个必要 Node；
- **30% Cross-page**：来自**同一 document 的不同页面**的至少 2 个必要 Node；
- **50% Cross-document**：来自**至少 2 个不同 document** 的必要 Nodes；其中总体 **35%** 为双文档、总体 **15%** 为三文档及以上。

这三类互斥。跨文档题就算同时跨页，仍计为 Cross-document。比例是目标，不得以强行拼接无关证据、构造虚假关联、伪造 Node IDs 或放宽审核门槛的方式凑数；配额不足必须报告。

必须保存：抽样 seed、方法及随机种子、原始文档和页、evidence unit、canonical node mapping 的实际状态、Question、Answer、每个 Node 的证据作用、证据必要性测试、来源核对状态、详细审核意见和可替代 Gold Sets。

**先检查数据、实现小批试验、做 QA audit、调整生成器，再扩量。** 严禁覆盖既有人工标注或修改原始 PDF/解析 checkpoint。

---

## 1. 可用数据集与文件路径

### 1.1 新下载、已解析完成的期刊 PDF（当前可用 18 篇）

原始 PDF 根目录：

~~~text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pdfs
~~~

页级解析材料（文本、bbox、页 JSON、页面图）根目录：

~~~text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work
~~~

**已完成页级解析且 checkpoint 无失败页的 document_id 范围**：

- real_001–real_013（13 篇）
- real_015–real_018（4 篇）
- real_020（1 篇）

**暂不可进入采样池**：

- **real_019**：目前仍在 dev-H100 队列中，只有完成解析、通过 checkpoint 和质量审计之后才能纳入。
- **real_014 及任何未列入已完成范围的 ID**：不能由编号连续性推断其已完成；先核对文件和实际状态。

新期刊数据可以先从已抽取的页级 **Evidence Units** 构建候选池，但不代表这些 Evidence Units 已经与最终 canonical node 一一正确绑定。记录 evidence_unit_id、source_json、bbox、page_number、PDF 路径；在生成最终 Gold 之前，必须核对并写入实际 canonical_node_id，必要时建立明确可审计的映射表。若当前只有 pending_evidence_node_assembly，不能把它写成 MAPPED_VERIFIED。

建议抽样前运行目录巡检，统计每个文档的页数、页 JSON 数、图片数、可用文字/表格/图片证据数、无效页及异常 OCR、重复内容。

### 1.2 最初旧语料（当前可用 25 文档、49 页）

旧语料根目录：

~~~text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113
~~~

文件清单：

~~~text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/documents.jsonl
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/pages.jsonl
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/nodes.jsonl
~~~

此数据源已有 Nodes 和页图，可作为 Node-first 采样的直接入口，但仍需检查 ID 唯一性、Node 内容、文档/页引用、page image 有效性及是否有语义重复。**“已有 node”不等于“QA 所需的 Gold Node 经过审核”。**

由于 25 文档只有 49 页：Cross-page 配额必须选择实际拥有两个以上可用页面、且跨页有必要证据的文档。不能假设每篇文档都有足够页数；Cross-document 可在同一旧语料内或在两个语料之间寻找可信证据组合，前提是来源实体和事实具有真实可验证的联系。

### 1.3 既有 QA 候选与审阅数据（不是自动 Gold）

新期刊人工草案：

~~~text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/qa_review_drafts_v1
~~~

旧语料 QA 草案：

~~~text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/qa_review_drafts_v1
~~~

整合 query / candidate gold：

~~~text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/all_qa_review_drafts_v1
~~~

172 页期刊密集扩展候选：

~~~text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/dense_magazine_candidates_v1
~~~

**使用限制**：

1. 这些内容只能用作**去重、质量故障分析、生成器回归测试和已知错误排除**；不是新 QA 的 Gold 真值。
2. 禁止把已有候选的 Question / Gold Answer 作为本次 Evidence-first 生成的隐式输入；否则无法证明新集独立。
3. 历史候选可能含泛化模板、答案整段复制 Evidence、OCR 伪文本、未完成 Node 映射；必须逐项重审，不能因已有 review_decision=ACCEPT 就跳过。
4. 对新生成问题执行与上述目录的语义去重，记录旧 draft_id 和匹配程度；高度重复时重新生成或排除。

---

## 2. 基本定义、类别边界与目标配额

### 2.1 Evidence Node

一个 Node 是可追溯到 source document 和页面/区域的最小信息单位（可能是 TEXT、TABLE、IMAGE、CAPTION 或其他实际 schema 类型）。不得把“任意一段模型生成的摘要”伪装成已有 Node。对于新期刊，尚未映射时只能称为 **Evidence Unit / provisional evidence**。

### 2.2 Single Node（20%）

- 只有 1 个必要 Node。
- 该 Node 独立支持完整答案，不依赖外部常识补事实。
- 合适的问题可以问定义、数值、机制、条件、技术取舍，但不是无意义的表面词汇定位。
- 如果段落过短、只是标题或目录、缺少独立可回答事实，记录 SKIP，而不是硬写问题。

### 2.3 Cross-page（30%）

- 至少 2 个必要 Nodes，来自**同一 document_id 的不同 page_number**。
- 仅跨 Node 但未跨页，不算 Cross-page。
- 设计目标是互补事实或跨页推理，而非把两段无关信息拼在一起。
- 建议在总样本中尽可能达到：**5% 近距离（1–2 页）**、**10% 中距离（3–10 页）**、**15% 远距离（>10 页）**。这是次级覆盖目标，不适用时必须报告实际分布和原因。

### 2.4 Cross-document（50%）

- 至少 2 个不同的 document_id，且跨文档节点均为必要证据。
- 总体建议 **35% 双文档** + **15% 三文档及以上**。不把跨文档问题重复算入 Cross-page。
- 允许同语料内跨文档，以及跨新/旧语料；必须标记 cross_corpus=true/false。
- 不得只因关键词相似就把不同文档关联；需要实体、技术、过程、时间线或可比指标的实际联系。
- 不要将同一原文的重复版本、目录/正文重复、转载内容错误当作两个独立文档证据。

### 2.5 抽样分布

最终配额依据**通过最终 QA 质量门槛的样本**计数，失败、SKIP、映射待核验的记录不算正式 Gold。分层抽样维度至少包括：

- corpus / source（新期刊、旧语料）；
- document_id、page_number（避免热门文档独占）；
- node_type、证据模态（TEXT / TABLE / IMAGE / CAPTION，按照数据库真实值映射）；
- 长度/结构/内容质量、OCR 异常标记；
- 题型：comparison、bridge/multi-hop、complementary evidence、temporal evolution、causal mechanism、constraint/tradeoff；
- 多证据页间距、文档数量、是否跨语料。

需要保留每个 stratum 的样本量、候选失败率及最终接受率。**无法从部分模态获得可信视觉证据时，不得仅凭 caption 或模型常识编造问题。**

---

## 3. 端到端工作流（必须严格按此顺序）

### Stage A — Source Inventory & Quality Gate（程序执行）

1. 读取新期刊的 work、PDF 目录及页级 checkpoint；读取旧语料 documents.jsonl / pages.jsonl / nodes.jsonl。
2. 对齐 document_id / page_number / node_id / evidence_unit_id / source_json / bbox / image_ref。检查字段实际 schema，不猜测字段名。
3. 排除无法定位、图片缺失、文本严重乱码、公式错误合并、目录噪音、页眉页脚、重复 Node、空 Node 等。**记录排除原因**。
4. 发现 PDF 与解析文本不一致时，先核查 PDF 页图；如果证据无法可靠恢复，SKIP，保留解析异常报告。
5. 新期刊若 node mapping 尚未完成，标记 PENDING_MAPPING；允许生成**provisional QA**用于内部试验，**不能进入正式 Gold**。
6. 输出 source_inventory.json、eligible_nodes.jsonl、excluded_nodes.jsonl、mapping_audit.jsonl。

### Stage B — Deterministic Stratified Seed Sampling（程序执行）

1. 固定 random seed 和 corpus snapshot/version。
2. 在**合格 Node Pool** 上分层抽取 Seed Node，确保不是 Terra/Sol 自己随意浏览、只挑最容易写题的节点。
3. 保留抽样权重、stratum、seed_node_id 或 provisional evidence_unit_id、随机种子、尝试次数。
4. 以最终有效样本的 20/30/50 目标做 quota tracking。每个 seed 可生成 0 或 1 个主要候选；失败后从抽样池替补，不要求每个 Node 都必须产题。
5. 不允许将不同内容的 source ID 通过文本相似性静默合并成一个 canonical ID。

### Stage C — Companion Evidence Discovery（仅适用于 Multi-node）

Cross-page：固定同一 document_id，搜索其他不同页面的 Nodes，保留页距、来源和候选分数。

Cross-document：固定不同 document_id，可先用多种独立召回通道寻找关系候选：

- BM25 / lexical；
- 多路 frozen dense embeddings；
- 实体/术语/年份/方法/单位等 metadata；
- 少量受控随机探索，避免全部候选都由同一 embedding 偏好驱动。

**必须将 candidate discovery 与最终接受评估的 Evidence Graph 分开**：不可仅从 Stage 1 当前保留的 edges 选 Gold pairs，也不可让后续待评估图见到 QA/Gold 标签。否则评估可能偏向 Graph Retrieval。

保存每条候选边的 proposer（BM25 / dense / metadata / random）、分数或排序、筛选原因。候选有语义相似性不等于 Gold Relation 成立。

### Stage D — Evidence Configuration Validation（模型判断 + 程序校验）

对候选 Evidence Group，先判断是否真实存在以下可解释关系：

- **Comparison**：两个资料的属性可以在有相同条件/单位或明确差别的前提下比较；
- **Bridge/Multi-hop**：A 提供中间实体/技术身份，B 提供进一步属性，连接必须显式可证；
- **Complementary evidence**：一处给机制，另一处给限制/后果/应用，两者共同回答；
- **Temporal evolution**：不同时期同一技术或过程的发展，必须验证实体一致性及时间顺序；
- **其他可解释关系**：可新增类别，但必须详细说明为什么所有节点必要。

先写 evidence_claims（逐节点抽取的原子事实）和 planned_reasoning_chain，再决定能否写题。**先确定可验证的证据组合，后写 Question**。

对每个 Node 执行 **necessity / ablation test**：移除后剩余证据若仍足够回答完整 Question，则该 Node 不是这个 Gold Set 的必要成员；尝试缩减为最小证据集合或重新设计题目。还需执行 corpus-level alternative evidence search，识别可能的单 Node 捷径、等价 Gold Sets 和隐藏冗余。

### Stage E — Question Generation

- Question 必须 standalone、自洽、无 this passage / this article / above table 等模糊指代。
- 先列出必要事实，再依据多证据关系写问句；不得在问题中添加证据没有的前提或未经证明的因果。
- 提高难度应依靠跨证据组合，不是堆形容词、复杂改写或奇怪句式。
- 不得直接透露答案，避免逐字复制源句造成过高 lexical overlap。
- Cross-document 问题必须**真正需要**多个文档，不要只问“这两篇文章分别讨论了什么”而没有有意义的共同推理目标。
- 对 TABLE：数字、行列、单位、脚注、表头都要核对；对 IMAGE：必须查看页面/图像像素，不能只凭图名推断；CAPTION 只能支持 caption 自身明确陈述的事实。
- 源材料不支持高质量问题时直接 SKIP，并记录具体原因。

### Stage F — Gold Answer Generation

- 回答完整覆盖 Question 的全部子要求，短而精确，不复制整段 Evidence。
- 每个事实都要能定位到至少一个 Gold Node 的原始片段或图像区域。
- 比较题明确比较维度、条件和数值单位；多跳题体现关键桥接关系。
- 不从通用知识补充证据未陈述的数量、年份、材料、因果关系、图中物体。
- 对多证据答案，给 answer_claim_support 映射（answer claim -> evidence Node IDs），确保没有“只靠一段就能回答全部”的伪 multi-hop。

### Stage G — Independent Review（独立于生成）

审核者必须单独给出以下判断（不能只给一个 ACCEPT/REJECT）：

1. **Question Validity**：指代明确、可回答、无未支持前提；
2. **Answer Correctness & Completeness**：每个关键事实准确，回答完整；
3. **Evidence Relevance & Sufficiency**：内容相关且支持全部答案；
4. **Evidence Necessity / Minimality**：每个 Gold Node 是否不可缺少；
5. **Source Integrity**：PDF、OCR、TABLE、IMAGE、bbox、页码是否准确；
6. **Node Mapping**：canonical ID 是否经核实，不把 pending 当 verified；
7. **Duplicate / Alternative Evidence**：是否和旧题重复，是否存在等价金标准集合；
8. **Benchmark Leakage / Difficulty**：有没有利用候选发现方式或待评估 Graph 的信息泄漏。

即便建议 ACCEPT，也必须写**具体审核意见**，包括每个证据节点支持哪个答案子事实、存在什么范围限制、为何它必要，以及映射是否已核实。

禁止空泛评语，例如 "looks correct"、"evidence sufficient"、"all good"。审核不过须指出具体的字段、错误原文、修改提议和再次检查条件。

### Stage H — Final Gold Gate

每条正式 Gold 必须满足：

- Question、Answer、Evidence Group 审核通过；
- 每个 evidence_unit_id 均成功定位到受控版本中的实际 canonical_node_id，映射可追溯；
- 原 PDF / 页图中的关键事实已经在需要时核验；
- multi-node 证据的必要性测试通过，并搜索过替代证据；
- 已完成去重，且不因模型独立生成了相似题而重复计分；
- 已标记所有 provenance、generation/review versions 和 sampling_strategy。

**内容通过但 mapping 未完成**只能标记 CONTENT_PASS_MAPPING_PENDING，不得叫 FINAL_ACCEPT。

---

## 4. 推荐输出 schema（以实际存储 schema 为准）

每个 QA 独立保存为 JSONL 记录，必要字段建议如下（请根据已有项目结构适配，**不得静默覆盖原文件**）：

~~~json
{
  "draft_id": "nodefirst_v2::unique_id",
  "corpus_snapshot": "frozen_dataset_version",
  "qa_category": "single_node | cross_page | cross_document",
  "cross_document_subtype": "two_documents | three_plus_documents | null",
  "reasoning_type": "comparison | bridge | complementary | temporal | other",
  "question": "Standalone, grounded question",
  "gold_answer": "Complete evidence-grounded answer",
  "seed": {
    "source_corpus": "real_documents_v1_20261113 | node_vqa_reuse_v1_20261113",
    "evidence_unit_id": null,
    "canonical_node_id": null,
    "sampling_stratum": "recorded_value",
    "sampling_seed": 17
  },
  "gold_evidence": [
    {
      "source_corpus": "real_documents_v1_20261113",
      "document_id": "real_001_batch_01_NASA-Spinoff-2023",
      "page_number": 7,
      "evidence_unit_id": "source_specific_evidence_unit_id",
      "canonical_node_id": null,
      "node_mapping_status": "PENDING_MAPPING",
      "source_json": "absolute_path",
      "source_pdf": "absolute_path",
      "page_image": "absolute_path_or_null",
      "bbox": null,
      "node_type": "TEXT",
      "support_claim_ids": ["c1"],
      "necessity_reason": "specific explanation"
    }
  ],
  "answer_claims": [
    {
      "claim_id": "c1",
      "claim_text": "An atomic, independently supported answer fact",
      "supporting_evidence_indices": [0]
    }
  ],
  "candidate_discovery": {
    "methods": ["bm25", "dense", "metadata"],
    "candidate_pool_version": "explicit_version",
    "graph_edges_used_for_gold_selection": false
  },
  "necessity_test": {
    "each_gold_node_required": null,
    "single_node_shortcut_found": null,
    "alternative_gold_sets": [],
    "notes": ""
  },
  "review": {
    "status": "UNREVIEWED | CONTENT_PASS_MAPPING_PENDING | FINAL_ACCEPT | REVISE | REJECT | NEEDS_SOURCE_VERIFICATION",
    "question_validity": null,
    "answer_correctness": null,
    "evidence_sufficiency": null,
    "mapping_verified": false,
    "review_notes": "Detailed, evidence-specific justification",
    "reviewer_model": null
  }
}
~~~

该 schema 只是约定参考，**示例 ID / 页码不代表实际获得审核通过的 Gold**。生成程序应尽可能兼容现有项目文件字段，并同时输出原始记录与规范化记录，提供映射字典。不得为缺失字段伪造 canonical_node_id。

---

## 5. 质量门槛与自动化检查

### 必须自动执行的校验

1. **Schema / references**：draft_id 唯一，document/page/node IDs 存在，来源路径可追溯，bbox 合法，所有 Gold Node 可定位；
2. **Category constraints**：single 恰好 1 Node；cross-page 至少 2 Nodes 且同文档不同页；cross-doc 至少 2 文档；
3. **Answer claim grounding**：每个独立答案事实均有对应 Evidence；没有仅复制 Evidence 全文；
4. **Multi-node necessity**：节点删除测试与局部替代检索完整记录；发现单 Node 完整回答应降级或重写；
5. **Question template quality**：禁止泛化模板、脱离上下文不清晰的代词、伪复杂问题；
6. **Source quality**：缺图/表结构异常、OCR 垃圾、公式重复、内容截断、目录等单独标记并暂停 Gold；
7. **Dedup**：和本次生成及既有候选题进行 lexical + semantic 去重，保存匹配候选；
8. **Leakage**：Gold Evidence 选择不得依赖待评估 Stage 1 的 accepted edges 或 QA 本身派生的边。

### 模型人工语义审核仍然必须

程序只能筛掉显性错误；严肃比较、因果/时间连接、原图判断、必要性及单节点捷径都需要独立语义审核。对不确定问题必须保留 NEEDS_SOURCE_VERIFICATION，不得“合理猜测”自动放行。

### 通过后必须报告的统计

- 两套语料的候选 Node 数、eligible 数、excluded 数及原因；
- 各文档/各模态抽样数、SKIP 和接受率；
- single / cross-page / cross-doc 的目标与实际比例；
- cross-page 距离直方图和跨文档使用的 document_count；
- cross_corpus 的数量、每个 source corpus 的覆盖；
- question/reasoning types、answer length、Evidence Set size；
- duplicate、OCR、mapping 未完成、替代 Gold Sets、ablation 失败统计；
- 独立评审决策分布、待人工处理队列和所有改变的 diff。

---

## 6. 失败与恢复策略（不能靠凑数）

- **Seed Node 不合适**：SKIP_NOT_ANSWERABLE，替补抽样；
- **找不到真正互补的跨页/跨文档 Node**：SKIP_NO_VALID_GROUP，不能随机硬配；
- **整段 OCR 是异常文本或重复伪公式**：QUARANTINE_SOURCE，并回到 page image / PDF；
- **Gold Evidence 不充分**：REVISE_EVIDENCE，增加或替换经验证证据；
- **Gold Answer 不完整或过度推断**：REVISE_ANSWER；必要时改 Question；
- **Question 太泛、重复或伪多跳**：REGENERATE_QUESTION；
- **canonical mapping pending / ambiguous**：CONTENT_PASS_MAPPING_PENDING 或 NEEDS_MAPPING_VERIFICATION；
- **候选仅依赖待评估 Graph 边才能发现**：记录风险并从独立候选源重试；
- **多证据有替代集合**：记录 alternative_gold_sets；不能在检索评分时把所有其他正确证据错误算负例。

---

## 7. 输出目录和实施顺序

请先根据项目文件布局创建一个**新的版本化输出目录**，例如：

~~~text
DynamicEdgeGraph/datasets/nodefirst_qa_v2_20261117/
  source_inventory.json
  eligible_nodes.jsonl
  excluded_nodes.jsonl
  sampled_seeds.jsonl
  evidence_group_candidates.jsonl
  qa_drafts.jsonl
  qa_independent_reviews.jsonl
  qa_gold_verified.jsonl
  mapping_audit.jsonl
  failed_or_skipped.jsonl
  alternative_gold_sets.jsonl
  sampling_report.md
  repair_log.md
~~~

如果项目已有相同职责的目录/格式，应优先复用真实规范，不要生成不兼容的平行 schema。保留不可变原始输入、每次运行的 config/seed/model/prompt/version。

**分阶段执行：**

1. **Inventory-only dry-run**：先读实际 schema 和目录，输出文件/节点/页清单、异常与可用候选数，明确 real_019 暂停，不做大批生成；
2. **Pilot**：先按 20/30/50 做小批试验（例如 50 条目标：10 single、15 cross-page、25 cross-document），独立审核每条；
3. **Audit**：核对多证据必要性、OCR、mapping、模态与来源偏差，修复采样和生成逻辑；
4. **Scale**：只有在 pilot 符合标准后扩量，保持固定随机种子和可复现实验；
5. **Final export**：仅导出 FINAL_ACCEPT 且 mapping verified 的 QA；另保留 CONTENT_PASS_MAPPING_PENDING 和 REVISE 队列。

若历史脚本产生的数量与本规范给定的 18 篇/25 文档/49 页不一致，先打印实际差异报告，不能悄悄替换数据范围。**real_019 后续解析完成，也必须以新 corpus snapshot/version 单独纳入**，避免版本混淆。

---

## 8. 对检索论文评估的额外约束

本 Benchmark 的 20/30/50 是**人为设置的多证据压力测试分布**，并非声称代表真实用户查询分布。报告检索结果时应分别呈现 single / cross-page / cross-document 分数，尤其要做 macro-average、按 Evidence Set 大小/页距/文档数分组，并与一个更自然分布的小型 query 集合分别报告。

冻结 QA/Gold 与 Graph 构建之间的边界：任何利用 Gold QA 或 Gold Node ID 产生、调节或筛选的边，不得参与同批数据的公平评估。候选发现、生成、审核和最终 Retrieval 必须保存可追溯版本。

**最重要的原则**：成功指标不是生成了多少问答，而是抽样范围清楚、答案有证据、Node IDs 可验证、每个多证据关系真实且必要、评估不存在明显的自我偏置。
