# QA Gold Benchmark — Codex 逐条修复任务书

> **版本 / 使用范围**：2026-11-16 基于原始 `all_qa_drafts.jsonl` 与先前 AI 审核版 `all_qa_drafts_ai_reviewed.jsonl`；总计 **148** 条。
> **重要边界**：这是 QA 草稿与抽取证据的审计，不是已检查原 PDF、没有连接 HoreKa2 canonical node 数据库。任何 `BOUND_TO_EXISTING_LEGACY_NODE` 都不代表已经核验最终 canonical node ID；任何 `PENDING_EVIDENCE_NODE_ASSEMBLY` 都不能当成“映射正确”。
> **原则**：原始 reviewer_decision 是历史建议，修复后仍必须重新审核；不可把 REJECT 批量改 ACCEPT，更不可只改答案却保留错误的 Evidence Gold。

## 0. 给 Codex 的执行指令（可以直接复制到 Codex）

你正在修复一个多文档 Evidence Retrieval Benchmark 的 QA 草稿。请先在仓库内定位原始 QA JSONL 与生成脚本，确认字段/下游消费位置，再按本报告中每个 `draft_id` 精确匹配执行。不要仅按行号匹配，因为存在 `manual_qa_review_v1`、`legacy_qa_review_v1`、`auto_new_expansion`、`auto_legacy_expansion` 四种不同 ID 命名。

**必须按以下次序完成：**

1. **备份与可重放性**：保留原始 JSONL 和任何 gold 标注，不覆盖唯一副本；写新版本及逐条 diff；保留 `draft_id`、`document_id`、`evidence_unit_id`、原始 source paths。不要未经确认就创建或移动路径。
2. **修复来源、再改 QA**：先处理 `distorted_page`、截断、拼栏/OCR 噪声、目录/作者列表、图注或公式孤岛。PDF 只有在真实项目环境可访问时才核验；无法访问则记录 `SOURCE_NOT_VERIFIED` 并暂停此条进入 gold。
3. **判断三个彼此独立的维度**：`question_validity`（问题是否具体可独立理解）、`answer_correctness`（回答是否准确且覆盖问题）、`evidence_validity`（每条被选 evidence 是否足以支持问题与答案）。证据与答案都正确不代表 question 设计合格；证据主题相关不代表节点可做 Gold Evidence。
4. **修 10 条原始 REJECT**：`manual_qa_review_v1::{003,008,009,013,014,018,025,029,044,050}`。报告给出可核验的保守改写。除有真实原文支持的直接改动外，不允许凭常识填补事实。
5. **重新生成 90 条模板题**：全量 `legacy_qa_review` 23 条、`auto_new_expansion` 30 条、`auto_legacy_expansion` 37 条。清除 “selected passage / this document / what causal, technical, or comparative relationship...” 等无法检索的指示型模板。新问题必须明确实体、条件、比较维度和所需回答；金答案必须是从原文可严格核验的简短命题，不能原段落复制。
6. **来源不适合就剔除，不强行修出答案**：目录、课程安排、纯作者列表、无上下文 LaTeX、无法核验的图像或错序页应设 `EXCLUDE_OR_PARK`，不要按事实问答强行保留。
7. **映射与去重**：88 条 `PENDING_EVIDENCE_NODE_ASSEMBLY` 要在 parser/normalizer 之后找到目标 canonical node；60 条 `BOUND_TO_EXISTING_LEGACY_NODE` 要按 `source_node_file`、`source_atom_ids`、文本及 bbox 核验映射。任何重解析、拼接、拆分、替换证据都需重新生成并验证 node mapping；按下文重复组跨题检查检索集泄漏。
8. **状态管理**：仅在三维审核完成且 node mapping 核验后进入 gold；修复候选先置于 review-required 状态。不要把自动建议批注当成最终人工批准，也不要为迎合 reviewer_decision 而修改证据。

**推荐新增或单独维护的 QA 审核字段**（如果现有 schema 不允许新增，写到外部 QA audit manifest，不要破坏下游）：

```json
{"question_validity":"VALID|NEEDS_REWRITE|INVALID", "answer_correctness":"SUPPORTED|PARTIAL|UNSUPPORTED|UNVERIFIED", "evidence_validity":"FULL|PARTIAL|MISMATCH|UNVERIFIED", "node_mapping_verification":"VERIFIED|PENDING|FAILED", "source_text_verification":"VERIFIED|OCR_SUSPECT|TRUNCATED|NOT_CHECKED", "benchmark_action":"KEEP|EDIT|REGENERATE|EXCLUDE_OR_PARK", "review_state":"NEEDS_REVIEW|APPROVED|REJECTED", "review_explanation":"..."}
```

## 1. 审核盘点和优先级

- 总样本：**148**；此前综合建议 **48 ACCEPT / 100 REJECT**，它不是 canonical node 准确率。
- 单证据 **123**、多证据 **25**；多证据修复需检查是否真的需要所有引用节点，不能给多条无关证据凑数。
- 新采样 QA：`manual_qa_review_v1` **58** 条，其中 **10 REJECT**；`legacy_qa_review_v1` **23** 条；`auto_new_expansion` **30** 条；`auto_legacy_expansion` **37** 条。后三组合计 **90 REJECT**，主要是无明确检索意图的模板问题。
- 节点映射：**88 条 PENDING / 60 条 BOUND_TO_EXISTING_LEGACY_NODE**。前者不能声称已指向最终 canonical node；后者也尚未由本报告独立核对 node ID。
- 以下 `row_number` 是本文件里的阅读编号，并非数据库 primary key；程序更新必须使用 **完整的 draft_id**。

| 紧急度 | 条数 | 含义 |
| --- | ---: | --- |
| `P0_BLOCK_AND_SOURCE_REVIEW` | 26 | 不能直接生成 gold，先修源或剔除 |
| `P0_QA_FIX_REQUIRED` | 74 | 必须修 Q/A 或证据后重审 |
| `P1_SOURCE_VERIFY_BEFORE_RELEASE` | 10 | 目前答案核心可信，但来源文本异常需核对 |
| `P1_DEDUP_BEFORE_BENCHMARK` | 27 | 主要需去重和防数据泄漏 |
| `P1_EVIDENCE_ALIGNMENT` | 1 | 证据覆盖边界或问法有差距 |
| `P2_OPTIONAL_CLEANUP` | 10 | 无强制问题，可做精度/措辞改进 |

### 1.1 高度相近、建议成组去重的 QA

注意：以下只是文本/语义层面的重复候选，不是已做全量 embedding 近重复聚类，建议对 QA 问题+Gold Evidence 集合再做自动查重。

**#001 ↔ #027**, **#002 ↔ #028**, **#004 ↔ #030**, **#006 ↔ #031**, **#007 ↔ #033**, **#009 ↔ #035**, **#011 ↔ #037**, **#013 ↔ #039**, **#014 ↔ #040**, **#015 ↔ #041**, **#016 ↔ #042**, **#017 ↔ #043**, **#018 ↔ #044**, **#019 ↔ #045**, **#020 ↔ #046**, **#021 ↔ #047**, **#022 ↔ #048**, **#023 ↔ #049**, **#024 ↔ #050**, **#026 ↔ #052**.

优先倾向：#027 over #001、#028 over #002、#030 over #004、#031 over #006、#033 over #007、#035 over #009、#039 over #013、#040 over #014、#041 or #015、#042 or #016、#043 over #017、#045 over #019、#048 over #022、#049 over #023、#052 over #026。**最终以实验是否需要单证据/多证据分层为准**；两版本可以保留用于对照，但不得混入同一独立评测集合。

### 1.2 高风险原始 Evidence 位置

- **直接排除或转为元数据任务的目录/名单/日程**：#062, #065, #082, #085, #087, #108, #118, #140。
- **需要先重解析 `distorted_page` 的整页片段**：#089, #090, #091, #092, #093, #094, #095, #096, #097, #098, #099, #100, #101, #102, #103, #104, #108, #109。
- **图文复合节点**：#076, #112, #138；不能凭文本图注验证图中实际信息。
- **公式缺上下文**：#137。
- **抽取噪声/截断需要特殊注意的条目**：#002, #005, #006, #024, #025, #027, #028, #030, #031, #050, #055, #056, #083, #086, #113, #124, #137（非完整列表，其他条目仍需常规抽样核验）。

## 2. 字段级执行策略与自动化验收

**核心 schema**：各条均有 `draft_id`, `document_id`, `question`, `gold_answer_draft`, `gold_evidence_draft[]`, `question_type_actual`, `node_mapping_status`, `review_status`, `reviewer_decision`, `reviewer_notes`。`answer_status` 只存在于部分来源（manual/legacy）；`question_design` 也不是所有条目都有。请 Codex 根据原 schema 更新，勿假定所有字段都存在。

- Question：不可含 “selected passage” / “in <document_id>” / “according to this excerpt” 等前提（除非任务明确定义为文内定位而非开放语料检索）；必须是无需提前知道 evidence 也能理解的问题。
- Answer：至少包含问题要求的实体、比较两边或因果主因；不能只是长原文、未回应类型的属性描述；有数字时保留单位、限定条件和近似词。
- Evidence：核查每一子句与 source text 的逐项 entailment；引用不含主张时禁止靠常识补事实。`single_evidence` 仅可留一条独立足够 evidence；补第二条必须更新类型并重新验证。
- OCR/Parsing：如发生分栏、断句、超长整页、图表表头/正文混合，不允许把错误识别结果回写为事实；应定位真实 PDF 页，对 parser 的改动保留可复现日志。
- Node Mapping：若 `future_node_mapping` 为占位或旧 legacy 链接，只能用现有 evidence ID 作暂时锚点；最终要记录 canonical node ID、映射规则、page/bbox/text overlap、parse version，并检查不跨文档/不跨页误绑。
- Reject/Exclude：优先使用非破坏性的 `EXCLUDE_OR_PARK`，并保留审计样本可回溯；不要直接删除历史审计信息。

**最低完成验收**：

1. 148 个 `draft_id` 完整存在于变更日志，且没有重复 ID 或错位覆盖。
2. 每条修复均有 `before` / `after` 和变更原因；对 100 原 REJECT 没有无证据的批量 ACCEPT。
3. 每一条保留到最终 benchmark 的 QA 三维标注都是有效且 node mapping 为 VERIFIED；有原文定位信息。
4. 任何题目若通过增加/减少 evidence 改变证据数，`question_type_actual` 与实际 `gold_evidence_draft` 长度一致。
5. 高重复组不跨 train/val/test，并且同一 gold evidence 复用到不同 splits 时明确有防泄漏策略。
6. parser 输出的 `distorted_page`、目录、署名和公式孤岛没有被误当可靠事实 QA。

## 3. 148 条逐条修复说明

**阅读说明**：每条包含完整 `draft_id`、原 Q/A、当前候选证据的ID/页/类型、原审核批注、明确修改动作、字段级提议和验证门槛。`建议新 Q/A` 只是保守候选文本，若 PDF 核验不通过则不得直接采纳。对于第 59–148 条，无法从现有文本凭空确定“唯一正确 gold”，所以给出针对性的重写主题和必须完成的检验，而非制造 90 条貌似完整但未经验证的新答案。

### #001 · `manual_qa_review_v1::001`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`TIGHTEN_QUESTION_OR_ADD_EVIDENCE`。
- **文档与节点状态**：`real_001_batch_01_NASA-Spinoff-2023`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_evidence_draft`。
- **相似/重复题**：#027；需做去重或不同split隔离。

**原 Question：**
````text
Which long-running Kennedy research effort supplied the closed-loop, plant-based model later adapted for self-reliant food production?
````

**原 Gold Answer：**
````text
The Controlled Ecological Life Support System (CELS) program.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_001_batch_01_NASA-Spinoff-2023:p0007:e005` · 页 `7` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_001_batch_01_NASA-Spinoff-2023/pages/page_0007/output_json/page_0007.json`
   - bbox：`[298, 196, 732, 245]`

````text
NASA has worked for decades to develop a life-support system that functions as a self-replenishing ecology. At the heart of this work was the Controlled Ecological Life Support System (CELS) program, which ran for about 25 years, between the late 1970s and early 2000s, at NASA's Kennedy Space Center in Florida. It relied especially on plants, which recycle waste into food and oxygen.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据明确点名 CELS，并交代其在肯尼迪航天中心运行约25年、利用植物将废弃物转化为食物和氧气；因此核心答案准确。局限：该单段没有直接证明这些成果后来“被改造用于本地食物自给”，这一应用属于题干额外背景。建议将问题收窄为“哪个在肯尼迪持续约25年的闭环生命维持项目依靠植物循环废物”，或加入后续转化应用的段落作为第二条证据。 【建议标签】weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #001 行号。**目标操作**：`TIGHTEN_QUESTION_OR_ADD_EVIDENCE`。
2. 候选答案 CELS 正确；原题 later adapted for self-reliant food production 在本单证据内没有着落。若希望保留跨场景迁移的问法，优先参考 #027 的两个证据并设计成 multi_evidence；避免与 #027 重复计分。
3. **候选新 `question`**（需核验后应用）：
````text
Which long-running NASA Kennedy program used plants to recycle waste into food and oxygen in a closed-loop life-support system?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #002 · `manual_qa_review_v1::002`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`REPARSE_OCR_AND_TIGHTEN_QUESTION`。
- **文档与节点状态**：`real_001_batch_01_NASA-Spinoff-2023`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft`。
- **相似/重复题**：#028；需做去重或不同split隔离。

**原 Question：**
````text
What physical behavior makes a low-emission aviation energy carrier difficult to contain even before a vehicle can exploit its energy density?
````

**原 Gold Answer：**
````text
Because hydrogen has one of the lowest boiling points of any element and its gaseous form must be kept extremely cold or at remarkably high pressure.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_001_batch_01_NASA-Spinoff-2023:p0009:e007` · 页 `9` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_001_batch_01_NASA-Spinoff-2023/pages/page_0009/output_json/page_0009.json`
   - bbox：`[344, 252, 731, 312]`

````text
While NASA is testing it to carry liquid oxygen into space, a commercial airline is interested in the fact that the BHL could ultra-cold fuels without developing the micromicrols that they believe are so essential for certain propellant tanks. Hydrogen has one of the lowest boiling points of any element on Earth and its burning gas form must be kept extremely cold, or it needs to be kept under remarkably high pressure.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】段落直接支持氢的沸点极低，以及储存时必须采用极低温度或高压，因此答案抓住了储氢难点。需要注意：题干的“low-emission aviation”和“energy density”不是本条证据单独提供的事实；原始抽取中还出现“burning gas form”“BHL/micromicrols”等疑似OCR或版面拼接错误。建议先对照第9页PDF修复原文，改写题干为“氢的什么物理性质导致低温或高压储存需求”，并把低排放及能量密度的主张另配证据。 【建议标签】weak_evidence, other。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #002 行号。**目标操作**：`REPARSE_OCR_AND_TIGHTEN_QUESTION`。
2. 先对照 PDF p9 核实 BHL、micromicrols、burning gas form 等异常 OCR；原证据不支持 low-emission aviation、energy density 两个附加限定。提议答案表述为物理上相容的液态低温/气态高压，必须经原文核对才能采纳。与 #028 去重。
3. **候选新 `question`**（需核验后应用）：
````text
Why does hydrogen require either cryogenic or high-pressure storage?
````
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Hydrogen has an extremely low boiling point, so keeping it as a liquid requires very low temperatures, while gaseous hydrogen can be contained at high pressure.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #003 · `manual_qa_review_v1::003`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REWRITE_QUESTION_AND_ANSWER`。
- **文档与节点状态**：`real_002_batch_02_Spinoff.2022`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`。

**原 Question：**
````text
Which environmental variables must be jointly tuned, rather than optimized one at a time, for a controlled farm to tailor a crop recipe?
````

**原 Gold Answer：**
````text
It optimizes conditions such as water, nutrients, light, airflow, and temperature for particular plants and cultivars.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_002_batch_02_Spinoff.2022:p0018:e002` · 页 `18` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_002_batch_02_Spinoff.2022/pages/page_0018/output_json/page_0018.json`
   - bbox：`[49, 135, 267, 208]`

````text
Different plants require different balances of water, nutrients, light, airflow, and more. NASA studied and documented all this information for dozens of species, and now Green Sense Farm Holdings Inc. is using some of that individualized plant research to help growers on Earth.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】段落列举水分、养分、光照、气流以及“more”，支持按植物种类调整这些因素的配比；但候选答案加入“temperature”和“cultivars”，现有证据没有明确出现。问题也额外假定“不是逐项优化而是联合调参”，段落没有直接做这种对比。建议删除未证实的温度/品种层级及优化方式，答案限定为 water, nutrients, light and airflow，并把问题改成“哪些环境条件需要根据不同植物调整配比”。 【建议标签】unsupported_answer, ambiguous_question。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #003 行号。**目标操作**：`REWRITE_QUESTION_AND_ANSWER`。
2. 移除 temperature、cultivars、jointly tuned rather than one at a time：这些未在当前证据出现。
3. **候选新 `question`**（需核验后应用）：
````text
Which environmental factors does NASA plant research say must be balanced differently for different plant species?
````
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Water, nutrients, light, and airflow.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #004 · `manual_qa_review_v1::004`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`TIGHTEN_QUESTION_OR_ADD_EVIDENCE`。
- **文档与节点状态**：`real_002_batch_02_Spinoff.2022`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_evidence_draft`。
- **相似/重复题**：#030；需做去重或不同split隔离。

**原 Question：**
````text
What timing reference lets a navigation network avoid an irreversible trajectory error during a one-shot deep-space encounter?
````

**原 Gold Answer：**
````text
Atomic clocks.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_002_batch_02_Spinoff.2022:p0031:e007` · 页 `31` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_002_batch_02_Spinoff.2022/pages/page_0031/output_json/page_0031.json`
   - bbox：`[270, 407, 487, 493]`

````text
NASA Deep Space Network (DSN), a sort of GPS system for space, relies on atomic clocks for extreme accuracy. Any modern navigation system must accurately time radio signals to triangulate a measurement, but the time for accuracy is even higher in space, where great distances can compound even tiny errors.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据明确指出深空网络（DSN）依赖原子钟获得极高精度，准确计时无线电信号以支持导航定位，核心答案“Atomic clocks”可直接定位。局限：“one-shot encounter”和“irreversible trajectory error”不在此单段内，属于问题为提高难度而加上的场景假设。建议直接问深空网络使用什么计时装置保障远距离导航精度，或补上木星飞掠的一次性机会证据。 【建议标签】weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #004 行号。**目标操作**：`TIGHTEN_QUESTION_OR_ADD_EVIDENCE`。
2. Atomic clocks 被直接支持；one-shot encounter、irreversible trajectory error 需引用飞掠背景节点（如 #030）才能保留。
3. **候选新 `question`**（需核验后应用）：
````text
What timing reference does NASA’s Deep Space Network rely on to time radio signals accurately for navigation?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #005 · `manual_qa_review_v1::005`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`TIGHTEN_QUESTION_AND_VERIFY_OCR`。
- **文档与节点状态**：`real_003_batch_03_NASA_Spinoff_2021`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_evidence_draft`。

**原 Question：**
````text
What class of persistent industrial contaminant motivated the field-center cleanup demonstration?
````

**原 Gold Answer：**
````text
Polychlorinated biphenyls, or PCBs.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_003_batch_03_NASA_Spinoff_2021:p0022:e007` · 页 `22` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_003_batch_03_NASA_Spinoff_2021/pages/page_0022/output_json/page_0022.json`
   - bbox：`[279, 254, 494, 364]`

````text
The contaminants she was working against were polychlorinated biphenyls, more commonly referred to as PCBs. When the molecules were first developed and manufactured into multiple formulas, they were added to paint because the formulae used to make these 100% pure temperature extremes. That meant paint wouldn't crack, peel, or catch fire, all important qualities for buildings located near rocket launches.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】片段直接将污染物命名为 polychlorinated biphenyls（PCBs），因此目标实体完全匹配。段落的油漆配方描述存在明显OCR异常（如“100% pure temperature extremes”），但不影响PCB实体辨识。题干中的“field-center cleanup demonstration”不是在这一段完整交代，若要严格验证这一背景，需补充清理项目所在段落。 【建议标签】other。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #005 行号。**目标操作**：`TIGHTEN_QUESTION_AND_VERIFY_OCR`。
2. 答案 PCBs 可保留，但 field-center cleanup demonstration 非本段完整陈述；p22 下半段油漆性质 OCR 明显串扰，先回查 PDF。
3. **候选新 `question`**（需核验后应用）：
````text
Which industrial contaminants are identified in the NASA cleanup account?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #006 · `manual_qa_review_v1::006`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`ADD_HISTORICAL_EVIDENCE_OR_TIGHTEN_QUESTION`。
- **文档与节点状态**：`real_003_batch_03_NASA_Spinoff_2021`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_evidence_draft`。
- **相似/重复题**：#031；需做去重或不同split隔离。

**原 Question：**
````text
Which food sector became the first regulatory test case for the preventive safety system developed for spaceflight?
````

**原 Gold Answer：**
````text
Low-acid canned food manufacturers.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_003_batch_03_NASA_Spinoff_2021:p0034:e002` · 页 `34` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_003_batch_03_NASA_Spinoff_2021/pages/page_0034/output_json/page_0034.json`
   - bbox：`[48, 196, 265, 331]`

````text
In 1973, low-acid canned food manufacturers became the first to be subject to HACCP regulations, and they were the only ones for a long time. Then in 1993, an outbreak of food poisoning due to a Shiga tono-producing strain of E. coli bacteria caused the meat and poultry industries to close down. This was a time of economic confidence. Within a decade, the U.S. Department of Agriculture (USDA) had HACCP regulations in place for meat and poultry, and the FDA required the system for all seafood and juice producers. By
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】1973年低酸罐装食品制造商成为最早受到HACCP法规约束的行业，证据与答案逐字对应。证据后半部分涉及1993年事件与后续监管，存在“industries to close down”等明显拼接/识别疑点，建议回查PDF。题干中“HACCP源自航天食品安全”的来历未由此段单独证实，若评估完整因果链可配第二段。 【建议标签】other。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #006 行号。**目标操作**：`ADD_HISTORICAL_EVIDENCE_OR_TIGHTEN_QUESTION`。
2. 现有段落支持 low-acid canned food manufacturers；spaceflight 起源需额外证据，可与 #031 作交叉参照。p34 后半段疑似识别/拼接错误。
3. **候选新 `question`**（需核验后应用）：
````text
Which food-production sector first became subject to HACCP regulations in 1973?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #007 · `manual_qa_review_v1::007`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`TIGHTEN_QUESTION_OR_ADD_TELEMETRY_EVIDENCE`。
- **文档与节点状态**：`real_004_batch_04_Spinoff2020`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_evidence_draft`。
- **相似/重复题**：#033；需做去重或不同split隔离。

**原 Question：**
````text
Which set of body signals had to be integrated into one operational telemetry workflow to assess a crew member during flight?
````

**原 Gold Answer：**
````text
Temperature, ECG heart data, breath cycles, and blood pressure.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_004_batch_04_Spinoff2020:p0028:e001` · 页 `28` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_004_batch_04_Spinoff2020/pages/page_0028/output_json/page_0028.json`
   - bbox：`[93, 148, 549, 294]`

````text
In the end, the astronauts wore a belt carrying four differ- ent signal conditioners that each captured data from sensors and electrodes attached across the body: an oral probe for temperature, electrodes for ECG (electrocardiogram) heart data and breath cycles, and an inflatable cuff with a sound transducer over an artery for blood pressure.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据逐项给出口腔探针测体温、ECG电极测心脏信号与呼吸周期、袖带与动脉声音传感器测血压；候选答案四类信号齐全。问题中的“integrated into one operational telemetry workflow”超出了这一传感器描述段的范围，需补后续信号接入机载遥测的证据。若坚持single_evidence，宜仅问采集了哪些生理指标。 【建议标签】weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #007 行号。**目标操作**：`TIGHTEN_QUESTION_OR_ADD_TELEMETRY_EVIDENCE`。
2. 原段只有采集端，不覆盖完整 telemetry workflow；如要保留后者，可加入 #033 的机载遥测段。
3. **候选新 `question`**（需核验后应用）：
````text
Which physiological signals did astronauts’ belt-mounted sensors measure?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #008 · `manual_qa_review_v1::008`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REWRITE_QUESTION_AND_ANSWER_OR_ADD_EVIDENCE`。
- **文档与节点状态**：`real_004_batch_04_Spinoff2020`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`。

**原 Question：**
````text
What architectural feature allowed the optical sensing system to improve speed as the number of monitored channels increased?
````

**原 Gold Answer：**
````text
It monitored changes in the ratios of multiple spectral components simultaneously, allowing many sensors to be monitored at once.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_004_batch_04_Spinoff2020:p0035:e003` · 页 `35` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_004_batch_04_Spinoff2020/pages/page_0035/output_json/page_0035.json`
   - bbox：`[93, 643, 549, 744]`

````text
The ability to monitor multiple sensors simultaneously allows for much faster readings, which is important for detecting, for example, the tiny, rapid vibrations caused by friction with a textured surface.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】给出的证据只解释“并行监控多个传感器可更快获得读数”，完全没有提及光谱成分的比例、比率变化或相应架构。候选答案中的“ratios of multiple spectral components”因而是无依据的额外机制。建议先移除光谱比率机制，将问题和答案改成并行监控多个传感器带来的速度收益；若要保留原问法，应补精确描述光谱比率的另一节点。 【建议标签】unsupported_answer, weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #008 行号。**目标操作**：`REWRITE_QUESTION_AND_ANSWER_OR_ADD_EVIDENCE`。
2. 当前唯一节点未说 spectral-component ratios；如果保留该物理架构必须在原文中找到新的、确切支持的 evidence。
3. **候选新 `question`**（需核验后应用）：
````text
Why does simultaneous monitoring of multiple sensors make optical sensing faster?
````
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Monitoring multiple sensors simultaneously allows faster readings, including of rapid vibrations from contact with a textured surface.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #009 · `manual_qa_review_v1::009`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`FIX_ANSWER_KEEP_TWO_EVIDENCES`。
- **文档与节点状态**：`real_005_batch_05_Spinoff2019`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。
- **相似/重复题**：#035；需做去重或不同split隔离。

**原 Question：**
````text
What miniaturization tradeoff separates the most accurate laboratory timekeepers from versions that can fly on a spacecraft?
````

**原 Gold Answer：**
````text
They can fill an entire laboratory, making them too large for a satellite.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_005_batch_05_Spinoff2019:p0052:e003` · 页 `52` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_005_batch_05_Spinoff2019/pages/page_0052/output_json/page_0052.json`
   - bbox：`[93, 328, 550, 477]`

````text
The best clocks are atomic clocks, and the best atomic clocks currently made “won’t lose a second in the entire life of the observable universe,” says Gregory Heckler, the deputy telecommunications systems manager for NASA’s Tracking and Data Relay Satellites (TDRS) at Goddard Space Flight Center.
````

2. `real_005_batch_05_Spinoff2019:p0052:e004` · 页 `52` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_005_batch_05_Spinoff2019/pages/page_0052/output_json/page_0052.json`
   - bbox：`[93, 476, 550, 626]`

````text
Unfortunately, those clocks tend to be enormous — filling up an entire laboratory — and so impractical, to say the least, for a satellite. To make a clock small enough to fit on a satellite, scientists are currently able to achieve pretty decent accuracy, good to maybe a second of drift in 30,000 years, but there's still plenty of room to improve.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】两条证据足以完整回答精度—体积折中：实验室顶级原子钟体积极大，卫星级设备虽可缩小，却退化到约3万年漂移1秒。现有候选答案只写“占据整间实验室”，完全漏掉小型化后的精度水平，而题目明确问tradeoff。建议把这两组对比信息都写入gold answer；当前应拒绝不完整答案，而不是补一个无关背景。 【建议标签】unsupported_answer。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #009 行号。**目标操作**：`FIX_ANSWER_KEEP_TWO_EVIDENCES`。
2. 两个节点已足够回答；补上小型卫星钟精度数字。若与 #035 同属评测集则优先留 #035，避免同源同事实重复。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
The most accurate laboratory atomic clocks are too large for spacecraft (they can occupy an entire laboratory); clocks made small enough for satellites trade some precision for size, with roughly one second of drift over 30,000 years according to the article.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #010 · `manual_qa_review_v1::010`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`OPTIONAL_QUESTION_PRECISION`。
- **文档与节点状态**：`real_005_batch_05_Spinoff2019`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。

**原 Question：**
````text
Which elemental signatures were prioritized as biological clues, and what ordering did the investigator give them?
````

**原 Gold Answer：**
````text
Carbon, sulfur, and nitrogen, in that order.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_005_batch_05_Spinoff2019:p0077:e003` · 页 `77` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_005_batch_05_Spinoff2019/pages/page_0077/output_json/page_0077.json`
   - bbox：`[93, 279, 550, 478]`

````text
The Ames Research Center planetary scientist says his favorite isotopes are those of carbon, sulfur, and nitrogen, in that order, “ because biology does interesting things with them and leaves an isotopic signature. ” For example, he says, the ratio of different isotopes in a carbon sample can reveal whether it's a product of biology. And his favorite compound is water, which carries isotopic evidence of its many phase changes between gas, liquid, and solid.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】片段明确将生物同位素线索按 carbon → sulfur → nitrogen 排序，并说明生物过程会留下同位素特征。候选答案准确且简洁。若要提高检索价值，题目可明确“哪位行星科学家偏好的三种同位素元素及次序”；当前问法的“elemental signatures”稍显抽象，但不影响唯一答案。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #010 行号。**目标操作**：`OPTIONAL_QUESTION_PRECISION`。
2. Carbon, sulfur, nitrogen 顺序直接支持，无必改项；不要把 isotope signatures 含混解释成一般元素丰度。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #011 · `manual_qa_review_v1::011`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`OPTIONAL_ANSWER_NORMALIZATION`。
- **文档与节点状态**：`real_006_batch_06_Spinoff2018`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。
- **相似/重复题**：#037；需做去重或不同split隔离。

**原 Question：**
````text
What nondeterminism had to be eliminated before a common data network could carry mission-critical control traffic?
````

**原 Gold Answer：**
````text
It could not guarantee message delivery or transmission time, so messages could interrupt one another, be lost, or be damaged.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_006_batch_06_Spinoff2018:p0051:e003` · 页 `51` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_006_batch_06_Spinoff2018/pages/page_0051/output_json/page_0051.json`
   - bbox：`[93, 353, 550, 527]`

````text
Until recently, though, Ethernet could never be used for critical systems like the spacecraft avionics responsible for navigation, communication, and other essential functions, because it's imprecise. There's no guarantee how long it will take to transmit a message or even whether it will arrive at its intended destination. Messages can interrupt each other or be lost or damaged.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据明确说明传统以太网无法保证消息到达时间或是否到达，消息还会互相打断、丢失或损坏；候选答案与这些约束吻合。题干聚焦“哪种非确定性”而答案混入错误后果，尚可接受；建议在标准答案中概括为 non-deterministic latency and delivery，并把丢包/损坏作为例子，以便评测答案一致性。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #011 行号。**目标操作**：`OPTIONAL_ANSWER_NORMALIZATION`。
2. 区分不确定的传输时延/到达性与后果，不要推导为绝对零丢包保证。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Traditional Ethernet could not guarantee either message-delivery latency or successful delivery; interference, loss, or corruption could occur.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #012 · `manual_qa_review_v1::012`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`KEEP_WITH_CLAIM_SCOPE`。
- **文档与节点状态**：`real_006_batch_06_Spinoff2018`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。

**原 Question：**
````text
Which reactive chemical species explain why the air-cleaning method can act throughout a space rather than only at a device surface?
````

**原 Gold Answer：**
````text
Hydroxyls, hydrogen peroxide, and superoxides.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_006_batch_06_Spinoff2018:p0080:e002` · 页 `80` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_006_batch_06_Spinoff2018/pages/page_0080/output_json/page_0080.json`
   - bbox：`[94, 224, 550, 423]`

````text
The oxidizers ActivePure deploys include hydroxyls, hydrogen peroxide, and superoxides, all charged particles that clean air and surfaces but pose no threat to humans or pets. They naturally distribute themselves throughout the air, so the only question is the quantity needed to clean a given space, Urso says, noting that this is why the company offers the technology in different scales and also develops custom solutions for areas of any size.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】文本明确列出 hydroxyls、hydrogen peroxide 和 superoxides，并指出氧化剂在空气中自然分散，因而可覆盖空气和表面。三个实体准确。需要注意“对人宠无害”只是原文企业声称，不属于本题要验证的内容；不应在gold answer中扩展为安全性结论。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #012 行号。**目标操作**：`KEEP_WITH_CLAIM_SCOPE`。
2. 三个氧化性物种得到直接支持。文本所称对人/宠物无害是商家引述，不要把其安全性扩展入 gold answer。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #013 · `manual_qa_review_v1::013`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`FIX_ANSWER_KEEP_EVIDENCE`。
- **文档与节点状态**：`real_007_batch_07_Spinoff2017`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。
- **相似/重复题**：#039；需做去重或不同split隔离。

**原 Question：**
````text
What size-versus-durability compromise made the early rechargeable chemistry attractive for flight applications despite its shorter service life?
````

**原 Gold Answer：**
````text
They were reliable for only about 400–500 shallow discharge cycles, compared with about 10,000 cycles for nickel-cadmium batteries.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_007_batch_07_Spinoff2017:p0098:e000` · 页 `98` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_007_batch_07_Spinoff2017/pages/page_0098/output_json/page_0098.json`
   - bbox：`[93, 75, 550, 294]`

````text
By 1972 Lewis had tested and proven silver-zinc cells based on a specific inorganic separator and a specially prepared zinc electrode, which were able to function as a rechargeable battery after heat sterilization. The cells were still only reliable up to 400 to 500 shallow discharge cycles, as opposed to the 10,000-cycle life of the nickel-cadmium batteries commonly used in space applications of the time, but they could result in batteries one-third the size of nickel- cadmium units, a substantial saving in weight.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】题目要求描述银锌电池的“体积—寿命”折中；证据同时给出浅放电循环400–500次 vs 镍镉10000次，和体积约为镍镉的三分之一、节省重量两面。现有答案只提寿命劣势，遗漏使其适合航天的关键体积优势。建议补成完整双边比较后再收录。 【建议标签】unsupported_answer。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #013 行号。**目标操作**：`FIX_ANSWER_KEEP_EVIDENCE`。
2. 现有答案只回答寿命劣势，遗漏尺寸优势，无法回答 tradeoff。注意与 #039 同证据；选择更优题保留，避免重复。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Silver–zinc cells offered a substantial size and weight advantage—batteries could be about one-third the size of comparable nickel–cadmium batteries—but lasted only about 400–500 shallow discharge cycles versus roughly 10,000 for nickel–cadmium.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #014 · `manual_qa_review_v1::014`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REWRITE_QUESTION_OR_ADD_DIAGNOSTIC_DESIGN_EVIDENCE`。
- **文档与节点状态**：`real_007_batch_07_Spinoff2017`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_evidence_draft`。
- **相似/重复题**：#040；需做去重或不同split隔离。

**原 Question：**
````text
Why does distance from terrestrial medical support change the design requirements for diagnostic instruments on exploration missions?
````

**原 Gold Answer：**
````text
Space travel can suppress immunity and make some bacteria more virulent, while a Mars mission would be months from an emergency return or a nearby doctor.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_007_batch_07_Spinoff2017:p0041:e002` · 页 `41` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_007_batch_07_Spinoff2017/pages/page_0041/output_json/page_0041.json`
   - bbox：`[93, 201, 551, 452]`

````text
NASA astronauts are screened for sound health, among a slew of other requirements, but no one is invulnerable, especially in space. For reasons not fully understood, space travel appears to suppress the human immune system, while some bacteria become heartier and more virulent in microgravity. Meanwhile, aboard the International Space Station, the nearest medi- cal doctor is on the other side of atmospheric reentry. On a future mission to Mars, any emergency return would likely take months.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】证据支持太空环境下免疫抑制、部分细菌更有毒、在火星任务中数月无法紧急返回等需求背景，但没有具体描述“诊断仪器必须如何设计”，更没有候选答案中的尺寸/速度约束。题目是设计要求，答案却停留在风险与距离动机，问答焦点不匹配。建议改问“为何探测任务更需要自主医学检测”，或与具体小型快速诊断技术段落组成multi_evidence。 【建议标签】unsupported_answer, weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #014 行号。**目标操作**：`REWRITE_QUESTION_OR_ADD_DIAGNOSTIC_DESIGN_EVIDENCE`。
2. 现有答案解释远距离医疗风险和免疫变化，但不是仪器的 size/speed 设计需求；若保留原题，补 #040 的仪器限制证据并写到具体设计要求。
3. **候选新 `question`**（需核验后应用）：
````text
Why do astronauts on long-duration exploration missions need medical diagnostic capability without immediate support from Earth?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #015 · `manual_qa_review_v1::015`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`KEEP_BUT_SCOPE_STORAGE_CLAIM`。
- **文档与节点状态**：`real_008_batch_08_Spinoff2016`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#041；需做去重或不同split隔离。

**原 Question：**
````text
Why is a pressurized chemical energy store attractive when a remote renewable-power site may sit idle for long periods?
````

**原 Gold Answer：**
````text
Pressurized hydrogen can be stored virtually indefinitely without losses, whereas unused alkaline batteries lose energy over time.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_008_batch_08_Spinoff2016:p0126:e003` · 页 `126` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_008_batch_08_Spinoff2016/pages/page_0126/output_json/page_0126.json`
   - bbox：`[93, 684, 550, 975]`

````text
It's the first electrolyzer to be competitive with bat- teries and even provides some advantages. For example, unused alkaline batteries lose energy over time, whereas a cylinder of pressurized hydrogen gas will keep virtually indefinitely without losses. Batteries also lose energy to heat if power is drawn from them rapidly, which is not the case with hydrogen fuel cells. At telecommunication towers in remote parts of Africa or India, which are often powered by solar energy, batteries have performance issues due to the heat. “ Our panels love heat, ” Guerra says. “ The hotter the electrolyte, the more efficient they get. ”
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据明确对比闲置碱性电池自放电与加压氢气筒“virtually indefinitely without losses”，直接解释远程站点长期储能优势。需避免将这句话泛化为任何条件下无储存损耗：它针对封闭高压氢筒、对比的是文中指定电池。建议gold answer保留“文中所述加压氢气/闲置碱性电池”限定。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #015 行号。**目标操作**：`KEEP_BUT_SCOPE_STORAGE_CLAIM`。
2. 不要概括为所有氢能链路“永不损耗”；限定为文中封闭压力容器储存、与闲置碱性电池的比较。#041 主题高度相似。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #016 · `manual_qa_review_v1::016`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`DEDUPLICATE_OR_KEEP`。
- **文档与节点状态**：`real_008_batch_08_Spinoff2016`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#042；需做去重或不同split隔离。

**原 Question：**
````text
Which pair of physical risks requires a cryogenic propellant system to control both temperature and microscopic leakage?
````

**原 Gold Answer：**
````text
Liquid hydrogen must be kept below −423 °F; leaks are a priority because hydrogen escapes through tiny cracks and is highly flammable.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_008_batch_08_Spinoff2016:p0073:e003` · 页 `73` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_008_batch_08_Spinoff2016/pages/page_0073/output_json/page_0073.json`
   - bbox：`[92, 353, 552, 674]`

````text
But harnessing that energy requires a great deal of technological know-how on the Agency's part. For one, keeping hydrogen in its liquid state means maintaining it at a temperature below -423 °F. The element must also be insulated from external heat sources during launch, lest it begin to evaporate. Then there's the persistent threat of leakage. As the smallest and lightest of atoms, hydrogen escapes through the tiniest of cracks. That makes it a hazard, as the element is highly flammable, to the point where high-pressure joint leaks can cause combustion. As a result, detecting leaks is a top priority, but it's also a challenge, because the gas — and the flame it emits — are odorless and colorless.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】同一段清楚说明液氢必须低于 −423 °F，并指出小尺度裂缝泄漏、易燃、无色无味等检测风险，答案与问题的两个方面一致。可以在标准答案中明确保温隔热防止蒸发和检测无色无味氢气，以使双风险链条更完整。题材与#042高度重叠，建议后续检查重复问题。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #016 行号。**目标操作**：`DEDUPLICATE_OR_KEEP`。
2. 温度和微裂缝泄漏双风险都得到支持，补充无色无味难检测可选。与 #042 同主题、同 evidence，优先保留更可评分的版本。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #017 · `manual_qa_review_v1::017`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`DEDUPLICATE_OR_KEEP`。
- **文档与节点状态**：`real_009_batch_09_Spinoff2015`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#043；需做去重或不同split隔离。

**原 Question：**
````text
What additional biological parameter turns a regional atmospheric water-loss estimate into a decision useful for a particular crop field?
````

**原 Gold Answer：**
````text
A crop coefficient specific to the crop and its growth stage is multiplied by ETo to produce a more refined measurement.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_009_batch_09_Spinoff2015:p0111:e001` · 页 `111` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_009_batch_09_Spinoff2015/pages/page_0111/output_json/page_0111.json`
   - bbox：`[93, 214, 550, 532]`

````text
As helpful as ETo data is, farmers and irrigators must still perform additional calculations to convert the ETo information into a number specific to their fields and crops. For example, the utility of ETo information is increased when paired with another piece of data called the crop coefficient. Specific to the crop type and its stage of growth, the number, when multiplied by ETo, results in a more refined measurement of evapotranspiration specific to a particular crop and field. As it turns out, in recent years NASA and the US Department of Agriculture (USDA) together were discovering that Landsat and MODIS data could be used to map vegetation conditions and, from that, derive crop coefficients.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据完整定义 crop coefficient：按作物类型与生长阶段选择，将其乘以参考蒸散量ETo得到田块与作物特定估计。候选答案精确。若要设计稍难问题，可加入 Landsat/MODIS 如何间接求取系数的后半段；当前题目是清晰的单段定位题，与#043语义重合较大。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #017 行号。**目标操作**：`DEDUPLICATE_OR_KEEP`。
2. 作物系数 × ETo 有明确支持。与 #043 同段重复，建议 #043 多一些遥感系数来源；根据评测目标选一个。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #018 · `manual_qa_review_v1::018`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`FIX_ANSWER_KEEP_TWO_EVIDENCES`。
- **文档与节点状态**：`real_009_batch_09_Spinoff2015`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。
- **相似/重复题**：#044；需做去重或不同split隔离。

**原 Question：**
````text
Why must an underground-water inference workflow remove surface clutter before it combines radar observations with other Earth data?
````

**原 Gold Answer：**
````text
It processes NASA SAR and SIR data with geophysical and geological inputs, then adds NASA Landsat data as a critical input.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_009_batch_09_Spinoff2015:p0060:e004` · 页 `60` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_009_batch_09_Spinoff2015/pages/page_0060/output_json/page_0060.json`
   - bbox：`[93, 369, 550, 563]`

````text
a proprietary process Gachet developed that removes surface obstacles from NASA SAR data and SIR data without harming the soil wetness signal. In other words, the WATEX processes NASA SAR imagery so that information about groundwater can be inferred without the interference of surface features such as infrastructure, rocks, or vegetation. This process is combined with several other inputs, such as geophysical and geological data.
````

2. `real_009_batch_09_Spinoff2015:p0060:e005` · 页 `60` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_009_batch_09_Spinoff2015/pages/page_0060/output_json/page_0060.json`
   - bbox：`[94, 562, 550, 926]`

````text
Then there's NASA Landsat satellite data, which is added as a critical input to the WATEX System. Started in 1972, the Landsat program, administered by both NASA and the US Geological Survey, is the longest continuous satellite-based record of the Earth's surface through not only visual imagery but also the near- infrared, short-wave, and thermal infrared bands of the electromagnetic spectrum. By analyzing the time-lapsed imagery, scientists are able to monitor numerous environ- mental conditions, from deforestation to agricultural land use and rates of erosion. For WATEX, Gachet utilized Landsat data to note the chemical signatures of rocks and also discern surface landscapes, which give clues to where water might accumulate by looking at slopes, flood plains and ditches.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】两条证据说明WATEX先清除SAR/SIR地表障碍并保留土壤湿度信息，再融合地球物理、地质与Landsat数据。现有答案只罗列输入数据，没解释“为什么必须去除地表杂波”：基础设施、岩石、植被等地表特征会干扰地下水推断。建议在答案补这一因果动机及去除时必须保留soil-wetness signal的约束。 【建议标签】unsupported_answer。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #018 行号。**目标操作**：`FIX_ANSWER_KEEP_TWO_EVIDENCES`。
2. 原答案只列出数据来源，遗漏“为何去除地表杂波”和“不能损伤湿度信号”；两条证据支持补写。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Surface features such as infrastructure, rocks, and vegetation can obscure radar-based groundwater inference. WATEX first removes those surface obstacles from SAR/SIR observations while preserving the soil-wetness signal, then combines that signal with geophysical, geological, and Landsat inputs.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #019 · `manual_qa_review_v1::019`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`TIGHTEN_QUESTION_OR_ADD_SCALE_EVIDENCE`。
- **文档与节点状态**：`real_010_batch_10_Spinoff2013`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_evidence_draft`。
- **相似/重复题**：#045；需做去重或不同split隔离。

**原 Question：**
````text
What institutional resource helped a commercial heat-shield program cope with a scaling problem that an earlier capsule did not face?
````

**原 Gold Answer：**
````text
It could consult NASA engineers with roughly 40–50 years of heat-shield knowledge and experience.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_010_batch_10_Spinoff2013:p0065:e001` · 页 `65` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_010_batch_10_Spinoff2013/pages/page_0065/output_json/page_0065.json`
   - bbox：`[93, 459, 550, 728]`

````text
Having seen the Stardust capsule's successful reentry, the company was very interested in the choice of PICA as a material for their heat shield. Fortunately, under the provisions of the contract, in addition to financial funding SpaceX also had access to NASA's brain trust of engineers for technical consultation, which the firm made full use of. “The group of people we worked with had basically designed every American heat shield since the Apollo days,” says Andrew Chambers, the company's project lead in this arena. “We were able to tap 40–50 years of knowl- edge and experience, which was absolutely invaluable.”
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】段落说明SpaceX依据合作合同取得NASA工程师咨询，并直接指出经验积累约40–50年，候选答案抓准“制度性资源”。局限：题干暗示“早期舱体没有遇到的尺寸扩展问题”，该证据没有说明Stardust与Dragon尺寸差别，需要下一节点来论证。建议改成单纯问NASA提供什么工程支持，或标为multi_evidence并附尺寸对比段。 【建议标签】weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #019 行号。**目标操作**：`TIGHTEN_QUESTION_OR_ADD_SCALE_EVIDENCE`。
2. NASA 40–50年热防护工程知识可直接回答；题干 Stardust–Dragon 尺寸升级尚需 #045 另一段。
3. **候选新 `question`**（需核验后应用）：
````text
What engineering expertise could SpaceX access from NASA while developing its heat-shield technology?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #020 · `manual_qa_review_v1::020`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`TIGHTEN_QUESTION`。
- **文档与节点状态**：`real_010_batch_10_Spinoff2013`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`。
- **相似/重复题**：#046；需做去重或不同split隔离。

**原 Question：**
````text
Why did an astronaut-assistance robot need human-compatible manipulation rather than only autonomous mobility?
````

**原 Gold Answer：**
````text
It needed to perform the same tasks as humans and use the same tools astronauts use to service spaceflight hardware.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_010_batch_10_Spinoff2013:p0075:e002` · 页 `75` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_010_batch_10_Spinoff2013/pages/page_0075/output_json/page_0075.json`
   - bbox：`[93, 204, 550, 378]`

````text
R obonaut 2 flew aboard Space Shuttle Discovery to the International Space Station (ISS) in early 2011, but its development has been many years in the making. In 1997, Johnson Space Center engineers embarked on a mission to build a robot that could perform the same tasks as humans so it could assist astronauts in space.
````

2. `real_010_batch_10_Spinoff2013:p0075:e003` · 页 `75` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_010_batch_10_Spinoff2013/pages/page_0075/output_json/page_0075.json`
   - bbox：`[94, 378, 550, 576]`

````text
In collaboration with the Defense Advanced Research Projects Agency (DARPA), Johnson aimed to build Robonaut 1—a humanoid robot complete with dexterous manipulation, or a capability to use its hands—to work alongside its human counterparts. In order to lend a help- ing hand, Robonaut needed to be able to use the same tools as astronauts to service space flight hardware, which was designed for human servicing.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一段交代Robonaut面向与宇航员相同的任务，第二段解释需要能用人的工具操作供人维护的航天硬件。两段联合构成充分的任务需求→灵巧操作因果链。答案准确；但“rather than only autonomous mobility”是题目人为加入的对照，原文没有直接讨论纯移动方案，建议改为“为什么灵巧手操作是Robonaut的设计目标”。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #020 行号。**目标操作**：`TIGHTEN_QUESTION`。
2. 原证据未把灵巧操作与“只会自主移动”方案作严格对照。与 #046 同主题，跨单证据/多证据避免泄漏。
3. **候选新 `question`**（需核验后应用）：
````text
Why was dexterous, human-compatible manipulation essential to Robonaut’s mission?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #021 · `manual_qa_review_v1::021`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`OPTIONAL_ANSWER_COMPLETENESS`。
- **文档与节点状态**：`real_011_batch_11_Spinoff2012`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#047；需做去重或不同split隔离。

**原 Question：**
````text
What combination of motion, sampling limitations, and cost makes conventional aerodynamic sensing poorly suited to spinning rotor blades?
````

**原 Gold Answer：**
````text
They provide measurements only at discrete locations and standard static instrumentation cannot handle a moving rotor; dynamic taps greatly increase cost.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_011_batch_11_Spinoff2012:p0056:e003` · 页 `56` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_011_batch_11_Spinoff2012/pages/page_0056/output_json/page_0056.json`
   - bbox：`[93, 354, 550, 577]`

````text
All of this makes acquiring a true understanding of rotorcraft aerodynamics a difficult task. A traditional means of acquiring aerodynamic data is to conduct wind tunnel tests using a vehicle model outfitted with pressure taps and other sensors. These sensors add significant costs to wind tunnel testing while only providing measurements at discrete locations on the model's surface. In addition, standard sensor solutions do not work for pulling data from a rotor in motion.
````

2. `real_011_batch_11_Spinoff2012:p0056:e004` · 页 `56` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_011_batch_11_Spinoff2012/pages/page_0056/output_json/page_0056.json`
   - bbox：`[93, 577, 550, 800]`

````text
“Typical static pressure instrumentation can’t handle that,” explains Neal Watkins, electronics engineer in Langley Research Center’s Advanced Sensing and Optical Measurement Branch. “There are dynamic pressure taps, but your costs go up by a factor of five to ten if you use those. In addition, recovery of the pressure tap readings is accomplished through slip rings, which allow only a limited amount of sensors and can require significant maintenance throughout a typical rotor test.”
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一段指出传统压力孔测量点离散、移动旋翼上常规方案不能工作；第二段说明动态压力孔成本增加5–10倍，滑环限制传感器数量并增加维护。候选答案涵盖运动、采样和成本三点。为提高完整性，建议标准答案加入滑环通道数量/维护约束，且避免把5–10倍描述成所有动态传感器的普遍成本。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #021 行号。**目标操作**：`OPTIONAL_ANSWER_COMPLETENESS`。
2. 已有移动、离散采样和成本三因子；可补滑环通道数和维护成本，但不可将 5–10× 外推至全部动态传感器。与 #047 重复。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #022 · `manual_qa_review_v1::022`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`DEDUPLICATE_OR_KEEP`。
- **文档与节点状态**：`real_011_batch_11_Spinoff2012`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#048；需做去重或不同split隔离。

**原 Question：**
````text
What capture-and-computation workflow allowed a rover imaging system to produce panoramas far beyond the native sensor resolution?
````

**原 Gold Answer：**
````text
A NASA-built automated tripod and photo-processing software combined a series of smaller shots into a large image.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_011_batch_11_Spinoff2012:p0088:e003` · 页 `88` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_011_batch_11_Spinoff2012/pages/page_0088/output_json/page_0088.json`
   - bbox：`[93, 380, 549, 528]`

````text
While the rovers each took a mere 1 megapixel camera for the journey, the pictures they have become famous for measure up to 96 megapixels in size. This was made pos- sible by a NASA-built automated tripod, which with the help of photo processing software seamlessly integrates a series of smaller shots into one large image.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】片段直接给出约1MP原始相机、最大96MP全景和NASA自动化支架与拼接软件，因此工作流和提升数量级都得到支持。需区分“高分辨率拼接后的像素数”与单帧传感器原生分辨率，不应表述成相机自身升级为96MP。候选答案保持了这种区分；与#048有明显重复。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #022 行号。**目标操作**：`DEDUPLICATE_OR_KEEP`。
2. 明确拼接图像总像素不等于原传感器像素；与 #048 重复，#048 还包含商业转化。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #023 · `manual_qa_review_v1::023`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`DEDUPLICATE_OR_KEEP`。
- **文档与节点状态**：`real_012_batch_12_Spinoff2011`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#049；需做去重或不同split隔离。

**原 Question：**
````text
Which two commercial aircraft marked the transition from experimental electronic flight control to mainstream airline adoption, and in what sequence?
````

**原 Gold Answer：**
````text
The Airbus 320 in 1987 and Boeing's 777 in 1994.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_012_batch_12_Spinoff2011:p0079:e003` · 页 `79` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_012_batch_12_Spinoff2011/pages/page_0079/output_json/page_0079.json`
   - bbox：`[93, 461, 550, 779]`

````text
The first commercial airliner to fly with DFBW was the Airbus 320 in 1987, followed by Boeing's 777 in 1994. Today, the technology features in a number of aircraft from both manufacturers. For commercial air- craft, the technology replaces heavy mechanical systems, allowing airlines to benefit from greater fuel efficiency or carry more passengers and cargo. The heightened responsiveness of DFBW-enabled aircraft allows pilots to provide a smoother flight, and the system's redundan- cies help ensure safe operation of the vehicle. Mechanical maintenance needs are also reduced, saving costs and time spent on upkeep and repairs of the mechanical systems and reducing the chance of failures.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据明确给出Airbus A320（文中写Airbus 320）1987年、Boeing 777 1994年这一先后顺序，标准答案充分。题干中的“from experimental to mainstream”属于历史发展概括，当前引文以商用首飞为依据。建议保留航空器型号规范拼写“A320”和“Boeing 777”，不要将商业采用年份误当成全部机队投入运营时间。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #023 行号。**目标操作**：`DEDUPLICATE_OR_KEEP`。
2. 规范机型名称为 Airbus A320、Boeing 777；文中采用年份不等于所有商业运营年份。与 #049 事实高度重叠。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #024 · `manual_qa_review_v1::024`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`VERIFY_TRUNCATED_EVIDENCE_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_012_batch_12_Spinoff2011`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_evidence_draft`。
- **相似/重复题**：#050；需做去重或不同split隔离。

**原 Question：**
````text
Which nanoscale conductor is proposed for solar cells because it combines extreme thinness with unusual electrical, thermal, and mechanical properties?
````

**原 Gold Answer：**
````text
A carbon nanotube.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_012_batch_12_Spinoff2011:p0150:e003` · 页 `150` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_012_batch_12_Spinoff2011/pages/page_0150/output_json/page_0150.json`
   - bbox：`[93, 474, 550, 646]`

````text
To build upon existing photovoltaic technology, NASA's Glenn Research Center has worked on a variety of innovative designs and materials to incorporate into photovoltaic cells, the building blocks of solar power sys- tems. One of these materials is the carbon nanotube—a tiny structure about 50,000 times finer than the average human hair, with notably high electrical and thermal con-
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据明确点名carbon nanotube并描述其极细尺寸，足以支撑“哪种材料”的实体答案。问题附加的高导电、导热、强度三性质，在所抽取的片段中实际在“thermal con-”处被截断，无法完成逐项核验；建议补齐跨栏/跨段正文后再作为严格的性质组合题。与#050高度重复。 【建议标签】weak_evidence, duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #024 行号。**目标操作**：`VERIFY_TRUNCATED_EVIDENCE_AND_DEDUPLICATE`。
2. 碳纳米管实体直接出现，但属性组合在 thermal con- 后被截断；需查 PDF/相邻段以核实 conductivity/strength。与 #050 重复。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #025 · `manual_qa_review_v1::025`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`FIX_ANSWER_OR_RECOVER_EVIDENCE`。
- **文档与节点状态**：`real_013_batch_13_Spinoff2010`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。

**原 Question：**
````text
What makes the subscale testbed experimentally different from a simulator even though both are used to develop flight-control methods?
````

**原 Gold Answer：**
````text
Its subscale vehicle actually flies as a remotely piloted aircraft and communicates with display and control computers through a high-bandwidth telemetry link.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_013_batch_13_Spinoff2010:p0162:e000` · 页 `162` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_013_batch_13_Spinoff2010/pages/page_0162/output_json/page_0162.json`
   - bbox：`[93, 164, 549, 240]`

````text
The difference between AirSTAR and a flight simula- tor is that in AirSTAR, the vehicle is actually flying as a remotely piloted aircraft communicating with display and
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】当前证据片段只到“vehicle is actually flying as a remotely piloted aircraft communicating with display and”，未保留后续内容。虽然可确认“不是纯模拟而是真机遥控飞行”，但候选答案额外声称与显示控制计算机采用“high-bandwidth telemetry link”，在所给证据里无法核实。建议补齐下一段或页内连续文本，或把答案裁剪为“真实遥控的缩比飞行器而非软件仿真”。 【建议标签】weak_evidence, unsupported_answer。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #025 行号。**目标操作**：`FIX_ANSWER_OR_RECOVER_EVIDENCE`。
2. 该节点在 “communicating with display and” 截断；high-bandwidth telemetry link 未得到本节点证明。若保留链路说法，恢复同页续段并正确映射。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Unlike a purely simulated aircraft, the subscale testbed uses an actual remotely piloted vehicle in flight.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #026 · `manual_qa_review_v1::026`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`DEDUPLICATE_AND_AVOID_CAUSAL_OVERCLAIM`。
- **文档与节点状态**：`real_013_batch_13_Spinoff2010`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#052；需做去重或不同split隔离。

**原 Question：**
````text
What paired observational result supports interpreting the Maryland phenology shift as a broader environmental change rather than isolated beekeeper anecdotes?
````

**原 Gold Answer：**
````text
It came about a half-day earlier each year on average and had shifted about a month earlier since the 1970s.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_013_batch_13_Spinoff2010:p0202:e000` · 页 `202` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_013_batch_13_Spinoff2010/pages/page_0202/output_json/page_0202.json`
   - bbox：`[93, 164, 551, 339]`

````text
Data from the network, when combined with additional data that reach back to the 1920s, indicate that the timing of spring nectar flows have undergone extraordinary changes. “Each year, the nectar flow comes about a half-day earlier on average,” said Esaias. “In total, since the 1970s, it has moved forward by about month in Maryland.”
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】段落给出两个数值：每年花蜜流平均提前约半天，自1970年代以来马里兰累计提前约一个月，两者均与答案一致。局限：该段只是长期观测现象，并未直接证明其“由环境变化引起”或排除观察者偏差；题干“rather than isolated anecdotes”可解释为长期数据支撑，但不能提升为气候因果证据。与#052重复。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #026 行号。**目标操作**：`DEDUPLICATE_AND_AVOID_CAUSAL_OVERCLAIM`。
2. 半天/年与约一个月/1970年代以来两趋势是观察事实；不要把结果表述成已经确定气候因果。#052 多证据加交叉验证，建议留 #052。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #027 · `manual_qa_review_v1::027`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`KEEP_MULTIEVIDENCE_VERIFY_OCR_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_001_batch_01_NASA-Spinoff-2023`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_evidence_draft`。
- **相似/重复题**：#001；需做去重或不同split隔离。

**原 Question：**
````text
What design logic connects life support for an orbiting crew with a method for local food autonomy?
````

**原 Gold Answer：**
````text
CELS treated plants as part of a closed loop that recycled waste into food and oxygen; its results helped give rise to controlled-environment agriculture for self-reliant communities.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_001_batch_01_NASA-Spinoff-2023:p0007:e005` · 页 `7` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_001_batch_01_NASA-Spinoff-2023/pages/page_0007/output_json/page_0007.json`
   - bbox：`[298, 196, 732, 245]`

````text
NASA has worked for decades to develop a life-support system that functions as a self-replenishing ecology. At the heart of this work was the Controlled Ecological Life Support System (CELS) program, which ran for about 25 years, between the late 1970s and early 2000s, at NASA's Kennedy Space Center in Florida. It relied especially on plants, which recycle waste into food and oxygen.
````

2. `real_001_batch_01_NASA-Spinoff-2023:p0007:e006` · 页 `7` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_001_batch_01_NASA-Spinoff-2023/pages/page_0007/output_json/page_0007.json`
   - bbox：`[298, 251, 731, 300]`

````text
The project's results, published in hundreds of papers over the years, have given rise to the controlled environment agriculture movement (Spinet 2021). But Womack wanted to apply the findings to something closer. NASA's goal is – a closed-loop, self-sustaining life-support system that would enable self-reliance for families, homesteaders, and communities.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一节点给出CELS植物—废物—食物/氧气循环，第二节点明确从研究成果到受控环境农业及家庭/社区自给的应用目标，两个环节齐全。多证据设计合理；但第二段有明显转录问题（“Spinet 2021”及标点），建议核对PDF，避免把公司愿景误表述成已验证的现实农业效果。与#001内容重叠，保留这一题更有多跳价值。 【建议标签】duplicate, other。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #027 行号。**目标操作**：`KEEP_MULTIEVIDENCE_VERIFY_OCR_AND_DEDUPLICATE`。
2. CELS→受控环境农业→社区自主的两跳证据完整；修复 Spinet 2021 拼接和标点噪声，区分技术愿景与已经实现的效果。与 #001 重复优先此题。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #028 · `manual_qa_review_v1::028`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`VERIFY_OCR_AND_SCOPE_CLAIMS_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_001_batch_01_NASA-Spinoff-2023`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`, `gold_evidence_draft`。
- **相似/重复题**：#002；需做去重或不同split隔离。

**原 Question：**
````text
Why does using hydrogen as an aviation fuel create both an emissions advantage and a storage-engineering challenge?
````

**原 Gold Answer：**
````text
Hydrogen produces no carbon emissions and has high energy per pound, but its low boiling point means it must be kept extremely cold or at high pressure in a strong tank.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_001_batch_01_NASA-Spinoff-2023:p0009:e006` · 页 `9` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_001_batch_01_NASA-Spinoff-2023/pages/page_0009/output_json/page_0009.json`
   - bbox：`[344, 184, 731, 245]`

````text
Replacing jet fuel with hydrogen would be good for business and the environment. Hydrogen generates no carbon emissions and packs three times the energy per pound of hydrocarbon. It's a cleaner, more cost-effective, and more environmentally friendly fuel than fossil fuels, can't safely hold hydrogen. A solution is the carbo-fibrilled Hybrid Laminar (HHL) cryotank developed by Glycer-Taylor Laboratories (GT) Inc. of Tulsa, Tennessee.
````

2. `real_001_batch_01_NASA-Spinoff-2023:p0009:e007` · 页 `9` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_001_batch_01_NASA-Spinoff-2023/pages/page_0009/output_json/page_0009.json`
   - bbox：`[344, 252, 731, 312]`

````text
While NASA is testing it to carry liquid oxygen into space, a commercial airline is interested in the fact that the BHL could ultra-cold fuels without developing the micromicrols that they believe are so essential for certain propellant tanks. Hydrogen has one of the lowest boiling points of any element on Earth and its burning gas form must be kept extremely cold, or it needs to be kept under remarkably high pressure.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一段陈述氢燃料不产生碳排放并具有较高单位重量能量，第二段说明极低沸点引出的冷储或高压储存困难，两条联合支持优势—挑战的对照。注意原文存在严重OCR粘连与疑似错误专有名词；“no carbon emissions”应理解为文中燃烧端表述，不能外推到制氢全生命周期。最好核对原始PDF并精确写“cryogenic storage or high-pressure containment”。与#002相关。 【建议标签】other, duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #028 行号。**目标操作**：`VERIFY_OCR_AND_SCOPE_CLAIMS_AND_DEDUPLICATE`。
2. 第一段背景明显OCR粘连/公司名可疑；“no carbon emissions”不得外推为全生命周期零排放；与 #002 同议题，优先本多证据题。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Hydrogen offers high energy per unit mass and no carbon emissions at the point of use, but its low boiling point requires cryogenic storage or high-pressure containment.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #029 · `manual_qa_review_v1::029`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`FIX_ANSWER_OR_ADD_EVIDENCE`。
- **文档与节点状态**：`real_002_batch_02_Spinoff.2022`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。

**原 Question：**
````text
What agricultural pressures make controlled-environment farming a long-term response rather than merely an efficiency improvement?
````

**原 Gold Answer：**
````text
The article projects 2.3 billion additional people by 2050, largely in cities, while conventional agriculture can deplete nutrients and contaminate water and soil; controlled environments address resource reuse and chemical dependence.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_002_batch_02_Spinoff.2022:p0017:e003` · 页 `17` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_002_batch_02_Spinoff.2022/pages/page_0017/output_json/page_0017.json`
   - bbox：`[279, 166, 491, 264]`

````text
The United Nations predicts Earth will have to feed another 2.3 billion people by the year 2050, with most concentrated in urban centers far from farmland. Current agriculture may not have the capacity to feed that many people, and it threatens future production by depleting soil of essential nutrients and contaminating freshwater supplies and soil with pesticides and herbicides.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】证据支持人口增加约23亿、人口更加城市化、农地与城市距离、传统农业土壤养分流失和农药/除草剂污染风险。但候选答案最后加入“受控环境可循环利用资源并减少化学依赖”，当前证据尚未陈述这种解决机制。题目是“压力”，可以保留前半部分并删除解决方案断言；如果要求论证回应方式，应增加其他段落。 【建议标签】unsupported_answer, weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #029 行号。**目标操作**：`FIX_ANSWER_OR_ADD_EVIDENCE`。
2. 把 resource reuse / reduced chemical dependence 解决机制删掉，因为当前节点只列农业压力；如要保留，补来源后转 multi_evidence。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Projected population growth of about 2.3 billion by 2050, increasing concentration in cities far from farmland, nutrient depletion, and pesticide/herbicide contamination pressure conventional agriculture.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #030 · `manual_qa_review_v1::030`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`REMOVE_UNSOURCED_MECHANISM_AND_VERIFY_OCR`。
- **文档与节点状态**：`real_002_batch_02_Spinoff.2022`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`, `gold_evidence_draft`。
- **相似/重复题**：#004；需做去重或不同split隔离。

**原 Question：**
````text
During an irreversible celestial rendezvous, what metrological capability makes a navigation decision trustworthy?
````

**原 Gold Answer：**
````text
Their extremely steady atomic oscillations provide the timing accuracy needed by the Deep Space Network to navigate to the right time and place; a missed Jupiter flyby could waste the entire mission investment.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_002_batch_02_Spinoff.2022:p0031:e005` · 页 `31` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_002_batch_02_Spinoff.2022/pages/page_0031/output_json/page_0031.json`
   - bbox：`[270, 223, 494, 333]`

````text
"If you've been flying for six years, and you have just one chance for a Jupiter flyby, and you don't get there at the right time and place, the entire investment you've made is essentially gone,"" explained Luke Malek, former researcher at NASA's Jet Propulsion Laboratory in Southern California. "Over time, you can't allow you to successfully navigate to your target, and be sure they're extremely important."
````

2. `real_002_batch_02_Spinoff.2022:p0031:e007` · 页 `31` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_002_batch_02_Spinoff.2022/pages/page_0031/output_json/page_0031.json`
   - bbox：`[270, 407, 487, 493]`

````text
NASA Deep Space Network (DSN), a sort of GPS system for space, relies on atomic clocks for extreme accuracy. Any modern navigation system must accurately time radio signals to triangulate a measurement, but the time for accuracy is even higher in space, where great distances can compound even tiny errors.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】引文一描述漫长飞行后木星飞掠机会难以重来，二解释DSN使用原子钟精确计时无线电信号；场景与测量需求形成两证据链，答案核心准确。需指出候选答案的“extremely steady atomic oscillations”并非引文原话，只是对原子钟机理的常识性补充，评测时最好收窄为“atomic-clock timing precision”；第一个引文转录噪声明显。 【建议标签】other。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #030 行号。**目标操作**：`REMOVE_UNSOURCED_MECHANISM_AND_VERIFY_OCR`。
2. 核实 p31 飞掠引文乱码；“extremely steady atomic oscillations”非此证据直接表述。与 #004 有主题重合。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
NASA’s Deep Space Network relies on atomic clocks to time radio signals accurately for navigation over great distances; an error during a one-off Jupiter flyby could jeopardize the mission.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #031 · `manual_qa_review_v1::031`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`VERIFY_TIMELINE_OCR_AND_SCOPE`。
- **文档与节点状态**：`real_003_batch_03_NASA_Spinoff_2021`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_evidence_draft`。
- **相似/重复题**：#006；需做去重或不同split隔离。

**原 Question：**
````text
How did HACCP move from a NASA-developed safety approach to broad food-industry regulation?
````

**原 Gold Answer：**
````text
After its 1971 presentation and FDA training, low-acid canned food makers were regulated in 1973; following the 1993 E. coli outbreak, USDA rules covered meat and poultry and FDA requirements expanded to seafood and juice.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_003_batch_03_NASA_Spinoff_2021:p0034:e001` · 页 `34` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_003_batch_03_NASA_Spinoff_2021/pages/page_0034/output_json/page_0034.json`
   - bbox：`[49, 67, 270, 189]`

````text
The company presented HACCP to the world at the first National Conference on Food Protection in 1971. It was not immediately embraced, but after being questioned by the committee of inquiry about that summer, the National Canners Association petitioned the Food and Drug Administration (FDA) for regulations to prevent food poisoning. The FDA in turn asked Pilsbury to train its supervisors and food inspectors so that system it had developed for NASA.
````

2. `real_003_batch_03_NASA_Spinoff_2021:p0034:e002` · 页 `34` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_003_batch_03_NASA_Spinoff_2021/pages/page_0034/output_json/page_0034.json`
   - bbox：`[48, 196, 265, 331]`

````text
In 1973, low-acid canned food manufacturers became the first to be subject to HACCP regulations, and they were the only ones for a long time. Then in 1993, an outbreak of food poisoning due to a Shiga tono-producing strain of E. coli bacteria caused the meat and poultry industries to close down. This was a time of economic confidence. Within a decade, the U.S. Department of Agriculture (USDA) had HACCP regulations in place for meat and poultry, and the FDA required the system for all seafood and juice producers. By
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】两段构成从1971年向外界介绍HACCP、FDA要求培训，到1973年低酸罐装食品首次受监管，再到后续肉类/家禽、海产品与果汁扩张的时间线。答案有足够依据。需核对1971年段落中“Pilsbury”等错拼，以及1993年食物中毒段落的可疑断句；谨慎区分监管启动时间与后来各部门具体规则生效时间。 【建议标签】other。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #031 行号。**目标操作**：`VERIFY_TIMELINE_OCR_AND_SCOPE`。
2. 修复 1971 段 Pillsbury 拼写、1973/1993 文本异常；监管扩展“within a decade”不等于每种产品同年生效。与 #006 事实交叉。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #032 · `manual_qa_review_v1::032`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`OPTIONAL_ANSWER_FOCUS`。
- **文档与节点状态**：`real_003_batch_03_NASA_Spinoff_2021`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。

**原 Question：**
````text
By what charge-based mechanism can the Apollo-era purification approach disable microbes?
````

**原 Gold Answer：**
````text
Positively charged silver ions bind to and disrupt negatively charged microbial cell membranes before entering the cells, which is why NASA commissioned an electrolytic silver-ion generator for Apollo water purification.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_003_batch_03_NASA_Spinoff_2021:p0024:e003` · 页 `24` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_003_batch_03_NASA_Spinoff_2021/pages/page_0024/output_json/page_0024.json`
   - bbox：`[49, 200, 265, 300]`

````text
The ancients, of course, had no idea how it worked – that when positively charged silver ions dissolve into water or other substances, they bond with and disrupt the negatively charged cell membranes of bacteria and other microorganisms before entering them and wreaking general havoc. But as understanding has improved, so has technology for delivering the ions.
````

2. `real_003_batch_03_NASA_Spinoff_2021:p0024:e004` · 页 `24` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_003_batch_03_NASA_Spinoff_2021/pages/page_0024/output_json/page_0024.json`
   - bbox：`[49, 305, 257, 380]`

````text
In the 1960s, Johnson, then known as the Manned Spacecraft Center, commissioned an electrolytic silver ion generator to purify water on the Apollo missions. The following decade, in the run-up to the space shuttle missions, the center sponsored a more advanced prototype.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一段明确银离子带正电、与微生物带负电的细胞膜结合并破坏膜结构；第二段证明NASA为Apollo用水净化委托了电解银离子发生器。机理与任务应用均被覆盖。问题只问灭活机制，答案连带NASA历史背景也可接受，但建议把机理写成首句、历史应用写成辅助句，以免答案过长。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #032 行号。**目标操作**：`OPTIONAL_ANSWER_FOCUS`。
2. 先给正电银离子与带负电细胞膜结合并破坏的机制，再用 Apollo 水净化作为背景。无强制修复。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #033 · `manual_qa_review_v1::033`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`REMOVE_UNSUPPORTED_ANSWER_CLAUSE`。
- **文档与节点状态**：`real_004_batch_04_Spinoff2020`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。
- **相似/重复题**：#007；需做去重或不同split隔离。

**原 Question：**
````text
How did the astronaut monitoring design combine multiple body measurements with mission operations rather than merely recording medical data?
````

**原 Gold Answer：**
````text
Separate conditioners captured temperature, ECG, breathing, and blood pressure, then fed the signals to onboard telemetry so ground stations could assess condition during flight and plan later missions.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_004_batch_04_Spinoff2020:p0028:e001` · 页 `28` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_004_batch_04_Spinoff2020/pages/page_0028/output_json/page_0028.json`
   - bbox：`[93, 148, 549, 294]`

````text
In the end, the astronauts wore a belt carrying four differ- ent signal conditioners that each captured data from sensors and electrodes attached across the body: an oral probe for temperature, electrodes for ECG (electrocardiogram) heart data and breath cycles, and an inflatable cuff with a sound transducer over an artery for blood pressure.
````

2. `real_004_batch_04_Spinoff2020:p0028:e002` · 页 `28` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_004_batch_04_Spinoff2020/pages/page_0028/output_json/page_0028.json`
   - bbox：`[93, 294, 549, 414]`

````text
Then the data was fed directly into the onboard telemetry system, explains the article. For the first time ever, “ ground monitoring stations receive the telemetered signals during flight. These signals are used to assess the physiological condition of the astronaut. ”
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】一段列出体温、心电/呼吸、血压的传感器，另一段说明信号直接进入机载遥测并由地面站实时用于评估宇航员生理状态；两段共同满足“医疗测量与飞行任务联动”。候选答案末尾“plan later missions”不在这两段的可见证据里，建议删去或补一条关于任务规划的段落。 【建议标签】weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #033 行号。**目标操作**：`REMOVE_UNSUPPORTED_ANSWER_CLAUSE`。
2. 删去 “plan later missions” 或增补直接证据。#007 仅覆盖前半段，这题更符合 multi_evidence。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
A belt-mounted set of signal conditioners measured body temperature, ECG/heart and breathing signals, and blood pressure; the data then entered the onboard telemetry system for ground stations to monitor astronaut physiology during flight.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #034 · `manual_qa_review_v1::034`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`TIGHTEN_INSTRUMENT_REFERENCE`。
- **文档与节点状态**：`real_004_batch_04_Spinoff2020`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`。

**原 Question：**
````text
Why was a helium-neon metrology laser unsuitable for a long-lived satellite instrument, and what lifetime target drove the replacement?
````

**原 Gold Answer：**
````text
A vacuum makes helium difficult to contain and helium-neon lasers last only three to four years, far short of the 10–15 year satellite lifetime expected for CrIS.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_004_batch_04_Spinoff2020:p0117:e004` · 页 `117` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_004_batch_04_Spinoff2020/pages/page_0117/output_json/page_0117.json`
   - bbox：`[94, 747, 550, 946]`

````text
“ On industrial systems, we used to use a helium-neon laser. Essentially, that's a tube with gas inside, and by applying a high voltage, it creates a laser signal," Soucy says. But that wouldn't work in space for a variety of reasons. For one, in the vacuum of space, it is difficult to contain the helium. For another, the lifespan of these lasers is only about three to four years — far too short for a satellite expected to last 10 to 15 years.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】段落直接解释空间真空环境下氦气难以封存、氦氖激光器寿命约3–4年，而预期卫星需运行10–15年，答案完全对应寿命差距。题干将这些因素与CrIS关联，但节选没有出现CrIS名称；若要求读者识别具体仪器，需要补上下文。其余无明显问题。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #034 行号。**目标操作**：`TIGHTEN_INSTRUMENT_REFERENCE`。
2. 本段没点名 CrIS，不可用该单节点证明具体仪器身份；保留必须补上文。
3. **候选新 `question`**（需核验后应用）：
````text
Why was a helium–neon laser unsuitable for a satellite expected to operate for 10–15 years?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #035 · `manual_qa_review_v1::035`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`KEEP_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_005_batch_05_Spinoff2019`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#009；需做去重或不同split隔离。

**原 Question：**
````text
How does shrinking a time standard alter the tradeoff between precision and physical footprint?
````

**原 Gold Answer：**
````text
The best clocks may not lose a second over the observable universe's lifetime but fill a laboratory, whereas satellite-sized clocks accept roughly a second of drift in 30,000 years to fit on a spacecraft.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_005_batch_05_Spinoff2019:p0052:e003` · 页 `52` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_005_batch_05_Spinoff2019/pages/page_0052/output_json/page_0052.json`
   - bbox：`[93, 328, 550, 477]`

````text
The best clocks are atomic clocks, and the best atomic clocks currently made “won’t lose a second in the entire life of the observable universe,” says Gregory Heckler, the deputy telecommunications systems manager for NASA’s Tracking and Data Relay Satellites (TDRS) at Goddard Space Flight Center.
````

2. `real_005_batch_05_Spinoff2019:p0052:e004` · 页 `52` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_005_batch_05_Spinoff2019/pages/page_0052/output_json/page_0052.json`
   - bbox：`[93, 476, 550, 626]`

````text
Unfortunately, those clocks tend to be enormous — filling up an entire laboratory — and so impractical, to say the least, for a satellite. To make a clock small enough to fit on a satellite, scientists are currently able to achieve pretty decent accuracy, good to maybe a second of drift in 30,000 years, but there's still plenty of room to improve.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】两条证据构成非常清楚的精度与物理体积对照：实验室级极高精度却太大，卫星级可缩小但约3万年漂移1秒。候选答案比#009完整，适合作为multi_evidence样本。应在措辞上注明“observable universe lifetime”是文章引用的量级说法，而非要精确验证的普适常数；与#009同源，应作去重选择。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #035 行号。**目标操作**：`KEEP_AND_DEDUPLICATE`。
2. 比 #009 的答案完整。文章对“宇宙寿命内不误1秒”是受访者量级表述，不当作可精确验证的常数。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #036 · `manual_qa_review_v1::036`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`KEEP`。
- **文档与节点状态**：`real_005_batch_05_Spinoff2019`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。

**原 Question：**
````text
How did the revised mass-spectrometer detector reduce signal degradation compared with earlier designs?
````

**原 Gold Answer：**
````text
A metal-oxide-coated silicon pixel directly received ion charge, avoiding the multiple ion-to-electron-to-photon conversions that added noise and blurred the beam focus.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_005_batch_05_Spinoff2019:p0152:e003` · 页 `152` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_005_batch_05_Spinoff2019/pages/page_0152/output_json/page_0152.json`
   - bbox：`[93, 487, 549, 681]`

````text
Working together, Wadsworth and Sinha came up with a simpler design. By coating each silicon pixel with a tough, conductive coating of metal oxide, they could make the CCD blind to light but able to directly receive a charge from an ion striking the sensor. The device would be enabled by some of the refined circuitry and strong separation between pixels that Wadsworth had developed for Mars rover cameras.
````

2. `real_005_batch_05_Spinoff2019:p0152:e002` · 页 `152` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_005_batch_05_Spinoff2019/pages/page_0152/output_json/page_0152.json`
   - bbox：`[93, 318, 549, 487]`

````text
Sinha had helped develop a mass spectrometer that used a CCD array in its focal plane—much easier to use than predecessors that had camera film in their focal planes—but it was complex and required high voltage. It essentially con- verted ions to electrons to photons, then back to electrons and finally to a digital signal, and every conversion added noise to the signal and blurred the focus of the ion beam.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】先前方案需多次离子→电子→光子→电子转换，增加噪声并模糊聚焦；改进方案用金属氧化物涂层像素直接感受离子电荷，恰好形成改造机理与效果对照。两个节点完整支撑答案，属于较好的因果式multi_evidence。建议避免将“减少转换步骤”拔高为已有定量信噪比改善，材料没有给数值。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #036 行号。**目标操作**：`KEEP`。
2. 离子直接进入感光器与避免多步转换噪声的机制有完整证据；不要捏造定量SNR改善。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #037 · `manual_qa_review_v1::037`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`SOFTEN_ABSOLUTE_CLAIM_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_006_batch_06_Spinoff2018`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。
- **相似/重复题**：#011；需做去重或不同split隔离。

**原 Question：**
````text
Which two forms of communication uncertainty must be controlled before avionics can share a common network?
````

**原 Gold Answer：**
````text
It had to make message timing and delivery deterministic, eliminating the possibility that messages would interrupt one another, be lost, or be damaged; this enabled a single network for critical Orion systems.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_006_batch_06_Spinoff2018:p0051:e003` · 页 `51` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_006_batch_06_Spinoff2018/pages/page_0051/output_json/page_0051.json`
   - bbox：`[93, 353, 550, 527]`

````text
Until recently, though, Ethernet could never be used for critical systems like the spacecraft avionics responsible for navigation, communication, and other essential functions, because it's imprecise. There's no guarantee how long it will take to transmit a message or even whether it will arrive at its intended destination. Messages can interrupt each other or be lost or damaged.
````

2. `real_006_batch_06_Spinoff2018:p0051:e004` · 页 `51` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_006_batch_06_Spinoff2018/pages/page_0051/output_json/page_0051.json`
   - bbox：`[93, 527, 550, 675]`

````text
But a sophisticated deterministic Ethernet system devel- oped for NASA's new Orion space capsule allows all the spacecraft's systems to communicate on a single Ethernet network—and the technology is also being applied to integrate systems for self-driving cars, industrial applications, defense programs, commercial spacecraft, and more.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一段说明传输延迟和消息是否送达不可确定，第二段指出确定性以太网让Orion的各系统共用网络；问题要求的两类不确定性与候选答案一致。建议将“消除所有消息损坏风险”改为“提供确定性、可控的通信行为”，因为证据没有给出绝对零故障保证。与#011内容交叉。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #037 行号。**目标操作**：`SOFTEN_ABSOLUTE_CLAIM_AND_DEDUPLICATE`。
2. 原答案“eliminating the possibility”暗示绝对零中断/损坏，来源无此保证。与 #011 重复。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
A deterministic Ethernet approach addressed uncertainty in message-delivery timing and reliability, allowing Orion systems to share a single network.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #038 · `manual_qa_review_v1::038`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`KEEP_AVOID_COUNTERFACTUAL_CLAIM`。
- **文档与节点状态**：`real_006_batch_06_Spinoff2018`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。

**原 Question：**
````text
Why do unexpected rover and lander failures make high-fidelity planetary simulants a mission-design requirement?
````

**原 Gold Answer：**
````text
Phoenix could not deliver sticky icy soil and Spirit became stuck in hidden soft sulfate; accurate simulants are needed because hardware sent to other worlds is only as good as the environments used to test it.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_006_batch_06_Spinoff2018:p0083:e002` · 页 `83` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_006_batch_06_Spinoff2018/pages/page_0083/output_json/page_0083.json`
   - bbox：`[91, 202, 551, 458]`

````text
After the Phoenix lander settled into the northern polar region of Mars in 2008, its operators dis- covered that icy soil scraped from the planet's surface was too sticky to deliver from the probe's scoop to one of its instruments, forcing them to content them- selves with only analyzing dry soil. A little over a year later, near the planet's equator, the Spirit rover got stuck in a deposit of soft iron sulfate hidden under a layer of normal-looking Martian soil, putting an end to more than five years of roaming.
````

2. `real_006_batch_06_Spinoff2018:p0083:e003` · 页 `83` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_006_batch_06_Spinoff2018/pages/page_0083/output_json/page_0083.json`
   - bbox：`[92, 458, 551, 662]`

````text
These and other unexpected difficulties that have confronted rovers and landers on other worlds might be avoided in future missions if engineers building them have more accurate testing environments, including “simulants” imitating the dirt, dust, and rock of a given planet. As a 2012 paper out of NASA’s Marshall Space Flight Center notes, technology sent to other planets and moons “is only as good as the simulants used to test it.”
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】Phoenix土样黏附导致无法送入仪器、Spirit陷入隐藏的松软沉积层，是两个具体失败案例；后一段明确论证更准确的土壤/岩石模拟物有助于设计阶段发现问题，支撑整个问答。注意该论证是“可能避免未来同类问题”，不是证明这些历史事故必然可以通过特定模拟物避免。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #038 行号。**目标操作**：`KEEP_AVOID_COUNTERFACTUAL_CLAIM`。
2. 模拟物可提高地面测试代表性，但不能由文章推出历史两次事故“确定本可避免”。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #039 · `manual_qa_review_v1::039`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`KEEP_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_007_batch_07_Spinoff2017`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#013；需做去重或不同split隔离。

**原 Question：**
````text
What performance tradeoff made the early silver-zinc battery technology potentially valuable despite its shorter cycle life?
````

**原 Gold Answer：**
````text
It managed only 400–500 shallow cycles versus 10,000 for nickel-cadmium, but could produce batteries one-third the size, saving substantial weight.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_007_batch_07_Spinoff2017:p0098:e000` · 页 `98` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_007_batch_07_Spinoff2017/pages/page_0098/output_json/page_0098.json`
   - bbox：`[93, 75, 550, 294]`

````text
By 1972 Lewis had tested and proven silver-zinc cells based on a specific inorganic separator and a specially prepared zinc electrode, which were able to function as a rechargeable battery after heat sterilization. The cells were still only reliable up to 400 to 500 shallow discharge cycles, as opposed to the 10,000-cycle life of the nickel-cadmium batteries commonly used in space applications of the time, but they could result in batteries one-third the size of nickel- cadmium units, a substantial saving in weight.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】文本同时给出400–500对10000浅循环的寿命劣势，以及银锌电池约三分之一尺寸与减重优势；候选答案完整覆盖两项权衡。可保留。与#013使用同一证据；#013答案缺少尺寸优势，优先保留本题并去掉冗余。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #039 行号。**目标操作**：`KEEP_AND_DEDUPLICATE`。
2. 与 #013 同节点和相同tradeoff，#039更完整；建议优先留 #039。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #040 · `manual_qa_review_v1::040`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`ADD_SPEED_CONSTRAINT_TO_ANSWER_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_007_batch_07_Spinoff2017`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。
- **相似/重复题**：#014；需做去重或不同split隔离。

**原 Question：**
````text
Why must exploration-mission diagnostics be both rapid and compact rather than relying on terrestrial laboratory equipment?
````

**原 Gold Answer：**
````text
Spaceflight can suppress immunity and increase bacterial virulence, while emergency return from Mars could take months; terrestrial lab technologies are too large for exploration missions.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_007_batch_07_Spinoff2017:p0041:e002` · 页 `41` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_007_batch_07_Spinoff2017/pages/page_0041/output_json/page_0041.json`
   - bbox：`[93, 201, 551, 452]`

````text
NASA astronauts are screened for sound health, among a slew of other requirements, but no one is invulnerable, especially in space. For reasons not fully understood, space travel appears to suppress the human immune system, while some bacteria become heartier and more virulent in microgravity. Meanwhile, aboard the International Space Station, the nearest medi- cal doctor is on the other side of atmospheric reentry. On a future mission to Mars, any emergency return would likely take months.
````

2. `real_007_batch_07_Spinoff2017:p0041:e004` · 页 `41` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_007_batch_07_Spinoff2017/pages/page_0041/output_json/page_0041.json`
   - bbox：`[93, 602, 551, 873]`

````text
“ We don't currently have lab technologies we use terrestrially that are of a size that would be acceptable for use in space, at least not on an exploration mission, ” Shaw says. Blood work, for example, normally involves a few samples being taken and sent to different locations where they're analyzed using the kind of heavy, bulky tabletop equipment that would cost a fortune to launch into space. What Shaw and her colleagues want instead would more resemble a home pregnancy test, with a single sample analyzed by one small device that produces results within minutes.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一段给出免疫与细菌风险以及火星医疗救援延迟，第二段明确地面实验设备笨重、发射成本高，希望在几分钟内用单一小设备分析样本；答案基本准确。建议补出“minutes”和“single sample”的快速诊断需求，使“rapid”不仅停留在题干而在答案里也明确。与#014有内容重复，但本题证据更完整。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #040 行号。**目标操作**：`ADD_SPEED_CONSTRAINT_TO_ANSWER_AND_DEDUPLICATE`。
2. 回答要出现题干 rapid 的证据要求；与 #014 同题材且当前两节点更充分。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Spaceflight may suppress immunity and increase some bacterial risks, while a Mars emergency return could take months. Exploration diagnostics therefore need to replace bulky terrestrial labs with compact equipment that can analyze samples in minutes.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #041 · `manual_qa_review_v1::041`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`KEEP_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_008_batch_08_Spinoff2016`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#015；需做去重或不同split隔离。

**原 Question：**
````text
Why can hydrogen storage outperform batteries for remote solar-powered telecommunications sites in hot climates?
````

**原 Gold Answer：**
````text
Hydrogen can store excess renewable power without the idle losses of alkaline batteries and without rapid-draw heat losses, while solar-linked batteries can suffer performance problems in hot locations.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_008_batch_08_Spinoff2016:p0126:e003` · 页 `126` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_008_batch_08_Spinoff2016/pages/page_0126/output_json/page_0126.json`
   - bbox：`[93, 684, 550, 975]`

````text
It's the first electrolyzer to be competitive with bat- teries and even provides some advantages. For example, unused alkaline batteries lose energy over time, whereas a cylinder of pressurized hydrogen gas will keep virtually indefinitely without losses. Batteries also lose energy to heat if power is drawn from them rapidly, which is not the case with hydrogen fuel cells. At telecommunication towers in remote parts of Africa or India, which are often powered by solar energy, batteries have performance issues due to the heat. “ Our panels love heat, ” Guerra says. “ The hotter the electrolyte, the more efficient they get. ”
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】段落比较加压氢气长期存储、快速供能时电池发热损耗，以及炎热地区太阳能通信塔的电池性能问题，完整支持题目。需要注意“virtually indefinitely without losses”是针对压力容器的陈述；“panels love heat”似指该公司电解设备，不能泛化为所有光伏板在高温下效率更高。与#015高度相近。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #041 行号。**目标操作**：`KEEP_AND_DEDUPLICATE`。
2. 与 #015 重复；原文说压力氢筒比较闲置碱性电池，不可泛化“所有热环境太阳能板效率提高”。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #042 · `manual_qa_review_v1::042`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`KEEP_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_008_batch_08_Spinoff2016`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#016；需做去重或不同split隔离。

**原 Question：**
````text
Why do liquid-hydrogen launch systems require both extreme thermal control and highly sensitive leak detection?
````

**原 Gold Answer：**
````text
Hydrogen must stay below −423 °F to remain liquid, but its atoms escape through tiny cracks and high-pressure leaks can cause combustion because the gas is highly flammable.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_008_batch_08_Spinoff2016:p0073:e003` · 页 `73` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_008_batch_08_Spinoff2016/pages/page_0073/output_json/page_0073.json`
   - bbox：`[92, 353, 552, 674]`

````text
But harnessing that energy requires a great deal of technological know-how on the Agency's part. For one, keeping hydrogen in its liquid state means maintaining it at a temperature below -423 °F. The element must also be insulated from external heat sources during launch, lest it begin to evaporate. Then there's the persistent threat of leakage. As the smallest and lightest of atoms, hydrogen escapes through the tiniest of cracks. That makes it a hazard, as the element is highly flammable, to the point where high-pressure joint leaks can cause combustion. As a result, detecting leaks is a top priority, but it's also a challenge, because the gas — and the flame it emits — are odorless and colorless.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】氢液化温度阈值−423 °F、保温防蒸发、微小缝隙泄漏和高压下燃烧风险都在同一段出现，足够支持双重工程挑战。候选答案准确；若提高完整性可补“气体与火焰无色无味导致难检测”。与#016几乎重复，应在评测集里二选一。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #042 行号。**目标操作**：`KEEP_AND_DEDUPLICATE`。
2. 与 #016 同证据，至少做相同答案模板去重；可补无色无味造成检测难度。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #043 · `manual_qa_review_v1::043`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`KEEP_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_009_batch_09_Spinoff2015`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#017；需做去重或不同split隔离。

**原 Question：**
````text
What sequence of environmental and biological measurements converts a general atmospheric loss estimate into crop-level irrigation guidance?
````

**原 Gold Answer：**
````text
A crop coefficient for a crop and growth stage multiplies ETo for a field-specific estimate; Landsat and MODIS vegetation data can be used to derive those coefficients.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_009_batch_09_Spinoff2015:p0111:e001` · 页 `111` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_009_batch_09_Spinoff2015/pages/page_0111/output_json/page_0111.json`
   - bbox：`[93, 214, 550, 532]`

````text
As helpful as ETo data is, farmers and irrigators must still perform additional calculations to convert the ETo information into a number specific to their fields and crops. For example, the utility of ETo information is increased when paired with another piece of data called the crop coefficient. Specific to the crop type and its stage of growth, the number, when multiplied by ETo, results in a more refined measurement of evapotranspiration specific to a particular crop and field. As it turns out, in recent years NASA and the US Department of Agriculture (USDA) together were discovering that Landsat and MODIS data could be used to map vegetation conditions and, from that, derive crop coefficients.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】同一段同时包含ETo、按作物与生育阶段定义的crop coefficient、二者相乘得到特定田块蒸散量，以及Landsat/MODIS反演系数的路径；答案与题目的“序列”一致。建议标准答案明确“ETo是参考蒸散量，而不是已经针对该田块的蒸散量”。与#017重复，应择其一。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #043 行号。**目标操作**：`KEEP_AND_DEDUPLICATE`。
2. 与 #017 同证据，题目包含 Landsat/MODIS 的系数反演扩展；解释 ETo 是参考值而非最终田块值。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #044 · `manual_qa_review_v1::044`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`ADD_LANDSAT_EVIDENCE_OR_REMOVE_CLAUSE`。
- **文档与节点状态**：`real_009_batch_09_Spinoff2015`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`, `gold_evidence_draft`。
- **相似/重复题**：#018；需做去重或不同split隔离。

**原 Question：**
````text
Why does WATEX need to combine multiple remote-sensing and geophysical inputs rather than reading groundwater directly from one image?
````

**原 Gold Answer：**
````text
Its processing removes surface obstacles from SAR and SIR imagery while preserving soil-wetness signals, then combines geophysical, geological, and Landsat inputs to infer groundwater.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_009_batch_09_Spinoff2015:p0060:e004` · 页 `60` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_009_batch_09_Spinoff2015/pages/page_0060/output_json/page_0060.json`
   - bbox：`[93, 369, 550, 563]`

````text
a proprietary process Gachet developed that removes surface obstacles from NASA SAR data and SIR data without harming the soil wetness signal. In other words, the WATEX processes NASA SAR imagery so that information about groundwater can be inferred without the interference of surface features such as infrastructure, rocks, or vegetation. This process is combined with several other inputs, such as geophysical and geological data.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】问题要求WATEX结合多源数据的理由和方法；当前单证据仅交代SAR/SIR去除地表障碍、保留湿度信号并结合地质/地球物理数据。答案又加入Landsat输入，虽可能在邻近段落成立，却未在所选证据中出现。建议去掉Landsat或将#018中的Landsat段补为第二证据；若坚持单证据，应把答案限定在“地表特征干扰地下水间接推断”。 【建议标签】weak_evidence, unsupported_answer。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #044 行号。**目标操作**：`ADD_LANDSAT_EVIDENCE_OR_REMOVE_CLAUSE`。
2. 当前仅一节点，不能支撑 Landsat；若坚持 Landsat，加入 #018 第二条证据，并更新 question_type_actual 为 multi_evidence。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
WATEX removes obstructing surface features from SAR/SIR observations while preserving soil-wetness information, and combines the result with geophysical and geological data to infer groundwater.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #045 · `manual_qa_review_v1::045`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`MAKE_ANSWER_COMPLETE`。
- **文档与节点状态**：`real_010_batch_10_Spinoff2013`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。
- **相似/重复题**：#019；需做去重或不同split隔离。

**原 Question：**
````text
What did the private reentry-vehicle developer gain that addressed a scale-up risk absent in an earlier capsule?
````

**原 Gold Answer：**
````text
SpaceX could draw on 40–50 years of NASA heat-shield knowledge, while Dragon faced a scaling challenge that Stardust's much smaller sample-return capsule did not.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_010_batch_10_Spinoff2013:p0065:e001` · 页 `65` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_010_batch_10_Spinoff2013/pages/page_0065/output_json/page_0065.json`
   - bbox：`[93, 459, 550, 728]`

````text
Having seen the Stardust capsule's successful reentry, the company was very interested in the choice of PICA as a material for their heat shield. Fortunately, under the provisions of the contract, in addition to financial funding SpaceX also had access to NASA's brain trust of engineers for technical consultation, which the firm made full use of. “The group of people we worked with had basically designed every American heat shield since the Apollo days,” says Andrew Chambers, the company's project lead in this arena. “We were able to tap 40–50 years of knowl- edge and experience, which was absolutely invaluable.”
````

2. `real_010_batch_10_Spinoff2013:p0065:e002` · 页 `65` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_010_batch_10_Spinoff2013/pages/page_0065/output_json/page_0065.json`
   - bbox：`[93, 728, 551, 1121]`

````text
Over the next few years Ames and SpaceX worked closely with one another, and throughout much of 2008 Rasky worked half-time for SpaceX through an Interagency Personnel Assignment agreement. With this particular heat shield, Dragon's designers would have to contend with a challenge that Stardust didn't pose—size. Stardust's Sample Return Capsule only required a PICA shield that was a little over 1 meter in diameter; to protect the much bulkier Dragon a 4-meter version was needed. With the 1-meter shield, Rasky and his team worked with Fiber Materials Incorporated to fabricate a single piece of PICA, but that wouldn't be possible with the larger Dragon cargo transporter. To solve that problem they devised an efficient and cost-effective method for manu- facturing smaller PICA tiles, which were then fabricated into a single heat shield.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】两节点分别证明SpaceX从NASA获得40–50年热防护工程经验，以及Dragon需要4米PICA防热盾、Stardust只需约1米且单件制造方法无法直接放大，因而存在尺寸扩展风险。答案抓住两点，不过没写出解决办法“改为多个PICA小瓦片组装”；建议补入以真正回应“gain addressed risk”的工程意义。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #045 行号。**目标操作**：`MAKE_ANSWER_COMPLETE`。
2. 须核实所选两段包含“多瓦片组装”语句才可采用建议中的最后半句；否则先补工程方案段再扩展答案。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
SpaceX gained access to decades of NASA heat-shield expertise when scaling PICA from the much smaller Stardust application to Dragon; the larger shield required an engineering change such as assembling multiple smaller PICA tiles rather than one large monolithic piece.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #046 · `manual_qa_review_v1::046`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`TIGHTEN_QUESTION_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_010_batch_10_Spinoff2013`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`。
- **相似/重复题**：#020；需做去重或不同split隔离。

**原 Question：**
````text
Why did Robonaut need human-like dexterity instead of simply mobile-robot obstacle avoidance?
````

**原 Gold Answer：**
````text
It was designed to work alongside astronauts and use existing human-serviceable hardware and tools, which required hands capable of the same task-oriented manipulation as people.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_010_batch_10_Spinoff2013:p0075:e003` · 页 `75` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_010_batch_10_Spinoff2013/pages/page_0075/output_json/page_0075.json`
   - bbox：`[94, 378, 550, 576]`

````text
In collaboration with the Defense Advanced Research Projects Agency (DARPA), Johnson aimed to build Robonaut 1—a humanoid robot complete with dexterous manipulation, or a capability to use its hands—to work alongside its human counterparts. In order to lend a help- ing hand, Robonaut needed to be able to use the same tools as astronauts to service space flight hardware, which was designed for human servicing.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据明确说明Robonaut以与宇航员并肩工作、使用宇航员现成工具维护为人设计的航天硬件为目标，所以必须具备灵巧手。候选答案准确；“instead of obstacle avoidance”是并未被引文直接对比的对照项，建议简化问题。与#020高度重复，建议仅留证据更充分的一条或用于单/多证据对照实验而不是同一评价集合。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #046 行号。**目标操作**：`TIGHTEN_QUESTION_AND_DEDUPLICATE`。
2. 无证据支持“而不是避障”这一明确对照；与 #020 去重。
3. **候选新 `question`**（需核验后应用）：
````text
Why did Robonaut require dexterous hands compatible with astronauts’ tools and human-serviceable hardware?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #047 · `manual_qa_review_v1::047`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`REMOVE_UNCITED_DISCRETE_SAMPLING_OR_ADD_EVIDENCE`。
- **文档与节点状态**：`real_011_batch_11_Spinoff2012`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`, `gold_evidence_draft`。
- **相似/重复题**：#021；需做去重或不同split隔离。

**原 Question：**
````text
Why is rotorcraft pressure measurement both technically harder and more expensive than conventional wind-tunnel sensing?
````

**原 Gold Answer：**
````text
Rotor blades flex and experience rapid pressure changes; conventional sensors sample only discrete locations and cannot work on moving rotors, while dynamic alternatives can raise costs fivefold.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_011_batch_11_Spinoff2012:p0056:e002` · 页 `56` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_011_batch_11_Spinoff2012/pages/page_0056/output_json/page_0056.json`
   - bbox：`[92, 202, 549, 354]`

````text
The rotors of certain helicopters can spin at speeds as high as 500 revolutions per minute. As the blades slice through the air, they flex, moving into the wind and back out, experiencing pressure changes on the order of thousands of times a second and even higher.
````

2. `real_011_batch_11_Spinoff2012:p0056:e004` · 页 `56` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_011_batch_11_Spinoff2012/pages/page_0056/output_json/page_0056.json`
   - bbox：`[93, 577, 550, 800]`

````text
“Typical static pressure instrumentation can’t handle that,” explains Neal Watkins, electronics engineer in Langley Research Center’s Advanced Sensing and Optical Measurement Branch. “There are dynamic pressure taps, but your costs go up by a factor of five to ten if you use those. In addition, recovery of the pressure tap readings is accomplished through slip rings, which allow only a limited amount of sensors and can require significant maintenance throughout a typical rotor test.”
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一段指出桨叶高速转动、弯曲并经历高频压力变化；第二段指出静态传感器不胜任、动态压力孔成本增加5–10倍且滑环带来通道和维护限制。候选答案核心因果正确。小缺口：“只能在离散点采样”出现在相邻的#021证据节点而非本题给出的两段，建议去掉此短语或补入第三节点。与#021重复较多。 【建议标签】weak_evidence, duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #047 行号。**目标操作**：`REMOVE_UNCITED_DISCRETE_SAMPLING_OR_ADD_EVIDENCE`。
2. 原答案的 discrete locations 事实在 #021 引文而非本题两段；如需保留可加第三证据。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Spinning and flexing rotor blades create fast-changing pressure measurements that static wind-tunnel sensors cannot handle; dynamic taps can cost roughly 5–10 times as much and require additional slip-ring channels and maintenance.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #048 · `manual_qa_review_v1::048`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`KEEP_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_011_batch_11_Spinoff2012`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#022；需做去重或不同split隔离。

**原 Question：**
````text
What technical pipeline allowed 1-megapixel Mars-rover cameras to yield 96-megapixel panoramic images later used commercially?
````

**原 Gold Answer：**
````text
A NASA automated tripod captured multiple smaller shots and photo-processing software stitched them into a high-resolution composite, a technology later brought to market with Carnegie Mellon.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_011_batch_11_Spinoff2012:p0088:e003` · 页 `88` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_011_batch_11_Spinoff2012/pages/page_0088/output_json/page_0088.json`
   - bbox：`[93, 380, 549, 528]`

````text
While the rovers each took a mere 1 megapixel camera for the journey, the pictures they have become famous for measure up to 96 megapixels in size. This was made pos- sible by a NASA-built automated tripod, which with the help of photo processing software seamlessly integrates a series of smaller shots into one large image.
````

2. `real_011_batch_11_Spinoff2012:p0088:e006` · 页 `88` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_011_batch_11_Spinoff2012/pages/page_0088/output_json/page_0088.json`
   - bbox：`[93, 674, 550, 849]`

````text
Through multiple commercial partnerships, NASA and Carnegie Mellon University first brought the supersized digital picture technology to the market as the GigaPan robotic platform ( Spinoff 2008) . Soon after it had spun off into consumer applications, the technology's potential caught the eye of Major League Baseball Advanced Media (MLBAM) LP, based in New York City.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】首段覆盖1MP传感器→自动拍摄多张→软件拼成96MP全景，第二段覆盖NASA和Carnegie Mellon合作的GigaPan商业化。技术流程与商业转化都有证据；但“automated tripod”是原文用词，实际应核对是否指自动拍摄支架/云台而非单纯脚架。与#022共享核心技术事实，去重时优先保留本条更完整版本。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #048 行号。**目标操作**：`KEEP_AND_DEDUPLICATE`。
2. 比 #022 多了商业化节点，优先保留。原文“automated tripod”可核查是云台/支架，避免仅将拼接像素说成传感器分辨率。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #049 · `manual_qa_review_v1::049`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`KEEP_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_012_batch_12_Spinoff2011`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。
- **相似/重复题**：#023；需做去重或不同split隔离。

**原 Question：**
````text
How did digital fly-by-wire progress from NASA test flights to commercial-aircraft benefits?
````

**原 Gold Answer：**
````text
After more than 200 DFBW flights, Airbus 320 adopted it in 1987 and Boeing 777 in 1994; replacing heavy mechanical systems improved fuel efficiency or cargo capacity and made flights smoother.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_012_batch_12_Spinoff2011:p0079:e000` · 页 `79` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_012_batch_12_Spinoff2011/pages/page_0079/output_json/page_0079.json`
   - bbox：`[93, 164, 550, 265]`

````text
The DFBW program's final flight occurred on April 2, 1985—the last of more than 200 successful flights that collectively provided the impetus for changing the way aircraft are designed and flown around the world.
````

2. `real_012_batch_12_Spinoff2011:p0079:e003` · 页 `79` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_012_batch_12_Spinoff2011/pages/page_0079/output_json/page_0079.json`
   - bbox：`[93, 461, 550, 779]`

````text
The first commercial airliner to fly with DFBW was the Airbus 320 in 1987, followed by Boeing's 777 in 1994. Today, the technology features in a number of aircraft from both manufacturers. For commercial air- craft, the technology replaces heavy mechanical systems, allowing airlines to benefit from greater fuel efficiency or carry more passengers and cargo. The heightened responsiveness of DFBW-enabled aircraft allows pilots to provide a smoother flight, and the system's redundan- cies help ensure safe operation of the vehicle. Mechanical maintenance needs are also reduced, saving costs and time spent on upkeep and repairs of the mechanical systems and reducing the chance of failures.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】一段提供NASA在1985年前超过200次DFBW试飞，另一段给出A320（1987）、B777（1994）商用节点和省重、节油、载荷、乘坐平顺性收益；完整形成技术迁移链。建议答复中明确“替代机械控制链及冗余设计”，将安全/维护收益与效率收益区分；与#023存在事实重叠但本题更有多证据价值。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #049 行号。**目标操作**：`KEEP_AND_DEDUPLICATE`。
2. 比 #023 有 NASA 试飞与商用过渡两跳，优先保留。核对“1987/1994”对应的事件性质。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #050 · `manual_qa_review_v1::050`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`FIX_ENTITY_ANSWER_AND_RECOVER_TRUNCATION`。
- **文档与节点状态**：`real_012_batch_12_Spinoff2011`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft`。
- **相似/重复题**：#024；需做去重或不同split隔离。

**原 Question：**
````text
What material class offers a solar-device designer simultaneous gains in conductivity, heat transport, and strength at microscopic dimensions?
````

**原 Gold Answer：**
````text
They are about 50,000 times finer than a human hair while combining high electrical and thermal conductivity with exceptional mechanical strength.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_012_batch_12_Spinoff2011:p0150:e003` · 页 `150` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_012_batch_12_Spinoff2011/pages/page_0150/output_json/page_0150.json`
   - bbox：`[93, 474, 550, 646]`

````text
To build upon existing photovoltaic technology, NASA's Glenn Research Center has worked on a variety of innovative designs and materials to incorporate into photovoltaic cells, the building blocks of solar power sys- tems. One of these materials is the carbon nanotube—a tiny structure about 50,000 times finer than the average human hair, with notably high electrical and thermal con-
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT】问题问的是“哪类材料”，但答案只重复“细如发丝、导电导热和强度高”的性质，完全没有给出核心实体“carbon nanotubes”。此外唯一证据在“thermal con-”处截断，无法核验候选答案关于强度的部分。应改为“A carbon nanotube (CNT)”并补完材料性质的正文；与#024重复。 【建议标签】unsupported_answer, weak_evidence, duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #050 行号。**目标操作**：`FIX_ENTITY_ANSWER_AND_RECOVER_TRUNCATION`。
2. 最严重错误是“问材料却答性质”；thermal con- 之后证据被截断，不能不核查就保留强度/导热全部属性；与 #024 去重。
3. **候选新 `question`**（需核验后应用）：
````text
Which nanoscale material is identified for its extremely small diameter and potential conductive properties in solar-device applications?
````
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Carbon nanotubes (CNTs).
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #051 · `manual_qa_review_v1::051`

- **综合判定**：`ACCEPT`；**优先级**：`P1_EVIDENCE_ALIGNMENT`；**修复动作**：`REMOVE_UNSUPPORTED_TELEMETRY_AND_SCOPE_SCALING`。
- **文档与节点状态**：`real_013_batch_13_Spinoff2010`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。

**原 Question：**
````text
How can a physical scale model yield transferable flight-control results rather than merely imitate flight virtually?
````

**原 Gold Answer：**
````text
Its structural scaling matches mass distribution and density as well as geometry, yielding faster but otherwise identical flight-dynamic and aerodynamic responses, while telemetry links it to control computers.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_013_batch_13_Spinoff2010:p0162:e002` · 页 `162` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_013_batch_13_Spinoff2010/pages/page_0162/output_json/page_0162.json`
   - bbox：`[101, 259, 273, 564]`

````text
The unmanned vehicles in the AirSTAR facility are only about 1/20th the size of the transport aircraft they are built to represent.
````

2. `real_013_batch_13_Spinoff2010:p0162:e004` · 页 `162` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_013_batch_13_Spinoff2010/pages/page_0162/output_json/page_0162.json`
   - bbox：`[93, 583, 549, 778]`

````text
a careful structural design that scales the mass distribu- tion and density along with the geometry, these sub-scale flight vehicles provide flight-dynamic and aerodynamic responses that are faster, but otherwise identical, to their full-scale counterparts. This retains relevance to the target application, and allows experiments to be conducted that have more risk and incur larger structural loads than would be feasible on a full-scale transport.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】两段分别提供AirSTAR缩比约1/20及按几何、质量分布和密度缩放后可保留对应气动/动力响应（但变化更快），足以解释物理试验为什么有可迁移性。答案末尾称“telemetry links it to control computers”在本题两段里没有出现，建议删掉或补控制通信节点；不能将“otherwise identical”当作所有实际动态量完全相等。 【建议标签】weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #051 行号。**目标操作**：`REMOVE_UNSUPPORTED_TELEMETRY_AND_SCOPE_SCALING`。
2. 该题两段不支持 telemetry links to control computers；也不要将 otherwise identical 当成各物理量严格相同。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
AirSTAR used a real subscale aircraft whose geometry, mass distribution, and density were scaled to reproduce corresponding aerodynamic and flight-dynamic behavior, though the dynamics occur faster than full scale.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #052 · `manual_qa_review_v1::052`

- **综合判定**：`ACCEPT`；**优先级**：`P1_DEDUP_BEFORE_BENCHMARK`；**修复动作**：`SOFTEN_CLIMATE_CAUSALITY_AND_DEDUPLICATE`。
- **文档与节点状态**：`real_013_batch_13_Spinoff2010`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。
- **相似/重复题**：#026；需做去重或不同split隔离。

**原 Question：**
````text
How did HoneyBeeNet data become evidence for a climate-related shift rather than just an isolated local observation?
````

**原 Gold Answer：**
````text
Its long-term records showed nectar flow arriving about a half-day earlier yearly and about a month earlier since the 1970s, and the timing nearly perfectly matched satellite vegetation green-up data.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_013_batch_13_Spinoff2010:p0202:e000` · 页 `202` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_013_batch_13_Spinoff2010/pages/page_0202/output_json/page_0202.json`
   - bbox：`[93, 164, 551, 339]`

````text
Data from the network, when combined with additional data that reach back to the 1920s, indicate that the timing of spring nectar flows have undergone extraordinary changes. “Each year, the nectar flow comes about a half-day earlier on average,” said Esaias. “In total, since the 1970s, it has moved forward by about month in Maryland.”
````

2. `real_013_batch_13_Spinoff2010:p0202:e001` · 页 `202` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_013_batch_13_Spinoff2010/pages/page_0202/output_json/page_0202.json`
   - bbox：`[93, 338, 551, 485]`

````text
Esaias and Goddard colleague Robert Wolfe recently compared nectar flow data from HoneyBeeNet to satellite data that measures the annual “green up” of vegetation in the spring, one of the first times that scientists have attempted such a comparison. They corresponded nearly perfectly, confirming the usefulness of the citizen-
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一段为花蜜流每年提前约半天、1970年代以来约提前一月的长期趋势，第二段为HoneyBeeNet与卫星春季返青时间数据接近一致的跨来源验证。证据链支持不是孤立观察，但“climate-related shift”属于解释层面，不等于这两节点直接证明单一气候成因。建议答案用“consistent with a broader seasonal shift”而非确定的气候因果；与#026重叠。 【建议标签】duplicate。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #052 行号。**目标操作**：`SOFTEN_CLIMATE_CAUSALITY_AND_DEDUPLICATE`。
2. 不要将“climate-related”表述成明确因果。比 #026 多一条独立对照证据，优先保留。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
HoneyBeeNet records show earlier nectar flow (roughly half a day per year and about one month since the 1970s) and closely match satellite vegetation green-up timing, consistent with a broader seasonal shift.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #053 · `manual_qa_review_v1::053`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`KEEP_WITH_PHYSICAL_CAVEAT`。
- **文档与节点状态**：`real_020_batch_20_spin03`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。

**原 Question：**
````text
Why did the surgical tracking system need both a substantially higher sampling rate and closed-loop compensation, rather than merely following the eye with a conventional camera?
````

**原 Gold Answer：**
````text
Saccadic motion occurs about 100 times per second, whereas conventional video trackers sample only 60–250 times per second and can force a laser shutdown and restart; LADARTracker samples at 4,000 times per second and continuously compensates for movement in a closed loop.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_020_batch_20_spin03:p0012:e002` · 页 `12` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0012/output_json/page_0012.json`
   - bbox：`[195, 510, 513, 847]`

````text
During LASIK surgery, laser pulses must be accurately placed to reshape the cornea. A challenge to this procedure is the patient's con- stant eye movement. A person's eyes make small, involuntary movements known as saccadic movements about 100 times per second. Since the sac- cadic movements will not stop dur- ing LASIK surgery, most excimer laser systems use an eye tracking device that measures the movements and guides the placement of the laser beam.
````

2. `real_020_batch_20_spin03:p0012:e004` · 页 `12` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0012/output_json/page_0012.json`
   - bbox：`[195, 994, 658, 1163]`

````text
type. The most commonly used video tracking systems follow eye movements between 60 to 250 times per sec- ond, meaning that they cannot keep up with saccadic movements. Therefore, when the eye moves too far from the limits set by the eye surgeon, the surgeon must shut down the laser beam and restart the surgery once the laser is properly centered.
````

3. `real_020_batch_20_spin03:p0012:e005` · 页 `12` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0012/output_json/page_0012.json`
   - bbox：`[195, 1164, 658, 1456]`

````text
Sufficient speed is not a problem for Alcon's patent- ed LADARTracker, TM a LADAR eye tracking device that measures eye movements at a rate of 4,000 times per second, 4 times the perceived safety margin. The LADARTracker also employs a closed-loop system, which keeps the device locked on the eye at all times. Eye movement information is continuously relayed to the system, allowing the system to compensate for the movements. Video tracking systems, on the other hand, are open-loop systems that try to follow eye movements rather than compensate for them. LADARVision is cur- rently the only excimer laser device that continually
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】三段明确提供眼跳约100次/秒、一般视频追踪60–250次/秒会跟不上、LADAR每秒4000次且闭环补偿眼球运动，候选答案充分。需要谨慎：眼跳发生频率与眼球运动速度不是同一物理量，不能仅把“100 vs 250”简单比较得出采样不足；应按原文总结常规系统难以追踪快速眼动。重点是高采样与闭环补偿共同避免频繁中断。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #053 行号。**目标操作**：`KEEP_WITH_PHYSICAL_CAVEAT`。
2. 不要把 100 次/秒眼跳与 60–250 Hz 采样做同一维度的性能绝对判定；原文的功能结论是 LADAR 4000 Hz 加闭环补偿减少重定位中断。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #054 · `manual_qa_review_v1::054`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`KEEP_WITH_CAUSAL_CAVEAT`。
- **文档与节点状态**：`real_020_batch_20_spin03`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`reviewer_notes (preserve / optional)`。

**原 Question：**
````text
What evidence suggests that turning pilot-attention biofeedback into an interactive game changed adherence more than the measured clinical outcomes?
````

**原 Gold Answer：**
````text
After forty one-hour sessions, both the game and traditional-biofeedback groups improved on brain-wave and attention-related measures, but the game group had fewer no-shows and no drop-outs, with parents more satisfied and children appearing to enjoy it more.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_020_batch_20_spin03:p0014:e003` · 页 `14` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0014/output_json/page_0014.json`
   - bbox：`[193, 632, 659, 829]`

````text
One of the most progressive physiological methods to spawn from Langley biofeedback research is known as Extended Attention Span Training (EAST). As a modifi- cation of biocybernetic technology used to increase the mental engagement of pilots, EAST transcends conven- tional neurofeedback systems by taking the form of a video game that responds to brain electrical activity and joystick input.
````

2. `real_020_batch_20_spin03:p0015:e004` · 页 `15` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0015/output_json/page_0015.json`
   - bbox：`[85, 798, 551, 1308]`

````text
After forty 1-hour sessions, both groups showed signifi- cant improvements in everyday brain-wave patterns, as well as in tests measuring attention span, impulsiveness, and hyperactivity. The key difference in the outcome, however, was motivation. According to Alan Pope, Ph.D., a psychol- ogist from Langley's Crew/Vehicle Integration Branch and co-inventor of EAST, the video game group experienced fewer no-shows for testing and no drop-outs. Additionally, Pope adds that the parents were more satisfied with the results of the video game training, and the kids seemed to have more fun. He is also quick to note that violent video games are not recommended, but rather that car racing, skateboarding, and other skills-type games are best suited for the interactive technology. By adapting to today's most pop- ular video games, S.M.A.R.T. BrainGames fully preserves high-tech entertainment value, unlike previous biofeedback methods that had a propensity to be too repetitive and simplistic. These training methods typically employed “ go-no-go ” games, in which animation or computer graph- ics would move along a predetermined path, lacking inter- activity or user control over the game itself.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】两段分别描述游戏式脑电反馈EAST设计及40次1小时训练后两组临床/行为指标均改善，但游戏组缺席少且无人退出、家长满意度更高。结论支持“依从性差别比观察到的临床收益差别更突出”。不过文中没提供随机化、样本量或组间显著性检验，不宜提升为已经证实游戏导致更好的治疗效果。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #054 行号。**目标操作**：`KEEP_WITH_CAUSAL_CAVEAT`。
2. 仅可描述缺席/退课差异和所报告的评估指标，不可推断组间治疗效果显著差异或游戏机制因果已证实。

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #055 · `manual_qa_review_v1::055`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`RECOVER_TRUNCATED_ORIGIN_EVIDENCE_OR_TIGHTEN_ANSWER`。
- **文档与节点状态**：`real_020_batch_20_spin03`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`, `gold_evidence_draft`。

**原 Question：**
````text
How did an astronaut-monitoring research system become usable for home chronic-care patients who lacked their own computer or Internet connection?
````

**原 Gold Answer：**
````text
NASA-funded work produced a miniature device for real-time collection and analysis of multiple astronaut physiological signals; the commercial system adapted it to collect readings from common home instruments and securely send them over an ordinary telephone line, so patients needed neither a personal computer nor Internet access.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_020_batch_20_spin03:p0030:e003` · 页 `30` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0030/output_json/page_0030.json`
   - bbox：`[194, 778, 659, 928]`

````text
NASA's Johnson Space Center granted Cybernet Systems Phase I and Phase II Small Business Innovation Research (SBIR) contracts, building upon the company's previous SBIR work on multiple military and Federal Government development projects. The pur- pose of the NASA project was to enable remote physio-
````

2. `real_020_batch_20_spin03:p0031:e000` · 页 `31` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0031/output_json/page_0031.json`
   - bbox：`[85, 193, 550, 539]`

````text
The battery-powered and portable MedStar interface device collects physiological data from off-the-shelf instruments regularly used at home by chronic-disease patients with high blood pressure, diabetes, congestive heart failure, or respiratory conditions. These devices include weight scales, blood pressure cuffs, and glucose monitors. The MedStar device then securely transmits the data over a standard telephone line to the Cybernet Medical collection server, located at a hospital or a dis- ease management company's facility, for retrieval and analysis. The process enables a health care team to imme- diately note changes in a patient's condition and make appropriate action recommendations — resulting in fewer patient interventions and emergency hospitalizations.
````

3. `real_020_batch_20_spin03:p0031:e001` · 页 `31` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0031/output_json/page_0031.json`
   - bbox：`[85, 539, 550, 713]`

````text
Measuring 10 square inches and weighing less than a pound, the patient-friendly MedStar device is small and light and operates on standard AA batteries. Since a patient does not need a personal computer or Internet access to transmit MedStar's collected data, the device can be immediately deployed by disease management organizations regardless of patient demographics.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】后两段充分说明MedStar接入体重秤、血压袖带、血糖仪，并经普通电话线安全传到远程服务器，用户无需电脑或互联网，直接支撑家庭慢病使用方式。第一条NASA项目背景证据被截断在“remote physio-”，不能独立验证候选答案所说最初“实时采集分析多种宇航员信号”。建议补完整原始段，或缩短NASA起源叙述。 【建议标签】weak_evidence。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #055 行号。**目标操作**：`RECOVER_TRUNCATED_ORIGIN_EVIDENCE_OR_TIGHTEN_ANSWER`。
2. 首节点停在 remote physio-，无从证明原答案“实时采集分析多种宇航员生理信号”；要保留详细NASA原始方案必须恢复段落。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
NASA-funded work led to remote physiological-monitoring technology; the commercial MedStar interface gathered readings from home instruments and securely sent them over telephone lines, requiring neither a personal computer nor Internet access.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #056 · `manual_qa_review_v1::056`

- **综合判定**：`ACCEPT`；**优先级**：`P1_SOURCE_VERIFY_BEFORE_RELEASE`；**修复动作**：`SCOPE_VENDOR_PERFORMANCE_CLAIM`。
- **文档与节点状态**：`real_020_batch_20_spin03`；`multi_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。

**原 Question：**
````text
Which two changes allowed a tool designed for prolonged space operations to become a scalable commercial network-operations platform?
````

**原 Gold Answer：**
````text
NASA moved from paper procedures toward electronic management for longer missions and used Timeliner for autonomous ISS functions; its commercial successor retained an English-like, reliable runtime but added interfaces to networked devices, servers, databases, and applications plus distributed execution capable of millions of simultaneous events.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_020_batch_20_spin03:p0076:e003` · 页 `76` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0076/output_json/page_0076.json`
   - bbox：`[194, 568, 659, 966]`

````text
The concept behind the Auspice software spawned from a computer program originally developed in 1981 by Cambridge, Massachusetts-based Draper Laboratory for simulating tasks performed by astronauts aboard the Space Shuttle. At the time, the Space Shuttle Program was dependent upon paper-based procedures for its manned space missions, which typically averaged 2 weeks in duration. As the Shuttle Program progressed, NASA began increasing the length of manned missions in preparation for a more permanent space habitat. Acknowledging the need to relinquish paper-based pro- cedures in favor of an electronic processing format to properly monitor and manage the complexities of these longer missions, NASA realized that Draper's task- simulation software could be applied to its vision of year-round space occupancy.
````

2. `real_020_batch_20_spin03:p0076:e006` · 页 `76` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0076/output_json/page_0076.json`
   - bbox：`[687, 314, 1153, 676]`

````text
Known as Timeliner, the software was used for the first time aboard the ISS in June 2003 to autonomously activate and control experiment payloads in the Microgravity Science Glovebox, a sealed container with built-in gloves that provides a safe, enclosed workspace for investigations conducted in the low- gravity environment. It is further anticipated to auto- mate other ISS procedural tasks typically performed by human operators—or those that execute a control process—including vehicle control, performance of preflight and postflight subsystem checkout, and han- dling of failure detection and recovery. While Draper Laboratory additionally received a patent on Timeliner in 1998, the software was licensed to Auspice in 1997, for exclusive use in commercial markets.
````

3. `real_020_batch_20_spin03:p0076:e007` · 页 `76` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0076/output_json/page_0076.json`
   - bbox：`[687, 677, 1153, 943]`

````text
“ We took the baseline version Timeliner and com- mercialized it as TLX, ” said Rick Berthold, Draper's for- mer ISS Timeliner lead engineer who cofounded Auspice and remains as its chief technical officer. “ The original Tineliner gave us the revolutionary English-like devel- opment language and an ultra-reliable runtime environ- ment. We greatly extended the utility of the language, added interconnectivity to networking devices, servers, databases, and application software, and built a limitless distributed execution environment that could process up to millions of simultaneous events. ”
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】第一段解释长期空间任务推动从纸质程序转向电子流程；第二段证明Timeliner在ISS用于实验载荷的自主控制；第三段详细说明TLX继承类似英语的编程语言和可靠运行环境，并扩展网络/服务器/数据库互联与百万事件级分布式执行。三节点构成清楚的技术演变；“limitless”属于商业宣称，标准答案最好使用“claimed to process up to millions of events”。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #056 行号。**目标操作**：`SCOPE_VENDOR_PERFORMANCE_CLAIM`。
2. 将 limitless / millions events 标为商家描述，不作为独立实测吞吐结论。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Longer space missions drove the transition from paper procedures to electronic automation, including Timeliner on the ISS. TLX retained an English-like language and reliable runtime while adding connections to network devices, servers, databases and applications, with the company describing distributed execution for up to millions of simultaneous events.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #057 · `manual_qa_review_v1::057`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`TIGHTEN_QUESTION_AVOID_NEW_CATEGORY_ASSERTION`。
- **文档与节点状态**：`real_020_batch_20_spin03`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`。

**原 Question：**
````text
What new category of optical imperfection could the wavefront-guided procedure address that earlier treatment had missed?
````

**原 Gold Answer：**
````text
It enabled surgeons to measure and address visual distortions that had previously gone undetected.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_020_batch_20_spin03:p0013:e004` · 页 `13` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0013/output_json/page_0013.json`
   - bbox：`[577, 402, 1041, 685]`

````text
Eye surgeons across the country are utilizing the LADARVision 4000 for LASIK surgery. In October 2002, Alcon's LADARVision system, consisting of the LADARVision 4000 and the LADARWave wavefront measurement device, became the first to gain FDA approval for wavefront-guided LASIK. The result- ing procedure, called CustomCornea, allows surgeons to measure and address visual distortions that previously went undetected. The precision of the tracking device and the small spot beam make the LADARVision system the premier equipment to deliver these precise treatments.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】片段确实说波前测量支持检测并校正此前未被发现的视觉失真，因此候选答案可被直接支持。题干的“new category of optical imperfection”没有给出更具体分类；如期望回答高阶像差等专业术语，单条证据不支持，绝不可由模型自动补充。建议问题直接问CustomCornea相对早期LASIK扩展了什么类型的视觉失真检测/处理能力。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #057 行号。**目标操作**：`TIGHTEN_QUESTION_AVOID_NEW_CATEGORY_ASSERTION`。
2. 只确认“previously undetected visual distortions”，没给 higher-order aberrations 等术语；不要自动补新的类别。
3. **候选新 `question`**（需核验后应用）：
````text
What additional visual distortions could the CustomCornea wavefront-guided LASIK approach measure and address?
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #058 · `manual_qa_review_v1::058`

- **综合判定**：`ACCEPT`；**优先级**：`P2_OPTIONAL_CLEANUP`；**修复动作**：`OPTIONAL_ANSWER_PRECISION`。
- **文档与节点状态**：`real_020_batch_20_spin03`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`gold_answer_draft`。

**原 Question：**
````text
In the interactive training feedback loop, which two mental states governed the simulated vehicle's progress and control?
````

**原 Gold Answer：**
````text
Focus acted as the accelerator and calmness as the steering; wandering focus caused the vehicle to lose ground and fail to qualify.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_020_batch_20_spin03:p0015:e000` · 页 `15` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0015/output_json/page_0015.json`
   - bbox：`[84, 192, 463, 605]`

````text
For example, if an individual is engaging in a race car game in which the goal is to post a fast time to qualify for the next race, it is important for him or her to maintain both speed and control. As the user improves focus, the S.M.A.R.T. BrainGames system will allow for faster speed and easier steering; if the user's focus wanders, the race car will lose ground and not qualify. In essence, the brain acts as the “ accelerator, ” and the calmness acts as the “ steering, ” notes CyberLearning Technology. In the case of ADHD, where relentless distractions and/or impulsive behav- ior take over, the biofeedback technology behind S.M.A.R.T. BrainGames has displayed great results in helping those with the disorder to concentrate and self-regulate.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：ACCEPT】证据明确把大脑专注类比为加速器、平静程度类比为方向盘：专注提高时加速更快、操控更容易，注意力涣散时赛车落后并可能无法晋级。候选答案整体正确。更精确的英文可以写成“focus controls acceleration and calmness supports steering”，避免让人误解系统真的检测了两个完全独立且已定义量纲的状态变量。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #058 行号。**目标操作**：`OPTIONAL_ANSWER_PRECISION`。
2. 原文是类比，不是严格两维传感量的科学定义；精简后避免误解。
4. **候选新 `gold_answer_draft`**（需核验后应用）：
````text
Focus functioned like the accelerator, improving speed, while calmness functioned like steering control; losing focus made it harder for the simulated car to maintain progress.
````

**完成门槛**：
保持题目与答案子句都能被本条所选证据（或经核验新证据）完整支撑；若修改证据数量同步调整 single/multi 类型；若存在重复问题则确认评测数据隔离；无论综合 ACCEPT/REJECT，最终 canonical node ID 均须实查验证。

---

### #059 · `legacy_qa_review_v1::001`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CERNCourier2022NovDec-digitaledition`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about CERNCourier2022NovDec-digitaledition? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
AGNs are galaxies in which the super- massive black hole at their centre is accre- ting matter, thereby producing violent jets responsible for the observed emissions. While our galaxy has a supermassive black hole at its centre, it is currently not accreting matter and therefore the nucleus of the Milky Way is not active. Strong films of past activity were, however, discovered using the Fermi –LAT satellite in 2019. In particular, the data showed two giant masses, the merger and the starburst (shown as the Fermi galaxies - extending from the galactic centre and covering almost-half of the sky (see Image). The exact origin of the giant plasma lobes remains to be understood. However, their position and bipolar nature point towards an origin in the Milky Way's centre several million years ago, likely during a period of high activity in the galactic nucleus.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CERNCourier2022NovDec-digitaledition_page_0006_HY_021` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_1/hybrid/shard_1/CERNCourier2022NovDec-digitaledition/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_035`
   - bbox：`[[851.0, 287.0, 1044.0, 572.0]]`

````text
AGNs are galaxies in which the super- massive black hole at their centre is accre- ting matter, thereby producing violent jets responsible for the observed emissions. While our galaxy has a supermassive black hole at its centre, it is currently not accreting matter and therefore the nucleus of the Milky Way is not active. Strong films of past activity were, however, discovered using the Fermi –LAT satellite in 2019. In particular, the data showed two giant masses, the merger and the starburst (shown as the Fermi galaxies - extending from the galactic centre and covering almost-half of the sky (see Image). The exact origin of the giant plasma lobes remains to be understood. However, their position and bipolar nature point towards an origin in the Milky Way's centre several million years ago, likely during a period of high activity in the galactic nucleus.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“AGN的中央黑洞吸积与喷流，以及银河系核当前不活跃”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么存在中心超大质量黑洞并不意味着银河系核目前属于活跃星系核？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #059 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：解释银河系中心当前缺少黑洞吸积为何不属于活跃星系核，并区分观测到的历史喷流迹象与尚未确定的起源
3. **具体重写目标**：解释银河系中心当前缺少黑洞吸积为何不属于活跃星系核，并区分观测到的历史喷流迹象与尚未确定的起源。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #060 · `legacy_qa_review_v1::002`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CERNCourier2025JanFeb-digitaledition`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about CERNCourier2025JanFeb-digitaledition? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
Central to this effort is the integration of CERN's federated-learning platform, CAFEIN. A decentralised approach to training machine-learning algorithms without exchanging data, it was initi- ated thanks to seed funding from CERN's knowledge transfer budget for the ben- efit of medical applications. In CAFEIN workshops on risk diagnosis, treatment and prevention strategies for stroke vic- tims, ultimately saving countless lives. A main topic of the kickoff meeting was the development of the "U-platform" – a federated data ecosystem co-designed by Siemens Healthineers and CERN. Based CAFEIN, the infrastructure will enable the secure and privacy preserving training of advanced AI algorithms for personalised stroke diagnostics, risk prediction and treatment decisions without sharing sen- sitive patient data between institutions. Building on CERN's expertise, including using deep learning and AI techniques to brain pathologies under the EU TRUST- roike project, the CAFEIN team is poised to handle the increasing complexity and scale of data sets required by UMBRELLA.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CERNCourier2025JanFeb-digitaledition_page_0017_HY_006` · 页 `page_0017` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_1/CERNCourier2025JanFeb-digitaledition/page_0017/evidence_nodes.jsonl`
   - 旧版原子节点：`A_011, A_012`
   - bbox：`[[338.0, 418.0, 525.0, 756.0], [532.0, 352.0, 718.0, 365.0]]`

````text
Central to this effort is the integration of CERN's federated-learning platform, CAFEIN. A decentralised approach to training machine-learning algorithms without exchanging data, it was initi- ated thanks to seed funding from CERN's knowledge transfer budget for the ben- efit of medical applications. In CAFEIN workshops on risk diagnosis, treatment and prevention strategies for stroke vic- tims, ultimately saving countless lives. A main topic of the kickoff meeting was the development of the "U-platform" – a federated data ecosystem co-designed by Siemens Healthineers and CERN. Based CAFEIN, the infrastructure will enable the secure and privacy preserving training of advanced AI algorithms for personalised stroke diagnostics, risk prediction and treatment decisions without sharing sen- sitive patient data between institutions. Building on CERN's expertise, including using deep learning and AI techniques to brain pathologies under the EU TRUST- roike project, the CAFEIN team is poised to handle the increasing complexity and scale of data sets required by UMBRELLA.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“CERN的CAFEIN联邦学习平台及医疗应用”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】CAFEIN如何在不交换原始数据的情况下支持医疗领域的协作式模型训练？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #060 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：解释 CAFEIN 联邦学习如何不跨机构交换敏感患者数据而支持卒中 AI 研究
3. **具体重写目标**：解释 CAFEIN 联邦学习如何不跨机构交换敏感患者数据而支持卒中 AI 研究。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #061 · `legacy_qa_review_v1::003`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CERNCourier2026MayJun-digitaledition`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about CERNCourier2026MayJun-digitaledition? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
The final run also gave a sense of the scale of modern physics data sets. sPHENIX alone recorded more than 200 petabytes of raw data, more than every previous RHIC dataset combined, including 40 bil- lion gold–ion collision events. Analysis of RHIC data will continue for at least another decade. Much of RHIC's infra- structure will then live on in the EC, including its ion sources, pre-accelera- tor chain and one of its superconducting storage rings. A new electron ring will share the tunnel, crossing the ion beam at points where polarised electrons and ions will collide. The EC will enable precision measurements that reveal how quarks and gluons are organised within protons or atomic nuclei, helping physicists to understand how mass, spin, and nuclear structure emerge from the strong force.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CERNCourier2026MayJun-digitaledition_page_0006_HY_017` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_0/CERNCourier2026MayJun-digitaledition/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_025`
   - bbox：`[[554.0, 721.0, 749.0, 993.0]]`

````text
The final run also gave a sense of the scale of modern physics data sets. sPHENIX alone recorded more than 200 petabytes of raw data, more than every previous RHIC dataset combined, including 40 bil- lion gold–ion collision events. Analysis of RHIC data will continue for at least another decade. Much of RHIC's infra- structure will then live on in the EC, including its ion sources, pre-accelera- tor chain and one of its superconducting storage rings. A new electron ring will share the tunnel, crossing the ion beam at points where polarised electrons and ions will collide. The EC will enable precision measurements that reveal how quarks and gluons are organised within protons or atomic nuclei, helping physicists to understand how mass, spin, and nuclear structure emerge from the strong force.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“sPHENIX最终运行记录的原始数据与金离子碰撞事件规模”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】sPHENIX在RHIC最后一轮运行中收集了多少原始数据和金离子碰撞事件？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #061 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：提问 sPHENIX 最后运行记录的原始数据规模和金离子碰撞事件量，并明确单位
3. **具体重写目标**：提问 sPHENIX 最后运行记录的原始数据规模和金离子碰撞事件量，并明确单位。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #062 · `legacy_qa_review_v1::004`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`EXCLUDE_FROM_FACTUAL_QA`。
- **文档与节点状态**：`CLADmag_2025_H2`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`review_status`, `answer_status (if present)`, `benchmark_membership (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about CLADmag_2025_H2? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
50 Flights of fancy An olive oil museum with a giant bull's horn and a fantastical hotel: Two very different projects from Philippe Starck show his love of the surreal 58 The era of the stadium district As Foster + Partners share new details of their Manchester United stadium district, we look at some more projects reinventing sports architecture 66 The art of hospitality India Mahdavi has brought her hotel and bar design experience to a colourful new art museum in Norway with a mission to welcome everyone
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CLADmag_2025_H2_page_0006_HY_006` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_5/hybrid/shard_1/CLADmag_2025_H2/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_012`
   - bbox：`[[797.0, 1046.0, 1137.0, 1473.0]]`

````text
50 Flights of fancy An olive oil museum with a giant bull's horn and a fantastical hotel: Two very different projects from Philippe Starck show his love of the surreal 58 The era of the stadium district As Foster + Partners share new details of their Manchester United stadium district, we look at some more projects reinventing sports architecture 66 The art of hospitality India Mahdavi has brought her hotel and bar design experience to a colourful new art museum in Norway with a mission to welcome everyone
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“杂志目录罗列Starck、球场地区和酒店设计专题”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。材料属于目录、活动安排、概述或标题型文字，不保证存在单一可验证的机制或结论；应先判断该节点是否适合生成问答。 【建议重写题目】目录第50页与第58页分别介绍哪些建筑或设计主题？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #062 行号。**目标操作**：`EXCLUDE_FROM_FACTUAL_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：目录页仅含专题标题、页码与简介；不适合生成因果技术问答，应排除或转元数据检索
3. **具体重写目标**：目录页仅含专题标题、页码与简介；不适合生成因果技术问答，应排除或转元数据检索。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：此来源是目录/日程/作者/索引类，不足以作为因果知识型 gold。默认 `EXCLUDE_OR_PARK`；只有明确改造成表格/元数据检索任务且 schema、评价指标允许才考虑保留。

**完成门槛**：
该条退出事实型 Gold QA（留审计记录）；若改为元数据任务需有新的明确任务类型、验证过的表格/目录源及可评分答案。

---

### #063 · `legacy_qa_review_v1::005`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CyberPhysicalModelingChapter4`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about CyberPhysicalModelingChapter4? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
• Causal modeling describes cause-and- effect relationships between variables. • Clear separation between INPUTs and OUTPUTs • Unidirectional Connections between Blocks • Blocks represent a function
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CyberPhysicalModelingChapter4_page_0006_HY_001` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_5/hybrid/shard_0/CyberPhysicalModelingChapter4/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_003`
   - bbox：`[[67.0, 185.0, 625.0, 466.0]]`

````text
• Causal modeling describes cause-and- effect relationships between variables. • Clear separation between INPUTs and OUTPUTs • Unidirectional Connections between Blocks • Blocks represent a function
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“因果建模的输入输出及单向连接结构”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】因果模块建模对模块输入输出及连接方向提出什么要求？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #063 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：根据材料描述因果模型中变量输入输出及单向连接关系，避免假定不存在的推理机制
3. **具体重写目标**：根据材料描述因果模型中变量输入输出及单向连接关系，避免假定不存在的推理机制。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #064 · `legacy_qa_review_v1::006`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`DLRmagazine_176_EN`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about DLRmagazine_176_EN? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
This ship was the target of a combined jamming and spoofing attack. In a jamming attack, global navigation satellite system (GNSS) signals are submerged by an interfering signal. This prevents a standard navigation receiver from detecting them, meaning it is unable to determine a position. Tech- nically, such interference is relatively simple to carry out. Since navigation satellites are over 20,000 kilometres from Earth, GNSS signals are quite weak. As a result, small, portable jammers can easily block these signals within a radius of a few kilometres. Although the trade and use of such devices are prohibited, they are regularly seized by police and customs officials. For large-scale disruptions, however, more powerful equipment is required, which is not easily available commercially and is likely employed by state players. Spoofing, on the other hand, involves transmitting deceptive signals that appear to a receiver to be genuine satellite signals but actually generate false position and time information. This type of attack is much more technically demanding.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `DLRmagazine_176_EN_page_0009_HY_004` · 页 `page_0009` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_6/hybrid/shard_0/DLRmagazine_176_EN/page_0009/evidence_nodes.jsonl`
   - 旧版原子节点：`D010`
   - bbox：`[[923, 549, 1163, 853]]`

````text
This ship was the target of a combined jamming and spoofing attack. In a jamming attack, global navigation satellite system (GNSS) signals are submerged by an interfering signal. This prevents a standard navigation receiver from detecting them, meaning it is unable to determine a position. Tech- nically, such interference is relatively simple to carry out. Since navigation satellites are over 20,000 kilometres from Earth, GNSS signals are quite weak. As a result, small, portable jammers can easily block these signals within a radius of a few kilometres. Although the trade and use of such devices are prohibited, they are regularly seized by police and customs officials. For large-scale disruptions, however, more powerful equipment is required, which is not easily available commercially and is likely employed by state players. Spoofing, on the other hand, involves transmitting deceptive signals that appear to a receiver to be genuine satellite signals but actually generate false position and time information. This type of attack is much more technically demanding.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“GNSS干扰中的jamming与spoofing原理”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】GNSS jamming为何会使常规接收机无法确定位置？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #064 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：区分 GNSS jamming 与 spoofing 如何分别干扰真实卫星信号和引入欺骗信号
3. **具体重写目标**：区分 GNSS jamming 与 spoofing 如何分别干扰真实卫星信号和引入欺骗信号。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #065 · `legacy_qa_review_v1::007`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`EXCLUDE_FROM_FACTUAL_QA`。
- **文档与节点状态**：`ESS203_day_01`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`review_status`, `answer_status (if present)`, `benchmark_membership (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about ESS203_day_01? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
Art meets Science We will watch an Extreme Ice Survey video Your Lab groups will discuss the questions in the Lab 1 handout No formal writing assignment this week.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `ESS203_day_01_slide_0020_HY_004` · 页 `slide_0020` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_3/hybrid/shard_0/ESS203_day_01/slide_0020/evidence_nodes.jsonl`
   - 旧版原子节点：`A_004`
   - bbox：`[[93, 560, 1519, 1028]]`

````text
Art meets Science We will watch an Extreme Ice Survey video Your Lab groups will discuss the questions in the Lab 1 handout No formal writing assignment this week.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“课程安排、视频与实验小组讨论”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。材料属于目录、活动安排、概述或标题型文字，不保证存在单一可验证的机制或结论；应先判断该节点是否适合生成问答。 【建议重写题目】ESS203第一天实验前要求学生观看什么视频，以及本周是否有正式写作作业？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #065 行号。**目标操作**：`EXCLUDE_FROM_FACTUAL_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：课程安排页只含观看视频和实验组讨论通知；不适合科学事实检索，应排除
3. **具体重写目标**：课程安排页只含观看视频和实验组讨论通知；不适合科学事实检索，应排除。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：此来源是目录/日程/作者/索引类，不足以作为因果知识型 gold。默认 `EXCLUDE_OR_PARK`；只有明确改造成表格/元数据检索任务且 schema、评价指标允许才考虑保留。

**完成门槛**：
该条退出事实型 Gold QA（留审计记录）；若改为元数据任务需有新的明确任务类型、验证过的表格/目录源及可评分答案。

---

### #066 · `legacy_qa_review_v1::008`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`IDU-41f597b3-c201-4fa7-8cac-466610c36a27`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about IDU-41f597b3-c201-4fa7-8cac-466610c36a27? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
In this paper, we make the case that growth regressions can provide policy-relevant insights into a country's growth performance, even if they only provide descriptive correlations. Such correlations tell what policy-relevant changes in key macroeconomic variables countries typically experience in their growth process. This allows for a quantitative assessment of how special or representative the policy mix of a country's growth performance is. For example, if typical growth correlates can explain a country's growth performance well, this suggests that key macroeconomic variables move in line with the experience of other growing economies. Even in this case, the policy mix of this country may still be unique (see the Ethiopia case study in Moller and Wacker, 2017) . Conversely, if typical growth correlates cannot explain a country's performance well, this can be insightful in its own way. Can we learn something new for growth theory from this country? Or has the country just had “ good luck ” ? Obtaining quantitative assessments of successful policy mixes is particularly useful today as growth policies may face trade-offs with climate goals (Haberl et al., 2020; Wollburg et al., 2023) .
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `IDU-41f597b3-c201-4fa7-8cac-466610c36a27_page_0004_HY_004` · 页 `page_0004` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_6/hybrid/shard_0/IDU-41f597b3-c201-4fa7-8cac-466610c36a27/page_0004/evidence_nodes.jsonl`
   - 旧版原子节点：`A_005`
   - bbox：`[[184.0, 738.0, 913.0, 1025.0]]`

````text
In this paper, we make the case that growth regressions can provide policy-relevant insights into a country's growth performance, even if they only provide descriptive correlations. Such correlations tell what policy-relevant changes in key macroeconomic variables countries typically experience in their growth process. This allows for a quantitative assessment of how special or representative the policy mix of a country's growth performance is. For example, if typical growth correlates can explain a country's growth performance well, this suggests that key macroeconomic variables move in line with the experience of other growing economies. Even in this case, the policy mix of this country may still be unique (see the Ethiopia case study in Moller and Wacker, 2017) . Conversely, if typical growth correlates cannot explain a country's performance well, this can be insightful in its own way. Can we learn something new for growth theory from this country? Or has the country just had “ good luck ” ? Obtaining quantitative assessments of successful policy mixes is particularly useful today as growth policies may face trade-offs with climate goals (Haberl et al., 2020; Wollburg et al., 2023) .
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“增长回归可提供政策关联而非因果结论”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么增长回归即便只提供描述性相关，也可能对政策分析有帮助？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #066 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：比较增长回归的政策相关性分析与因果归因之间的推断边界
3. **具体重写目标**：比较增长回归的政策相关性分析与因果归因之间的推断边界。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #067 · `legacy_qa_review_v1::009`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`Luminous Garden Agnes Northrop and the Women of Tiffany Studios`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about Luminous Garden Agnes Northrop and the Women of Tiffany Studios? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
Cochran's substantial fortune gave her the resources to build a grand house, which she named Linden Hall after the linden trees that lined the drive on the property (fig. 7 ). She did not follow the example of her economic peers in the Pittsburgh area who were constructing country homes just outside the city. Rather, she followed in the footsteps of her father-in-law, who believed pas- ionately in living in the place where he grew up and from where he derived his wealth. James Cochran had not only owned and operated hundreds of coke ovens in the area, but he had also owned the Dawson Cemetery, founded the local bank, and built Dawson's main bridge. Sarah furthered those principles of local com- mitment through extensive philanthropy to Dawson and the surrounding areas.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `Luminous Garden Agnes Northrop and the Women of Tiffany Studios_page_0014_HY_003` · 页 `page_0014` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_3/hybrid/shard_1/Luminous Garden Agnes Northrop and the Women of Tiffany Studios/page_0014/evidence_nodes.jsonl`
   - 旧版原子节点：`A_007`
   - bbox：`[[266.0, 828.0, 829.0, 1038.0]]`

````text
Cochran's substantial fortune gave her the resources to build a grand house, which she named Linden Hall after the linden trees that lined the drive on the property (fig. 7 ). She did not follow the example of her economic peers in the Pittsburgh area who were constructing country homes just outside the city. Rather, she followed in the footsteps of her father-in-law, who believed pas- ionately in living in the place where he grew up and from where he derived his wealth. James Cochran had not only owned and operated hundreds of coke ovens in the area, but he had also owned the Dawson Cemetery, founded the local bank, and built Dawson's main bridge. Sarah furthered those principles of local com- mitment through extensive philanthropy to Dawson and the surrounding areas.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“Cochran财力及Linden Hall宅邸的选址”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】Cochran为什么没有像同地区富裕阶层一样在城郊建造乡间住宅？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #067 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：解释 Sarah Cochran 的财力/家庭背景与 Linden Hall 选址建设之间的具体联系
3. **具体重写目标**：解释 Sarah Cochran 的财力/家庭背景与 Linden Hall 选址建设之间的具体联系。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #068 · `legacy_qa_review_v1::010`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`ML1_11_Reinforcement_Learning_1`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about ML1_11_Reinforcement_Learning_1? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
■ Learning process is active instead of passive – No fixed dataset, data/experience is collected by interacting with the environment. ■ No supervision, just a reward signal ■ Interactions are often sequential – Future decisions may depend on previous ones. ■ We can learn optimal behavior without examples of optimal behavior.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `ML1_11_Reinforcement_Learning_1_page_0006_HY_004` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_5/hybrid/shard_1/ML1_11_Reinforcement_Learning_1/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_006`
   - bbox：`[[109.0, 453.0, 1506.0, 763.0]]`

````text
■ Learning process is active instead of passive – No fixed dataset, data/experience is collected by interacting with the environment. ■ No supervision, just a reward signal ■ Interactions are often sequential – Future decisions may depend on previous ones. ■ We can learn optimal behavior without examples of optimal behavior.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“强化学习通过与环境交互及奖励信号学习”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】强化学习与固定数据集上的监督学习在数据获取和反馈信号上有何区别？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #068 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：比较强化学习主动收集交互数据和从奖励信号学习，与固定数据集的差异
3. **具体重写目标**：比较强化学习主动收集交互数据和从奖励信号学习，与固定数据集的差异。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #069 · `legacy_qa_review_v1::011`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`arxiv_1508_02357`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about arxiv_1508_02357? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
Triggers generated by matched filtering the data against the template bank are subject to a chi-squared test that determines if the time-frequency distribution of power in the data is consistent with the expected power in the matching template waveform [16] . To construct this test, the template is split into $p$ frequency bins. These bins are constructed so that each contributes an equal amount of power to the total matched-filter SNR. The matched-filter SNR, $\rho_i$ , is constructed for each of these $p$ bins. For a real signal, $\rho_i$ should contain $1/p$ of the total power. The $\chi^2$ statistic compares the expected to the measured power in each bin according to $$\chi ^ { 2 } = p \sum _ { i = 1 } ^ { p } \left[ \left( \frac { \rho _ { c o s } ^ { 2 } } { p } - \rho _ { c o s , i } ^ { 2 } \right) ^ { 2 } + \left( \frac { \rho _ { s i n } ^ { 2 } } { p } - \rho _ { s i n , i } ^ { 2 } \right) ^ { 2 } \right] , \quad( 5 )$$ where $\rho^2_{\rm cos}$ and $\rho^2_{\rm sin}$ are the SNRs of the two orthogonal phases of the matched filter. Lower-mass binary systems, such as binary neutron stars, lose energy to gravitational waves more slowly than higher-mass systems. Consequently, the waveforms of lower mass systems are longer, having more gravitational-wave cycles in the sensitive band of the detector. The PyCBC pipeline allows the number of bins to be specified as a function of the intrinsic parameters of the template. This allows the search to use more bins in the chi-squared test for longer templates, making the test more effective. In previous analyses, the chi-squared test was the most computationally costly part of the pipeline [18] . The PyCBC pipeline uses a more efficient algorithm for computing the chi-squared statistic, which vastly reduces the computational cost. Details of the chi-squared test are given in Section 3.4 .
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `arxiv_1508_02357_page_0006_HY_002` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_1/arxiv_1508_02357/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_004, A_005, A_006`
   - bbox：`[[140.0, 307.0, 1048.0, 565.0], [338.0, 581.0, 1044.0, 661.0], [140.0, 678.0, 1048.0, 1033.0]]`

````text
Triggers generated by matched filtering the data against the template bank are subject to a chi-squared test that determines if the time-frequency distribution of power in the data is consistent with the expected power in the matching template waveform [16] . To construct this test, the template is split into $p$ frequency bins. These bins are constructed so that each contributes an equal amount of power to the total matched-filter SNR. The matched-filter SNR, $\rho_i$ , is constructed for each of these $p$ bins. For a real signal, $\rho_i$ should contain $1/p$ of the total power. The $\chi^2$ statistic compares the expected to the measured power in each bin according to $$\chi ^ { 2 } = p \sum _ { i = 1 } ^ { p } \left[ \left( \frac { \rho _ { c o s } ^ { 2 } } { p } - \rho _ { c o s , i } ^ { 2 } \right) ^ { 2 } + \left( \frac { \rho _ { s i n } ^ { 2 } } { p } - \rho _ { s i n , i } ^ { 2 } \right) ^ { 2 } \right] , \quad( 5 )$$ where $\rho^2_{\rm cos}$ and $\rho^2_{\rm sin}$ are the SNRs of the two orthogonal phases of the matched filter. Lower-mass binary systems, such as binary neutron stars, lose energy to gravitational waves more slowly than higher-mass systems. Consequently, the waveforms of lower mass systems are longer, having more gravitational-wave cycles in the sensitive band of the detector. The PyCBC pipeline allows the number of bins to be specified as a function of the intrinsic parameters of the template. This allows the search to use more bins in the chi-squared test for longer templates, making the test more effective. In previous analyses, the chi-squared test was the most computationally costly part of the pipeline [18] . The PyCBC pipeline uses a more efficient algorithm for computing the chi-squared statistic, which vastly reduces the computational cost. Details of the chi-squared test are given in Section 3.4 .
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“匹配滤波后的χ²检验与频率分箱”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】引力波匹配滤波检索为什么将模板拆成若干等预期信噪比分箱进行χ²检验？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #069 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：说明匹配滤波触发后 χ² 检验如何用于辨别信号与噪声；必要时补公式上下文
3. **具体重写目标**：说明匹配滤波触发后 χ² 检验如何用于辨别信号与噪声；必要时补公式上下文。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #070 · `legacy_qa_review_v1::012`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`arxiv_1510_04615`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about arxiv_1510_04615? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
In Figure 1 and Table B3 we present the dependence of the merger rate density on the calculational method (method I, II, and III). For this exercise we have used one specific population synthesis model, so as to highlight the differences in our merger rate density calculations. In methods II and III we employ the evolutionary model V2 with low metallicity enrichment; this model utilizes re- stricted CE survival (see Sec. 3 ). In method I we use the same evolutionary model V2, but the metallicity evo- lution treatment is oversimplified. Additionally, in this case no merger redshift information is available, so only the intrinsic total merger masses are used. Obviously, if we assume — as we have — a constant comoving density of Milky Way-like galaxies (see eq. 1 ), we can draw from a random distribution of redshifts. However this modifica- tion is not applied to our calculations, as our intent is to emphasize the differences between the methods that use (or do not use) redshift information about the merg- ers. We find strikingly large differences between method I and the other two methods of merger rate density calcu- lation. For comparison we also include the expected ad- vanced LIGO/Virgo upper limits (see Sec. 4.2 ). We note that this curve represents the upper limits resulting from non-detection. When comparing these limits to the pre- dicted rates, there are two relevant points of comparison: the overall rate, and the mass distribution. Places where the predictions overlap significantly with the upper limit curve indicate that the models predict detections. In these cases, the predicted event rate of BH-BH mergers across all mass bins would be inconsistent with an absence of de- tections in advanced LIGO (as represented by the upper limit curve). In addition, by comparing the shape of the upper limit curve to the shape of the predictions, we are provided with a visual indication of how the mass selec- tion effects of the instruments impacts the predicted mass distributions of sources.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `arxiv_1510_04615_page_0006_HY_007` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_1/hybrid/shard_1/arxiv_1510_04615/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_010, A_011`
   - bbox：`[[89.0, 1365.0, 603.0, 1500.0], [644.0, 98.0, 1159.0, 765.0]]`

````text
In Figure 1 and Table B3 we present the dependence of the merger rate density on the calculational method (method I, II, and III). For this exercise we have used one specific population synthesis model, so as to highlight the differences in our merger rate density calculations. In methods II and III we employ the evolutionary model V2 with low metallicity enrichment; this model utilizes re- stricted CE survival (see Sec. 3 ). In method I we use the same evolutionary model V2, but the metallicity evo- lution treatment is oversimplified. Additionally, in this case no merger redshift information is available, so only the intrinsic total merger masses are used. Obviously, if we assume — as we have — a constant comoving density of Milky Way-like galaxies (see eq. 1 ), we can draw from a random distribution of redshifts. However this modifica- tion is not applied to our calculations, as our intent is to emphasize the differences between the methods that use (or do not use) redshift information about the merg- ers. We find strikingly large differences between method I and the other two methods of merger rate density calcu- lation. For comparison we also include the expected ad- vanced LIGO/Virgo upper limits (see Sec. 4.2 ). We note that this curve represents the upper limits resulting from non-detection. When comparing these limits to the pre- dicted rates, there are two relevant points of comparison: the overall rate, and the mass distribution. Places where the predictions overlap significantly with the upper limit curve indicate that the models predict detections. In these cases, the predicted event rate of BH-BH mergers across all mass bins would be inconsistent with an absence of de- tections in advanced LIGO (as represented by the upper limit curve). In addition, by comparing the shape of the upper limit curve to the shape of the predictions, we are provided with a visual indication of how the mass selec- tion effects of the instruments impacts the predicted mass distributions of sources.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“双黑洞并合率估计方法对红移信息的依赖”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么是否纳入并合红移信息会使不同方法估计的双黑洞并合率差别很大？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #070 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：说明黑洞并合率估计中红移/质量参数及不同估计方法的区别
3. **具体重写目标**：说明黑洞并合率估计中红移/质量参数及不同估计方法的区别。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #071 · `legacy_qa_review_v1::013`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`arxiv_1511_05955`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about arxiv_1511_05955? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
is a likelihood ratio and, in turn, a sufficient statistic. Thus, compressing the data vector into a Bayes factor is lossless as long the two hypotheses perfectly describe all possible data realizations. Nevertheless, there might be multiple model classes for both signals and noise within the broader signal-versus-noise hypotheses. Expanding on our previous examples, GW burst signals can have varying morphologies, and the detector noise may be- have as either Gaussian or non-Gaussian noise at differ- ent times [41] . We can compute Bayes factors for each of these model class hypotheses, but then we need a way of combining the Bayes factors without losing information about the overall signal-versus-noise hypothesis. If we treat the set of Bayes factors for each model hypothesis as another data vector $\vec{x}_B$ , then further compression of the data into the likelihood ratio
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `arxiv_1511_05955_page_0003_HY_014` · 页 `page_0003` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_0/arxiv_1511_05955/page_0003/evidence_nodes.jsonl`
   - 旧版原子节点：`A_018`
   - bbox：`[[636.0, 514.0, 1138.0, 886.0]]`

````text
is a likelihood ratio and, in turn, a sufficient statistic. Thus, compressing the data vector into a Bayes factor is lossless as long the two hypotheses perfectly describe all possible data realizations. Nevertheless, there might be multiple model classes for both signals and noise within the broader signal-versus-noise hypotheses. Expanding on our previous examples, GW burst signals can have varying morphologies, and the detector noise may be- have as either Gaussian or non-Gaussian noise at differ- ent times [41] . We can compute Bayes factors for each of these model class hypotheses, but then we need a way of combining the Bayes factors without losing information about the overall signal-versus-noise hypothesis. If we treat the set of Bayes factors for each model hypothesis as another data vector $\vec{x}_B$ , then further compression of the data into the likelihood ratio
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“似然比作为充分统计量成立的模型前提”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】在什么条件下，把探测器数据压缩为似然比或Bayes因子才不会损失信息？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #071 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：询问似然比何时是充分统计量，强调成立的模型或假设范围
3. **具体重写目标**：询问似然比何时是充分统计量，强调成立的模型或假设范围。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #072 · `legacy_qa_review_v1::014`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`climate_change_with_ml`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about climate_change_with_ml? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
turbine, or other variable electricity generator, there is some mix of natural gas plants, storage, or other controllable sources ready to buffer changes in its output (e.g. when unexpected clouds block the sun or the wind blows less strongly than predicted). Today, this buffer is often provided by coal and natural gas plants run in a CO 2 -emitting standby mode called spinning reserve . In the future, this role is expected to be played by energy storage technologies such as batteries ( § 2.3 ), pumped hydro, or power-to-gas [29] . $^7$ ML can both reduce emissions from today's standby generators and enable the transition to carbon-free systems by helping improve necessary technologies (namely forecasting, scheduling, and control) and by helping create advanced electricity markets that accommodate both variable electricity and flexible demand.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `climate_change_with_ml_page_0006_HY_001` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_0/climate_change_with_ml/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_003`
   - bbox：`[[140.0, 1100.0, 1095.0, 1320.0]]`

````text
turbine, or other variable electricity generator, there is some mix of natural gas plants, storage, or other controllable sources ready to buffer changes in its output (e.g. when unexpected clouds block the sun or the wind blows less strongly than predicted). Today, this buffer is often provided by coal and natural gas plants run in a CO 2 -emitting standby mode called spinning reserve . In the future, this role is expected to be played by energy storage technologies such as batteries ( § 2.3 ), pumped hydro, or power-to-gas [29] . $^7$ ML can both reduce emissions from today's standby generators and enable the transition to carbon-free systems by helping improve necessary technologies (namely forecasting, scheduling, and control) and by helping create advanced electricity markets that accommodate both variable electricity and flexible demand.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“可再生能源波动及备用电源与机器学习作用”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么高比例风光电力需要灵活备用资源，机器学习可以在哪些环节降低排放？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #072 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：询问可再生电源随机波动为何需要辅助调度与预测，不夸大机器学习贡献
3. **具体重写目标**：询问可再生电源随机波动为何需要辅助调度与预测，不夸大机器学习贡献。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #073 · `legacy_qa_review_v1::015`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`detr`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about detr? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
There is no canonical deep learning model to directly predict sets. The basic set prediction task is multilabel classification (see e.g., [ 40 , 33 ] for references in the context of computer vision) for which the baseline approach, one-vs-rest, does not apply to problems such as detection where there is an underlying structure between elements (i.e., near-identical boxes). The first difficulty in these tasks is to avoid near-duplicates. Most current detectors use postprocessings such as non-maximal suppression to address this issue, but direct set prediction are postprocessing-free. They need global inference schemes that model interactions between all predicted elements to avoid redundancy. For constant-size set pre- diction, dense fully connected networks [ 9 ] are sufficient but costly. A general approach is to use auto-regressive sequence models such as recurrent neural net- works [ 48 ] . In all cases, the loss function should be invariant by a permutation of the predictions. The usual solution is to design a loss based on the Hungarian al- gorithm [ 20 ] , to find a bipartite matching between ground-truth and prediction. This enforces permutation-invariance, and guarantees that each target element has a unique match. We follow the bipartite matching loss approach. In contrast to most prior work however, we step away from autoregressive models and use transformers with parallel decoding, which we describe below.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `detr_page_0003_HY_004` · 页 `page_0003` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_2/hybrid/shard_1/detr/page_0003/evidence_nodes.jsonl`
   - 旧版原子节点：`A_007`
   - bbox：`[[47.0, 346.0, 573.0, 671.0]]`

````text
There is no canonical deep learning model to directly predict sets. The basic set prediction task is multilabel classification (see e.g., [ 40 , 33 ] for references in the context of computer vision) for which the baseline approach, one-vs-rest, does not apply to problems such as detection where there is an underlying structure between elements (i.e., near-identical boxes). The first difficulty in these tasks is to avoid near-duplicates. Most current detectors use postprocessings such as non-maximal suppression to address this issue, but direct set prediction are postprocessing-free. They need global inference schemes that model interactions between all predicted elements to avoid redundancy. For constant-size set pre- diction, dense fully connected networks [ 9 ] are sufficient but costly. A general approach is to use auto-regressive sequence models such as recurrent neural net- works [ 48 ] . In all cases, the loss function should be invariant by a permutation of the predictions. The usual solution is to design a loss based on the Hungarian al- gorithm [ 20 ] , to find a bipartite matching between ground-truth and prediction. This enforces permutation-invariance, and guarantees that each target element has a unique match. We follow the bipartite matching loss approach. In contrast to most prior work however, we step away from autoregressive models and use transformers with parallel decoding, which we describe below.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“DETR集合预测、重复框与匈牙利匹配”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么直接集合预测目标检测需要置换不变的匈牙利匹配损失？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #073 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：询问 DETR 的集合预测为何使用二分匈牙利匹配避免重复预测
3. **具体重写目标**：询问 DETR 的集合预测为何使用二分匈牙利匹配避免重复预测。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #074 · `legacy_qa_review_v1::016`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`entropy`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about entropy? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
These artificial languages are useful in constructing simple problems and examples to illustrate vari- ous possibilities. We can also approximate to a natural language by means of a series of simple artificial languages. The zero-order approximation is obtained by choosing all letters with the same probability and independently. The first-order approximation is obtained by choosing successive letters independently but each letter having the same probability that it has in the natural language. $^5$ Thus, in the first-order ap- proximation to English, E is chosen with probability .12 (its frequency in normal English) and W with probability .02, but there is no influence between adjacent letters and no tendency to form the preferred
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `entropy_page_0006_HY_013` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_5/hybrid/shard_0/entropy/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_015`
   - bbox：`[[181.0, 1217.0, 1052.0, 1388.0]]`

````text
These artificial languages are useful in constructing simple problems and examples to illustrate vari- ous possibilities. We can also approximate to a natural language by means of a series of simple artificial languages. The zero-order approximation is obtained by choosing all letters with the same probability and independently. The first-order approximation is obtained by choosing successive letters independently but each letter having the same probability that it has in the natural language. $^5$ Thus, in the first-order ap- proximation to English, E is chosen with probability .12 (its frequency in normal English) and W with probability .02, but there is no influence between adjacent letters and no tendency to form the preferred
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“香农对自然语言的零阶/一阶统计近似”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】香农的一阶英文字母近似与零阶近似有什么区别？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #074 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：说明香农零阶/一阶随机字母模型如何保留不同程度的统计依赖
3. **具体重写目标**：说明香农零阶/一阶随机字母模型如何保留不同程度的统计依赖。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #075 · `legacy_qa_review_v1::017`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`gNtSaU-1511.05999v3`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about gNtSaU-1511.05999v3? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
The wave parameters $e[i]$ and $\psi[i]$ describe the polar- ization pattern. In some case they can be related to the astrophysical source parameters. In this section we ex- plicitly use the sample index $i$ to demonstrate that the event parameter may vary during its time-frequency evo- lution. For example, for binary systems $e[i]$ are defined by the inclination angle of the source and $\psi[i]$ are defined by the polarization angle. The parameters $e[i]$ and $\psi[i]$ can be constrained when sources with a certain polar- ization state are considered. For un-modeled signals all $e[i]$ and $\psi[i]$ are free parameters or, in other words, the wave polarization is random ( $r$ -waves). In this case, the solution for the network responses has been already de- scribed in the previous section. By imposing constraints on $e[i]$ and $\psi[i]$ , the $r$ -waves can be divided into sub- classes with more definite polarization states. For ex- ample, most GW signals should produce patterns with fixed chirality (all $e[i]>0$ or all $e[i]<0$ ). Therefore, the vectors $\tilde{\boldsymbol{\xi}}_{\times}$ can be constrained to have the same chirality ( $\iota$ -waves). A more narrow sub-class of $\iota$ -waves are non- precessing binary systems, where the parameters $e[i]$ are related to the inclination angle of the source and there- fore $e[i]=const$ . The angles $\psi[i]$ define the orientation of the reconstructed response vectors in the network plane. Assuming that the parameters $e[i]$ are free, the constraint $\psi[i}=const$ describes a particular class of GW signals with the same direction of the network response vectors ( $\Psi$ -waves). The elliptical, linear and circular waves are defined when both angles $e[i]$ and $\psi[i]$ are constrained. The constraints for the $\iota$ -waves and $\Psi$ -waves, and their combinations characterizing different polarization mod- els are summarized in Table I . The simplest solution is for the waves with the circular polarization: $e[i] = \pm 1$ . A less strict (loose) circular polarization constraint is when $\boldsymbol{\xi}_{\times}=0$ . In this case the network responses are defined by the vectors $\boldsymbol{\xi}_{+}$ and $\boldsymbol{\xi}_{\times}$ and the condition $e[i]=\pm 1$ is not enforced. For linear waves $e[i] = 0$ and all $0^{\circ}$ -phase response vectors are co-aligned, or $\psi[i] = const$ . Respec- tively, a less strict (loose) linear polarization constraint is defined by the condition $\tilde{\pmb{\xi}}_{\times}=0$ when the condition $\psi[i]=const$ is not enforced. The polarization constraints can be used to construct weakly modeled burst searches targeting broad classes of GW transients. The $\iota$ -wave constraint can be applied to any rotating source. The el- liptical, circular and the $\psi$ -wave constraints can be used to search for compact binary sources with different spin configurations.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gNtSaU-1511.05999v3_page_0006_HY_001` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_1/gNtSaU-1511.05999v3/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_003, A_004, A_005`
   - bbox：`[[104.0, 158.0, 608.0, 904.0], [104.0, 1296.0, 607.0, 1464.0], [634.0, 104.0, 1137.0, 292.0]]`

````text
The wave parameters $e[i]$ and $\psi[i]$ describe the polar- ization pattern. In some case they can be related to the astrophysical source parameters. In this section we ex- plicitly use the sample index $i$ to demonstrate that the event parameter may vary during its time-frequency evo- lution. For example, for binary systems $e[i]$ are defined by the inclination angle of the source and $\psi[i]$ are defined by the polarization angle. The parameters $e[i]$ and $\psi[i]$ can be constrained when sources with a certain polar- ization state are considered. For un-modeled signals all $e[i]$ and $\psi[i]$ are free parameters or, in other words, the wave polarization is random ( $r$ -waves). In this case, the solution for the network responses has been already de- scribed in the previous section. By imposing constraints on $e[i]$ and $\psi[i]$ , the $r$ -waves can be divided into sub- classes with more definite polarization states. For ex- ample, most GW signals should produce patterns with fixed chirality (all $e[i]>0$ or all $e[i]<0$ ). Therefore, the vectors $\tilde{\boldsymbol{\xi}}_{\times}$ can be constrained to have the same chirality ( $\iota$ -waves). A more narrow sub-class of $\iota$ -waves are non- precessing binary systems, where the parameters $e[i]$ are related to the inclination angle of the source and there- fore $e[i]=const$ . The angles $\psi[i]$ define the orientation of the reconstructed response vectors in the network plane. Assuming that the parameters $e[i]$ are free, the constraint $\psi[i}=const$ describes a particular class of GW signals with the same direction of the network response vectors ( $\Psi$ -waves). The elliptical, linear and circular waves are defined when both angles $e[i]$ and $\psi[i]$ are constrained. The constraints for the $\iota$ -waves and $\Psi$ -waves, and their combinations characterizing different polarization mod- els are summarized in Table I . The simplest solution is for the waves with the circular polarization: $e[i] = \pm 1$ . A less strict (loose) circular polarization constraint is when $\boldsymbol{\xi}_{\times}=0$ . In this case the network responses are defined by the vectors $\boldsymbol{\xi}_{+}$ and $\boldsymbol{\xi}_{\times}$ and the condition $e[i]=\pm 1$ is not enforced. For linear waves $e[i] = 0$ and all $0^{\circ}$ -phase response vectors are co-aligned, or $\psi[i] = const$ . Respec- tively, a less strict (loose) linear polarization constraint is defined by the condition $\tilde{\pmb{\xi}}_{\times}=0$ when the condition $\psi[i]=const$ is not enforced. The polarization constraints can be used to construct weakly modeled burst searches targeting broad classes of GW transients. The $\iota$ -wave constraint can be applied to any rotating source. The el- liptical, circular and the $\psi$ -wave constraints can be used to search for compact binary sources with different spin configurations.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“引力波偏振参数与双星轨道倾角和偏振角”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】二元并合源的哪些物理角度会影响引力波的椭圆率和偏振角参数？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #075 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：解释引力波两个偏振参数与轨道倾角及极化角的物理对应；保留符号定义
3. **具体重写目标**：解释引力波两个偏振参数与轨道倾角及极化角的物理对应；保留符号定义。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #076 · `legacy_qa_review_v1::018`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_WITH_VISUAL_EVIDENCE_OR_EXCLUDE`。
- **文档与节点状态**：`gw150914_detection`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about gw150914_detection? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
FIG. 1. The gravitational-wave event GW150914 observed by the LIGO Hanford (H1, left column panels) and Livingston (L1, right column panels) detectors. Times are shown relative to September 14, 2015 at 09:50:45 UTC. For visualization, all time series are filtered with a 35–350 Hz bandpass filter to suppress large fluctuations outside the detectors' most sensitive frequency band, and band-reject filters to remove the strong instrumental spectral lines seen in the Fig. 3 spectra. Top row, left: H1 strain. Top row, right: L1 strain. GW150914 arrived first at L1 and $6.9^{+0.5}_{-0.7}$ ms later at H1; for a visual comparison, the H1 data are also shown, shifted in time by this amount and inverted (to account for the detectors' relative orientations). Second row: Gravitational-wave strain projected onto each detector in the 35–350 Hz band. Solid lines show a numerical relativity waveform for a system with parameters consistent with those recovered from GW150914 [ 37 , 38 ] confirmed to 99.9 % by an independent calculation based on [ 15 ] . Shaded areas show 90 % credible regions for two independent waveform reconstructions. One (dark gray) models the signal using binary black hole template waveforms [ 39 ] . The other (light gray) does not use an astrophysical model, but instead calculates the strain signal as a linear combination of sine-Gaussian wavelets [ 40 , 41 ] . These reconstructions have a 94 % overlap, as shown in [ 39 ] . Third row: Residuals after subtracting the filtered numerical relativity waveform from the filtered detector time series. Bottom row:A time-frequency representation [ 42 ] of the strain data, showing the signal frequency increasing over time.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gw150914_detection_page_0002_HY_003` · 页 `page_0002` · 类型 `COMPOSITE`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_1/hybrid/shard_0/gw150914_detection/page_0002/evidence_nodes.jsonl`
   - 旧版原子节点：`A_009`
   - bbox：`[[74.0, 856.0, 843.0, 1072.0], [79.0, 236.0, 837.0, 850.0]]`

````text
FIG. 1. The gravitational-wave event GW150914 observed by the LIGO Hanford (H1, left column panels) and Livingston (L1, right column panels) detectors. Times are shown relative to September 14, 2015 at 09:50:45 UTC. For visualization, all time series are filtered with a 35–350 Hz bandpass filter to suppress large fluctuations outside the detectors' most sensitive frequency band, and band-reject filters to remove the strong instrumental spectral lines seen in the Fig. 3 spectra. Top row, left: H1 strain. Top row, right: L1 strain. GW150914 arrived first at L1 and $6.9^{+0.5}_{-0.7}$ ms later at H1; for a visual comparison, the H1 data are also shown, shifted in time by this amount and inverted (to account for the detectors' relative orientations). Second row: Gravitational-wave strain projected onto each detector in the 35–350 Hz band. Solid lines show a numerical relativity waveform for a system with parameters consistent with those recovered from GW150914 [ 37 , 38 ] confirmed to 99.9 % by an independent calculation based on [ 15 ] . Shaded areas show 90 % credible regions for two independent waveform reconstructions. One (dark gray) models the signal using binary black hole template waveforms [ 39 ] . The other (light gray) does not use an astrophysical model, but instead calculates the strain signal as a linear combination of sine-Gaussian wavelets [ 40 , 41 ] . These reconstructions have a 94 % overlap, as shown in [ 39 ] . Third row: Residuals after subtracting the filtered numerical relativity waveform from the filtered detector time series. Bottom row:A time-frequency representation [ 42 ] of the strain data, showing the signal frequency increasing over time.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“GW150914图注中的探测器与滤波范围”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】GW150914的图1波形为什么先采用35–350 Hz带通滤波？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #076 行号。**目标操作**：`REGENERATE_WITH_VISUAL_EVIDENCE_OR_EXCLUDE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：图注/图像复合节点；若问图中的时域波形或滤波范围必须联合图像，不得单靠图注作金标准
3. **具体重写目标**：图注/图像复合节点；若问图中的时域波形或滤波范围必须联合图像，不得单靠图注作金标准。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：必须核实图像/图注联合证据，评测若只允许纯文本 node 则排除依赖图形读数的题。

**完成门槛**：
实际图像与图注一致，并且当前检索单元能访问图像；图像若不可用不得作为正式 Gold Evidence。

---

### #077 · `legacy_qa_review_v1::019`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`gw150914_gr_test`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about gw150914_gr_test? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
We begin by constraining the level of coherent (i.e., GW- like) residual strain left after removing the most-probable GR waveform from the GW150914 data, and use this esti- mated level to bound GR violations which are not degener- ate with changes in the parameters of the binary. We then verify that the mass and spin parameters of the final black hole, as predicted from the binary's inspiral signal, are consis- tent with the final parameters inferred from the post-inspiral (merger and ringdown) signal. We find that the data fol- lowing the peak of GW150914 are consistent with the least- damped quasi-normal mode (QNM) inferred from the final black-hole's characteristics. Next, we perform targeted mea- surements of the PN and phenomenological coefficients ffi cients that parameterize theoretical waveform models, and find no ten- sion with the values predicted in GR and numerical-relativity (NR) simulations. Furthermore, we search for evidence of dispersion in the propagation of GW150914 toward the Earth, as it would appear in a theory in which the graviton is as- signed a finite Compton wavelength (i.e., a nonzero mass). Finally, we show that, due to the LIGO network configura- tion, we cannot exclude the presence of non-GR polarization states in GW150914.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gw150914_gr_test_page_0006_HY_005` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_1/gw150914_gr_test/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_006`
   - bbox：`[[635.0, 106.0, 1138.0, 637.0]]`

````text
We begin by constraining the level of coherent (i.e., GW- like) residual strain left after removing the most-probable GR waveform from the GW150914 data, and use this esti- mated level to bound GR violations which are not degener- ate with changes in the parameters of the binary. We then verify that the mass and spin parameters of the final black hole, as predicted from the binary's inspiral signal, are consis- tent with the final parameters inferred from the post-inspiral (merger and ringdown) signal. We find that the data fol- lowing the peak of GW150914 are consistent with the least- damped quasi-normal mode (QNM) inferred from the final black-hole's characteristics. Next, we perform targeted mea- surements of the PN and phenomenological coefficients ffi cients that parameterize theoretical waveform models, and find no ten- sion with the values predicted in GR and numerical-relativity (NR) simulations. Furthermore, we search for evidence of dispersion in the propagation of GW150914 toward the Earth, as it would appear in a theory in which the graviton is as- signed a finite Compton wavelength (i.e., a nonzero mass). Finally, we show that, due to the LIGO network configura- tion, we cannot exclude the presence of non-GR polarization states in GW150914.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“GR波形残差与并合前后参数一致性检验”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】GW150914的广义相对论检验采用了哪两类一致性或残差检验？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #077 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 GW150914 广义相对论检验如何利用一致性残差，而非泛泛复述论文
3. **具体重写目标**：问 GW150914 广义相对论检验如何利用一致性残差，而非泛泛复述论文。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #078 · `legacy_qa_review_v1::020`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`gw150914_properties`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about gw150914_properties? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
In Table I , we also indicate how sensitive our results are to our choice of waveform. For each parameter, we give systematic errors on the boundaries of the 90 % credible intervals due to the uncertainty in the waveform models considered in the analysis; the quoted values are the 90 % range of a normal distribution estimated from the variance of results from the different models. (If $X$ were an edge of a credible interval, we quote systematic uncertainty $\pm1.64\sigma_\text{sys}$ using the estimate $\sigma_\text{sys}^2=[(X_\text{EOBNR}-X_\text{Overall})^2+(X_\text{IMRPhenom}-X_\text{Overall})^2]/2$ . For parameters with bounded ranges, like the spins, the normal distributions should be truncated. However, for transparency, we still quote the 90 % range of the uncut distributions. These numbers provide estimates of the order of magnitude of the potential systematic error). Assuming a normally distributed error is the least constraining choice [ 90 ] and gives a conservative estimate. The uncertainty from waveform modeling is less significant than the statistical uncertainty; therefore, we are confident that the results are robust against this potential systematic error. We consider this point in detail later in the Letter.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gw150914_properties_page_0006_HY_005` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_1/gw150914_properties/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_009, A_010`
   - bbox：`[[101.0, 1281.0, 604.0, 1453.0], [632.0, 99.0, 1135.0, 448.0]]`

````text
In Table I , we also indicate how sensitive our results are to our choice of waveform. For each parameter, we give systematic errors on the boundaries of the 90 % credible intervals due to the uncertainty in the waveform models considered in the analysis; the quoted values are the 90 % range of a normal distribution estimated from the variance of results from the different models. (If $X$ were an edge of a credible interval, we quote systematic uncertainty $\pm1.64\sigma_\text{sys}$ using the estimate $\sigma_\text{sys}^2=[(X_\text{EOBNR}-X_\text{Overall})^2+(X_\text{IMRPhenom}-X_\text{Overall})^2]/2$ . For parameters with bounded ranges, like the spins, the normal distributions should be truncated. However, for transparency, we still quote the 90 % range of the uncut distributions. These numbers provide estimates of the order of magnitude of the potential systematic error). Assuming a normally distributed error is the least constraining choice [ 90 ] and gives a conservative estimate. The uncertainty from waveform modeling is less significant than the statistical uncertainty; therefore, we are confident that the results are robust against this potential systematic error. We consider this point in detail later in the Letter.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“波形模型差异对90%可信区间边界的系统误差”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】该研究如何量化不同波形模型给黑洞参数的90%可信区间带来的系统误差？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #078 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：说明波形模型选择可能怎样影响黑洞参数估计的 90% 区间边界
3. **具体重写目标**：说明波形模型选择可能怎样影响黑洞参数估计的 90% 区间边界。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #079 · `legacy_qa_review_v1::021`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`hallmarks_of_aging`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about hallmarks_of_aging? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
A prominent aging-associated alteration in intercellular communication is `inflammaging', i.e. a smoldering pro-inflammatory phenotype that accompanies aging in mammals (Salminen et al., 2012) . Inflammaging may result from multiple causes such as the accumulation of pro-inflammatory tissue damage, the failure of an ever more dysfunctional immune system to effectively clear pathogens and dysfunctional host cells, the propensity of senescent cells to secrete pro-inflammatory cytokines (see section on Cellular Senescence), the enhanced activation of the NF- $\kappa$ B transcription factor, or the occurrence of a defective autophagy response (Salminen et al., 2012) . These alterations result in an enhanced activation of the NLRP3 inflammasome and other pro-inflammatory pathways, finally leading to increased production of IL-1 $\beta$ , tumor necrosis factor and interferons (Green et al., 2011; Salminen et al., 2012) . Inflammation is also involved in the pathogenesis of obesity and type 2 diabetes, two conditions that contribute to, and correlate with aging in the human population (Barzilai et al., 2012) . Likewise, defective inflammatory responses play a critical role in atherosclerosis (Tabas, 2010) . The recent finding that age-associated inflammation inhibits epidermal stem cell function (Doles et al., 2012) , further supports the intricate concatenation of different hallmarks that reinforces the aging process. Paralleling inflammaging, the function of the adaptive immune system declines (Deeks, 2011) . This immunosenescence may aggravate the aging phenotype at the systemic level, due to the failure of the immune system to clear infectious agents, infected cells, and cells on the verge of malignant transformation. Moreover, one of the functions of the immune system is to recognize and eliminate senescent cells (see section on Stem Cell Exhaustion), as well as hyperploid cells that accumulate in aging tissues and premalignant lesions (Davoli and de Lange, 2011; Senovilla et al., 2012) .
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `hallmarks_of_aging_page_0018_HY_002` · 页 `page_0018` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_1/hallmarks_of_aging/page_0018/evidence_nodes.jsonl`
   - 旧版原子节点：`A_006`
   - bbox：`[[221.0, 309.0, 783.0, 724.0]]`

````text
A prominent aging-associated alteration in intercellular communication is `inflammaging', i.e. a smoldering pro-inflammatory phenotype that accompanies aging in mammals (Salminen et al., 2012) . Inflammaging may result from multiple causes such as the accumulation of pro-inflammatory tissue damage, the failure of an ever more dysfunctional immune system to effectively clear pathogens and dysfunctional host cells, the propensity of senescent cells to secrete pro-inflammatory cytokines (see section on Cellular Senescence), the enhanced activation of the NF- $\kappa$ B transcription factor, or the occurrence of a defective autophagy response (Salminen et al., 2012) . These alterations result in an enhanced activation of the NLRP3 inflammasome and other pro-inflammatory pathways, finally leading to increased production of IL-1 $\beta$ , tumor necrosis factor and interferons (Green et al., 2011; Salminen et al., 2012) . Inflammation is also involved in the pathogenesis of obesity and type 2 diabetes, two conditions that contribute to, and correlate with aging in the human population (Barzilai et al., 2012) . Likewise, defective inflammatory responses play a critical role in atherosclerosis (Tabas, 2010) . The recent finding that age-associated inflammation inhibits epidermal stem cell function (Doles et al., 2012) , further supports the intricate concatenation of different hallmarks that reinforces the aging process. Paralleling inflammaging, the function of the adaptive immune system declines (Deeks, 2011) . This immunosenescence may aggravate the aging phenotype at the systemic level, due to the failure of the immune system to clear infectious agents, infected cells, and cells on the verge of malignant transformation. Moreover, one of the functions of the immune system is to recognize and eliminate senescent cells (see section on Stem Cell Exhaustion), as well as hyperploid cells that accumulate in aging tissues and premalignant lesions (Davoli and de Lange, 2011; Senovilla et al., 2012) .
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“炎症性衰老及其潜在来源”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】文中如何定义inflammaging，并列举了哪些可能导致它的过程？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #079 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：提问炎症性衰老的细胞间通信变化及具体炎症介质，避免强因果宣称
3. **具体重写目标**：提问炎症性衰老的细胞间通信变化及具体炎症介质，避免强因果宣称。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #080 · `legacy_qa_review_v1::022`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`nist_ai_rmf_1_0`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about nist_ai_rmf_1_0? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
While there are myriad standards and best practices to help organizations mitigate the risks of traditional software or information-based systems, the risks posed by AI systems are in many ways unique (See Appendix B ). AI systems, for example, may be trained on data that can change over time, sometimes significantly and unexpectedly, affecting system function- ality and trustworthiness in ways that are hard to understand. AI systems and the contexts in which they are deployed are frequently complex, making it difficult to detect and respond to failures when they occur. AI systems are inherently socio-technical in nature, meaning they are influenced by societal dynamics and human behavior. AI risks – and benefits – can emerge from the interplay of technical aspects combined with societal factors related to how a system is used, its interactions with other AI systems, who operates it, and the social context in which it is deployed.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `nist_ai_rmf_1_0_page_0006_HY_003` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_0/nist_ai_rmf_1_0/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_006`
   - bbox：`[[176.0, 635.0, 1060.0, 959.0]]`

````text
While there are myriad standards and best practices to help organizations mitigate the risks of traditional software or information-based systems, the risks posed by AI systems are in many ways unique (See Appendix B ). AI systems, for example, may be trained on data that can change over time, sometimes significantly and unexpectedly, affecting system function- ality and trustworthiness in ways that are hard to understand. AI systems and the contexts in which they are deployed are frequently complex, making it difficult to detect and respond to failures when they occur. AI systems are inherently socio-technical in nature, meaning they are influenced by societal dynamics and human behavior. AI risks – and benefits – can emerge from the interplay of technical aspects combined with societal factors related to how a system is used, its interactions with other AI systems, who operates it, and the social context in which it is deployed.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“AI风险随训练数据漂移而改变的特殊性”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么NIST认为AI系统风险不能完全套用传统软件风险管理方法？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #080 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：说明数据分布改变为何使部署后的 AI 风险随时间演化
3. **具体重写目标**：说明数据分布改变为何使部署后的 AI 风险随时间演化。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #081 · `legacy_qa_review_v1::023`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`nvidia_2026_annual_report`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What substantive claim, mechanism, or result does the selected passage establish about nvidia_2026_annual_report? Include any condition that limits the claim.
````

**原 Gold Answer：**
````text
NVIDIA invents computing technologies that improve lives and address global challenges. Our goal is to integrate sound CS principles and practices across the Company. Our Board and management believe that environmental stewardship, social responsibility, and solid governance are important to our business strategy and long-term value creation. While the full Board has ultimate responsibility for CS matters that impact our business, each committee of the Board oversees CS matters across our business operations in the areas that align with their respective responsibilities. The NCGC is responsible for reviewing and discussing with management our policies, issues, and reporting related to sustainability, including overall sustainability strategy, risks, and opportunities, and related programs and initiatives. Our CS team updates the NCGC at least semiannually on these topics, as well as pertinent regulations and stakeholder inputs, and gathers feedback from the NCGC on issues such as climate change and human rights. The CS team also reports on sustainability issues to the full Board annually.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `nvidia_2026_annual_report_page_0050_HY_003` · 页 `page_0050` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_5/hybrid/shard_1/nvidia_2026_annual_report/page_0050/evidence_nodes.jsonl`
   - 旧版原子节点：`A_006`
   - bbox：`[[80.0, 510.0, 1148.0, 734.0]]`

````text
NVIDIA invents computing technologies that improve lives and address global challenges. Our goal is to integrate sound CS principles and practices across the Company. Our Board and management believe that environmental stewardship, social responsibility, and solid governance are important to our business strategy and long-term value creation. While the full Board has ultimate responsibility for CS matters that impact our business, each committee of the Board oversees CS matters across our business operations in the areas that align with their respective responsibilities. The NCGC is responsible for reviewing and discussing with management our policies, issues, and reporting related to sustainability, including overall sustainability strategy, risks, and opportunities, and related programs and initiatives. Our CS team updates the NCGC at least semiannually on these topics, as well as pertinent regulations and stakeholder inputs, and gathers feedback from the NCGC on issues such as climate change and human rights. The CS team also reports on sustainability issues to the full Board annually.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NVIDIA董事会与委员会的公司可持续治理职责”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】NVIDIA 2026年报如何描述董事会与管理层对公司可持续议题的责任分工？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #081 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：根据公司治理段说明 NVIDIA 董事会及委员会如何监督可持续性议题，不得超出报告措辞
3. **具体重写目标**：根据公司治理段说明 NVIDIA 董事会及委员会如何监督可持续性议题，不得超出报告措辞。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #082 · `auto_new_expansion::real_001_batch_01_NASA-Spinoff-2023::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`EXCLUDE_FROM_FACTUAL_QA`。
- **文档与节点状态**：`real_001_batch_01_NASA-Spinoff-2023`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`review_status`, `answer_status (if present)`, `benchmark_membership (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_001_batch_01_NASA-Spinoff-2023, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
<table><tr><td>4</td><td>Telescope Mirror Tech Improves Eye Surgery</td><td>System for guiding LASIK eye surgery</td><td>Johnson &amp; Johnson, Santa Ana, CA</td></tr><tr><td>5</td><td>Feeling Hot, Staying Cool</td><td>Temperature-controlling clothing for menopause</td><td>Fifty One, London, England</td></tr><tr><td>6</td><td>Astronaut Life Support for Earth Families</td><td>Aeroponic tower for growing crops, seafood</td><td>Eden Grow Systems, Houston, TX</td></tr><tr><td>7</td><td>Learning to Code with NASA Data</td><td>Data for computer science/programming lessons</td><td>Microsoft, Redmond, WA</td></tr><tr><td>8</td><td>The Science of the Perfect Cup for Coffee</td><td>Phase-change material mug</td><td>ThermAvant Technology, Columbia, MO</td></tr><tr><td>9</td><td>Flying (Not Quite) Blind</td><td>Avionics video switcher with simultaneous recording</td><td>Eon Instrumentation, Van Nys, CA</td></tr><tr><td>10</td><td>Cryofloids Come Under Pressure</td><td>Ultra-lightweight carbon composite cryofluid tank</td><td>Göyler-Taylor Laboratories, Tulsa, TN</td></tr><tr><td>11</td><td>Cubesats Take a Bus into Space</td><td>Small satellite hardware platform</td><td>Tyak Nano-Satellite Systems, Irvine, CA</td></tr><tr><td>12</td><td>Earth&#x27;s Twin Helps with Extreme Electronics</td><td>Single-board computer module for extreme heat</td><td>Ozark Integrated Circuits, Fayetteville, AR</td></tr><tr><td>13</td><td>Suspended Solar Panels See the Light</td><td>Suspended solar panel installations</td><td>Skyssun, Cleveland, OH</td></tr><tr><td>14</td><td>Space Program Pumps Up Turbomachinery</td><td>Turbopump machinery</td><td>Barber-Nichols, Arvada, CO</td></tr><tr><td>15</td><td>New Solar Array Design Saves Space</td><td>Solar array design for compact storage</td><td>Northrop Grumman, Goleta, CA</td></tr><tr><td>16</td><td>Traveling-Wave Waves Travel Far</td><td>Traveling-wave tube amplifier</td><td>Stallant Systems, Torrance, CA</td></tr><tr><td>17</td><td>Private Lessons for Private Spaceflight</td><td>Private astronaut training</td><td>Axion Space, Houston, TX</td></tr><tr><td>18</td><td>Device for Analyzing Deep Space Could Detect Tumors ...</td><td>Curved microchannel plates</td><td>Incom, Charilton, MA</td></tr><tr><td>19</td><td>Electrical Body Signals Help Researchers Restore Movement ...</td><td>Wireless sensors to map motor nerve activity</td><td>Delsys, Natica, MC</td></tr><tr><td>20</td><td>Space Robotics Take a Deep Dive</td><td>Aquanaut autonomous underwater robot</td><td>Naucluc Robotics, Houston, TX</td></tr><tr><td rowspan="4">26</td><td rowspan="4">NASA&#x27;s VITAL Contribution to Global Pandemic Relief</td><td rowspan="4">Low-cost respiratory ventilators</td><td>Bharat Forge, Pune, India</td></tr><tr><td>CuraSigma Systems, Bangalore, India</td></tr><tr><td>Russer Brasil, India/lufta, Brazil</td></tr><tr><td>STARK Industries, Columbus, OH</td></tr><tr><td rowspan="3">30</td><td rowspan="3">A High-Tech Farmer&#x27;s Almanac for Everyone</td><td rowspan="3">Open-source modeling and Earth-observation data and imagery</td><td>Ersi, Redlands, CA</td></tr><tr><td>First Street Foundation, Brooklyn, NY</td></tr><tr><td>Deles Insurance Solutions, San Francisco, CA</td></tr><tr><td>34</td><td>NASA Helps Serve Yellowstone Fungi for Breakfast</td><td>Fv meat-alternative protein</td><td>Nature&#x27;s Fynd, Chicago, IL</td></tr><tr><td>38</td><td>Giant Batteries Deliver Renewable Energy When It&#x27;s Needed</td><td>Flow battery</td><td>ESS, Wilsonville, OR</td></tr><tr><td rowspan="3">40</td><td rowspan="3">The View from Space Keeps Getting Better</td><td rowspan="3">Landsat Earth-imaging data and data-analysis tools</td><td>Perennial, Boulder, CO</td></tr><tr><td>Baker Family Farm, Sacramento County, CA</td></tr><tr><td>Mapbox, Washington, DC</td></tr><tr><td rowspan="2">48</td><td rowspan="2">An Electronic Traffic Monitor for Airports</td><td rowspan="2">Airport ground traffic management system</td><td>Charlotte Douglas International Airport, Charlotte, NC</td></tr><tr><td>Southwest Airlines, Dallas, TX</td></tr><tr><td>52</td><td>Cloning Metal Parts for Space and Earth</td><td>Additive-manufacturing modeling software</td><td>Sentient Science, Buffalo, NY</td></tr><tr><td>54</td><td>NASA Research Illuminates Medical Uses of Light</td><td>LED-based medical light-therapy devices</td><td>Multi Radiance Medical, Solon, OH</td></tr><tr><td rowspan="2">58</td><td rowspan="2">Weather Forecasters Adopt NASA&#x27;s &#x27;Occult&#x27; Science</td><td rowspan="2">Atmospheric sounding technique for better weather forecasting</td><td>GeoOptics, Pasadena, CA</td></tr><tr><td>Planetoid, Golden, CO</td></tr><tr><td>62</td><td>With NASA&#x27;s Help, the Moon Becomes a Commercial Destination</td><td>Commercial lunar lander</td><td>Spire Global, Vienna, VA</td></tr><tr><td>64</td><td>Shuttle-Analysis Software Improves Airplane, Turbine Safety</td><td>Fracture-mechanics software</td><td>Intuitive Machines, Houston, TX</td></tr><tr><td>66</td><td>IFIND Finds Its Way into Rescues&#x27; Toolkit</td><td>Microwave radar for search and recovery operations</td><td>Siemens Energy, Orlando, FL</td></tr><tr><td>72</td><td>Space Radiation Research Fights Cancer on Earth</td><td>Diagnostic test to customize cancer treatment</td><td>Promega, Fitchburg, WI</td></tr></table>
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_001_batch_01_NASA-Spinoff-2023:p0042:e001` · 页 `42` · 类型 `tab`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_001_batch_01_NASA-Spinoff-2023/pages/page_0042/output_json/page_0042.json`
   - bbox：`[50, 80, 729, 748]`

````text
<table><tr><td>4</td><td>Telescope Mirror Tech Improves Eye Surgery</td><td>System for guiding LASIK eye surgery</td><td>Johnson &amp; Johnson, Santa Ana, CA</td></tr><tr><td>5</td><td>Feeling Hot, Staying Cool</td><td>Temperature-controlling clothing for menopause</td><td>Fifty One, London, England</td></tr><tr><td>6</td><td>Astronaut Life Support for Earth Families</td><td>Aeroponic tower for growing crops, seafood</td><td>Eden Grow Systems, Houston, TX</td></tr><tr><td>7</td><td>Learning to Code with NASA Data</td><td>Data for computer science/programming lessons</td><td>Microsoft, Redmond, WA</td></tr><tr><td>8</td><td>The Science of the Perfect Cup for Coffee</td><td>Phase-change material mug</td><td>ThermAvant Technology, Columbia, MO</td></tr><tr><td>9</td><td>Flying (Not Quite) Blind</td><td>Avionics video switcher with simultaneous recording</td><td>Eon Instrumentation, Van Nys, CA</td></tr><tr><td>10</td><td>Cryofloids Come Under Pressure</td><td>Ultra-lightweight carbon composite cryofluid tank</td><td>Göyler-Taylor Laboratories, Tulsa, TN</td></tr><tr><td>11</td><td>Cubesats Take a Bus into Space</td><td>Small satellite hardware platform</td><td>Tyak Nano-Satellite Systems, Irvine, CA</td></tr><tr><td>12</td><td>Earth&#x27;s Twin Helps with Extreme Electronics</td><td>Single-board computer module for extreme heat</td><td>Ozark Integrated Circuits, Fayetteville, AR</td></tr><tr><td>13</td><td>Suspended Solar Panels See the Light</td><td>Suspended solar panel installations</td><td>Skyssun, Cleveland, OH</td></tr><tr><td>14</td><td>Space Program Pumps Up Turbomachinery</td><td>Turbopump machinery</td><td>Barber-Nichols, Arvada, CO</td></tr><tr><td>15</td><td>New Solar Array Design Saves Space</td><td>Solar array design for compact storage</td><td>Northrop Grumman, Goleta, CA</td></tr><tr><td>16</td><td>Traveling-Wave Waves Travel Far</td><td>Traveling-wave tube amplifier</td><td>Stallant Systems, Torrance, CA</td></tr><tr><td>17</td><td>Private Lessons for Private Spaceflight</td><td>Private astronaut training</td><td>Axion Space, Houston, TX</td></tr><tr><td>18</td><td>Device for Analyzing Deep Space Could Detect Tumors ...</td><td>Curved microchannel plates</td><td>Incom, Charilton, MA</td></tr><tr><td>19</td><td>Electrical Body Signals Help Researchers Restore Movement ...</td><td>Wireless sensors to map motor nerve activity</td><td>Delsys, Natica, MC</td></tr><tr><td>20</td><td>Space Robotics Take a Deep Dive</td><td>Aquanaut autonomous underwater robot</td><td>Naucluc Robotics, Houston, TX</td></tr><tr><td rowspan="4">26</td><td rowspan="4">NASA&#x27;s VITAL Contribution to Global Pandemic Relief</td><td rowspan="4">Low-cost respiratory ventilators</td><td>Bharat Forge, Pune, India</td></tr><tr><td>CuraSigma Systems, Bangalore, India</td></tr><tr><td>Russer Brasil, India/lufta, Brazil</td></tr><tr><td>STARK Industries, Columbus, OH</td></tr><tr><td rowspan="3">30</td><td rowspan="3">A High-Tech Farmer&#x27;s Almanac for Everyone</td><td rowspan="3">Open-source modeling and Earth-observation data and imagery</td><td>Ersi, Redlands, CA</td></tr><tr><td>First Street Foundation, Brooklyn, NY</td></tr><tr><td>Deles Insurance Solutions, San Francisco, CA</td></tr><tr><td>34</td><td>NASA Helps Serve Yellowstone Fungi for Breakfast</td><td>Fv meat-alternative protein</td><td>Nature&#x27;s Fynd, Chicago, IL</td></tr><tr><td>38</td><td>Giant Batteries Deliver Renewable Energy When It&#x27;s Needed</td><td>Flow battery</td><td>ESS, Wilsonville, OR</td></tr><tr><td rowspan="3">40</td><td rowspan="3">The View from Space Keeps Getting Better</td><td rowspan="3">Landsat Earth-imaging data and data-analysis tools</td><td>Perennial, Boulder, CO</td></tr><tr><td>Baker Family Farm, Sacramento County, CA</td></tr><tr><td>Mapbox, Washington, DC</td></tr><tr><td rowspan="2">48</td><td rowspan="2">An Electronic Traffic Monitor for Airports</td><td rowspan="2">Airport ground traffic management system</td><td>Charlotte Douglas International Airport, Charlotte, NC</td></tr><tr><td>Southwest Airlines, Dallas, TX</td></tr><tr><td>52</td><td>Cloning Metal Parts for Space and Earth</td><td>Additive-manufacturing modeling software</td><td>Sentient Science, Buffalo, NY</td></tr><tr><td>54</td><td>NASA Research Illuminates Medical Uses of Light</td><td>LED-based medical light-therapy devices</td><td>Multi Radiance Medical, Solon, OH</td></tr><tr><td rowspan="2">58</td><td rowspan="2">Weather Forecasters Adopt NASA&#x27;s &#x27;Occult&#x27; Science</td><td rowspan="2">Atmospheric sounding technique for better weather forecasting</td><td>GeoOptics, Pasadena, CA</td></tr><tr><td>Planetoid, Golden, CO</td></tr><tr><td>62</td><td>With NASA&#x27;s Help, the Moon Becomes a Commercial Destination</td><td>Commercial lunar lander</td><td>Spire Global, Vienna, VA</td></tr><tr><td>64</td><td>Shuttle-Analysis Software Improves Airplane, Turbine Safety</td><td>Fracture-mechanics software</td><td>Intuitive Machines, Houston, TX</td></tr><tr><td>66</td><td>IFIND Finds Its Way into Rescues&#x27; Toolkit</td><td>Microwave radar for search and recovery operations</td><td>Siemens Energy, Orlando, FL</td></tr><tr><td>72</td><td>Space Radiation Research Fights Cancer on Earth</td><td>Diagnostic test to customize cancer treatment</td><td>Promega, Fitchburg, WI</td></tr></table>
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA Spinoff的目录表格而非解释性论证”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。本段实际是HTML表格/目录索引，缺少明确字段关系，原问却虚构了因果、技术或比较命题；不能把目录整表当作答案。 【建议重写题目】目录第4至第6页分别列出什么衍生技术与对应企业？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #082 行号。**目标操作**：`EXCLUDE_FROM_FACTUAL_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：目录/索引表（NASA Spinoff），应排除解释性 QA；如果做元数据题须转换目标任务类型
3. **具体重写目标**：目录/索引表（NASA Spinoff），应排除解释性 QA；如果做元数据题须转换目标任务类型。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：此来源是目录/日程/作者/索引类，不足以作为因果知识型 gold。默认 `EXCLUDE_OR_PARK`；只有明确改造成表格/元数据检索任务且 schema、评价指标允许才考虑保留。

**完成门槛**：
该条退出事实型 Gold QA（留审计记录）；若改为元数据任务需有新的明确任务类型、验证过的表格/目录源及可评分答案。

---

### #083 · `auto_new_expansion::real_001_batch_01_NASA-Spinoff-2023::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`real_001_batch_01_NASA-Spinoff-2023`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_001_batch_01_NASA-Spinoff-2023, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
But in a way, the whole concept was far ahead of its time. In the 1970s, before digital displays were common, scientists might print the data in the form of characters on a line printer, contour the characters with a marker, and then stand on ladders to view large-scale Landsat images. The ideas for these digital displays were from Landsat project scientist at Goddard Space Flight Center in Greenbelt, Maryland, where NASA's portion of the program is managed. Distribution meant mailing CDs or tapes. With the advent of high-speed internet and high-performance computing, access to – and applications of – Landsat data exploded in the 2010s. More recently, Masek said, cloud computing has made it easy for users to build using the entire Landsat archive, a dataset most users simply couldn't have downloaded.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_001_batch_01_NASA-Spinoff-2023:p0025:e002` · 页 `25` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_001_batch_01_NASA-Spinoff-2023/pages/page_0025/output_json/page_0025.json`
   - bbox：`[279, 47, 500, 266]`

````text
But in a way, the whole concept was far ahead of its time. In the 1970s, before digital displays were common, scientists might print the data in the form of characters on a line printer, contour the characters with a marker, and then stand on ladders to view large-scale Landsat images. The ideas for these digital displays were from Landsat project scientist at Goddard Space Flight Center in Greenbelt, Maryland, where NASA's portion of the program is managed. Distribution meant mailing CDs or tapes. With the advent of high-speed internet and high-performance computing, access to – and applications of – Landsat data exploded in the 2010s. More recently, Masek said, cloud computing has made it easy for users to build using the entire Landsat archive, a dataset most users simply couldn't have downloaded.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“早期数字数据的打印与人工等值线表示”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】在数字显示器普及之前，科学家如何从打印机输出的数据构建图形表示？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #083 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：介绍 1970 年代电子显示不足时如何从打印数字数据生成手工等值线，避免无上下文指示词
3. **具体重写目标**：介绍 1970 年代电子显示不足时如何从打印数字数据生成手工等值线，避免无上下文指示词。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #084 · `auto_new_expansion::real_002_batch_02_Spinoff.2022::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`VERIFY_SOURCE_MODALITY_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_002_batch_02_Spinoff.2022`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_002_batch_02_Spinoff.2022, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
• NASA pioneered the first-ever indoor, vertical farm in the United States – an effort to better understand how to use plants to keep astronauts fed and healthy on long-duration flights. Today, numerous companies are learning from our example, using our technology and techniques to grow food for Earth’s burgeoning population with a far smaller environmental footprint (page 26). • Kennedy Space Center, besides being the site of our most historic launches, is also located in one of the largest and most diverse wildlife preserves in Florida. Some of those early launches took an environmental toll we didn’t learn about until later. Seeking to mitigate the effects of long-term space travel, the space industry developed a robots technology, which now helps relieve polluted environments around the world (page 48). • Robots are crucial to our efforts to explore space and other things – they support astronauts and can form the advance party for places humans have yet to reach. But the human machine is hard to replicate. A collaboration with industry helped us design a better robotic hand – and the effort has been adapted into a robotic glove that helps manufacturing workers reduce injuries (page 44).
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_002_batch_02_Spinoff.2022:p0004:e016` · 页 `4` · 类型 `list`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_002_batch_02_Spinoff.2022/pages/page_0004/output_json/page_0004.json`
   - bbox：`[993, 466, 1404, 659]`

````text
• NASA pioneered the first-ever indoor, vertical farm in the United States – an effort to better understand how to use plants to keep astronauts fed and healthy on long-duration flights. Today, numerous companies are learning from our example, using our technology and techniques to grow food for Earth’s burgeoning population with a far smaller environmental footprint (page 26). • Kennedy Space Center, besides being the site of our most historic launches, is also located in one of the largest and most diverse wildlife preserves in Florida. Some of those early launches took an environmental toll we didn’t learn about until later. Seeking to mitigate the effects of long-term space travel, the space industry developed a robots technology, which now helps relieve polluted environments around the world (page 48). • Robots are crucial to our efforts to explore space and other things – they support astronauts and can form the advance party for places humans have yet to reach. But the human machine is hard to replicate. A collaboration with industry helped us design a better robotic hand – and the effort has been adapted into a robotic glove that helps manufacturing workers reduce injuries (page 44).
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA早期室内垂直种植研究对地面农业的启发”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】NASA为什么首先探索室内垂直农业，其成果如何扩散到地面企业？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #084 行号。**目标操作**：`VERIFY_SOURCE_MODALITY_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：列表条目只给 NASA 室内垂直农场研究的简短事实；优先找正文核实并重写可独立回答的问题
3. **具体重写目标**：列表条目只给 NASA 室内垂直农场研究的简短事实；优先找正文核实并重写可独立回答的问题。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #085 · `auto_new_expansion::real_002_batch_02_Spinoff.2022::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`EXCLUDE_FROM_FACTUAL_QA`。
- **文档与节点状态**：`real_002_batch_02_Spinoff.2022`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`review_status`, `answer_status (if present)`, `benchmark_membership (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_002_batch_02_Spinoff.2022, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
<table><tr><td>Page</td><td>Article</td><td>Technology</td><td>Company, Location</td></tr><tr><td>4</td><td>Measuring Moon Dust to Fight Air Pollution</td><td>Air-quality sensor system</td><td>Lunar Outpost, Denver, CO</td></tr><tr><td>5</td><td>Microbes Help Trees Clean Up Pollution</td><td>Plant endophytes for environmental cleanup</td><td>Intrinsky Environmental, Moffett Field, CA</td></tr><tr><td>6</td><td>Pounding Metal Parts into Profit</td><td>Ultrasonic additive manufacturing</td><td>Fabricious, Columbus, OH</td></tr><tr><td>7</td><td>Water Purification Anywhere on Earth</td><td>Filter medium for water bottles</td><td>nkd LIFE, West Palm Beach, FL</td></tr><tr><td>9</td><td>Plasma Improves 3D Electronics Printing</td><td>Plasma jet 3D electronics printer</td><td>Space Foundry, San Jose, CA</td></tr><tr><td>10</td><td>Computers Tough Enough For Space</td><td>Processor for cubats</td><td>Space Micro, San Diego, CA</td></tr><tr><td>10</td><td>Software Keeps Cloud Traffic Moving</td><td>Portable batch system for computer workloads</td><td>Altair Engineering, Troy, MI</td></tr><tr><td>12</td><td>Antennas Find Their Cool</td><td>Ultra-thin polymer aerogel</td><td>Blueshift Materials, Spencer, MA</td></tr><tr><td>13</td><td>Test Rockets Prepare for Distant Landings</td><td>Rocket-powered vertical takeoff and landing</td><td>Masten Space Systems, Mojave, CA</td></tr><tr><td>14</td><td>Swinging the HamR</td><td>Hybrid remotely piloted aircraft</td><td>Advanced Aircraft Company, Hampton, VA</td></tr><tr><td>15</td><td>Getting Water Out of Snow with NASA Tech</td><td>Lidar and spectrometer sensors, modeling software</td><td>Airborne Snow Observatories, Mammoth Lakes, CA</td></tr><tr><td>16</td><td>Stay Safe with Battery Testing for Space</td><td>Battery testing methods</td><td>Underwaters Laboratories, Northbrook, IL</td></tr><tr><td rowspan="3">17</td><td rowspan="3">Keeping Warmer in the Great Outdoors</td><td rowspan="3">Outdoor gear with new spin on aerogel insulation</td><td>Cold Case Gear, Pagosa Springs, CO</td></tr><tr><td>Outdoor Research, Seattle, WA</td></tr><tr><td>Primal off, Latham, NY</td></tr><tr><td>18</td><td>The &quot;Cobot&quot; Revolution Is Coming</td><td>Bulk metallic glass for robot gears, more</td><td>Amorphology, Pasadena, CA</td></tr><tr><td>19</td><td>Satellite Software Helps Global Forecasting</td><td>Satellite scheduling software</td><td>Orbit Logic, Greenbelt, MD</td></tr><tr><td>20</td><td>From a Lightbox to Lamps</td><td>LED lighting for maintaining circadian rhythms</td><td>Ario, Seattle, WA</td></tr><tr><td>21</td><td>&quot;Positive Energy&quot; Captures Contaminants</td><td>Water filtration medium</td><td>Western Water International, Forestville, MD</td></tr><tr><td>22</td><td>From Spacecrafts to Racing Suits</td><td>Phase-change materials</td><td>Walero, Mooreville, NC</td></tr><tr><td>23</td><td>Some Engineering Is Only Skin Deep</td><td>Surface finishing for 3D-printed superalloys</td><td>REM Surface Engineering, Southington, CT</td></tr><tr><td rowspan="3">26</td><td rowspan="3">A Moveable Feast: Plant Research for Space Advances</td><td rowspan="3">Growing techniques and research data for controlled environment agriculture</td><td>Plenty Unlimited, San Francisco, CA</td></tr><tr><td>Green Sense Farm Holdings, Portage, IN</td></tr><tr><td>Bowery Farming, New York, NY</td></tr><tr><td rowspan="2">30</td><td rowspan="2">NASA Helps Private Lander Shoot for the Moon</td><td>Commercial lunar lander</td><td>CSS Farms, Waterloo, SD</td></tr><tr><td>Drome traffic management app</td><td>Astrobatic Technology, Pittsburgh, PA</td></tr><tr><td rowspan="3">34</td><td rowspan="3">NASA Helps Drones Take Flight</td><td>Detect-and-avoid system for aircraft</td><td>Aviation, Santa Monica, CA</td></tr><tr><td>Drome flight testing environment</td><td>General Atomics, San Diego, CA</td></tr><tr><td>Drome flight testing environment</td><td>CAL Analytics, Beavercreek, OH</td></tr><tr><td>40</td><td>Space Pens, Pencils, and How NASA Takes Notes in Space</td><td>Space Pen for writing under adverse conditions</td><td>Fisher Pen Company, Boulder City, NV</td></tr><tr><td>42</td><td>Forecasting Saharan Dust to Minimize Health Risks</td><td>Air-quality forecast and alert system</td><td>University of Puerto Rico, San Juan, Puerto Rico</td></tr><tr><td>44</td><td>NASA&#x27;s Robotic Glove Finds Commercial Handhold</td><td>Ironhand industrial grip-enhancing robotic glove</td><td>Bioaero Technologies, Stockholm, Sweden</td></tr><tr><td rowspan="3">48</td><td rowspan="3">Safely Detoxifying Soil and Groundwater with NASA Technology</td><td rowspan="3">Emulsified zero-valent iron (EZVI)</td><td>Profectus, Fleetport, IL</td></tr><tr><td>Toxicological and Environmental Associates, Miramar Beach, FL</td></tr><tr><td>Woodard &amp; Curran, Portland, ME</td></tr><tr><td>51</td><td>Expertise Flows from Computer Cognition</td><td>Expert System AI technology</td><td>Terra Systems, Clayton, DE</td></tr><tr><td>53</td><td>Lasers Make Waves in Self-Driving Cars, Quantum Devices</td><td>Optoelectronic oscillator and optical resonator</td><td>Beyond Limits, Glendale, CA</td></tr><tr><td rowspan="2">56</td><td rowspan="2">Lighting in a Bottle</td><td>Circadian rhythm and ultraviolet LED lighting</td><td>O'EIwes, Pasadena, CA</td></tr><tr><td>LED-based grow lights</td><td>Healthie, Orlando, FL</td></tr><tr><td rowspan="2">60</td><td rowspan="2">Clean Air Tech for Spacecraft Helps Fight Pandemic</td><td>Air purifiers based on photocatalytic oxidation</td><td>VividGro, Chicago, IL</td></tr><tr><td>Air-quality sensor to manage indoor environments</td><td>ActivePure Technology, Dallas, TX</td></tr><tr><td rowspan="2">64</td><td rowspan="2">&quot;Reflecting&quot; on Life&#x27;s Daily Challenges</td><td>Jackets with Ultrafast lining</td><td>TFI Environmental, Toronto, Canada</td></tr><tr><td>Jackets with Ultrafast lining</td><td>Airgloss, Rome, Italy</td></tr></table>
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_002_batch_02_Spinoff.2022:p0037:e001` · 页 `37` · 类型 `tab`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_002_batch_02_Spinoff.2022/pages/page_0037/output_json/page_0037.json`
   - bbox：`[50, 80, 728, 746]`

````text
<table><tr><td>Page</td><td>Article</td><td>Technology</td><td>Company, Location</td></tr><tr><td>4</td><td>Measuring Moon Dust to Fight Air Pollution</td><td>Air-quality sensor system</td><td>Lunar Outpost, Denver, CO</td></tr><tr><td>5</td><td>Microbes Help Trees Clean Up Pollution</td><td>Plant endophytes for environmental cleanup</td><td>Intrinsky Environmental, Moffett Field, CA</td></tr><tr><td>6</td><td>Pounding Metal Parts into Profit</td><td>Ultrasonic additive manufacturing</td><td>Fabricious, Columbus, OH</td></tr><tr><td>7</td><td>Water Purification Anywhere on Earth</td><td>Filter medium for water bottles</td><td>nkd LIFE, West Palm Beach, FL</td></tr><tr><td>9</td><td>Plasma Improves 3D Electronics Printing</td><td>Plasma jet 3D electronics printer</td><td>Space Foundry, San Jose, CA</td></tr><tr><td>10</td><td>Computers Tough Enough For Space</td><td>Processor for cubats</td><td>Space Micro, San Diego, CA</td></tr><tr><td>10</td><td>Software Keeps Cloud Traffic Moving</td><td>Portable batch system for computer workloads</td><td>Altair Engineering, Troy, MI</td></tr><tr><td>12</td><td>Antennas Find Their Cool</td><td>Ultra-thin polymer aerogel</td><td>Blueshift Materials, Spencer, MA</td></tr><tr><td>13</td><td>Test Rockets Prepare for Distant Landings</td><td>Rocket-powered vertical takeoff and landing</td><td>Masten Space Systems, Mojave, CA</td></tr><tr><td>14</td><td>Swinging the HamR</td><td>Hybrid remotely piloted aircraft</td><td>Advanced Aircraft Company, Hampton, VA</td></tr><tr><td>15</td><td>Getting Water Out of Snow with NASA Tech</td><td>Lidar and spectrometer sensors, modeling software</td><td>Airborne Snow Observatories, Mammoth Lakes, CA</td></tr><tr><td>16</td><td>Stay Safe with Battery Testing for Space</td><td>Battery testing methods</td><td>Underwaters Laboratories, Northbrook, IL</td></tr><tr><td rowspan="3">17</td><td rowspan="3">Keeping Warmer in the Great Outdoors</td><td rowspan="3">Outdoor gear with new spin on aerogel insulation</td><td>Cold Case Gear, Pagosa Springs, CO</td></tr><tr><td>Outdoor Research, Seattle, WA</td></tr><tr><td>Primal off, Latham, NY</td></tr><tr><td>18</td><td>The &quot;Cobot&quot; Revolution Is Coming</td><td>Bulk metallic glass for robot gears, more</td><td>Amorphology, Pasadena, CA</td></tr><tr><td>19</td><td>Satellite Software Helps Global Forecasting</td><td>Satellite scheduling software</td><td>Orbit Logic, Greenbelt, MD</td></tr><tr><td>20</td><td>From a Lightbox to Lamps</td><td>LED lighting for maintaining circadian rhythms</td><td>Ario, Seattle, WA</td></tr><tr><td>21</td><td>&quot;Positive Energy&quot; Captures Contaminants</td><td>Water filtration medium</td><td>Western Water International, Forestville, MD</td></tr><tr><td>22</td><td>From Spacecrafts to Racing Suits</td><td>Phase-change materials</td><td>Walero, Mooreville, NC</td></tr><tr><td>23</td><td>Some Engineering Is Only Skin Deep</td><td>Surface finishing for 3D-printed superalloys</td><td>REM Surface Engineering, Southington, CT</td></tr><tr><td rowspan="3">26</td><td rowspan="3">A Moveable Feast: Plant Research for Space Advances</td><td rowspan="3">Growing techniques and research data for controlled environment agriculture</td><td>Plenty Unlimited, San Francisco, CA</td></tr><tr><td>Green Sense Farm Holdings, Portage, IN</td></tr><tr><td>Bowery Farming, New York, NY</td></tr><tr><td rowspan="2">30</td><td rowspan="2">NASA Helps Private Lander Shoot for the Moon</td><td>Commercial lunar lander</td><td>CSS Farms, Waterloo, SD</td></tr><tr><td>Drome traffic management app</td><td>Astrobatic Technology, Pittsburgh, PA</td></tr><tr><td rowspan="3">34</td><td rowspan="3">NASA Helps Drones Take Flight</td><td>Detect-and-avoid system for aircraft</td><td>Aviation, Santa Monica, CA</td></tr><tr><td>Drome flight testing environment</td><td>General Atomics, San Diego, CA</td></tr><tr><td>Drome flight testing environment</td><td>CAL Analytics, Beavercreek, OH</td></tr><tr><td>40</td><td>Space Pens, Pencils, and How NASA Takes Notes in Space</td><td>Space Pen for writing under adverse conditions</td><td>Fisher Pen Company, Boulder City, NV</td></tr><tr><td>42</td><td>Forecasting Saharan Dust to Minimize Health Risks</td><td>Air-quality forecast and alert system</td><td>University of Puerto Rico, San Juan, Puerto Rico</td></tr><tr><td>44</td><td>NASA&#x27;s Robotic Glove Finds Commercial Handhold</td><td>Ironhand industrial grip-enhancing robotic glove</td><td>Bioaero Technologies, Stockholm, Sweden</td></tr><tr><td rowspan="3">48</td><td rowspan="3">Safely Detoxifying Soil and Groundwater with NASA Technology</td><td rowspan="3">Emulsified zero-valent iron (EZVI)</td><td>Profectus, Fleetport, IL</td></tr><tr><td>Toxicological and Environmental Associates, Miramar Beach, FL</td></tr><tr><td>Woodard &amp; Curran, Portland, ME</td></tr><tr><td>51</td><td>Expertise Flows from Computer Cognition</td><td>Expert System AI technology</td><td>Terra Systems, Clayton, DE</td></tr><tr><td>53</td><td>Lasers Make Waves in Self-Driving Cars, Quantum Devices</td><td>Optoelectronic oscillator and optical resonator</td><td>Beyond Limits, Glendale, CA</td></tr><tr><td rowspan="2">56</td><td rowspan="2">Lighting in a Bottle</td><td>Circadian rhythm and ultraviolet LED lighting</td><td>O'EIwes, Pasadena, CA</td></tr><tr><td>LED-based grow lights</td><td>Healthie, Orlando, FL</td></tr><tr><td rowspan="2">60</td><td rowspan="2">Clean Air Tech for Spacecraft Helps Fight Pandemic</td><td>Air purifiers based on photocatalytic oxidation</td><td>VividGro, Chicago, IL</td></tr><tr><td>Air-quality sensor to manage indoor environments</td><td>ActivePure Technology, Dallas, TX</td></tr><tr><td rowspan="2">64</td><td rowspan="2">&quot;Reflecting&quot; on Life&#x27;s Daily Challenges</td><td>Jackets with Ultrafast lining</td><td>TFI Environmental, Toronto, Canada</td></tr><tr><td>Jackets with Ultrafast lining</td><td>Airgloss, Rome, Italy</td></tr></table>
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA Spinoff目录的页码/产品/企业索引”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。本段实际是HTML表格/目录索引，缺少明确字段关系，原问却虚构了因果、技术或比较命题；不能把目录整表当作答案。 【建议重写题目】2022年NASA Spinoff目录第4页列出的技术及企业是什么？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #085 行号。**目标操作**：`EXCLUDE_FROM_FACTUAL_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：产品/页码目录表不是技术因果证据；排除或仅做结构化表格定位任务
3. **具体重写目标**：产品/页码目录表不是技术因果证据；排除或仅做结构化表格定位任务。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：此来源是目录/日程/作者/索引类，不足以作为因果知识型 gold。默认 `EXCLUDE_OR_PARK`；只有明确改造成表格/元数据检索任务且 schema、评价指标允许才考虑保留。

**完成门槛**：
该条退出事实型 Gold QA（留审计记录）；若改为元数据任务需有新的明确任务类型、验证过的表格/目录源及可评分答案。

---

### #086 · `auto_new_expansion::real_003_batch_03_NASA_Spinoff_2021::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`VERIFY_SOURCE_MODALITY_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_003_batch_03_NASA_Spinoff_2021`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_003_batch_03_NASA_Spinoff_2021, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
With an eye toward returning samples from Mars, Honeybee Robotic developed a bit that can break off and return a rock core with its arm, but it was not enough to do more than sample both the inner and outer tubes are thicker on one side than on the other. In drift mode, pictured on the left, the thick and thin sides of the tubes are covered with a nice honey bee shaped waxed picture, with the core drilled, the inner and outside has rotated half a turn, putting both the thick sides on the right to show the core loftward and snap it off. This also creates a little "stay" at the end of the video, showing the texture inside the pit for retreat. Credit: Honeybee Robotics/Jimme Smith
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_003_batch_03_NASA_Spinoff_2021:p0016:e010` · 页 `16` · 类型 `cap`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_003_batch_03_NASA_Spinoff_2021/pages/page_0016/output_json/page_0016.json`
   - bbox：`[516, 633, 730, 748]`

````text
With an eye toward returning samples from Mars, Honeybee Robotic developed a bit that can break off and return a rock core with its arm, but it was not enough to do more than sample both the inner and outer tubes are thicker on one side than on the other. In drift mode, pictured on the left, the thick and thin sides of the tubes are covered with a nice honey bee shaped waxed picture, with the core drilled, the inner and outside has rotated half a turn, putting both the thick sides on the right to show the core loftward and snap it off. This also creates a little "stay" at the end of the video, showing the texture inside the pit for retreat. Credit: Honeybee Robotics/Jimme Smith
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“火星岩芯采样钻头与取样难题”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】Honeybee Robotics为火星样本返回任务开发的钻头需解决什么取芯约束？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #086 行号。**目标操作**：`VERIFY_SOURCE_MODALITY_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：图注只涉及 Honeybee Robotics 火星取样钻具；如问工作原理必须追加正文，不可仅凭图注推理
3. **具体重写目标**：图注只涉及 Honeybee Robotics 火星取样钻具；如问工作原理必须追加正文，不可仅凭图注推理。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #087 · `auto_new_expansion::real_003_batch_03_NASA_Spinoff_2021::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`EXCLUDE_FROM_FACTUAL_QA`。
- **文档与节点状态**：`real_003_batch_03_NASA_Spinoff_2021`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`review_status`, `answer_status (if present)`, `benchmark_membership (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_003_batch_03_NASA_Spinoff_2021, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
<table><tr><td>Page</td><td>Article</td><td>Technology</td><td>Company, Location</td></tr><tr><td>4</td><td>TetrUS Stacks Up Building Blocks for Aircraft Design</td><td>Aerodynamics-simulation software</td><td>Helden Aerospace, Acworth, GA</td></tr><tr><td>5</td><td>NASA Research Helps Make Electronics on Demand</td><td>SD Printer for electronic components</td><td>Electronic Alchemy, Huntsville, AL</td></tr><tr><td>6</td><td>Answering the Call of Distress</td><td>Software to improve search and rescue</td><td>Orbit Logic, Greenbelt, MD</td></tr><tr><td>7</td><td>Catch the Waves</td><td>Isolators for spectrum sensors</td><td>Micro Harmonics, Fincastle, VA</td></tr><tr><td>8</td><td>Debugging Code Is Rocket Science</td><td>Software code analyzer</td><td>iKOS, Vejle, Denmark</td></tr><tr><td>9</td><td>Space Fuel Cell Provides Deep-Sea Power</td><td>Fuel cells for offshore drilling</td><td>Telelyne Energy Systems, Hunt Valley, MD</td></tr><tr><td>10</td><td>Eagle Eyes in Treacherous Skies</td><td>Rugged drone</td><td>Black Swift Technologies, Boulder, CO</td></tr><tr><td>11</td><td>Keeping Tabs on the Sky</td><td>Air traffic communications program</td><td>Metron Aviation, Herndon, VA</td></tr><tr><td>12</td><td>Odor-Eliminating Shoe Inserts rely on NASA-Tested Cloth</td><td>Odor-reducing shoe inserts</td><td>Zorpads, New York, NY</td></tr><tr><td>13</td><td>Fix It like an Astronaut with Augmented Reality</td><td>Augmented reality procedures program</td><td>Tietronix Software, Houston, TX</td></tr><tr><td>14</td><td>Hearing Silence from the Stratosphere</td><td>Infrasound microphone</td><td>Stratodynamics, Lewes, DE</td></tr><tr><td>15</td><td>For Work or Play, Comfort All Day</td><td>Chairs with foam, cooling technology</td><td>Raynor Gaming, West Hempstead, NY</td></tr><tr><td>16</td><td>Hot Water on Demand</td><td>Tankless water heater</td><td>Selsco, Houston, TX</td></tr><tr><td>17</td><td>A New Doorway to Space</td><td>Larger-scale commercial airlock</td><td>Nanofricks, Webster, TX</td></tr><tr><td>18</td><td>Communicating via Long-Distance Lasers</td><td>Space-based laser communications</td><td>BridgeComm, Denver, CO</td></tr><tr><td>19</td><td>Smart Glasses Focus Attention</td><td>Attention-training glasses</td><td>Narbis, Amher, PA</td></tr><tr><td>20</td><td>Modeling Airflows to Help Air Filters</td><td>Efficient whole-room air filter</td><td>Health-Mor, Brooklyn, OH</td></tr><tr><td>21</td><td>Taking Out the Trash, NASA-Style</td><td>Plasma arc heater recycling</td><td>InEnTec, Columbia Ridge, Richmond, WA</td></tr><tr><td>22</td><td>Recalibrating Fine Motor Skills</td><td>Motor skills software</td><td>Liddos Holdings, Reston, VA</td></tr><tr><td rowspan="3">24</td><td rowspan="3">The Rewards of Perseverance</td><td>Rock core breakoff drill bits</td><td>Honeybee Robotics, Brooklyn, NY</td></tr><tr><td>Extremely sensitive spectrometer</td><td>Photos Systems, Covina, CA</td></tr><tr><td>Improved circuit board manufacturing</td><td>Tempo Automation, San Francisco, CA</td></tr><tr><td>30</td><td>Medical Mission Control</td><td>Remote health-monitoring system</td><td>Ejetta, San Francisco, CA</td></tr><tr><td rowspan="3">32</td><td rowspan="3">In the Right Hands, NASA Satellite Data and Analysis</td><td>Earth data analysis for conservation</td><td>Digital Earth Africa, Addis Ababa, Ethiopia</td></tr><tr><td>Data tool to manage climate change</td><td>Earthrise Alliance, Washington, DC</td></tr><tr><td>Satellite data for African farmers</td><td>Mercy Corps, Portland, OR</td></tr><tr><td>36</td><td>Cleaning up a Toxic Legacy</td><td>Toxic chemical cleanup</td><td>ecoSPEARS, Altamonte Springs, FL</td></tr><tr><td rowspan="3">38</td><td rowspan="3">Space-Age Water Conservation</td><td>Water-recycling shower</td><td>Orbital Systems, Malmo, Sweden</td></tr><tr><td>Filtration for water softeners</td><td>Puronics, Livermore, CA</td></tr><tr><td>Forward-osmosis water purification</td><td>Aquaporin, Copenhagen, Denmark</td></tr><tr><td>42</td><td>In Cloud Computing, Open Source Becomes Big Business</td><td>Open source cloud computing infrastructure</td><td>Red Hat, Raleigh, NC</td></tr><tr><td rowspan="4">46</td><td rowspan="4">A Case Made in Space</td><td>Aerogel-insulated bottle</td><td>CamelBak, Petaluma, CA</td></tr><tr><td>Liquid cooling pump for supercomputing</td><td>Chillilyme, Carlsbad, CA</td></tr><tr><td>Durable polymer for medical implants</td><td>Imitec, Schenectady, NY</td></tr><tr><td>Precise, high-temperature sensors</td><td>Intelligent Fiber Optic Systems, San Jose, CA</td></tr><tr><td>50</td><td>Gecko Gripper Finally Sticks</td><td>Industrial robotic gripper</td><td>OnRobot, Culver City, CA</td></tr><tr><td rowspan="2">52</td><td rowspan="2">Planets Take Virtual Shape on Earth with NASA Knowledge and Imagery</td><td>Immersive virtual reality experience</td><td>Google, Mountain View, CA</td></tr><tr><td>Planet and Moon models with VR</td><td>Quantum AR Technologies, Cupertino, CA</td></tr><tr><td>56</td><td>Airports Go Digital</td><td>Digital airport communications</td><td>Telrad, Delmar, NY</td></tr><tr><td rowspan="3">58</td><td rowspan="3">Food Safety Program for Space Has Taken Over on Earth</td><td rowspan="3">Hazard prevention protocol for food</td><td>Butterball, Garner, NC</td></tr><tr><td>Pillsbury/General Mills, Minneapolis, MN</td></tr><tr><td>Ocean Spray, Lakeville-Middleboro, MA</td></tr></table>
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_003_batch_03_NASA_Spinoff_2021:p0035:e001` · 页 `35` · 类型 `tab`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_003_batch_03_NASA_Spinoff_2021/pages/page_0035/output_json/page_0035.json`
   - bbox：`[50, 86, 699, 746]`

````text
<table><tr><td>Page</td><td>Article</td><td>Technology</td><td>Company, Location</td></tr><tr><td>4</td><td>TetrUS Stacks Up Building Blocks for Aircraft Design</td><td>Aerodynamics-simulation software</td><td>Helden Aerospace, Acworth, GA</td></tr><tr><td>5</td><td>NASA Research Helps Make Electronics on Demand</td><td>SD Printer for electronic components</td><td>Electronic Alchemy, Huntsville, AL</td></tr><tr><td>6</td><td>Answering the Call of Distress</td><td>Software to improve search and rescue</td><td>Orbit Logic, Greenbelt, MD</td></tr><tr><td>7</td><td>Catch the Waves</td><td>Isolators for spectrum sensors</td><td>Micro Harmonics, Fincastle, VA</td></tr><tr><td>8</td><td>Debugging Code Is Rocket Science</td><td>Software code analyzer</td><td>iKOS, Vejle, Denmark</td></tr><tr><td>9</td><td>Space Fuel Cell Provides Deep-Sea Power</td><td>Fuel cells for offshore drilling</td><td>Telelyne Energy Systems, Hunt Valley, MD</td></tr><tr><td>10</td><td>Eagle Eyes in Treacherous Skies</td><td>Rugged drone</td><td>Black Swift Technologies, Boulder, CO</td></tr><tr><td>11</td><td>Keeping Tabs on the Sky</td><td>Air traffic communications program</td><td>Metron Aviation, Herndon, VA</td></tr><tr><td>12</td><td>Odor-Eliminating Shoe Inserts rely on NASA-Tested Cloth</td><td>Odor-reducing shoe inserts</td><td>Zorpads, New York, NY</td></tr><tr><td>13</td><td>Fix It like an Astronaut with Augmented Reality</td><td>Augmented reality procedures program</td><td>Tietronix Software, Houston, TX</td></tr><tr><td>14</td><td>Hearing Silence from the Stratosphere</td><td>Infrasound microphone</td><td>Stratodynamics, Lewes, DE</td></tr><tr><td>15</td><td>For Work or Play, Comfort All Day</td><td>Chairs with foam, cooling technology</td><td>Raynor Gaming, West Hempstead, NY</td></tr><tr><td>16</td><td>Hot Water on Demand</td><td>Tankless water heater</td><td>Selsco, Houston, TX</td></tr><tr><td>17</td><td>A New Doorway to Space</td><td>Larger-scale commercial airlock</td><td>Nanofricks, Webster, TX</td></tr><tr><td>18</td><td>Communicating via Long-Distance Lasers</td><td>Space-based laser communications</td><td>BridgeComm, Denver, CO</td></tr><tr><td>19</td><td>Smart Glasses Focus Attention</td><td>Attention-training glasses</td><td>Narbis, Amher, PA</td></tr><tr><td>20</td><td>Modeling Airflows to Help Air Filters</td><td>Efficient whole-room air filter</td><td>Health-Mor, Brooklyn, OH</td></tr><tr><td>21</td><td>Taking Out the Trash, NASA-Style</td><td>Plasma arc heater recycling</td><td>InEnTec, Columbia Ridge, Richmond, WA</td></tr><tr><td>22</td><td>Recalibrating Fine Motor Skills</td><td>Motor skills software</td><td>Liddos Holdings, Reston, VA</td></tr><tr><td rowspan="3">24</td><td rowspan="3">The Rewards of Perseverance</td><td>Rock core breakoff drill bits</td><td>Honeybee Robotics, Brooklyn, NY</td></tr><tr><td>Extremely sensitive spectrometer</td><td>Photos Systems, Covina, CA</td></tr><tr><td>Improved circuit board manufacturing</td><td>Tempo Automation, San Francisco, CA</td></tr><tr><td>30</td><td>Medical Mission Control</td><td>Remote health-monitoring system</td><td>Ejetta, San Francisco, CA</td></tr><tr><td rowspan="3">32</td><td rowspan="3">In the Right Hands, NASA Satellite Data and Analysis</td><td>Earth data analysis for conservation</td><td>Digital Earth Africa, Addis Ababa, Ethiopia</td></tr><tr><td>Data tool to manage climate change</td><td>Earthrise Alliance, Washington, DC</td></tr><tr><td>Satellite data for African farmers</td><td>Mercy Corps, Portland, OR</td></tr><tr><td>36</td><td>Cleaning up a Toxic Legacy</td><td>Toxic chemical cleanup</td><td>ecoSPEARS, Altamonte Springs, FL</td></tr><tr><td rowspan="3">38</td><td rowspan="3">Space-Age Water Conservation</td><td>Water-recycling shower</td><td>Orbital Systems, Malmo, Sweden</td></tr><tr><td>Filtration for water softeners</td><td>Puronics, Livermore, CA</td></tr><tr><td>Forward-osmosis water purification</td><td>Aquaporin, Copenhagen, Denmark</td></tr><tr><td>42</td><td>In Cloud Computing, Open Source Becomes Big Business</td><td>Open source cloud computing infrastructure</td><td>Red Hat, Raleigh, NC</td></tr><tr><td rowspan="4">46</td><td rowspan="4">A Case Made in Space</td><td>Aerogel-insulated bottle</td><td>CamelBak, Petaluma, CA</td></tr><tr><td>Liquid cooling pump for supercomputing</td><td>Chillilyme, Carlsbad, CA</td></tr><tr><td>Durable polymer for medical implants</td><td>Imitec, Schenectady, NY</td></tr><tr><td>Precise, high-temperature sensors</td><td>Intelligent Fiber Optic Systems, San Jose, CA</td></tr><tr><td>50</td><td>Gecko Gripper Finally Sticks</td><td>Industrial robotic gripper</td><td>OnRobot, Culver City, CA</td></tr><tr><td rowspan="2">52</td><td rowspan="2">Planets Take Virtual Shape on Earth with NASA Knowledge and Imagery</td><td>Immersive virtual reality experience</td><td>Google, Mountain View, CA</td></tr><tr><td>Planet and Moon models with VR</td><td>Quantum AR Technologies, Cupertino, CA</td></tr><tr><td>56</td><td>Airports Go Digital</td><td>Digital airport communications</td><td>Telrad, Delmar, NY</td></tr><tr><td rowspan="3">58</td><td rowspan="3">Food Safety Program for Space Has Taken Over on Earth</td><td rowspan="3">Hazard prevention protocol for food</td><td>Butterball, Garner, NC</td></tr><tr><td>Pillsbury/General Mills, Minneapolis, MN</td></tr><tr><td>Ocean Spray, Lakeville-Middleboro, MA</td></tr></table>
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA Spinoff目录表格”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。本段实际是HTML表格/目录索引，缺少明确字段关系，原问却虚构了因果、技术或比较命题；不能把目录整表当作答案。 【建议重写题目】2021年NASA Spinoff目录第4页介绍的产品、用途和公司分别是什么？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #087 行号。**目标操作**：`EXCLUDE_FROM_FACTUAL_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：NASA Spinoff 目录表，不是机制或比较论证；排除
3. **具体重写目标**：NASA Spinoff 目录表，不是机制或比较论证；排除。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：此来源是目录/日程/作者/索引类，不足以作为因果知识型 gold。默认 `EXCLUDE_OR_PARK`；只有明确改造成表格/元数据检索任务且 schema、评价指标允许才考虑保留。

**完成门槛**：
该条退出事实型 Gold QA（留审计记录）；若改为元数据任务需有新的明确任务类型、验证过的表格/目录源及可评分答案。

---

### #088 · `auto_new_expansion::real_004_batch_04_Spinoff2020::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`real_004_batch_04_Spinoff2020`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_004_batch_04_Spinoff2020, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
This was especially important for projects like the Two- Phase Flow Separator Experiment and the Packed Bed Reactor Experiment, both of which Motil oversaw. The former aimed to separate air and water through inertia by spinning them. The latter observed how air and water moved together through a packed bed reactor, a type of device that directs substances into a vessel packed with a catalyst to create desired reactions. Packed bed reactors are used on the International Space Station in air and water purification systems, fuel cells, and other devices, as well as in many applications on Earth. Currently, none of the packed bed reactors on the space station handle both liquid and gas, because scientists don't know how a two-phase system would perform in microgravity, but such a device would promise more efficient thermal-management and life-support systems.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_004_batch_04_Spinoff2020:p0156:e005` · 页 `156` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_004_batch_04_Spinoff2020/pages/page_0156/output_json/page_0156.json`
   - bbox：`[94, 625, 550, 1022]`

````text
This was especially important for projects like the Two- Phase Flow Separator Experiment and the Packed Bed Reactor Experiment, both of which Motil oversaw. The former aimed to separate air and water through inertia by spinning them. The latter observed how air and water moved together through a packed bed reactor, a type of device that directs substances into a vessel packed with a catalyst to create desired reactions. Packed bed reactors are used on the International Space Station in air and water purification systems, fuel cells, and other devices, as well as in many applications on Earth. Currently, none of the packed bed reactors on the space station handle both liquid and gas, because scientists don't know how a two-phase system would perform in microgravity, but such a device would promise more efficient thermal-management and life-support systems.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“微重力气液分离与填充床反应实验”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】Two-Phase Flow Separator Experiment采用什么物理方式分离空气与水？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #088 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：微重力条件下两相流分离与填充床实验的物理挑战；检查本段是否包含完整流程
3. **具体重写目标**：微重力条件下两相流分离与填充床实验的物理挑战；检查本段是否包含完整流程。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #089 · `auto_new_expansion::real_004_batch_04_Spinoff2020::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_004_batch_04_Spinoff2020`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_004_batch_04_Spinoff2020, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Foreword Even as NASA continues to unpack data from the most distant world ever visited—Ultima Thule, which the New Horizons probe zoomed past 4 billion miles from Earth at the start of last year—the Space Agency never takes its eyes off our home planet. In fact, the Agency's longest continually operated program is the Technology Transfer Program, which works to put the countless innovations that drive space exploration into the hands of U.S. companies and entrepreneurs. Now, as we gear up to send astronauts back to the Moon for the first time in more than half a century, those inven- tions and advances will only multiply. As always, NASA will rely on many commercial industry partners to help carry out this ambitious mission, which will see the first woman and next man set foot on the Moon and establish sustainable lunar exploration with our commercial and international partners by 2028. Just as the Apollo Program yielded some of NASA's most important commercial spinoffs and advanced the state of the Nation's technology, these new partnerships under the Artemis Program are sure to produce innovations that will benefit all Americans. Already, the Space Agency is partnering with com- panies to deliver payloads to the Moon through its new Commercial Lunar Payload Services program. Other companies are responding to calls to provide some of those payloads in the form of scientific instruments and technology investigations. We also selected 11 companies to study options and build prototype elements for landers as part of the Next Space Technologies for Exploration Partnerships program. These landers will carry astronauts from the lunar space station—named Gateway—to the Moon's surface. One day, companies will operate these landers commercially. NASA itself is also developing cutting edge technology demonstration payloads designed to prepare for our lunar future, including systems to prospect for resources, gather data on the environment, assist precision landing, and try out advanced solar arrays, among others. In the future, whether companies license technology NASA develops under Artemis, commercialize their own solutions to new lunar challenges, or use NASA scientific data or software in other applications, there are many avenues for these technologies to take on their own lives as commercial spinoffs benefiting the public. The Space Launch System, NASA's next-generation rocket that could make its first test run to the Moon as soon as this year, and the Orion capsule that's planned to carry astronauts to lunar orbit in 2022 have already led to several products documented in earlier editions of Spinoff with more to come. As you learn about the contributions that the 50 technologies featured in Spinoff 2020 have made to our economy, our planet, and our quality of life, imagine what might be possible in the future, as we take on the grand challenges of establishing a permanent human outpost on the natural satellite where humanity once briefly stepped. Jim Bridenstine Administrator National Aeronautics and Space Administration Spinoff 2020 5
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_004_batch_04_Spinoff2020:p0007:e000` · 页 `7` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_004_batch_04_Spinoff2020/pages/page_0007/output_json/page_0007.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Foreword Even as NASA continues to unpack data from the most distant world ever visited—Ultima Thule, which the New Horizons probe zoomed past 4 billion miles from Earth at the start of last year—the Space Agency never takes its eyes off our home planet. In fact, the Agency's longest continually operated program is the Technology Transfer Program, which works to put the countless innovations that drive space exploration into the hands of U.S. companies and entrepreneurs. Now, as we gear up to send astronauts back to the Moon for the first time in more than half a century, those inven- tions and advances will only multiply. As always, NASA will rely on many commercial industry partners to help carry out this ambitious mission, which will see the first woman and next man set foot on the Moon and establish sustainable lunar exploration with our commercial and international partners by 2028. Just as the Apollo Program yielded some of NASA's most important commercial spinoffs and advanced the state of the Nation's technology, these new partnerships under the Artemis Program are sure to produce innovations that will benefit all Americans. Already, the Space Agency is partnering with com- panies to deliver payloads to the Moon through its new Commercial Lunar Payload Services program. Other companies are responding to calls to provide some of those payloads in the form of scientific instruments and technology investigations. We also selected 11 companies to study options and build prototype elements for landers as part of the Next Space Technologies for Exploration Partnerships program. These landers will carry astronauts from the lunar space station—named Gateway—to the Moon's surface. One day, companies will operate these landers commercially. NASA itself is also developing cutting edge technology demonstration payloads designed to prepare for our lunar future, including systems to prospect for resources, gather data on the environment, assist precision landing, and try out advanced solar arrays, among others. In the future, whether companies license technology NASA develops under Artemis, commercialize their own solutions to new lunar challenges, or use NASA scientific data or software in other applications, there are many avenues for these technologies to take on their own lives as commercial spinoffs benefiting the public. The Space Launch System, NASA's next-generation rocket that could make its first test run to the Moon as soon as this year, and the Orion capsule that's planned to carry astronauts to lunar orbit in 2022 have already led to several products documented in earlier editions of Spinoff with more to come. As you learn about the contributions that the 50 technologies featured in Spinoff 2020 have made to our economy, our planet, and our quality of life, imagine what might be possible in the future, as we take on the grand challenges of establishing a permanent human outpost on the natural satellite where humanity once briefly stepped. Jim Bridenstine Administrator National Aeronautics and Space Administration Spinoff 2020 5
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA Spinoff卷首语介绍Ultima Thule飞掠”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。材料属于目录、活动安排、概述或标题型文字，不保证存在单一可验证的机制或结论；应先判断该节点是否适合生成问答。 【建议重写题目】卷首语以哪次外太阳系飞掠为例说明NASA持续进行的探索？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #089 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先重解析卷首语与 Ultima Thule 飞掠段，再考虑生成 QA
3. **具体重写目标**：整页混合/错序抽取：先重解析卷首语与 Ultima Thule 飞掠段，再考虑生成 QA。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #090 · `auto_new_expansion::real_005_batch_05_Spinoff2019::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_005_batch_05_Spinoff2019`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_005_batch_05_Spinoff2019, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Benefits Calculations of crop coverage, type, health, and growth, and especially forecasts of crop productivity interest organi- zations like the U.S. Department of Agriculture's (USDA) Foreign Agricultural Service, which provides unbiased commodity estimates and forecasts to create a marketing edge for U.S. producers in world markets. As GDA amassed enough global crop data to develop commercial products, the agricultural service became its biggest customer, but others, such as agricultural insur- ance companies, grain and commodity traders, and food transporters, also became clients, Hulina says. "Anybody who really needs to know where crops are, how they're progressing through the growing season, and what the output will be" is a potential customer, she adds. For commercial customers, GDA offers real-time and historical image-based data for 16 major crops around the world. This "agricultural intelligence" includes maps of crop coverage, acreage totals, ground conditions, crop health, and forecasts of yield per acre and overall global protection. These can also be broken down to national and state levels. The system pulls imaging from multiple sensors on several satellites, which vary in resolution, spectral bands, how wide a swath they can see, and how often they pass over a given area, letting the company tailor products to meet a wide range of needs. GDA says it's the only company to combine all these capabilities on a global scale. Its relatively new GeoSynergy webGIS service puts them all in one place to let the user manipulate and analyze calibrated, full-resolution current and historical imagery and data. Varylu gin says the company plans to continue adding new capabilities, as well as new sources of imagery as they become available. The Foreign Agricultural Service uses GDA's tools, among other sources, to create its monthly production estimates for all major commodity crops, and Hulina notes that crop futures markets move according to those estimates. "We are the only remote sensing firm supplying that line of evidence," she says. The estimates also help the service predict shortages to help direct its food aid programs. The company also counts the U.S. Geological Survey (USGS), the U.S. Forest Service, and the USDA's National Agricultural Statistics Service with its customers. But the company's success wouldn't be possible without two important Government initiatives, Varlyguin says. Earth-imaging analysis on a global scale wouldn't be feasible without free satellite im- agery. Landsat images, for example, cost hundreds to thousands of dollars per scene until the USGS decided in 2008 to make them free. And the SBIR program, he says, "is extremely beneficial, not just to GDA but to overall research and development. Without that, a lot of companies, including GDA, would be very different than they are." This map shows the correlations between GDA Corporation's crop yield forecasts and the U.S. Department of Agriculture's forecasts at the county level between 2005 and 2017 in the American Midwest, with deeper greens indicating higher correlation and reds showing less correlation. Areas with more complete historical data generate more consistent and accurate forecasts. Spoinoff 2019 Energy and Environment 123
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_005_batch_05_Spinoff2019:p0124:e000` · 页 `124` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_005_batch_05_Spinoff2019/pages/page_0124/output_json/page_0124.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Benefits Calculations of crop coverage, type, health, and growth, and especially forecasts of crop productivity interest organi- zations like the U.S. Department of Agriculture's (USDA) Foreign Agricultural Service, which provides unbiased commodity estimates and forecasts to create a marketing edge for U.S. producers in world markets. As GDA amassed enough global crop data to develop commercial products, the agricultural service became its biggest customer, but others, such as agricultural insur- ance companies, grain and commodity traders, and food transporters, also became clients, Hulina says. "Anybody who really needs to know where crops are, how they're progressing through the growing season, and what the output will be" is a potential customer, she adds. For commercial customers, GDA offers real-time and historical image-based data for 16 major crops around the world. This "agricultural intelligence" includes maps of crop coverage, acreage totals, ground conditions, crop health, and forecasts of yield per acre and overall global protection. These can also be broken down to national and state levels. The system pulls imaging from multiple sensors on several satellites, which vary in resolution, spectral bands, how wide a swath they can see, and how often they pass over a given area, letting the company tailor products to meet a wide range of needs. GDA says it's the only company to combine all these capabilities on a global scale. Its relatively new GeoSynergy webGIS service puts them all in one place to let the user manipulate and analyze calibrated, full-resolution current and historical imagery and data. Varylu gin says the company plans to continue adding new capabilities, as well as new sources of imagery as they become available. The Foreign Agricultural Service uses GDA's tools, among other sources, to create its monthly production estimates for all major commodity crops, and Hulina notes that crop futures markets move according to those estimates. "We are the only remote sensing firm supplying that line of evidence," she says. The estimates also help the service predict shortages to help direct its food aid programs. The company also counts the U.S. Geological Survey (USGS), the U.S. Forest Service, and the USDA's National Agricultural Statistics Service with its customers. But the company's success wouldn't be possible without two important Government initiatives, Varlyguin says. Earth-imaging analysis on a global scale wouldn't be feasible without free satellite im- agery. Landsat images, for example, cost hundreds to thousands of dollars per scene until the USGS decided in 2008 to make them free. And the SBIR program, he says, "is extremely beneficial, not just to GDA but to overall research and development. Without that, a lot of companies, including GDA, would be very different than they are." This map shows the correlations between GDA Corporation's crop yield forecasts and the U.S. Department of Agriculture's forecasts at the county level between 2005 and 2017 in the American Midwest, with deeper greens indicating higher correlation and reds showing less correlation. Areas with more complete historical data generate more consistent and accurate forecasts. Spoinoff 2019 Energy and Environment 123
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“作物覆盖、健康与产量预测的遥感用途”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么USDA海外农业部门关心通过遥感估计作物覆盖率和产量？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #090 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复作物类型/健康/产量遥感段落，再确定正确证据单元
3. **具体重写目标**：整页混合/错序抽取：先恢复作物类型/健康/产量遥感段落，再确定正确证据单元。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #091 · `auto_new_expansion::real_005_batch_05_Spinoff2019::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_005_batch_05_Spinoff2019`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_005_batch_05_Spinoff2019, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
The X-57 team is also helping to shape safety and testing requirements for electric and hybrid aircraft by sharing its work with industry standards boards, Cobleigh says, noting that companies often would be reluctant to share such information. "NASA makes sure everyone learns the lessons taxpayer dollars paid for." Benefits Electric motors are far more efficient than internal combustion engines and require much less maintenance, replacing the high heat and friction of combustion chambers and pistons with wound wires and magnets, Cobleigh points out. They are 90 percent efficient or better, meaning almost all the power is turned into useful work, while gas-powered engines are less than 30 percent efficient. Bye Aerospace calculates that the Sun Flyer will operate at a cost of $3 per hour. Electric motors also generate lower noise and no emis- sions. The low-hanging fruit for all-electric aircraft take-off and landing vehicles for transportation within cities, Cobleigh says, both of which would be far easier to turn a profit on with the lower fuel and maintenance costs of electric aircraft. Millecam says EP Systems has received considerable interest—and yet-unannounced contracts—in all those markets. Although the technology has a long way to go before there are three- or four-hour electric flights on large passenger airplanes, he says, "The technology is at the point now where it can be utilized on new vehicle concepts and new aviation business models." Without the assist from Armstrong, though, electric propulsion batteries might not have gotten off the ground, he says. "If NASA didn't have the foresight to see aviation going this way and the problems that need to be solved to get it there, this never would have happened." Clarke notes that the project didn't even set out to research batteries. It aimed to test efficient wing designs and power distribution systems. "And we ended up with this innovative component that's useful in industry now." The X-57 is planned to make its first electric flight this year but will continue to evolve over the next few years. In its final form, it's expected to run on about a fifth of the energy it would as a gap-powered craft. ❖ Bye Aerospace's Sun Flyer, an all-electric training airplane that's already begun flight testing, is powered by a battery pack that EP Systems based on the one it built, with NASA funding and expertise, for the X-57 aircraft. 42 Transportation
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_005_batch_05_Spinoff2019:p0043:e000` · 页 `43` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_005_batch_05_Spinoff2019/pages/page_0043/output_json/page_0043.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
The X-57 team is also helping to shape safety and testing requirements for electric and hybrid aircraft by sharing its work with industry standards boards, Cobleigh says, noting that companies often would be reluctant to share such information. "NASA makes sure everyone learns the lessons taxpayer dollars paid for." Benefits Electric motors are far more efficient than internal combustion engines and require much less maintenance, replacing the high heat and friction of combustion chambers and pistons with wound wires and magnets, Cobleigh points out. They are 90 percent efficient or better, meaning almost all the power is turned into useful work, while gas-powered engines are less than 30 percent efficient. Bye Aerospace calculates that the Sun Flyer will operate at a cost of $3 per hour. Electric motors also generate lower noise and no emis- sions. The low-hanging fruit for all-electric aircraft take-off and landing vehicles for transportation within cities, Cobleigh says, both of which would be far easier to turn a profit on with the lower fuel and maintenance costs of electric aircraft. Millecam says EP Systems has received considerable interest—and yet-unannounced contracts—in all those markets. Although the technology has a long way to go before there are three- or four-hour electric flights on large passenger airplanes, he says, "The technology is at the point now where it can be utilized on new vehicle concepts and new aviation business models." Without the assist from Armstrong, though, electric propulsion batteries might not have gotten off the ground, he says. "If NASA didn't have the foresight to see aviation going this way and the problems that need to be solved to get it there, this never would have happened." Clarke notes that the project didn't even set out to research batteries. It aimed to test efficient wing designs and power distribution systems. "And we ended up with this innovative component that's useful in industry now." The X-57 is planned to make its first electric flight this year but will continue to evolve over the next few years. In its final form, it's expected to run on about a fifth of the energy it would as a gap-powered craft. ❖ Bye Aerospace's Sun Flyer, an all-electric training airplane that's already begun flight testing, is powered by a battery pack that EP Systems based on the one it built, with NASA funding and expertise, for the X-57 aircraft. 42 Transportation
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“X-57对电动混合动力航空标准的影响”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】X-57团队为什么与行业标准制定机构分享其电动航空测试结果？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #091 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复 X-57 电动飞机安全和测试需求的正文段落
3. **具体重写目标**：整页混合/错序抽取：先恢复 X-57 电动飞机安全和测试需求的正文段落。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #092 · `auto_new_expansion::real_006_batch_06_Spinoff2018::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_006_batch_06_Spinoff2018`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_006_batch_06_Spinoff2018, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
But the young company wasn't ready to rest on its laurels. When we made the original jacket with these aerogel blankets, we learned that they were amazing insulators, and they were good for apparel—but not great,” Markesbery recalled. They noticed two main issues. First, the silica had a tendency to flake out of the fiber blanket with movement, a problem for a jacket intended for athletes. "Every time you move you're losing thermal performance you never get back," he said. The second problem was that the silica aerogel itself tends to suck out moisture on contact, "so if you touch it with your skin or your hand, it would dry out your skin. That meant we had to encapsulate the insulation, like a Ziploc baggie. That cut the breathability down to virtually zero. "We said this is a really good first step and market validation for aerogel use. But it can still get better. We needed a flexible sheet that maintained its insulation, but that didn't shed with motion," Markesbery says. The company continued its research and ultimately came up with a new, proprietary way to utilize aerogel in a flexible polymer composite, which it says provides more structure and stability than the fiber blanket. It also increases breathability for comfort and reduces the overall weight of the insulation. As a result, the next-generation jacket is at least 40 percent lighter than the original, weighing in at just 2.5 pounds or less. Oros calls its new, proprietary insulation SolarCore and used it in its products in 2016 and 2017—a product line that has been extended to include gloves, leggings, snow pants, and base-layer shirts. Even the knit hats are insulated with SolarCore, which is knitted into the brim. The company brag the insulation is so warm, it has added zippered vents in the jacket and snow pants in case the wearer overheats—all with just 3 millimeters of insulation. The company continues its research into aerogel upgrades, with more improvements planned in the next release of products in fall 2018. But the original product line and core and inspiration for development started with aerogel's NASA roots. As Markesbery says: "If it's good enough for space, shouldn't it be good enough for Earth?"♖ "If it's" good enough for space, shouldn't it be good enough for Earth?" — Michael Markesbery, Oros Oros makes extra-lightweight outwear lined with aerogel- infused insulation. NASA helped drive the innovations that made aerogel practical for apparel—in its original form, silica aerogel was extremely brittle, but it can be used in composites that are durable and flexible. Spinoff 2018 Consumer Goods 85
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_006_batch_06_Spinoff2018:p0086:e000` · 页 `86` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_006_batch_06_Spinoff2018/pages/page_0086/output_json/page_0086.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
But the young company wasn't ready to rest on its laurels. When we made the original jacket with these aerogel blankets, we learned that they were amazing insulators, and they were good for apparel—but not great,” Markesbery recalled. They noticed two main issues. First, the silica had a tendency to flake out of the fiber blanket with movement, a problem for a jacket intended for athletes. "Every time you move you're losing thermal performance you never get back," he said. The second problem was that the silica aerogel itself tends to suck out moisture on contact, "so if you touch it with your skin or your hand, it would dry out your skin. That meant we had to encapsulate the insulation, like a Ziploc baggie. That cut the breathability down to virtually zero. "We said this is a really good first step and market validation for aerogel use. But it can still get better. We needed a flexible sheet that maintained its insulation, but that didn't shed with motion," Markesbery says. The company continued its research and ultimately came up with a new, proprietary way to utilize aerogel in a flexible polymer composite, which it says provides more structure and stability than the fiber blanket. It also increases breathability for comfort and reduces the overall weight of the insulation. As a result, the next-generation jacket is at least 40 percent lighter than the original, weighing in at just 2.5 pounds or less. Oros calls its new, proprietary insulation SolarCore and used it in its products in 2016 and 2017—a product line that has been extended to include gloves, leggings, snow pants, and base-layer shirts. Even the knit hats are insulated with SolarCore, which is knitted into the brim. The company brag the insulation is so warm, it has added zippered vents in the jacket and snow pants in case the wearer overheats—all with just 3 millimeters of insulation. The company continues its research into aerogel upgrades, with more improvements planned in the next release of products in fall 2018. But the original product line and core and inspiration for development started with aerogel's NASA roots. As Markesbery says: "If it's good enough for space, shouldn't it be good enough for Earth?"♖ "If it's" good enough for space, shouldn't it be good enough for Earth?" — Michael Markesbery, Oros Oros makes extra-lightweight outwear lined with aerogel- infused insulation. NASA helped drive the innovations that made aerogel practical for apparel—in its original form, silica aerogel was extremely brittle, but it can be used in composites that are durable and flexible. Spinoff 2018 Consumer Goods 85
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“气凝胶保温夹克在实际服饰中的限制”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么最初采用气凝胶毯的服装设计虽保温出色却不适合日常穿着？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #092 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复气凝胶夹克商业用途的真实局限，避免从混合页面推理
3. **具体重写目标**：整页混合/错序抽取：先恢复气凝胶夹克商业用途的真实局限，避免从混合页面推理。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #093 · `auto_new_expansion::real_006_batch_06_Spinoff2018::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_006_batch_06_Spinoff2018`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_006_batch_06_Spinoff2018, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
2D Analysis Software Clarifies Medical, Weather, Intelligence Images NASA Technology ASA engineer Sennion Kizhner spent an entire week trying to understand the Hilbert-Huang Transform with the colleague who had devel- oped it, but to no avail. He hoped to develop a software that would get people using this powerful but complex new algorithm, he says, because he saw great potential in it that might require decades of development. Fortunately, no one needs to fully understand a transform to use it. "I have no clue how intestines work, but that doesn't prevent me from eating," says Kizhner, now recently retired from Goddard Space Flight Center's Instrument Electronics Development Branch. A transform—essentially, a particular type of math- ematical formula—helps scientists gather information from complex data. For example, Kizhner says, he might not be able to interpret the raw data from an electrocardiogram reading, but transforming the data into the frequency domain might show that something is happening about once a second, which is the normal respiration rate—a clue suggesting the phenomenon is probably associated with breathing. "You try to apply some known transform, and if you're lucky, it will give you something you understand," Kizhner says. One of the most commonly used transforms is the century-old Fourier Transform, originally devised to study heat transfer but now used in applications as diverse as quantum mechanics and digital image compression. The Fourier Transform, however, has severe limitations when it comes to analyzing natural phenomena. Kizhner had been looking for an alternative, and the Hilbert-Huang Transform (HHT), created by Goddard chief scientist for oceanography Norden Huang, seemed like a promising option. It's the product of the oceanographer's nearly four decades of attempts to come up with a transform that could make more sense of data on ocean waves and atmospheric turbulence. It breaks down a one-dimensional signal into a series of what Huang called intrinsic mode functions, isolating various frequencies, and then applies the preexisting one-dimensional Hilbert spectral analysis to decompose frequency components. Kizhner notes that the Royal Society of London published all of Huang's 100-page paper on the subject despite the organization's 10-page limit. "Obviously, someone was impressed." Although Kizhner still struggled to understand the mechanics of the transform, he and one of his students, Karin Blank, were able to write software to apply it, with initial funding from Goddard's Internal Research and Development (IRAD) Program. The resulting HHT Data Processing System software for one-dimensional data, which can be licensed from Goddard, works well beyond oceanography. "HHT1 works on data like nothing else before it, and people are using it all over the world," Kizhner says; including to help monitor blood flow in the brain after brain injuries (Spinoff 2010). In 2006, the Federal Laboratory Consortium's mid-Atlantic region named the software Best Technology of the Year. But Kizhner—and many others, including Huang himself—were looking for a way to use the transform in two dimensions to analyze images. "There are certain things in image processing that cannot be done well with existing techniques, so we always strive to find something new," he says. Goddard engineer Sennion Kizhner's two-dimensional version of the Hilbert-Huang Transform was first tried out on the radiometer for NASA's Soil Moisture Active Passive (SMAP) satellite, where it eliminates radio interference from imagery. 122 Information Technology Spinoff 2018
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_006_batch_06_Spinoff2018:p0123:e000` · 页 `123` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_006_batch_06_Spinoff2018/pages/page_0123/output_json/page_0123.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
2D Analysis Software Clarifies Medical, Weather, Intelligence Images NASA Technology ASA engineer Sennion Kizhner spent an entire week trying to understand the Hilbert-Huang Transform with the colleague who had devel- oped it, but to no avail. He hoped to develop a software that would get people using this powerful but complex new algorithm, he says, because he saw great potential in it that might require decades of development. Fortunately, no one needs to fully understand a transform to use it. "I have no clue how intestines work, but that doesn't prevent me from eating," says Kizhner, now recently retired from Goddard Space Flight Center's Instrument Electronics Development Branch. A transform—essentially, a particular type of math- ematical formula—helps scientists gather information from complex data. For example, Kizhner says, he might not be able to interpret the raw data from an electrocardiogram reading, but transforming the data into the frequency domain might show that something is happening about once a second, which is the normal respiration rate—a clue suggesting the phenomenon is probably associated with breathing. "You try to apply some known transform, and if you're lucky, it will give you something you understand," Kizhner says. One of the most commonly used transforms is the century-old Fourier Transform, originally devised to study heat transfer but now used in applications as diverse as quantum mechanics and digital image compression. The Fourier Transform, however, has severe limitations when it comes to analyzing natural phenomena. Kizhner had been looking for an alternative, and the Hilbert-Huang Transform (HHT), created by Goddard chief scientist for oceanography Norden Huang, seemed like a promising option. It's the product of the oceanographer's nearly four decades of attempts to come up with a transform that could make more sense of data on ocean waves and atmospheric turbulence. It breaks down a one-dimensional signal into a series of what Huang called intrinsic mode functions, isolating various frequencies, and then applies the preexisting one-dimensional Hilbert spectral analysis to decompose frequency components. Kizhner notes that the Royal Society of London published all of Huang's 100-page paper on the subject despite the organization's 10-page limit. "Obviously, someone was impressed." Although Kizhner still struggled to understand the mechanics of the transform, he and one of his students, Karin Blank, were able to write software to apply it, with initial funding from Goddard's Internal Research and Development (IRAD) Program. The resulting HHT Data Processing System software for one-dimensional data, which can be licensed from Goddard, works well beyond oceanography. "HHT1 works on data like nothing else before it, and people are using it all over the world," Kizhner says; including to help monitor blood flow in the brain after brain injuries (Spinoff 2010). In 2006, the Federal Laboratory Consortium's mid-Atlantic region named the software Best Technology of the Year. But Kizhner—and many others, including Huang himself—were looking for a way to use the transform in two dimensions to analyze images. "There are certain things in image processing that cannot be done well with existing techniques, so we always strive to find something new," he says. Goddard engineer Sennion Kizhner's two-dimensional version of the Hilbert-Huang Transform was first tried out on the radiometer for NASA's Soil Moisture Active Passive (SMAP) satellite, where it eliminates radio interference from imagery. 122 Information Technology Spinoff 2018
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“Hilbert–Huang变换在图像分析中的转化”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】NASA研究者为了将Hilbert–Huang变换用于二维图像分析面临什么困难？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #093 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先定位 Hilbert–Huang 分析转换为图像处理的技术段落
3. **具体重写目标**：整页混合/错序抽取：先定位 Hilbert–Huang 分析转换为图像处理的技术段落。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #094 · `auto_new_expansion::real_007_batch_07_Spinoff2017::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_007_batch_07_Spinoff2017`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_007_batch_07_Spinoff2017, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
technology and adapting it for this market, designing custom manifolds with units to measure pressure change, installing temperature sensors, and creating displays that could operate in high-radiation environments, for example. After years of rigorous testing, verification, and certifica- tion, Graftel made its first balanced flow meter sale in 2013 and has been finding customers around the world ever since. The company gathers requirements and specifications from its customers and passes them on to A+ FlowTek, which uses its software to generate optimal flow plate designs. Graftel then manufactures, tests, certifies, and helps install the meters. Benefits The major benefit of the balanced flow meter is that, unlike single-hole flow plates and some other flow meters, it causes little to no drop in pressure in the fluid or gas passing through it. This is because it also acts as a flow conditioner, minimizing friction and passing along flows that have uniform velocity and pressure profiles. " A regular flow plate with a single hole will have maybe 10 pounds of pressure drop," Van Buskirk says. "That could mean hundreds or thousands of dollars in lost production per hour." By increasing flow efficiency, the meter pays for itself within weeks when compared to those based on a single-hole plate, he says. "Balanced flow meters are typically considered a green technology due to the substantial reduction in fluid pump energy requirements," Kelley says. "One company unof- ficially stated a savings of $5 million over three years of operation using a $5,000 unit." Other instruments commonly used in the nuclear industry, such as ultrasound flow meters, can produce inconsistent results, whereas balanced flow meters are consistently accurate. It's also the only flow meter that can obtain accurate results even when placed near a bend in a pipe, which causes flow disturbances, another plus for nuclear plants. "In a lot of situations, the pipes in nuclear plants aren't just straight—they can be all over the place," Glover points out. The flow plates are cheaper than many alternatives, last longer, and are virtually maintenance-free. They are also resistant to the buildup that often plagues other flow meters. "Instead of months, they'll work for 10, 15 years, probably forever," Van Buskirk says. And while single-hole flow plates can reach volumes up to 115 decibels—about as noisy as a loud rock concert—the plates A+ FlowTek designs are barely audible. "It's a 100 percent increase in accuracy and pressure recovery and a 10-fold reduction in noise," says Glover. "It's night-and-day-type stuff—like going from a Volkswagen bus to a Ferrari." The company is working to incorporate a wireless communication system into the flow meters, a concept it pioneered in its work for the Limerick Generating Station in Pennsylvania and which would let engineers read flow data from their desks. The system had to be specially designed to make it impervious to hackers. "Graftel has really incorporated our plate into a total solution for the nuclear industry," Van Buskirk says. Breaking into the nuclear industry is slow work, but the company is beginning to see sales pick-up, Glover says, noting that Graftel recently reached an agreement to provide flow meters for all of Westinghouse's future AP1000 reactors outside of China. "We foresee a big future with the nuclear industry, and that's worldwide," says Van Buskirk. ❖ Since the early 2000s, balanced flow meters created through Marshall Space Flight Center's partnership with Quality Efficiency and Control have increased the accuracy of flow readings and improved efficiency in plants across a variety of industries. Since 2013, Graftel LLC has introduced the technology to the nuclear power industry, which has its own strict rules, requirements, and procedures. Spinoff 2017 Energy and Environment 131
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_007_batch_07_Spinoff2017:p0132:e000` · 页 `132` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_007_batch_07_Spinoff2017/pages/page_0132/output_json/page_0132.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
technology and adapting it for this market, designing custom manifolds with units to measure pressure change, installing temperature sensors, and creating displays that could operate in high-radiation environments, for example. After years of rigorous testing, verification, and certifica- tion, Graftel made its first balanced flow meter sale in 2013 and has been finding customers around the world ever since. The company gathers requirements and specifications from its customers and passes them on to A+ FlowTek, which uses its software to generate optimal flow plate designs. Graftel then manufactures, tests, certifies, and helps install the meters. Benefits The major benefit of the balanced flow meter is that, unlike single-hole flow plates and some other flow meters, it causes little to no drop in pressure in the fluid or gas passing through it. This is because it also acts as a flow conditioner, minimizing friction and passing along flows that have uniform velocity and pressure profiles. " A regular flow plate with a single hole will have maybe 10 pounds of pressure drop," Van Buskirk says. "That could mean hundreds or thousands of dollars in lost production per hour." By increasing flow efficiency, the meter pays for itself within weeks when compared to those based on a single-hole plate, he says. "Balanced flow meters are typically considered a green technology due to the substantial reduction in fluid pump energy requirements," Kelley says. "One company unof- ficially stated a savings of $5 million over three years of operation using a $5,000 unit." Other instruments commonly used in the nuclear industry, such as ultrasound flow meters, can produce inconsistent results, whereas balanced flow meters are consistently accurate. It's also the only flow meter that can obtain accurate results even when placed near a bend in a pipe, which causes flow disturbances, another plus for nuclear plants. "In a lot of situations, the pipes in nuclear plants aren't just straight—they can be all over the place," Glover points out. The flow plates are cheaper than many alternatives, last longer, and are virtually maintenance-free. They are also resistant to the buildup that often plagues other flow meters. "Instead of months, they'll work for 10, 15 years, probably forever," Van Buskirk says. And while single-hole flow plates can reach volumes up to 115 decibels—about as noisy as a loud rock concert—the plates A+ FlowTek designs are barely audible. "It's a 100 percent increase in accuracy and pressure recovery and a 10-fold reduction in noise," says Glover. "It's night-and-day-type stuff—like going from a Volkswagen bus to a Ferrari." The company is working to incorporate a wireless communication system into the flow meters, a concept it pioneered in its work for the Limerick Generating Station in Pennsylvania and which would let engineers read flow data from their desks. The system had to be specially designed to make it impervious to hackers. "Graftel has really incorporated our plate into a total solution for the nuclear industry," Van Buskirk says. Breaking into the nuclear industry is slow work, but the company is beginning to see sales pick-up, Glover says, noting that Graftel recently reached an agreement to provide flow meters for all of Westinghouse's future AP1000 reactors outside of China. "We foresee a big future with the nuclear industry, and that's worldwide," says Van Buskirk. ❖ Since the early 2000s, balanced flow meters created through Marshall Space Flight Center's partnership with Quality Efficiency and Control have increased the accuracy of flow readings and improved efficiency in plants across a variety of industries. Since 2013, Graftel LLC has introduced the technology to the nuclear power industry, which has its own strict rules, requirements, and procedures. Spinoff 2017 Energy and Environment 131
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“辐射环境中压力/温度监测与可视化适配”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】面向高辐射环境的压力监测设备做了哪些传感器和显示方面的改造？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #094 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复辐射环境下压力温度监测专用配件的完整介绍
3. **具体重写目标**：整页混合/错序抽取：先恢复辐射环境下压力温度监测专用配件的完整介绍。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #095 · `auto_new_expansion::real_007_batch_07_Spinoff2017::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_007_batch_07_Spinoff2017`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_007_batch_07_Spinoff2017, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Power Amplifiers Boost Radar, Communications, Defense Systems NASA Technology NORMALLY, state-of-the-art technology comes at a cost. But when QuinStar Technology was subcontracted in 2009 to build a power ampli- fier for one of NASA Jet Propulsion Laboratory's (JPL) radars, what the company delivered was not only more compact and reliable than the amplifiers typically used in such instruments but also less expensive. Remote Sensing Solutions (RSS), the prime contractor, had issued rigorous specifications for a solid-state power amplifier (SSPA) to boost signals from a radar operating at Ka-band frequencies—a slice of the microwave spectrum between 26 and 40 gigahertz—to be used in the calibration and validation of an instrument that would one day fly on the Surface Water Ocean Topography (SWOT) mission. The project, a cooperative effort between NASA and the French and Canadian space agencies, will use radar interferometers to create the first topographical map of Earth's oceans, lakes, and rivers, determining and monitoring the global distribution of freshwater, and examining how ocean currents interplay with climate change, among other studies. Before its 2020 satellite launch, the equipment has to be tested. So, in 2008, JPL granted the first of two Small Business Innovation Research (SBIR) contracts to RSS to design and build the Ka-Band SWOT Phenomenology Airborne Radar (KaSPAR), which is testing key SWOT instrument subsystems and measurement approach aboard a turboprop plane. Until recently, power amplifiers for such radars have generally been tube-based, but for KaSPAR, RSS wanted a highly efficient, compact, solid-state amplifier that could operate at high altitude and only required conduction cooling. The SBIR proposal for the project notes that a state-of-the-art SSPA would not only improve the surface- mapper’s performance but also open the way for such technology to fly on long-term unmanned aerial vehicle QuinStar and NASA shared the cost of developing a high-power W-band solid-state power amplifier for Goddard Space Flight Center's Cloud Radar System, which flew on the ER-2 high-altitude Earth science aircraft as part of the 2014 Integrated Precipitation and Hydrology Experiment. The power amplifier helped researchers collect data on precipitation distribution in clouds to improve understanding of precipitation over mountainous terrain, such as this supercell thunderstorm, photographed from the ER-2 as it passed over North Carolina on the evening of May 23, 2014. 152 Information Technology (UAV) missions. And power amplifiers have a multitude of applications, from communications to electronic warfare, so advancements could play out across a range of technologies. The subcontractor initially hired to build the ampli- fier wasn't able to complete the work, so RSS turned to Torrance, California-based QuinStar, which already had a history of pushing the boundaries of SSPA technology for other Government agencies. Technology Transfer There was little money left on the SBIR contract, and QuinStar, eager to advance its SSPA capabilities, invested a chunk of its own money to develop an amplifier of unprecedented efficiency. "The one we developed is very highly advanced and very potent," says Naresh Deo, vice president of business development for QuinStar, adding that technology is "unique and unprecedented and can serve some purposes it couldn't before." An SSPA routes a signal through an array of amplifiers, each of which boosts its portion of the signal, and then recombines the channels into a single, intensified output. The problem is that power is lost as the signal is recombined, with more channels meaning more energy dissipated when the signal is funneled back into a single pulse. "What's different about our power combiners is they're extremely efficient," Deo says, noting that, while most SSPAs lose around 20 percent of their amplified energy at recombination, QuinStar's now lose only 8 percent. Following delivery of the KaSPAR amplifier, RSS ordered another SSPA from QuinStar for JPL's Airborne Glacier and Land Ice Surface Topography Interferometer. "With that success, NASA started ordering all their SSPAs from us," Deo says. Spinoff 2017
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_007_batch_07_Spinoff2017:p0153:e000` · 页 `153` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_007_batch_07_Spinoff2017/pages/page_0153/output_json/page_0153.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Power Amplifiers Boost Radar, Communications, Defense Systems NASA Technology NORMALLY, state-of-the-art technology comes at a cost. But when QuinStar Technology was subcontracted in 2009 to build a power ampli- fier for one of NASA Jet Propulsion Laboratory's (JPL) radars, what the company delivered was not only more compact and reliable than the amplifiers typically used in such instruments but also less expensive. Remote Sensing Solutions (RSS), the prime contractor, had issued rigorous specifications for a solid-state power amplifier (SSPA) to boost signals from a radar operating at Ka-band frequencies—a slice of the microwave spectrum between 26 and 40 gigahertz—to be used in the calibration and validation of an instrument that would one day fly on the Surface Water Ocean Topography (SWOT) mission. The project, a cooperative effort between NASA and the French and Canadian space agencies, will use radar interferometers to create the first topographical map of Earth's oceans, lakes, and rivers, determining and monitoring the global distribution of freshwater, and examining how ocean currents interplay with climate change, among other studies. Before its 2020 satellite launch, the equipment has to be tested. So, in 2008, JPL granted the first of two Small Business Innovation Research (SBIR) contracts to RSS to design and build the Ka-Band SWOT Phenomenology Airborne Radar (KaSPAR), which is testing key SWOT instrument subsystems and measurement approach aboard a turboprop plane. Until recently, power amplifiers for such radars have generally been tube-based, but for KaSPAR, RSS wanted a highly efficient, compact, solid-state amplifier that could operate at high altitude and only required conduction cooling. The SBIR proposal for the project notes that a state-of-the-art SSPA would not only improve the surface- mapper’s performance but also open the way for such technology to fly on long-term unmanned aerial vehicle QuinStar and NASA shared the cost of developing a high-power W-band solid-state power amplifier for Goddard Space Flight Center's Cloud Radar System, which flew on the ER-2 high-altitude Earth science aircraft as part of the 2014 Integrated Precipitation and Hydrology Experiment. The power amplifier helped researchers collect data on precipitation distribution in clouds to improve understanding of precipitation over mountainous terrain, such as this supercell thunderstorm, photographed from the ER-2 as it passed over North Carolina on the evening of May 23, 2014. 152 Information Technology (UAV) missions. And power amplifiers have a multitude of applications, from communications to electronic warfare, so advancements could play out across a range of technologies. The subcontractor initially hired to build the ampli- fier wasn't able to complete the work, so RSS turned to Torrance, California-based QuinStar, which already had a history of pushing the boundaries of SSPA technology for other Government agencies. Technology Transfer There was little money left on the SBIR contract, and QuinStar, eager to advance its SSPA capabilities, invested a chunk of its own money to develop an amplifier of unprecedented efficiency. "The one we developed is very highly advanced and very potent," says Naresh Deo, vice president of business development for QuinStar, adding that technology is "unique and unprecedented and can serve some purposes it couldn't before." An SSPA routes a signal through an array of amplifiers, each of which boosts its portion of the signal, and then recombines the channels into a single, intensified output. The problem is that power is lost as the signal is recombined, with more channels meaning more energy dissipated when the signal is funneled back into a single pulse. "What's different about our power combiners is they're extremely efficient," Deo says, noting that, while most SSPAs lose around 20 percent of their amplified energy at recombination, QuinStar's now lose only 8 percent. Following delivery of the KaSPAR amplifier, RSS ordered another SSPA from QuinStar for JPL's Airborne Glacier and Land Ice Surface Topography Interferometer. "With that success, NASA started ordering all their SSPAs from us," Deo says. Spinoff 2017
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“雷达通信功率放大器开发背景”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】QuinStar在2009年的NASA功率放大器项目中要解决什么性能或成本限制？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #095 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复雷达/通信功率放大器技术正文，标题不可代替证据
3. **具体重写目标**：整页混合/错序抽取：先恢复雷达/通信功率放大器技术正文，标题不可代替证据。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #096 · `auto_new_expansion::real_008_batch_08_Spinoff2016::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_008_batch_08_Spinoff2016`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_008_batch_08_Spinoff2016, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Benefits A sample of the scenarios DTI has been testing is a loop of flight traffic data provided to the company, showing a swarm of red, yellow, and white airplanes massing along the Eastern Seaboard of the United States, with each color indicating whether a plane was landing, taking off, or in mid-flight. In standard display mode, the planes appear and blink off the map in real time. "What you've got is an incredible beehive of data that doesn't serve the pilot too well, nor the copilot, in terms of quick, intuitive understanding of what they are facing," Lagergren says. But switched into 3D mode, the clustered information is sorted and clarified. It's possible to determine whether one yellow plane is flying at a higher altitude than another, and whether two planes might be using the same runway at a busy airport. The 3D capability without glasses, thanks to eye-tracking technology, should help NASA ensure pilots have all the information they need to navigate increasingly busy airports, which are already struggling with higher demand for runway space, Ellis says. "Traffic densities are going up by three or four times, projected, in terms of air travel, in the next 20 years or so. That causes a lot of problems. How do we take four times the amount of aircraft we have now flying into Chicago-O'Hare, Boston-Logan or Reagan National in Washington, DC," he says. "You can't build another Reagan because DC's pretty densely populated. The only thing you can do is improve the efficiency of it." DTI isn't only thinking about pilots with this glassless 3D technology. Already the displays have been presented at two large digital visual arts conferences—Immersed in Toronto and SIGGRAPH in Vancouver—to rave reviews. At Immersed, DTI set up a console with the action role-playing game Skyrim, which features mountains, rivers, fields, and animals, including dragons and woolly mammoths. "We had these woolly mammoths walking over the terrain, up and down the mountain, into valleys, and it seemed like you could see forever," Lagergren says. "People were awed by it." The successful demonstration earned the company an invite to several technology conferences to show off its monitors. DTI also took its displays to the NVIDIA GPU Technology Conference and Emerging Companies Summit, in 2015, which highlights applications that are breaking new ground and pushing the boundaries of visual computing. Games built to be played or viewed in 3D rely on glasses, or players must remain in a "sweet spot" to get the full effect, but DTI has eliminated both those constraints, he says. "Now you can walk around and the monitor will track you and keep the 3D at your eyes. There's no loss of resolution or brightness, no restriction in head movement, and it works for two players." DTI's latest display, sold commercially as the DTI Mission Critical 2D/3D monitor, has also been met with enthusiasm from 3D animators, including James Stewart. His award-winning stop-motion short film, Foxed!, is among the clips used by DTI when demonstrating the monitor. Finally, there's been interest from car manufacturers as well, which could lead to 2D/3D displays as part of the center console, driver instrument cluster, and seattrack entertainment packages. "This thing is starting to take off," Lagergren says. "The market's ready to accept it." Spinoff 2016 Consumer Goods 101
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_008_batch_08_Spinoff2016:p0102:e000` · 页 `102` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_008_batch_08_Spinoff2016/pages/page_0102/output_json/page_0102.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Benefits A sample of the scenarios DTI has been testing is a loop of flight traffic data provided to the company, showing a swarm of red, yellow, and white airplanes massing along the Eastern Seaboard of the United States, with each color indicating whether a plane was landing, taking off, or in mid-flight. In standard display mode, the planes appear and blink off the map in real time. "What you've got is an incredible beehive of data that doesn't serve the pilot too well, nor the copilot, in terms of quick, intuitive understanding of what they are facing," Lagergren says. But switched into 3D mode, the clustered information is sorted and clarified. It's possible to determine whether one yellow plane is flying at a higher altitude than another, and whether two planes might be using the same runway at a busy airport. The 3D capability without glasses, thanks to eye-tracking technology, should help NASA ensure pilots have all the information they need to navigate increasingly busy airports, which are already struggling with higher demand for runway space, Ellis says. "Traffic densities are going up by three or four times, projected, in terms of air travel, in the next 20 years or so. That causes a lot of problems. How do we take four times the amount of aircraft we have now flying into Chicago-O'Hare, Boston-Logan or Reagan National in Washington, DC," he says. "You can't build another Reagan because DC's pretty densely populated. The only thing you can do is improve the efficiency of it." DTI isn't only thinking about pilots with this glassless 3D technology. Already the displays have been presented at two large digital visual arts conferences—Immersed in Toronto and SIGGRAPH in Vancouver—to rave reviews. At Immersed, DTI set up a console with the action role-playing game Skyrim, which features mountains, rivers, fields, and animals, including dragons and woolly mammoths. "We had these woolly mammoths walking over the terrain, up and down the mountain, into valleys, and it seemed like you could see forever," Lagergren says. "People were awed by it." The successful demonstration earned the company an invite to several technology conferences to show off its monitors. DTI also took its displays to the NVIDIA GPU Technology Conference and Emerging Companies Summit, in 2015, which highlights applications that are breaking new ground and pushing the boundaries of visual computing. Games built to be played or viewed in 3D rely on glasses, or players must remain in a "sweet spot" to get the full effect, but DTI has eliminated both those constraints, he says. "Now you can walk around and the monitor will track you and keep the 3D at your eyes. There's no loss of resolution or brightness, no restriction in head movement, and it works for two players." DTI's latest display, sold commercially as the DTI Mission Critical 2D/3D monitor, has also been met with enthusiasm from 3D animators, including James Stewart. His award-winning stop-motion short film, Foxed!, is among the clips used by DTI when demonstrating the monitor. Finally, there's been interest from car manufacturers as well, which could lead to 2D/3D displays as part of the center console, driver instrument cluster, and seattrack entertainment packages. "This thing is starting to take off," Lagergren says. "The market's ready to accept it." Spinoff 2016 Consumer Goods 101
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“空中交通数据的场景测试”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】DTI使用美国东海岸航班交通回放数据测试什么系统能力？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #096 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复空中交通场景测试的完整因果过程
3. **具体重写目标**：整页混合/错序抽取：先恢复空中交通场景测试的完整因果过程。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #097 · `auto_new_expansion::real_008_batch_08_Spinoff2016::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_008_batch_08_Spinoff2016`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_008_batch_08_Spinoff2016, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Open Innovation NASA's challenges, prizes, and crowdsourcing efforts result in groundbreaking achievements The Power of Prizes Most people recognize Charles Lindbergh as the man who achieved worldwide fame New York City to Paris in 1927. But relatively few people know that Lindbergh did it to win a $25,000 prize (worth approximately $340,000 today) offered by a New York City-based hotel owner—or that Lindbergh was virtually unknown in aviation circles before his historic achievement and that he narrowly outcompeted several teams of experienced airmen to achieve victory. Lindbergh's story unfolded nearly a century ago, but it continues to serve as an example of the extraor- dinary things people can accomplish when incentivized by awards, public honors, and cash prizes, as well as the ingenuity unleashed by competition on a level playing field, where underdogs can make their mark. Recognizing the power of this principle, in 2009 President Obama urged Federal agencies to pursue "high-risk, high-reward policy tools such as prizes and challenges to solve tough problems." Answering this call, NASA has increasingly turned to public competitions as a source of fresh ideas to help meet engineering challenges in aeronautics and space exploration. "Prize competitions have become a key component in NASA's toolkit for developing technology and solv- ing problems," says Gladys Henderson, executive of the Agency's Prizes and Challenges Program. "Because we only pay for success, we have found them to be remark- ably efficient in terms of getting the job done—which is a win not just for NASA but ultimately for taxpayers." Henderson notes that the open nature of competitions tends to make them popular among "nontraditional audiences"—that is, those outside the aerospace commu- nity—and that the high difficulty of NASA's objectives tends to bring in top talent, tempted by the chance to tackle a unique problem. The Agency's flagship effort in prize competitions dates to 2005, when the Centennial Challenges Program was established to engage the public in advancing technologies relevant to NASA missions. After proposing a set challenge for competitors—say, to build a robot capable of finding and collecting geological samples from a large field with varied terrain—along with precise criteria for success, NASA holds an event. Teams use either their own funds or outside investments to develop A robot scouts the field looking for samples to collect and return Return the 2014 Sample Return Robot Challenge. Eighteen million NASA prize purse at the competition. Many of the Centennial Challenges are annual events held over multiple years. The criteria for victory are focused on a significant advancement of the current tech- nology, such that it can take two to five years to award a prize. During the last 10 years, the program has overseen 20 competitions that have disbursed more than $6 mil- lion in awards and resulted in innovations in everything from robotics, fuel-efficient flight, and spaceship gloves to regolith excavators and ascent vehicles for Mars. And the entrants' technological achievements are often staggering: for example, the two winners of the 2011 Green Flight 198 Award-Winning Technologies Spinoff 2016
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_008_batch_08_Spinoff2016:p0199:e000` · 页 `199` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_008_batch_08_Spinoff2016/pages/page_0199/output_json/page_0199.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Open Innovation NASA's challenges, prizes, and crowdsourcing efforts result in groundbreaking achievements The Power of Prizes Most people recognize Charles Lindbergh as the man who achieved worldwide fame New York City to Paris in 1927. But relatively few people know that Lindbergh did it to win a $25,000 prize (worth approximately $340,000 today) offered by a New York City-based hotel owner—or that Lindbergh was virtually unknown in aviation circles before his historic achievement and that he narrowly outcompeted several teams of experienced airmen to achieve victory. Lindbergh's story unfolded nearly a century ago, but it continues to serve as an example of the extraor- dinary things people can accomplish when incentivized by awards, public honors, and cash prizes, as well as the ingenuity unleashed by competition on a level playing field, where underdogs can make their mark. Recognizing the power of this principle, in 2009 President Obama urged Federal agencies to pursue "high-risk, high-reward policy tools such as prizes and challenges to solve tough problems." Answering this call, NASA has increasingly turned to public competitions as a source of fresh ideas to help meet engineering challenges in aeronautics and space exploration. "Prize competitions have become a key component in NASA's toolkit for developing technology and solv- ing problems," says Gladys Henderson, executive of the Agency's Prizes and Challenges Program. "Because we only pay for success, we have found them to be remark- ably efficient in terms of getting the job done—which is a win not just for NASA but ultimately for taxpayers." Henderson notes that the open nature of competitions tends to make them popular among "nontraditional audiences"—that is, those outside the aerospace commu- nity—and that the high difficulty of NASA's objectives tends to bring in top talent, tempted by the chance to tackle a unique problem. The Agency's flagship effort in prize competitions dates to 2005, when the Centennial Challenges Program was established to engage the public in advancing technologies relevant to NASA missions. After proposing a set challenge for competitors—say, to build a robot capable of finding and collecting geological samples from a large field with varied terrain—along with precise criteria for success, NASA holds an event. Teams use either their own funds or outside investments to develop A robot scouts the field looking for samples to collect and return Return the 2014 Sample Return Robot Challenge. Eighteen million NASA prize purse at the competition. Many of the Centennial Challenges are annual events held over multiple years. The criteria for victory are focused on a significant advancement of the current tech- nology, such that it can take two to five years to award a prize. During the last 10 years, the program has overseen 20 competitions that have disbursed more than $6 mil- lion in awards and resulted in innovations in everything from robotics, fuel-efficient flight, and spaceship gloves to regolith excavators and ascent vehicles for Mars. And the entrants' technological achievements are often staggering: for example, the two winners of the 2011 Green Flight 198 Award-Winning Technologies Spinoff 2016
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA开放式创新挑战与奖励机制”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。材料属于目录、活动安排、概述或标题型文字，不保证存在单一可验证的机制或结论；应先判断该节点是否适合生成问答。 【建议重写题目】NASA为何用竞赛奖金和众包来征集技术方案？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #097 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复 NASA 开放创新挑战与奖励机制内容，勿只截取标题
3. **具体重写目标**：整页混合/错序抽取：先恢复 NASA 开放创新挑战与奖励机制内容，勿只截取标题。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #098 · `auto_new_expansion::real_009_batch_09_Spinoff2015::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_009_batch_09_Spinoff2015`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_009_batch_09_Spinoff2015, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
developed from off-the-shelf products," he says. "It's an industry-enabling technology." Now, he says, even many companies in the business of aerial imaging don't calibrate properly. "Many don't understand it, and it's expensive, so they don't do it." But proper radiometric calibration turns a camera into a scientific tool, Pagnutti says, explaining that in a calibrated camera, the digital number (DN) in each pixel can be assigned a reliable radiance value for each image. It becomes a measuring device. "You want more than a pretty picture. You want to know that DN value depicts a certain amount of radiance." When using digital satellite imagery to assess crop health or water resource management, for example, Stanley says, proper radiometry is essential. The same is true when using handheld units to determine the health of plants or human tissue. With the cost of calibration technology reduced, he says he foresees a day when cell phone cameras can become scientific instruments. Indeed, NASA and I2R are already using the com- pany's integrating spheres to calibrate cell phone-grade imaging technology for use in monitoring indoor lighting under an STTR contract. This technology might be used on the International Space Station (ISS) one day. As the ISS has changed its lighting to LEDs, astronauts have found they have a harder time sleeping. Under STTR, I2R will work to moderate lighting to either be conducive to sleep, or to induce focus or creative thinking—task- specific lighting. Stanley calls it—possibly to develop a lighting system for the space station. He notes that three groups at Johnson Space Center were already keeping track of this LED lighting project before Pagnutti had even written her final report on the integrating sphere. "One contract award doesn't generally lead to a suc- cessful product," he says, noting that I2R's work seems to be an exception. ❖ Spinoff 2015 Proper radiometric calibration is essential for satellite cameras used to monitor crop health, among other applications. Industrial Productivity 141
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_009_batch_09_Spinoff2015:p0142:e000` · 页 `142` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_009_batch_09_Spinoff2015/pages/page_0142/output_json/page_0142.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
developed from off-the-shelf products," he says. "It's an industry-enabling technology." Now, he says, even many companies in the business of aerial imaging don't calibrate properly. "Many don't understand it, and it's expensive, so they don't do it." But proper radiometric calibration turns a camera into a scientific tool, Pagnutti says, explaining that in a calibrated camera, the digital number (DN) in each pixel can be assigned a reliable radiance value for each image. It becomes a measuring device. "You want more than a pretty picture. You want to know that DN value depicts a certain amount of radiance." When using digital satellite imagery to assess crop health or water resource management, for example, Stanley says, proper radiometry is essential. The same is true when using handheld units to determine the health of plants or human tissue. With the cost of calibration technology reduced, he says he foresees a day when cell phone cameras can become scientific instruments. Indeed, NASA and I2R are already using the com- pany's integrating spheres to calibrate cell phone-grade imaging technology for use in monitoring indoor lighting under an STTR contract. This technology might be used on the International Space Station (ISS) one day. As the ISS has changed its lighting to LEDs, astronauts have found they have a harder time sleeping. Under STTR, I2R will work to moderate lighting to either be conducive to sleep, or to induce focus or creative thinking—task- specific lighting. Stanley calls it—possibly to develop a lighting system for the space station. He notes that three groups at Johnson Space Center were already keeping track of this LED lighting project before Pagnutti had even written her final report on the integrating sphere. "One contract award doesn't generally lead to a suc- cessful product," he says, noting that I2R's work seems to be an exception. ❖ Spinoff 2015 Proper radiometric calibration is essential for satellite cameras used to monitor crop health, among other applications. Industrial Productivity 141
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“航空成像的标定技术与行业难点”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】航空影像生产商为什么容易忽视摄像设备标定，该技术如何解决精度问题？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #098 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复航空成像标定技术具体作用，验证所引技术声称
3. **具体重写目标**：整页混合/错序抽取：先恢复航空成像标定技术具体作用，验证所引技术声称。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #099 · `auto_new_expansion::real_009_batch_09_Spinoff2015::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_009_batch_09_Spinoff2015`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_009_batch_09_Spinoff2015, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Ionospheric Mapping Software Ensures Accuracy of Pilots' GPS NASA Technology T o permit safe and reliable aircraft navigation over North America using the Global Positioning System (GPS), the Federal Aviation Administration (FAA) has developed the Wide Area Augmentation System (WAAS), which improves the accuracy, availability, continuity, and integrity of GPS positioning enough to ensure its safe use by pilots to determine their locations. The early development of WAAS relied on software developed at NASA's Jet Propulsion Laboratory (JPL), particularly the GPS-Inferred Positioning System (GIPSY) and the Global Ionospheric Mapping (GIM) software packages. The former has been licensed by hundreds of commercial and noncommercial organizations (Spinoff 1999 and 2010). More recently the continued development of WAAS has relied on companion software also developed at JPL. The SuperTruth and IonoSTAGE packages allow the system to address the threat to accurate positioning posed by code delays and phase advances due to refraction in Earth's ionosphere. More than about 50 miles above the planet's surface, electrons can be separated from atoms, resulting in positive ions and free electrons. Ionization of the upper atmosphere is much more active in the daytime since it's largely driven by the sun's ultraviolet radiation and the solar wind, which rip electrons off of neutral particles. Earth wind patterns and electrodynamics in the atmo- sphere help make the electron distribution irregular and patchy, resulting in "space weather" that can interfere with signals. GPS signal delays caused by activity in the ionosphere are measured in meters, with large delays being on the order of 40 meters, says Lawrence Sparks, senior technologist with the Ionospheric and Atmospheric Remote Sensing Group at JPL. While it doesn't take long for signals traveling at the speed of light to cover 40 meters, he says, even a delay of a small fraction of a second can make a significant difference in determining the position of a fast-moving plane. "It is crucial to bound the positioning errors accurately for landing an aircraft safely in fog, for example." GIM allows Raytheon Corporation, the prime con- tractor of the system, to map ionospheric disruption in real time by processing the delays between GPS satel- lites and the 38 WAAS reference stations around North America. Each signal includes a sort of time stamp, making it possible to determine how long it took to travel from the satellite to the receiver, Sparks says. WAAS broadcasts vertical ionospheric grid delays for regularly spaced points across the coverage area. The observations are also used to calculate and broadcast the grid ionospheric vertical error (GIVE) for those same points. The GIVEs bound the range of possible error in pilot positions derived from GPS—that is, they let users know how reliable the information provided by WAAS really is. "Only part of the ionosphere is sampled by WAAS at any given time," Sparks explains. "A disturbance can be overlooked because its location hasn't been sampled. To protect the user from such errors, WAAS relies on an ionospheric threat model." The threat model—one factor in calculating GIVE— is constructed from a sort of worst-case scenario based on historical data generated by SuperTruth, including records of severe ionospheric storms. "We try to quantify what kinds of ionospheric disturbances the system could have possibly missed." Sparks says. "For every possible satellite configuration, we determine the worst-case errors we've ever seen." These are usually caused by coronal mass ejections—huge bursts of solar wind and magnetic fields on the surface of the sun that can cause dramatic increases in the number of ions in Earth's upper atmosphere. Sparks designed and wrote the computer code comprising the Ionospheric Slant TEC Analysis Using GNSS-Based Estimation (IonoSTAGE) software package, 50 Transportation Spinoff 2015
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_009_batch_09_Spinoff2015:p0051:e000` · 页 `51` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_009_batch_09_Spinoff2015/pages/page_0051/output_json/page_0051.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Ionospheric Mapping Software Ensures Accuracy of Pilots' GPS NASA Technology T o permit safe and reliable aircraft navigation over North America using the Global Positioning System (GPS), the Federal Aviation Administration (FAA) has developed the Wide Area Augmentation System (WAAS), which improves the accuracy, availability, continuity, and integrity of GPS positioning enough to ensure its safe use by pilots to determine their locations. The early development of WAAS relied on software developed at NASA's Jet Propulsion Laboratory (JPL), particularly the GPS-Inferred Positioning System (GIPSY) and the Global Ionospheric Mapping (GIM) software packages. The former has been licensed by hundreds of commercial and noncommercial organizations (Spinoff 1999 and 2010). More recently the continued development of WAAS has relied on companion software also developed at JPL. The SuperTruth and IonoSTAGE packages allow the system to address the threat to accurate positioning posed by code delays and phase advances due to refraction in Earth's ionosphere. More than about 50 miles above the planet's surface, electrons can be separated from atoms, resulting in positive ions and free electrons. Ionization of the upper atmosphere is much more active in the daytime since it's largely driven by the sun's ultraviolet radiation and the solar wind, which rip electrons off of neutral particles. Earth wind patterns and electrodynamics in the atmo- sphere help make the electron distribution irregular and patchy, resulting in "space weather" that can interfere with signals. GPS signal delays caused by activity in the ionosphere are measured in meters, with large delays being on the order of 40 meters, says Lawrence Sparks, senior technologist with the Ionospheric and Atmospheric Remote Sensing Group at JPL. While it doesn't take long for signals traveling at the speed of light to cover 40 meters, he says, even a delay of a small fraction of a second can make a significant difference in determining the position of a fast-moving plane. "It is crucial to bound the positioning errors accurately for landing an aircraft safely in fog, for example." GIM allows Raytheon Corporation, the prime con- tractor of the system, to map ionospheric disruption in real time by processing the delays between GPS satel- lites and the 38 WAAS reference stations around North America. Each signal includes a sort of time stamp, making it possible to determine how long it took to travel from the satellite to the receiver, Sparks says. WAAS broadcasts vertical ionospheric grid delays for regularly spaced points across the coverage area. The observations are also used to calculate and broadcast the grid ionospheric vertical error (GIVE) for those same points. The GIVEs bound the range of possible error in pilot positions derived from GPS—that is, they let users know how reliable the information provided by WAAS really is. "Only part of the ionosphere is sampled by WAAS at any given time," Sparks explains. "A disturbance can be overlooked because its location hasn't been sampled. To protect the user from such errors, WAAS relies on an ionospheric threat model." The threat model—one factor in calculating GIVE— is constructed from a sort of worst-case scenario based on historical data generated by SuperTruth, including records of severe ionospheric storms. "We try to quantify what kinds of ionospheric disturbances the system could have possibly missed." Sparks says. "For every possible satellite configuration, we determine the worst-case errors we've ever seen." These are usually caused by coronal mass ejections—huge bursts of solar wind and magnetic fields on the surface of the sun that can cause dramatic increases in the number of ions in Earth's upper atmosphere. Sparks designed and wrote the computer code comprising the Ionospheric Slant TEC Analysis Using GNSS-Based Estimation (IonoSTAGE) software package, 50 Transportation Spinoff 2015
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“电离层映射与飞行员GPS精度”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】电离层映射技术通过什么方式提升航空GPS导航精度？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #099 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复电离层映射如何提高飞行员 GPS 精度的正文
3. **具体重写目标**：整页混合/错序抽取：先恢复电离层映射如何提高飞行员 GPS 精度的正文。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #100 · `auto_new_expansion::real_010_batch_10_Spinoff2013::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_010_batch_10_Spinoff2013`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_010_batch_10_Spinoff2013, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
When executing a procedure, PRIDE assists the opera- tor with a variety of tools to simplify and streamline the process of following instructions. It can format proce- dures for display in any number of media, for example, so that astronauts can use what they have on hand to read them, regardless of the platform used to write them. In electronic formats, an operator can check off steps as they are performed, which can be tracked (and later audited) by others managing the mission. NASA has turned to PRIDE for a variety of needs: In 2008 it was used to author medical procedures for the ISS. Capabilities to write procedures for EVAs were integrated in 2111, and in 2012 it powered the proce- dure-writing for Morpheus, a rapid prototype lander project designed to test a range of capabilities. Perhaps most importantly, NASA is using PRIDE to author pro- cedures for the prototype electronic procedure display for the Orion Multipurpose Crew Vehicle, the spacecraft scheduled to take astronauts beyond Earth's orbit for the first time since the Apollo Program. Benefits NASA may have been PRIDE's first user, but it won't be its last: in 2013 TRACLabs announced that it was marketing its software to private industry, starting with oil companies. As Dave Kortenkamp, president of TRACLabs, says, "We recognized pretty early on that procedures are ubiquitous, and any environment where there is some level of high dynamics and risk, people want to think things through. We live in Houston, where oil and gas is a very large industry, so it was a natural next step." TRACLabs is now working with a number of large companies in the oil and gas industry—"names you see on gas station signs as you drive down the street," says Kortenkamp—as well as with companies that provide services to them. The company will sell both the software and support services and is already on pace to generate millions of dollars through its entry into the market. On oil rigs with heavy machinery, any failure to strictly follow instructions can cause disaster. "After the Deepwater Horizon oil spill in 2011, these companies want to make sure that everything they're doing is according to best practices," says Kortenkamp. "Part of the problem in diagnosing what went wrong was that they weren't always sure who was doing what when. They're serious about making sure they're auditing procedures and keeping track of what's being done in the field." Using procedures written with PRIDE, oil compa- nies can better manage and audit oil rig operations. For example, when an expert authors procedures for a piece of drilling equipment, PRIDE captures that instruction in language the software understands. (Currently, such procedures are written in ordinary word processors.) "When the procedure is sent to the operator of that piece of equipment," says Kortenkamp, "the operator has some training but isn't necessarily an expert on that tool. With PRIDE, the operator can check off steps as he moves through them and use the software to branch off certain points in the procedure where there are questions that need to be answered." At the same time, PRIDE can draw relevant sensor data coming from the equipment and display context both for the operator and anyone monitoring the work remotely. Using industry-standard interfaces that are compatible with PRIDE, multiple people can use the same procedure on multiple rigs, and as they carry out their instructions, all of their interactions are stored in a remote database so that the company can review what's happening. If an operator breaks from his or her given instructions, support software can send out alerts so that appropriate actions can be taken—whether that means halting the operation or flagging it for further review. In the future, TRACLabs hopes to sell PRIDE in other markets, as it can easily be applied in many fields. For now, however, NASA's early adoption of PRIDE is helping the company get a foot in the door with an industry whose difficult environments and high risks sometimes resemble those of the space agency's. "It's widely recognized that NASA is at the cutting edge of operating complex things safely," says Kortenkamp. "It's fact that this is the direction NASA is moving for its procedures tells the oil and gas industry that it's a direction they should be moving as well." Spinoff 2013 103
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_010_batch_10_Spinoff2013:p0104:e000` · 页 `104` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_010_batch_10_Spinoff2013/pages/page_0104/output_json/page_0104.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
When executing a procedure, PRIDE assists the opera- tor with a variety of tools to simplify and streamline the process of following instructions. It can format proce- dures for display in any number of media, for example, so that astronauts can use what they have on hand to read them, regardless of the platform used to write them. In electronic formats, an operator can check off steps as they are performed, which can be tracked (and later audited) by others managing the mission. NASA has turned to PRIDE for a variety of needs: In 2008 it was used to author medical procedures for the ISS. Capabilities to write procedures for EVAs were integrated in 2111, and in 2012 it powered the proce- dure-writing for Morpheus, a rapid prototype lander project designed to test a range of capabilities. Perhaps most importantly, NASA is using PRIDE to author pro- cedures for the prototype electronic procedure display for the Orion Multipurpose Crew Vehicle, the spacecraft scheduled to take astronauts beyond Earth's orbit for the first time since the Apollo Program. Benefits NASA may have been PRIDE's first user, but it won't be its last: in 2013 TRACLabs announced that it was marketing its software to private industry, starting with oil companies. As Dave Kortenkamp, president of TRACLabs, says, "We recognized pretty early on that procedures are ubiquitous, and any environment where there is some level of high dynamics and risk, people want to think things through. We live in Houston, where oil and gas is a very large industry, so it was a natural next step." TRACLabs is now working with a number of large companies in the oil and gas industry—"names you see on gas station signs as you drive down the street," says Kortenkamp—as well as with companies that provide services to them. The company will sell both the software and support services and is already on pace to generate millions of dollars through its entry into the market. On oil rigs with heavy machinery, any failure to strictly follow instructions can cause disaster. "After the Deepwater Horizon oil spill in 2011, these companies want to make sure that everything they're doing is according to best practices," says Kortenkamp. "Part of the problem in diagnosing what went wrong was that they weren't always sure who was doing what when. They're serious about making sure they're auditing procedures and keeping track of what's being done in the field." Using procedures written with PRIDE, oil compa- nies can better manage and audit oil rig operations. For example, when an expert authors procedures for a piece of drilling equipment, PRIDE captures that instruction in language the software understands. (Currently, such procedures are written in ordinary word processors.) "When the procedure is sent to the operator of that piece of equipment," says Kortenkamp, "the operator has some training but isn't necessarily an expert on that tool. With PRIDE, the operator can check off steps as he moves through them and use the software to branch off certain points in the procedure where there are questions that need to be answered." At the same time, PRIDE can draw relevant sensor data coming from the equipment and display context both for the operator and anyone monitoring the work remotely. Using industry-standard interfaces that are compatible with PRIDE, multiple people can use the same procedure on multiple rigs, and as they carry out their instructions, all of their interactions are stored in a remote database so that the company can review what's happening. If an operator breaks from his or her given instructions, support software can send out alerts so that appropriate actions can be taken—whether that means halting the operation or flagging it for further review. In the future, TRACLabs hopes to sell PRIDE in other markets, as it can easily be applied in many fields. For now, however, NASA's early adoption of PRIDE is helping the company get a foot in the door with an industry whose difficult environments and high risks sometimes resemble those of the space agency's. "It's widely recognized that NASA is at the cutting edge of operating complex things safely," says Kortenkamp. "It's fact that this is the direction NASA is moving for its procedures tells the oil and gas industry that it's a direction they should be moving as well." Spinoff 2013 103
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“PRIDE程序执行辅助软件的呈现机制”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】PRIDE如何帮助操作人员跨不同显示媒介执行标准操作程序？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #100 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复 PRIDE 执行辅助工具如何指导步骤的解释段
3. **具体重写目标**：整页混合/错序抽取：先恢复 PRIDE 执行辅助工具如何指导步骤的解释段。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #101 · `auto_new_expansion::real_010_batch_10_Spinoff2013::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_010_batch_10_Spinoff2013`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_010_batch_10_Spinoff2013, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Programs Visualize Earth and Space for Interactive Education NASA Technology Incredible sights are being seen, thanks to the devel- opment of technology both inside and outside of NASA. With just a few clicks, NASA's Eyes on the Earth web application lets you see what it's like to fly around Earth with a satellite. A separate program—Eyes on the Solar System—allows you to wander through space and stop at any planet or spacecraft you see. Last but not least, NASA's Eyes on Exoplanets provides a close-up view of the stars and planets inside the Milky Way. No longer do such sights have to come only from your imagination. It all started in 2004 when Kevin Hussey, the manager of visualization technology applications and develop- ment at the Jet Propulsion Laboratory (JPL), was talking to a colleague who wondered, "Wouldn't it be cool if you could ride along with a spacecraft while it's doing its thing—especially if it is in a precarious situation or something noteworthy is going on?" Fascinated by the idea, Hussey set out to collaborate with others at JPL to produce a prototype in the appli- cation programming interface called DirectX 9 to show the orbit insertion of Cassini, the first spacecraft to orbit Saturn, in real time. Soon after, Hussey's team used Unity3D, a game development program for creating interactive video-game style content, to advance the visu- alization and incorporate interactivity. Upon completion of the Cassini Saturn interactive explorer, Hussey received requests to develop similar programs encompassing all of the spacecraft in orbit around Earth and then all of the spacecraft in the Solar System. Nearly a decade later, there are now 12 people in Hussey's group creating new ways of seeing what is happening in space and supporting the incredible tools that already exist. And Hussey is ecstatic about the results. "During the Mars Curiosity landing, over a 3-day period, there were approximately 1.2 million visitors to Eyes on the Solar System! During the asteroid DA14 close encounter in 2013, there were more than 350,000 users of Eyes on the Earth and over 84,000 people using Eyes on the Solar System! People are using it all over the world." One of the many mind-boggling features of the pro- grams is the capability to show real-time progress. Armed with information on the projected path of the space- craft—what is going to happen and when—Hussey's team uses game engine technology to show what is predicted to happen in real time. "For Curiosity, our real time visualization, which is based on the predicted telemetry, was only .6 seconds early in landing than the real thing," says Hussey. "As people around the world were watching Curiosity touch down, it was less than a second off." Technology Transfer After completing Eyes on the Earth in 2008, Hussey was asked to assist in the redesign of an administrative lobby at JPL. His first idea was to use projected imag- ery to create a visual experience like being in space. He began researching companies online to help his idea come to life when he found Milwaukee, Wisconsin-based The Elumenati. Hussey contacted the company and spoke with Hilary McVicker, the director of communications at The Elumenati, who explained how the company's domes, projection systems, and software can create immersive environments. Their patented optics fill ultra-wide screens in any shape and size with images, video, and interactive content, from fully-enclosed domes that create planetarium-like experiences to panoramas for simulating flight and exploring planetary surfaces. "Completely surrounding your audience with imagery creates a sense of presence in a virtual world that can't be replicated on a flat screen," says McVicker. "This makes our immersive environments uniquely effective in creating teachable moments, spaces for collaborative dialogue, and a 'wow' factor." 110 Energy and Environment Spinoff 2013
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_010_batch_10_Spinoff2013:p0111:e000` · 页 `111` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_010_batch_10_Spinoff2013/pages/page_0111/output_json/page_0111.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Programs Visualize Earth and Space for Interactive Education NASA Technology Incredible sights are being seen, thanks to the devel- opment of technology both inside and outside of NASA. With just a few clicks, NASA's Eyes on the Earth web application lets you see what it's like to fly around Earth with a satellite. A separate program—Eyes on the Solar System—allows you to wander through space and stop at any planet or spacecraft you see. Last but not least, NASA's Eyes on Exoplanets provides a close-up view of the stars and planets inside the Milky Way. No longer do such sights have to come only from your imagination. It all started in 2004 when Kevin Hussey, the manager of visualization technology applications and develop- ment at the Jet Propulsion Laboratory (JPL), was talking to a colleague who wondered, "Wouldn't it be cool if you could ride along with a spacecraft while it's doing its thing—especially if it is in a precarious situation or something noteworthy is going on?" Fascinated by the idea, Hussey set out to collaborate with others at JPL to produce a prototype in the appli- cation programming interface called DirectX 9 to show the orbit insertion of Cassini, the first spacecraft to orbit Saturn, in real time. Soon after, Hussey's team used Unity3D, a game development program for creating interactive video-game style content, to advance the visu- alization and incorporate interactivity. Upon completion of the Cassini Saturn interactive explorer, Hussey received requests to develop similar programs encompassing all of the spacecraft in orbit around Earth and then all of the spacecraft in the Solar System. Nearly a decade later, there are now 12 people in Hussey's group creating new ways of seeing what is happening in space and supporting the incredible tools that already exist. And Hussey is ecstatic about the results. "During the Mars Curiosity landing, over a 3-day period, there were approximately 1.2 million visitors to Eyes on the Solar System! During the asteroid DA14 close encounter in 2013, there were more than 350,000 users of Eyes on the Earth and over 84,000 people using Eyes on the Solar System! People are using it all over the world." One of the many mind-boggling features of the pro- grams is the capability to show real-time progress. Armed with information on the projected path of the space- craft—what is going to happen and when—Hussey's team uses game engine technology to show what is predicted to happen in real time. "For Curiosity, our real time visualization, which is based on the predicted telemetry, was only .6 seconds early in landing than the real thing," says Hussey. "As people around the world were watching Curiosity touch down, it was less than a second off." Technology Transfer After completing Eyes on the Earth in 2008, Hussey was asked to assist in the redesign of an administrative lobby at JPL. His first idea was to use projected imag- ery to create a visual experience like being in space. He began researching companies online to help his idea come to life when he found Milwaukee, Wisconsin-based The Elumenati. Hussey contacted the company and spoke with Hilary McVicker, the director of communications at The Elumenati, who explained how the company's domes, projection systems, and software can create immersive environments. Their patented optics fill ultra-wide screens in any shape and size with images, video, and interactive content, from fully-enclosed domes that create planetarium-like experiences to panoramas for simulating flight and exploring planetary surfaces. "Completely surrounding your audience with imagery creates a sense of presence in a virtual world that can't be replicated on a flat screen," says McVicker. "This makes our immersive environments uniquely effective in creating teachable moments, spaces for collaborative dialogue, and a 'wow' factor." 110 Energy and Environment Spinoff 2013
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA Eyes交互式地球太空教育软件”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。材料属于目录、活动安排、概述或标题型文字，不保证存在单一可验证的机制或结论；应先判断该节点是否适合生成问答。 【建议重写题目】NASA Eyes软件使公众能够以什么方式探索地球和太空数据？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #101 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复 NASA Eyes 软件交互式教育技术机制，勿只截取产品介绍标题
3. **具体重写目标**：整页混合/错序抽取：先恢复 NASA Eyes 软件交互式教育技术机制，勿只截取产品介绍标题。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #102 · `auto_new_expansion::real_011_batch_11_Spinoff2012::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_011_batch_11_Spinoff2012`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_011_batch_11_Spinoff2012, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Archiving Innovations Preserve Essential Historical Records NASA Technology The Moon hosts perhaps the most fascinating museum that no one ever visits. From reflecto meters to space boots, the lunar module's descent stage, and the famous first footprints left behind by Neil Armstrong, the Apollo 11 mission alone left over 100 artifacts on the Moon's surface. Among the items at rest in the lunar regolith is an aluminum capsule containing a simple silicon disc about the size of a half-dollar coin. The disc displays messages of goodwill from 73 countries and four US presidents, all inscribed in letters a quarter of the width of a human hair, visible only under a microscope. In order to compile the commemorative messages into a format that would not significantly add to Apollo 11's payload, while also being able to endure the wild tem- perature extremes of the Moon's surface, NASA partnered with Worcester, Massachusetts-based Sprague Electric Company. The company, which had already worked with the Agency to produce multiple components for the Apollo 11 mission, applied semiconductor manufacturing techniques to etch the messages on silicon, sizing them down until each individual message was smaller than the head of a pin. Sprague patented the technique in 1971, but it would be decades later when a pair of innovators would build upon the NASA-derived technology to create a spinoff that is now preserving vital records on Earth in the same way that the world's support of Apollo 11 is preserved on the Moon. Technology Transfer In 2006, P.R. Mukund, professor of electrical engineering at Rochester Institute of Technology, and PhD student Ajay Pasupuleti took on a task working with a material not typical to their field—palm leaves. The pair joined a project to preserve the content of the Sarvamoola Grantha, an ancient work of Hindu spiritual scholarship The famous Apollo 11 mission left behind over 100 artifacts on the Moon, including a small silicon disc inscribed with messages of goodwill from 73 countries (below). Spinoff 2012
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_011_batch_11_Spinoff2012:p0128:e000` · 页 `128` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_011_batch_11_Spinoff2012/pages/page_0128/output_json/page_0128.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Archiving Innovations Preserve Essential Historical Records NASA Technology The Moon hosts perhaps the most fascinating museum that no one ever visits. From reflecto meters to space boots, the lunar module's descent stage, and the famous first footprints left behind by Neil Armstrong, the Apollo 11 mission alone left over 100 artifacts on the Moon's surface. Among the items at rest in the lunar regolith is an aluminum capsule containing a simple silicon disc about the size of a half-dollar coin. The disc displays messages of goodwill from 73 countries and four US presidents, all inscribed in letters a quarter of the width of a human hair, visible only under a microscope. In order to compile the commemorative messages into a format that would not significantly add to Apollo 11's payload, while also being able to endure the wild tem- perature extremes of the Moon's surface, NASA partnered with Worcester, Massachusetts-based Sprague Electric Company. The company, which had already worked with the Agency to produce multiple components for the Apollo 11 mission, applied semiconductor manufacturing techniques to etch the messages on silicon, sizing them down until each individual message was smaller than the head of a pin. Sprague patented the technique in 1971, but it would be decades later when a pair of innovators would build upon the NASA-derived technology to create a spinoff that is now preserving vital records on Earth in the same way that the world's support of Apollo 11 is preserved on the Moon. Technology Transfer In 2006, P.R. Mukund, professor of electrical engineering at Rochester Institute of Technology, and PhD student Ajay Pasupuleti took on a task working with a material not typical to their field—palm leaves. The pair joined a project to preserve the content of the Sarvamoola Grantha, an ancient work of Hindu spiritual scholarship The famous Apollo 11 mission left behind over 100 artifacts on the Moon, including a small silicon disc inscribed with messages of goodwill from 73 countries (below). Spinoff 2012
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“保存航天历史档案的技术”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。材料属于目录、活动安排、概述或标题型文字，不保证存在单一可验证的机制或结论；应先判断该节点是否适合生成问答。 【建议重写题目】NASA采取什么数字化技术保存航天任务遗留的重要历史记录？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #102 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复历史档案存储和数字化保护的技术机制
3. **具体重写目标**：整页混合/错序抽取：先恢复历史档案存储和数字化保护的技术机制。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #103 · `auto_new_expansion::real_011_batch_11_Spinoff2012::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_011_batch_11_Spinoff2012`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_011_batch_11_Spinoff2012, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Johnson is on pace to sell more than 5 million bottles of his NASA-inspired drink in 2012. on the shelves at Whole Foods, as well as other local specialty food stores. Benefits Unpeeled starts with a kombucha base, to which Johnson adds his own blend of four different probiotics. The bacteria and yeast naturally form a cellulose matrix, or a balanced growth configuration, which allows the organisms to inhabit the same medium without killing each other off. The probiotics remain live and active to the time the consumer opens a bottle. Once consumed, the drink's bacteria propagate in the gastro-intestinal (GI) tract, aiding in digestion and reducing inflammation that causes muscle and joint pain. Unpeeled also helps balance the body's pH levels by alkalizing them. (The human body has a tendency to become oarcidic under the influence of the typical modern diet.) Johnson stresses that it is the quality of bacteria, not the quantity, that matters. Once the GI tract is seeded with good bacteria, they multiply on their own and crowd out pathogens. Each bottle of Unpeeled thus contains three servings' worth of probiotics, which he recommends be consumed throughout the day. From Unpeeled's earliest batches, customers have responded favorably to its health benefits. "This beverage is saving my life," one customer says. "It makes swell- ing go down [and] promotes good digestion. I don't know how I could do without it." Another of Johnson's customers—and longtime patient—has been faithfully drinking Unpeeled since before it had a name, and says the tea helps her manage her painful joints. Unpeeled currently comes in six flavors, which begin with the same green tea kombucha and are differentiated using natural flavorings such as raw ginger, cranberry, mango, seal salt, and juices from various organic fruits. In addition to enhancing flavor, these natural ingredients impart enzymes that bolster the drink's health benefits further. Johnson will soon release a second probiotic beverage line made from a coconut-water base, also to be available in a variety of flavors. Business has been booming for Unpeeled. What began as a back-of-the-office beer-bottle operation now takes up a 10,000 square-foot warehouse. In it are four of Johnson's custom built bioreactors bubbling away with the next batch. Johnson has hired 12 employees to meet production demands and plans on hiring more help soon. After selling 500,000 units in 2010 and over 1 million in 2011, he is on pace to sell more than 5 million bottles of his NASA-inspired drink in 2012. ❖ Mike Johnson (left), says he could not have created the bioreactors he gained at NASA. "There's no way I'd be able to do what I'm doing without that experience," he says. The result (above) is his line of probiotic beverages, Unpeeled. Spinoff 2012 Health and Medicine 37
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_011_batch_11_Spinoff2012:p0039:e000` · 页 `39` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_011_batch_11_Spinoff2012/pages/page_0039/output_json/page_0039.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Johnson is on pace to sell more than 5 million bottles of his NASA-inspired drink in 2012. on the shelves at Whole Foods, as well as other local specialty food stores. Benefits Unpeeled starts with a kombucha base, to which Johnson adds his own blend of four different probiotics. The bacteria and yeast naturally form a cellulose matrix, or a balanced growth configuration, which allows the organisms to inhabit the same medium without killing each other off. The probiotics remain live and active to the time the consumer opens a bottle. Once consumed, the drink's bacteria propagate in the gastro-intestinal (GI) tract, aiding in digestion and reducing inflammation that causes muscle and joint pain. Unpeeled also helps balance the body's pH levels by alkalizing them. (The human body has a tendency to become oarcidic under the influence of the typical modern diet.) Johnson stresses that it is the quality of bacteria, not the quantity, that matters. Once the GI tract is seeded with good bacteria, they multiply on their own and crowd out pathogens. Each bottle of Unpeeled thus contains three servings' worth of probiotics, which he recommends be consumed throughout the day. From Unpeeled's earliest batches, customers have responded favorably to its health benefits. "This beverage is saving my life," one customer says. "It makes swell- ing go down [and] promotes good digestion. I don't know how I could do without it." Another of Johnson's customers—and longtime patient—has been faithfully drinking Unpeeled since before it had a name, and says the tea helps her manage her painful joints. Unpeeled currently comes in six flavors, which begin with the same green tea kombucha and are differentiated using natural flavorings such as raw ginger, cranberry, mango, seal salt, and juices from various organic fruits. In addition to enhancing flavor, these natural ingredients impart enzymes that bolster the drink's health benefits further. Johnson will soon release a second probiotic beverage line made from a coconut-water base, also to be available in a variety of flavors. Business has been booming for Unpeeled. What began as a back-of-the-office beer-bottle operation now takes up a 10,000 square-foot warehouse. In it are four of Johnson's custom built bioreactors bubbling away with the next batch. Johnson has hired 12 employees to meet production demands and plans on hiring more help soon. After selling 500,000 units in 2010 and over 1 million in 2011, he is on pace to sell more than 5 million bottles of his NASA-inspired drink in 2012. ❖ Mike Johnson (left), says he could not have created the bioreactors he gained at NASA. "There's no way I'd be able to do what I'm doing without that experience," he says. The result (above) is his line of probiotic beverages, Unpeeled. Spinoff 2012 Health and Medicine 37
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA启发的康普茶饮料产品”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】Unpeeled如何利用康普茶基底开发其商用饮料？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #103 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复 NASA 启发的康普茶商业案例，并区分宣传与证据
3. **具体重写目标**：整页混合/错序抽取：先恢复 NASA 启发的康普茶商业案例，并区分宣传与证据。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #104 · `auto_new_expansion::real_012_batch_12_Spinoff2011::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_012_batch_12_Spinoff2011`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_012_batch_12_Spinoff2011, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
USA y Tu W hile NASA is committed to preparing the next gen- eration of scientists, engineers, and technologists, leading Spanish-language media company Univision Communications Inc. is focused on improving graduation rates and preparing Hispanic students for college. Together, NASA and Univision are launching an on-air and online initiative to help engage Hispanic students in science, technology, engineering, and mathematics (STEM) education. In October 2010, Univision aired a series of Spanish-language educational video segments produced by NASA entitled NASA y Tu (NASA and You). Featuring Hispanic employees from NASA, the 30-second videos present new perspectives on education and STEM careers. Among many featured NASA staff members are astronaut Jose Hernandez, who talks about his life and how he became an astro- nant, and Margaret Dominguez, an optics engineer, who talks about the engineering challenges of putting a mirror as large as a tennis court on a small spacecraft. A crew from Univision Communications Inc. films a video segment for an initiative to engage Hispanic students in science, technology, engineering, and mathematics education. Festival of Learning More than 500 science organizations gathered in the Nation's capital in 2010 as part of the first national Science and Engineering Festival—and NASA was one of them. Nearly 1 million people participated in the two-week event that began with activities in local schools and ended with a two-day expo attended by nearly 500,000 people. NASA booths at the expo featured hands-on activities, demonstrations, and exhibits. The event also marked the culmination of NASA's Summer of Innovation education initiative, aimed at engaging middle school students in science, technology, engineering, and math activities during the summer break. During its inaugural year, the program reached more than 75,000 middle-school students. The Science and Engineering Festival began with activities in local schools and ended with a 2-day expo on the National Mall and surrounding areas. 180 Education News Spinoff 2011
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_012_batch_12_Spinoff2011:p0182:e000` · 页 `182` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_012_batch_12_Spinoff2011/pages/page_0182/output_json/page_0182.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
USA y Tu W hile NASA is committed to preparing the next gen- eration of scientists, engineers, and technologists, leading Spanish-language media company Univision Communications Inc. is focused on improving graduation rates and preparing Hispanic students for college. Together, NASA and Univision are launching an on-air and online initiative to help engage Hispanic students in science, technology, engineering, and mathematics (STEM) education. In October 2010, Univision aired a series of Spanish-language educational video segments produced by NASA entitled NASA y Tu (NASA and You). Featuring Hispanic employees from NASA, the 30-second videos present new perspectives on education and STEM careers. Among many featured NASA staff members are astronaut Jose Hernandez, who talks about his life and how he became an astro- nant, and Margaret Dominguez, an optics engineer, who talks about the engineering challenges of putting a mirror as large as a tennis court on a small spacecraft. A crew from Univision Communications Inc. films a video segment for an initiative to engage Hispanic students in science, technology, engineering, and mathematics education. Festival of Learning More than 500 science organizations gathered in the Nation's capital in 2010 as part of the first national Science and Engineering Festival—and NASA was one of them. Nearly 1 million people participated in the two-week event that began with activities in local schools and ended with a two-day expo attended by nearly 500,000 people. NASA booths at the expo featured hands-on activities, demonstrations, and exhibits. The event also marked the culmination of NASA's Summer of Innovation education initiative, aimed at engaging middle school students in science, technology, engineering, and math activities during the summer break. During its inaugural year, the program reached more than 75,000 middle-school students. The Science and Engineering Festival began with activities in local schools and ended with a 2-day expo on the National Mall and surrounding areas. 180 Education News Spinoff 2011
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“西语教育媒体与NASA STEM推广”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】Univision通过什么合作方式支持西语学生的科学技术教育？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #104 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先恢复 NASA STEM 西语推广媒体的具体任务和结果
3. **具体重写目标**：整页混合/错序抽取：先恢复 NASA STEM 西语推广媒体的具体任务和结果。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #105 · `auto_new_expansion::real_012_batch_12_Spinoff2011::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`VERIFY_SOURCE_MODALITY_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_012_batch_12_Spinoff2011`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_012_batch_12_Spinoff2011, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
● Time-saving software derived from a suite of NASA- invented tools for improving the efficiency of air traffic control, now allowing commercial airlines to take the most direct possible flight paths and potentially save millions of gallons of fuel each year. (page 70) ● A health and fitness monitoring technology rendered into a simple strap or even a t-shirt, capable of mea- suring and recording the vital signs of soldiers, first responders, professional athletes, and consumers seek- ing to get in shape — developed with help from NASA physiologists. (page 108) ● A manufacturing process, devised for fabricating unique components for NASA deep space science missions, that now creates enabling parts for advanced medical imaging machines and gas turbine engines at a greatly reduced cost. (page 54) ● Fire suppression systems that incorporate the features of a NASA-derived rocket design into a powerful tool that firefighters can use to safely snuff out a threaten- ing blaze in seconds — even tackling wildfires in rugged conditions. (page 90) ● A new class of GPS navigation receivers that provide not only positioning capabilities for commercial satel- lites, but a unique means of collecting scientific data for weather forecasting and studies of our changing climate. (page 122) ● Coal gasification technology, developed with exper- tise gained from the design of rocket engines such as the Space Shuttle Main Engines, that can provide a 10-percent reduction in carbon emissions compared to conventional gasification plants, which are already the cleanest coal-based power systems available. These new
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_012_batch_12_Spinoff2011:p0007:e007` · 页 `7` · 类型 `list`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_012_batch_12_Spinoff2011/pages/page_0007/output_json/page_0007.json`
   - bbox：`[570, 266, 1033, 1124]`

````text
● Time-saving software derived from a suite of NASA- invented tools for improving the efficiency of air traffic control, now allowing commercial airlines to take the most direct possible flight paths and potentially save millions of gallons of fuel each year. (page 70) ● A health and fitness monitoring technology rendered into a simple strap or even a t-shirt, capable of mea- suring and recording the vital signs of soldiers, first responders, professional athletes, and consumers seek- ing to get in shape — developed with help from NASA physiologists. (page 108) ● A manufacturing process, devised for fabricating unique components for NASA deep space science missions, that now creates enabling parts for advanced medical imaging machines and gas turbine engines at a greatly reduced cost. (page 54) ● Fire suppression systems that incorporate the features of a NASA-derived rocket design into a powerful tool that firefighters can use to safely snuff out a threaten- ing blaze in seconds — even tackling wildfires in rugged conditions. (page 90) ● A new class of GPS navigation receivers that provide not only positioning capabilities for commercial satel- lites, but a unique means of collecting scientific data for weather forecasting and studies of our changing climate. (page 122) ● Coal gasification technology, developed with exper- tise gained from the design of rocket engines such as the Space Shuttle Main Engines, that can provide a 10-percent reduction in carbon emissions compared to conventional gasification plants, which are already the cleanest coal-based power systems available. These new
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA空管软件促成更直接的航路”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】源自NASA空管研究的软件如何让航空公司选择更直接的航线？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #105 行号。**目标操作**：`VERIFY_SOURCE_MODALITY_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：仅有列表：NASA 空管软件如何提高航路效率；须验证列表足以支撑问题，否则补正文
3. **具体重写目标**：仅有列表：NASA 空管软件如何提高航路效率；须验证列表足以支撑问题，否则补正文。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #106 · `auto_new_expansion::real_013_batch_13_Spinoff2010::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`real_013_batch_13_Spinoff2010`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_013_batch_13_Spinoff2010, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Here on Earth, if your sink springs a leak, you can call in a plumber, or if you're handy, you can head out to the local hardware store, buy a few replacement parts, and fix the problem yourself. If the leak isn't particularly bad, you can even place a bucket under the sink to catch the dripping water and put the chore off until the weekend. These options aren't exactly available to astronauts working on the International Space Station. They can't call in a specialist to make repairs when problems occur, and they can't run out to the hardware store for the exact parts needed for a repair. Plus, there isn't much free time in an astronaut's onboard schedule. Repairs need to be made as soon and as effi- ciently as possible. Toward that end, NASA funded the design of simple and reusable patch repair systems for servicing, maintaining, and repairing structural compo- nents in space without the need for heavy machinery or an expense of time.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_013_batch_13_Spinoff2010:p0094:e002` · 页 `94` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_013_batch_13_Spinoff2010/pages/page_0094/output_json/page_0094.json`
   - bbox：`[93, 204, 549, 662]`

````text
Here on Earth, if your sink springs a leak, you can call in a plumber, or if you're handy, you can head out to the local hardware store, buy a few replacement parts, and fix the problem yourself. If the leak isn't particularly bad, you can even place a bucket under the sink to catch the dripping water and put the chore off until the weekend. These options aren't exactly available to astronauts working on the International Space Station. They can't call in a specialist to make repairs when problems occur, and they can't run out to the hardware store for the exact parts needed for a repair. Plus, there isn't much free time in an astronaut's onboard schedule. Repairs need to be made as soon and as effi- ciently as possible. Toward that end, NASA funded the design of simple and reusable patch repair systems for servicing, maintaining, and repairing structural compo- nents in space without the need for heavy machinery or an expense of time.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“太空设施泄漏维修与地面环境的差异”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么航天器的泄漏维修不能像地面家庭管道维修那样处理？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #106 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：提问空间设施泄漏为何不能照搬地面维修；材料仅支持有限对比时不得补未述技术
3. **具体重写目标**：提问空间设施泄漏为何不能照搬地面维修；材料仅支持有限对比时不得补未述技术。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #107 · `auto_new_expansion::real_013_batch_13_Spinoff2010::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`real_013_batch_13_Spinoff2010`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_013_batch_13_Spinoff2010, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Solid oxide fuel cells like those in Bloom's Energy Server operate at temperatures upwards of 1,800 °F. The high temperatures, efficiently harnessed by the Bloom system's materials and design, enable the server to use natural gas, any number of environmentally friendly biogasses created from plant waste, or methane recaptured from landfills and farms. Fuel is fed into the system along with water. The high temperatures generate steam, which mixes with the fuel to create a reformed fuel called syngas on the surface of the cell. As the syngas moves across the anode, it draws oxygen ions from the cathode, and an electrochemical reaction results in electricity, water, and only a small amount of carbon dioxide—a process that according to Bloom is about 67-percent cleaner than that of a typical coal-fired power plant when using fossil fuels and 100-percent cleaner with renewable fuels. The server can switch between fuels on the fly and does not require an external chemical reformer or the expensive precious metals, corrosive acids, or molten materials required by other conventional fuel cell systems.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_013_batch_13_Spinoff2010:p0107:e002` · 页 `107` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_013_batch_13_Spinoff2010/pages/page_0107/output_json/page_0107.json`
   - bbox：`[93, 506, 550, 1021]`

````text
Solid oxide fuel cells like those in Bloom's Energy Server operate at temperatures upwards of 1,800 °F. The high temperatures, efficiently harnessed by the Bloom system's materials and design, enable the server to use natural gas, any number of environmentally friendly biogasses created from plant waste, or methane recaptured from landfills and farms. Fuel is fed into the system along with water. The high temperatures generate steam, which mixes with the fuel to create a reformed fuel called syngas on the surface of the cell. As the syngas moves across the anode, it draws oxygen ions from the cathode, and an electrochemical reaction results in electricity, water, and only a small amount of carbon dioxide—a process that according to Bloom is about 67-percent cleaner than that of a typical coal-fired power plant when using fossil fuels and 100-percent cleaner with renewable fuels. The server can switch between fuels on the fly and does not require an external chemical reformer or the expensive precious metals, corrosive acids, or molten materials required by other conventional fuel cell systems.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“固体氧化物燃料电池的高温优势”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】Bloom Energy的固体氧化物燃料电池为何可在高温下使用多种燃料？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #107 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：提问固体氧化物燃料电池为何在高温条件下运行并带来什么效益；需限定本段内容
3. **具体重写目标**：提问固体氧化物燃料电池为何在高温条件下运行并带来什么效益；需限定本段内容。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #108 · `auto_new_expansion::real_015_batch_15_spinoff2008::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`EXCLUDE_FROM_FACTUAL_QA`。
- **文档与节点状态**：`real_015_batch_15_spinoff2008`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`review_status`, `answer_status (if present)`, `benchmark_membership (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_015_batch_15_spinoff2008, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
is finding continued use in terrestrial and interplanetary studies. page 132 Virtual Reality System Offers a Wide Perspective As part of an SBIR agreement to improve the telepresence of Johnson Space Center's Robonaut, Baltimore-based Sensics Inc. created a head-mounted display with a high-resolution, three-dimensional pan- orama. The Sensics piSight is now being sold commercially for high-end virtual reality applications. Virtual surroundings appear in the viewfinder and respond to head movements. page 134 Software Simulates Sight: Flat Panel Mura Detection Radiant Imaging Inc., of Duvall, Washington, licensed the Spatial Standard Observer (SSO) software from Ames Research Center. The SSO simulates a simplified model of human spatial vision, operating on a pair of images that are viewed at a specific viewing distance with pixels having a known relation to lumi- nance. The SSO software was used to develop the TrueMURA Analysis Module, incorporated into Radiant Imaging's ProMetric 9.1 system. When used in con- junction with the ProMetric Series Imaging Colorimeters, the new software module provides a complete characterization and testing system for flat panel displays, es- pecially LCD panels and displays. page 136 Inductive System Monitors Tasks The Inductive Monitoring System is software developed at Ames Research Center that uses artificial intelligence and data mining techniques to build system- monitoring knowledge bases from archived or simulated sensor data. This information is then used to detect unusual or anomalous behavior that may indicate an impending system failure. iSagacy Inc., based out of Portland, Maine, executed a nonexclusive license and is now offering it for use for water treatment plants, water heating and cooling in the process industry, oil refiner- ies, public water distribution, and power generation plants. page 138 Mars Mapping Technology Brings Main Street to Life Berkeley, California-based earthmine inc., licensed 3-D data-generation software and algorithms from NASA's Jet Propulsion Laboratory originally used to create a 3-D representation of the local terrain to allow autonomous routing of the Mars Exploration Rovers. earthmine combined the software and algorithms with its unique capture hardware and Web deliv- ery technology in a system that integrates the information to deliver accurate street- level geospatial data through a Web-based interface. Complete municipalities are collected through high-quality, 3-D pan- oramic images—including every road, alley, and freeway—to create a complete, con- sistent, and publicly accessible geospatial view of cities for official and commercial applications. page 140 Intelligent Memory Module Overcomes Harsh Environments 3D Plus USA Inc., of McKinney, Texas, licensed Radiation Tolerant Intelligent Memory Stack technology from Langley Research Center for systems and methods to detect a failure event in field program- mable gate arrays. In partnership with Langley, 3D Plus developed the first high-density and fast access time memory module tolerant of space radiation effects. This module decreases design complex- ity for space-based electronics requiring memory with its simple interface and internal radiation tolerance management. Expected applications include commercial or scientific geostationary missions and deep space scientific exploration, and high-reliability computing in other radia- tion-intensive environments like nuclear facilities. page 142 Integrated Circuit Chip Improves Network Efficiency Under a 2002 Space Act Agreement, Rockville, Maryland-based BAE Systems Inc. worked with Goddard Space Flight Center to create a SpaceWire-based application-specific integrated circuit (ASIC) chip for bridging existing space electronics and Goddard's new link- and-switch routers. BAE Systems' ASIC integrates easily into an onboard system and also decreases the part count, overall system complexity, ongoing costs, and power requirements for the system's board while also improving speed and reliability. page 144 38 Spinoff 2008
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_015_batch_15_spinoff2008:p0040:e000` · 页 `40` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_015_batch_15_spinoff2008/pages/page_0040/output_json/page_0040.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
is finding continued use in terrestrial and interplanetary studies. page 132 Virtual Reality System Offers a Wide Perspective As part of an SBIR agreement to improve the telepresence of Johnson Space Center's Robonaut, Baltimore-based Sensics Inc. created a head-mounted display with a high-resolution, three-dimensional pan- orama. The Sensics piSight is now being sold commercially for high-end virtual reality applications. Virtual surroundings appear in the viewfinder and respond to head movements. page 134 Software Simulates Sight: Flat Panel Mura Detection Radiant Imaging Inc., of Duvall, Washington, licensed the Spatial Standard Observer (SSO) software from Ames Research Center. The SSO simulates a simplified model of human spatial vision, operating on a pair of images that are viewed at a specific viewing distance with pixels having a known relation to lumi- nance. The SSO software was used to develop the TrueMURA Analysis Module, incorporated into Radiant Imaging's ProMetric 9.1 system. When used in con- junction with the ProMetric Series Imaging Colorimeters, the new software module provides a complete characterization and testing system for flat panel displays, es- pecially LCD panels and displays. page 136 Inductive System Monitors Tasks The Inductive Monitoring System is software developed at Ames Research Center that uses artificial intelligence and data mining techniques to build system- monitoring knowledge bases from archived or simulated sensor data. This information is then used to detect unusual or anomalous behavior that may indicate an impending system failure. iSagacy Inc., based out of Portland, Maine, executed a nonexclusive license and is now offering it for use for water treatment plants, water heating and cooling in the process industry, oil refiner- ies, public water distribution, and power generation plants. page 138 Mars Mapping Technology Brings Main Street to Life Berkeley, California-based earthmine inc., licensed 3-D data-generation software and algorithms from NASA's Jet Propulsion Laboratory originally used to create a 3-D representation of the local terrain to allow autonomous routing of the Mars Exploration Rovers. earthmine combined the software and algorithms with its unique capture hardware and Web deliv- ery technology in a system that integrates the information to deliver accurate street- level geospatial data through a Web-based interface. Complete municipalities are collected through high-quality, 3-D pan- oramic images—including every road, alley, and freeway—to create a complete, con- sistent, and publicly accessible geospatial view of cities for official and commercial applications. page 140 Intelligent Memory Module Overcomes Harsh Environments 3D Plus USA Inc., of McKinney, Texas, licensed Radiation Tolerant Intelligent Memory Stack technology from Langley Research Center for systems and methods to detect a failure event in field program- mable gate arrays. In partnership with Langley, 3D Plus developed the first high-density and fast access time memory module tolerant of space radiation effects. This module decreases design complex- ity for space-based electronics requiring memory with its simple interface and internal radiation tolerance management. Expected applications include commercial or scientific geostationary missions and deep space scientific exploration, and high-reliability computing in other radia- tion-intensive environments like nuclear facilities. page 142 Integrated Circuit Chip Improves Network Efficiency Under a 2002 Space Act Agreement, Rockville, Maryland-based BAE Systems Inc. worked with Goddard Space Flight Center to create a SpaceWire-based application-specific integrated circuit (ASIC) chip for bridging existing space electronics and Goddard's new link- and-switch routers. BAE Systems' ASIC integrates easily into an onboard system and also decreases the part count, overall system complexity, ongoing costs, and power requirements for the system's board while also improving speed and reliability. page 144 38 Spinoff 2008
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“目录页里的虚拟现实和机器人项目”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。材料属于目录、活动安排、概述或标题型文字，不保证存在单一可验证的机制或结论；应先判断该节点是否适合生成问答。 【建议重写题目】该卷目录中用于Robonaut远程临场的虚拟现实项目位于哪一页？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #108 行号。**目标操作**：`EXCLUDE_FROM_FACTUAL_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：目录/混合页含虚拟现实和机器人项目标题；优先排除，不能将目录当机理证据
3. **具体重写目标**：目录/混合页含虚拟现实和机器人项目标题；优先排除，不能将目录当机理证据。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：此来源是目录/日程/作者/索引类，不足以作为因果知识型 gold。默认 `EXCLUDE_OR_PARK`；只有明确改造成表格/元数据检索任务且 schema、评价指标允许才考虑保留。

**完成门槛**：
该条退出事实型 Gold QA（留审计记录）；若改为元数据任务需有新的明确任务类型、验证过的表格/目录源及可评分答案。

---

### #109 · `auto_new_expansion::real_015_batch_15_spinoff2008::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
- **文档与节点状态**：`real_015_batch_15_spinoff2008`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_015_batch_15_spinoff2008, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Spinoff 2008 39 Portable Device Analyzes Rocks and Minerals inXitu Inc., of Mountain View, California, entered into a Phase Ⅱ SBIR contract with Ames Research Center to develop technol- ogies for the next generation of scientific instruments for materials analysis. The work resulted in a sample handling system that could find a wide range of applica- tions in research and industrial laboratories as a means to load powdered samples for analysis or process control. Potential industries include chemical, cement, inks, pharmaceutical, ceramics, and forensics. Additional applications include character- izing materials that cannot be ground to a fine size, such as explosives and research pharmaceuticals. pase 152 NASA Design Strengthens Wells Fiction Stir Welding (FSW) is a solid- state joining process—a combination of extruding and forging—ideal for use when the original metal characteristics must remain as unchanged as possible. While exploring ways to improve the use of FSW in manufacturing, engineers at Marshall Space Flight Center created technologies to address the method's shortcomings. MTS Systems Corporation, of Eden Prairie, Minnesota, discovered the NASA-developed technology and then signed a co-exclusive license agreement to commercialize Marshall's design for use in high-strength structural alloys. The result- ing process offers the added bonuses of being cost-competitive, efficient, and most importantly, versatile. pase 154 Polyimide Boosts High- Temperature Performance Maverick Corporation, of Blue Ash, Ohio, licensed DMBZ-15 polyimide technol- ogy from Glenn Research Center. This ultrahigh-temperature material provides substantial weight savings and reduced machining costs compared to the same component made with more traditional metallic materials. DMBZ-15 has a wide range of applications from aerospace (air- craft engine and airframe components, space transportation systems, and missiles) to non-aerospace (oil drilling, rolling mill), and is particularly well-suited to use as face sheets with honeycombs or thermal protec- tion systems for reusable launch vehicles, which encounter elevated temperatures during launch and reentry. pase 156 NASA Innovation Builds Better Nanotubes Nanotailor Inc., based in Austin, Texas, licensed Goddard Space Flight Center's unique single-walled carbon nanotube (SWCNT) fabrication process with plans to make high-quality, low-cost SWCNTs available commercially. Carbon nanotubes are being used in a wide variety of applica- tions, and NASA's improved production method will increase their applicability in medicine, microelectronics, advanced materials, and molecular containment. Nanotailor built and tested a prototype based on Goddard's process, and is using this technique to lower the cost and improve the integrity of nanotubes, offering a better product for use in biomaterials, advanced materials, space exploration, highway and building construction, and many other applications. pase 158
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_015_batch_15_spinoff2008:p0041:e000` · 页 `41` · 类型 `distorted_page`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_015_batch_15_spinoff2008/pages/page_0041/output_json/page_0041.json`
   - bbox：`[0, 0, 1600, 1237]`

````text
Spinoff 2008 39 Portable Device Analyzes Rocks and Minerals inXitu Inc., of Mountain View, California, entered into a Phase Ⅱ SBIR contract with Ames Research Center to develop technol- ogies for the next generation of scientific instruments for materials analysis. The work resulted in a sample handling system that could find a wide range of applica- tions in research and industrial laboratories as a means to load powdered samples for analysis or process control. Potential industries include chemical, cement, inks, pharmaceutical, ceramics, and forensics. Additional applications include character- izing materials that cannot be ground to a fine size, such as explosives and research pharmaceuticals. pase 152 NASA Design Strengthens Wells Fiction Stir Welding (FSW) is a solid- state joining process—a combination of extruding and forging—ideal for use when the original metal characteristics must remain as unchanged as possible. While exploring ways to improve the use of FSW in manufacturing, engineers at Marshall Space Flight Center created technologies to address the method's shortcomings. MTS Systems Corporation, of Eden Prairie, Minnesota, discovered the NASA-developed technology and then signed a co-exclusive license agreement to commercialize Marshall's design for use in high-strength structural alloys. The result- ing process offers the added bonuses of being cost-competitive, efficient, and most importantly, versatile. pase 154 Polyimide Boosts High- Temperature Performance Maverick Corporation, of Blue Ash, Ohio, licensed DMBZ-15 polyimide technol- ogy from Glenn Research Center. This ultrahigh-temperature material provides substantial weight savings and reduced machining costs compared to the same component made with more traditional metallic materials. DMBZ-15 has a wide range of applications from aerospace (air- craft engine and airframe components, space transportation systems, and missiles) to non-aerospace (oil drilling, rolling mill), and is particularly well-suited to use as face sheets with honeycombs or thermal protec- tion systems for reusable launch vehicles, which encounter elevated temperatures during launch and reentry. pase 156 NASA Innovation Builds Better Nanotubes Nanotailor Inc., based in Austin, Texas, licensed Goddard Space Flight Center's unique single-walled carbon nanotube (SWCNT) fabrication process with plans to make high-quality, low-cost SWCNTs available commercially. Carbon nanotubes are being used in a wide variety of applica- tions, and NASA's improved production method will increase their applicability in medicine, microelectronics, advanced materials, and molecular containment. Nanotailor built and tested a prototype based on Goddard's process, and is using this technique to lower the cost and improve the integrity of nanotubes, offering a better product for use in biomaterials, advanced materials, space exploration, highway and building construction, and many other applications. pase 158
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“便携式矿物分析装置的研制来源”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】inXitu的便携式岩石矿物分析技术最初通过哪一类NASA研发合同获得支持？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #109 行号。**目标操作**：`REPARSE_PAGE_THEN_REGENERATE_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：整页混合/错序抽取：先找到便携式矿物分析装置的具体传感/检测技术段落
3. **具体重写目标**：整页混合/错序抽取：先找到便携式矿物分析装置的具体传感/检测技术段落。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：`distorted_page` 意味着当前 evidence 不是可信的标准语义节点。必须重新解析、分割、恢复 reading order，回填正确 evidence ID 和 canonical node，再重新生成 Q/A；禁止保留旧页级噪声当最终 gold。

**完成门槛**：
源 PDF 和正文阅读顺序核验通过、evidence 从 `distorted_page` 重映射为有效节点、生成可独立理解的问题和可核验答案、mapping verified、二次人工复核通过。

---

### #110 · `auto_new_expansion::real_020_batch_20_spin03::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`real_020_batch_20_spin03`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_020_batch_20_spin03, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
NASA's Offices of Space Flight and Aerospace Technology, through the NASA Quest program, spon- sored a separate robot-design initiative called the Robotic Helper Design Challenge. In May, the 2-month educational activity brought students and NASA experts together for a live Webcast to review the progress of the students' designs, intended to help astronauts living and working on the ISS. Through the Webcast, the students engaged in a virtual tour of the ISS, learned about micro- gravity, and had questions about their designs answered by NASA experts. An estimated 2,500 students in 100 classrooms (representing 26 states and 7 countries) took part in the final design challenge. Entries included a Space Pet Involving Kinetic Energy (SPIKE) robot that uses propellers to steer itself while floating through low- gravity atmospheres (created by eighth graders at Barkalow Middle School in Freehold, New Jersey), and “Mr. Helper,” which comes equipped with a homing device so that it can return to its docking bay to recharge, and a large storage compartment for astronauts’ tools (created by fourth, fifth, and sixth grade students at the K.R. Smith Elementary School in San Jose, California). The inspiration for the design challenge was NASA's prototype Personal Satellite Assistant, an astronaut- support tool devised to move and operate autonomously or by remote control in the microgravity environment of the Space Shuttle, ISS, or a future space vehicle.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_020_batch_20_spin03:p0128:e001` · 页 `128` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0128/output_json/page_0128.json`
   - bbox：`[85, 242, 551, 903]`

````text
NASA's Offices of Space Flight and Aerospace Technology, through the NASA Quest program, spon- sored a separate robot-design initiative called the Robotic Helper Design Challenge. In May, the 2-month educational activity brought students and NASA experts together for a live Webcast to review the progress of the students' designs, intended to help astronauts living and working on the ISS. Through the Webcast, the students engaged in a virtual tour of the ISS, learned about micro- gravity, and had questions about their designs answered by NASA experts. An estimated 2,500 students in 100 classrooms (representing 26 states and 7 countries) took part in the final design challenge. Entries included a Space Pet Involving Kinetic Energy (SPIKE) robot that uses propellers to steer itself while floating through low- gravity atmospheres (created by eighth graders at Barkalow Middle School in Freehold, New Jersey), and “Mr. Helper,” which comes equipped with a homing device so that it can return to its docking bay to recharge, and a large storage compartment for astronauts’ tools (created by fourth, fifth, and sixth grade students at the K.R. Smith Elementary School in San Jose, California). The inspiration for the design challenge was NASA's prototype Personal Satellite Assistant, an astronaut- support tool devised to move and operate autonomously or by remote control in the microgravity environment of the Space Shuttle, ISS, or a future space vehicle.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NASA Quest机器帮手设计竞赛”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】Robotic Helper Design Challenge通过什么活动让学生参与机器人工程设计？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #110 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：重写为 NASA Quest 机器帮手设计竞赛的任务目的与参与方式；无技术因果则排除
3. **具体重写目标**：重写为 NASA Quest 机器帮手设计竞赛的任务目的与参与方式；无技术因果则排除。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #111 · `auto_new_expansion::real_020_batch_20_spin03::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`real_020_batch_20_spin03`；`single_evidence`；`PENDING_EVIDENCE_NODE_ASSEMBLY`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in real_020_batch_20_spin03, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
This year, NASA and the National Highway Traffic Safety Administration (NHTSA) joined forces to, literal- ly, take vehicles out for a spin. The NHTSA currently employs a consumer rating system that uses an engineer- ing formula to determine rollover resistance, but wanted to research new methods through NASA. Goddard Space Flight Center's High Capacity Centrifuge, used to test spacecraft before they are sent into space, was exactly what was needed to spin up some unique and original vehicle testing. Vehicles were positioned on the High Capacity Centrifuge's test platform, and spun until iner- tia and centrifugal force caused them to tip. A crash-test dummy was along for the ride in each vehicle to increase the realism and accuracy of the test results. The High Capacity Centrifuge is a big machine, more than 150 feet in diameter, filling an entire circular building. With two powerful motors running at full tilt, the outer edge of the test arm can reach speeds of more than 200 miles per hour, producing a force 30 times Earth's gravity. At rest, the giant multi-ton arm sits on bearings so smooth just two or three people can push it around the room. NASA and the NHTSA expect this first-of-its-kind test will
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `real_020_batch_20_spin03:p0133:e003` · 页 `133` · 类型 `para`。
   - 来源位置：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work/real_020_batch_20_spin03/pages/page_0133/output_json/page_0133.json`
   - bbox：`[193, 488, 659, 1045]`

````text
This year, NASA and the National Highway Traffic Safety Administration (NHTSA) joined forces to, literal- ly, take vehicles out for a spin. The NHTSA currently employs a consumer rating system that uses an engineer- ing formula to determine rollover resistance, but wanted to research new methods through NASA. Goddard Space Flight Center's High Capacity Centrifuge, used to test spacecraft before they are sent into space, was exactly what was needed to spin up some unique and original vehicle testing. Vehicles were positioned on the High Capacity Centrifuge's test platform, and spun until iner- tia and centrifugal force caused them to tip. A crash-test dummy was along for the ride in each vehicle to increase the realism and accuracy of the test results. The High Capacity Centrifuge is a big machine, more than 150 feet in diameter, filling an entire circular building. With two powerful motors running at full tilt, the outer edge of the test arm can reach speeds of more than 200 miles per hour, producing a force 30 times Earth's gravity. At rest, the giant multi-ton arm sits on bearings so smooth just two or three people can push it around the room. NASA and the NHTSA expect this first-of-its-kind test will
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“车辆翻滚安全的评价项目”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】NASA与NHTSA合作评估汽车翻滚安全性时关注了什么测试问题？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #111 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：重写为 NASA/NHTSA 车辆翻滚研究评测什么指标，避免引入未经证明的安全结论
3. **具体重写目标**：重写为 NASA/NHTSA 车辆翻滚研究评测什么指标，避免引入未经证明的安全结论。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #112 · `auto_legacy_expansion::CERNCourier2022NovDec-digitaledition::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_WITH_VISUAL_EVIDENCE_OR_EXCLUDE`。
- **文档与节点状态**：`CERNCourier2022NovDec-digitaledition`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in CERNCourier2022NovDec-digitaledition, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
ue to a lack of stellar evolution. To meas- ure the chemical composition of the gas clouds, Ashley and her team looked at the UV spectra from sources behind them to be the induced absorption lines. To their imprise, they found not only clouds with high metallicity but also those with lower metallicity, matching that of galactic halo cs, thereby implying a different origin for these clouds. Suggestions that the second class of clouds is a result of heavy clouds accumulating lower-metallicity gases are consistent with observations. If heavy clouds absorb these gases is significantly longer than the age of the Fermi bubbles, instead, it appears that while the bubbles radiod lag along gas clouds from the galactic lane, they also swept up existing halo gas clouds as they expanded outwards.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CERNCourier2022NovDec-digitaledition_page_0006_HY_035` · 页 `page_0006` · 类型 `COMPOSITE`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_1/hybrid/shard_1/CERNCourier2022NovDec-digitaledition/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_040`
   - bbox：`[[1365.0, 176.0, 1549.0, 436.0], [1050.0, 176.0, 1350.0, 353.0]]`

````text
ue to a lack of stellar evolution. To meas- ure the chemical composition of the gas clouds, Ashley and her team looked at the UV spectra from sources behind them to be the induced absorption lines. To their imprise, they found not only clouds with high metallicity but also those with lower metallicity, matching that of galactic halo cs, thereby implying a different origin for these clouds. Suggestions that the second class of clouds is a result of heavy clouds accumulating lower-metallicity gases are consistent with observations. If heavy clouds absorb these gases is significantly longer than the age of the Fermi bubbles, instead, it appears that while the bubbles radiod lag along gas clouds from the galactic lane, they also swept up existing halo gas clouds as they expanded outwards.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“紫外光谱中的吸收线用于气体云成分测量”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】研究者如何利用背景天体的紫外光谱判断银河系气体云的化学成分？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #112 行号。**目标操作**：`REGENERATE_WITH_VISUAL_EVIDENCE_OR_EXCLUDE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：复合图文节点：紫外吸收线如何反映气体云成分；需完整文本/图像并检查页内衔接
3. **具体重写目标**：复合图文节点：紫外吸收线如何反映气体云成分；需完整文本/图像并检查页内衔接。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：必须核实图像/图注联合证据，评测若只允许纯文本 node 则排除依赖图形读数的题。

**完成门槛**：
实际图像与图注一致，并且当前检索单元能访问图像；图像若不可用不得作为正式 Gold Evidence。

---

### #113 · `auto_legacy_expansion::CERNCourier2022NovDec-digitaledition::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CERNCourier2022NovDec-digitaledition`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in CERNCourier2022NovDec-digitaledition, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
with the SM prediction of $(3.7\pm1)\times10^{-7}$ , and reduces a previous tension between theory and experiment, which was based on the combination of the previous CMS result with the ATLAS and LHCb values. The variation in the central value of the $y(\text{GeV})$ ratio, i.e., $|\text{GeV}|\leq y\leq 1$ , from the use of a larger data sample and by the change of the B-hadron fragmentation fraction ratio (by about 8 % ), the meas- ured effective lifetime of the $B^{*}\to\mu\nu$ decay, $1.8\pm0.2\%,$ is also consistent with the SM prediction. The precision of this measurement is approaching the level necessary to probe the CP properties of our LHCb data, even if we did differ from the SM prediction. Finally, $B^{*}\to\mu\nu$ decay remains unseen.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CERNCourier2022NovDec-digitaledition_page_0017_HY_006` · 页 `page_0017` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_6/hybrid/shard_0/CERNCourier2022NovDec-digitaledition/page_0017/evidence_nodes.jsonl`
   - 旧版原子节点：`A_011`
   - bbox：`[[532.0, 168.0, 720.0, 404.0]]`

````text
with the SM prediction of $(3.7\pm1)\times10^{-7}$ , and reduces a previous tension between theory and experiment, which was based on the combination of the previous CMS result with the ATLAS and LHCb values. The variation in the central value of the $y(\text{GeV})$ ratio, i.e., $|\text{GeV}|\leq y\leq 1$ , from the use of a larger data sample and by the change of the B-hadron fragmentation fraction ratio (by about 8 % ), the meas- ured effective lifetime of the $B^{*}\to\mu\nu$ decay, $1.8\pm0.2\%,$ is also consistent with the SM prediction. The precision of this measurement is approaching the level necessary to probe the CP properties of our LHCb data, even if we did differ from the SM prediction. Finally, $B^{*}\to\mu\nu$ decay remains unseen.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“粒子衰变实验结果与标准模型预言的差异”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】新的实验测量如何影响此前某粒子衰变率与标准模型预言的张力？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #113 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：粒子衰变观测量与标准模型预言有何差别；必须标注对应的衰变通道和不确定度
3. **具体重写目标**：粒子衰变观测量与标准模型预言有何差别；必须标注对应的衰变通道和不确定度。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #114 · `auto_legacy_expansion::CERNCourier2025JanFeb-digitaledition::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CERNCourier2025JanFeb-digitaledition`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in CERNCourier2025JanFeb-digitaledition, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
The masses of SUSY particles have very important implications for both the physics of our universe and how they could be potentially produced and observed at experiments like CMS. The heavier the sparticle, the rarer its appearance. On the other hand, when heavy particle decay, their mass is con- verted to the masses and momenta of SM particles, like leptons and jets. These particles are detected by CMS, with large masses leaving potentially spectacular (and conspicuous) signatures. Each heavy sparticle is expected to continue to decay to lighter ones, ending with the lightest SUSY particles (LSPs). LSPs, though mas- sive, are stable and do not decay in the detector. Instead, they appear as missing momentum. In cases of compressed spar- cicle mass spectra, the mass difference between the initially produced sparticles and LSPs is small. This means the low rates of production of massive sparticles are not accompanied by high – momentum
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CERNCourier2025JanFeb-digitaledition_page_0006_HY_015` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_3/hybrid/shard_0/CERNCourier2025JanFeb-digitaledition/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_027`
   - bbox：`[[851.0, 367.0, 1044.0, 694.0]]`

````text
The masses of SUSY particles have very important implications for both the physics of our universe and how they could be potentially produced and observed at experiments like CMS. The heavier the sparticle, the rarer its appearance. On the other hand, when heavy particle decay, their mass is con- verted to the masses and momenta of SM particles, like leptons and jets. These particles are detected by CMS, with large masses leaving potentially spectacular (and conspicuous) signatures. Each heavy sparticle is expected to continue to decay to lighter ones, ending with the lightest SUSY particles (LSPs). LSPs, though mas- sive, are stable and do not decay in the detector. Instead, they appear as missing momentum. In cases of compressed spar- cicle mass spectra, the mass difference between the initially produced sparticles and LSPs is small. This means the low rates of production of massive sparticles are not accompanied by high – momentum
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“超对称粒子质量与CMS可探测性”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么假设的超对称粒子越重，其在CMS实验中越难产生和观测？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #114 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：超对称粒子质量与 CMS 探测器可探测性之间的关系；需谨慎区分排除上限与预测
3. **具体重写目标**：超对称粒子质量与 CMS 探测器可探测性之间的关系；需谨慎区分排除上限与预测。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #115 · `auto_legacy_expansion::CERNCourier2025JanFeb-digitaledition::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CERNCourier2025JanFeb-digitaledition`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in CERNCourier2025JanFeb-digitaledition, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Data on strokes is plentiful but frag- mented, making it difficult to exploit in data-driven treatment strategies. The toolbox of the high-energy physicist is well adapted to the task. To amplify CERN's societal contributions through technological innovation, the Unleash- ing of Cerebral Cortex Neuronate Patient-Centric Stroke Management for a Better, Rapid, Advanced and Personalised Stroke Diagnosis, Treatments and Out- come Prediction (UMBRELLA) project – co-led by Vall d'Hebron Research Institute and Siemens Healthineers – was officially launched on 1 October 2024. The kickoff meeting in Barcelona, Spain, convened more than 20 partners, including Philips, General Electric and Medtrion. Backed by nearly £27 million from the EU's Innovative Health Initiative and industry collaborators, the project aims to transform stroke care across Europe.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CERNCourier2025JanFeb-digitaledition_page_0017_HY_003` · 页 `page_0017` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_1/CERNCourier2025JanFeb-digitaledition/page_0017/evidence_nodes.jsonl`
   - 旧版原子节点：`A_005`
   - bbox：`[[46.0, 169.0, 234.0, 456.0]]`

````text
Data on strokes is plentiful but frag- mented, making it difficult to exploit in data-driven treatment strategies. The toolbox of the high-energy physicist is well adapted to the task. To amplify CERN's societal contributions through technological innovation, the Unleash- ing of Cerebral Cortex Neuronate Patient-Centric Stroke Management for a Better, Rapid, Advanced and Personalised Stroke Diagnosis, Treatments and Out- come Prediction (UMBRELLA) project – co-led by Vall d'Hebron Research Institute and Siemens Healthineers – was officially launched on 1 October 2024. The kickoff meeting in Barcelona, Spain, convened more than 20 partners, including Philips, General Electric and Medtrion. Backed by nearly £27 million from the EU's Innovative Health Initiative and industry collaborators, the project aims to transform stroke care across Europe.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“卒中数据碎片化与CERN分析工具”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】CERN的医疗数据平台要解决卒中研究中哪类数据整合瓶颈？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #115 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：卒中数据为何碎片化以及 CERN 平台在不共享敏感记录下处理数据的方法
3. **具体重写目标**：卒中数据为何碎片化以及 CERN 平台在不共享敏感记录下处理数据的方法。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #116 · `auto_legacy_expansion::CERNCourier2026MayJun-digitaledition::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CERNCourier2026MayJun-digitaledition`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in CERNCourier2026MayJun-digitaledition, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
The collaboration's main target is CPT symmetry. Charge conjugation (C), parity inversion (P) and time reversal (T), taken together, are expected to leave physics invariant. Matter and anti- matter must therefore have identical masses and magnetic moments, equal momentum sizes and the same neutral site sign. BASE tests CPT directly on protons and antiprotons, confined in electromagnetic traps, by measuring their cyclotron and spin-flip frequen- cies. "At low energies, measurements usually use only matter systems, on the assumption that antimatter behaves the same way without testing it," says Christian Smorra, leader of the collab- oration, and the use of 125 U and 90 g BASE-STEP. "Antiprotons are the only stable baryons that can be produced and trapped at low energies, enabling precise frequency measurements."
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CERNCourier2026MayJun-digitaledition_page_0008_HY_003` · 页 `page_0008` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_3/hybrid/shard_1/CERNCourier2026MayJun-digitaledition/page_0008/evidence_nodes.jsonl`
   - 旧版原子节点：`A_006`
   - bbox：`[[47.0, 457.0, 235.0, 745.0]]`

````text
The collaboration's main target is CPT symmetry. Charge conjugation (C), parity inversion (P) and time reversal (T), taken together, are expected to leave physics invariant. Matter and anti- matter must therefore have identical masses and magnetic moments, equal momentum sizes and the same neutral site sign. BASE tests CPT directly on protons and antiprotons, confined in electromagnetic traps, by measuring their cyclotron and spin-flip frequen- cies. "At low energies, measurements usually use only matter systems, on the assumption that antimatter behaves the same way without testing it," says Christian Smorra, leader of the collab- oration, and the use of 125 U and 90 g BASE-STEP. "Antiprotons are the only stable baryons that can be produced and trapped at low energies, enabling precise frequency measurements."
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“CPT对称性对物质与反物质的预言”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】CPT对称性为什么要求物质与反物质具有相同的某些物理属性？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #116 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 CPT 对称性的三个变换分别是什么及其对物质/反物质的含义
3. **具体重写目标**：问 CPT 对称性的三个变换分别是什么及其对物质/反物质的含义。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #117 · `auto_legacy_expansion::CERNCourier2026MayJun-digitaledition::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CERNCourier2026MayJun-digitaledition`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in CERNCourier2026MayJun-digitaledition, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Why, then, are they so elusive? Radio pulses are scattered by clumps of ionised gas along the line of sight, blurring them in time. The effect is severe everywhere, but worse near the dense GC, where it can stretch millisecond pulses to seconds at standard observing frequencies. Higher frequencies are scattered far less, and so pass through more cleanly. The BL GC survey took advantage of this, focusing on high radio frequencies of 8–12GHz, well above the band typically used for pulsar searches. The observations total more than 20 hours between 2021 and 2023, with 11 hours on the innermost 14 arcminutes around Sgr A$^*$ . The result is one of the deepest pulsar searches ever performed in this region.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CERNCourier2026MayJun-digitaledition_page_0006_HY_022` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_0/CERNCourier2026MayJun-digitaledition/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_035`
   - bbox：`[[850.0, 680.0, 1045.0, 924.0]]`

````text
Why, then, are they so elusive? Radio pulses are scattered by clumps of ionised gas along the line of sight, blurring them in time. The effect is severe everywhere, but worse near the dense GC, where it can stretch millisecond pulses to seconds at standard observing frequencies. Higher frequencies are scattered far less, and so pass through more cleanly. The BL GC survey took advantage of this, focusing on high radio frequencies of 8–12GHz, well above the band typically used for pulsar searches. The observations total more than 20 hours between 2021 and 2023, with 11 hours on the innermost 14 arcminutes around Sgr A$^*$ . The result is one of the deepest pulsar searches ever performed in this region.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“银河中心离子化气体对射电脉冲散射”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】银河中心的电离气体为什么使毫秒级射电脉冲更难探测？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #117 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：解释银河中心电离气体散射为何影响射电脉冲观测与源定位
3. **具体重写目标**：解释银河中心电离气体散射为何影响射电脉冲观测与源定位。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #118 · `auto_legacy_expansion::CLADmag_2025_H2::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`EXCLUDE_FROM_FACTUAL_QA`。
- **文档与节点状态**：`CLADmag_2025_H2`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`review_status`, `answer_status (if present)`, `benchmark_membership (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in CLADmag_2025_H2, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
26 CLAD news The world's first residential wellness island, Kulapat Yantrasast's MET wing renovation and the latest on New York's East Side Coastal Resiliency Project 32 Kengo Kuma The Japan National Stadium and V&A Dundee architect shares his secret for finding the elusive 'spirit of a place' 42 Sumayya Vally Aged 30, the founder of Counterspace was named on Time's list of people poised to make history. She tells CLADmag why it has always been her mission to do things differently
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CLADmag_2025_H2_page_0006_HY_005` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_5/hybrid/shard_1/CLADmag_2025_H2/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_011`
   - bbox：`[[437.0, 1046.0, 777.0, 1473.0]]`

````text
26 CLAD news The world's first residential wellness island, Kulapat Yantrasast's MET wing renovation and the latest on New York's East Side Coastal Resiliency Project 32 Kengo Kuma The Japan National Stadium and V&A Dundee architect shares his secret for finding the elusive 'spirit of a place' 42 Sumayya Vally Aged 30, the founder of Counterspace was named on Time's list of people poised to make history. She tells CLADmag why it has always been her mission to do things differently
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“CLAD杂志的内容索引”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。材料属于目录、活动安排、概述或标题型文字，不保证存在单一可验证的机制或结论；应先判断该节点是否适合生成问答。 【建议重写题目】CLAD第26页与第32页分别介绍哪些新闻与建筑师？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #118 行号。**目标操作**：`EXCLUDE_FROM_FACTUAL_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：CLAD 杂志新闻目录，仅含页码/标题；排除解释性 QA 或改为元数据任务
3. **具体重写目标**：CLAD 杂志新闻目录，仅含页码/标题；排除解释性 QA 或改为元数据任务。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：此来源是目录/日程/作者/索引类，不足以作为因果知识型 gold。默认 `EXCLUDE_OR_PARK`；只有明确改造成表格/元数据检索任务且 schema、评价指标允许才考虑保留。

**完成门槛**：
该条退出事实型 Gold QA（留审计记录）；若改为元数据任务需有新的明确任务类型、验证过的表格/目录源及可评分答案。

---

### #119 · `auto_legacy_expansion::CLADmag_2025_H2::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`CLADmag_2025_H2`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in CLADmag_2025_H2, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
This distinctive 42,000-seat stadium, designed by global giants Gensler, is partially submerged into the earth to keep well clear of flight paths immediately above. The result is a striking sunken arena, with a massive structural arch adding to the drama - as well as making this a symbolic gateway to Cairo. On arrival, fans of Egypt's biggest club Al-Ahly will be welcomed into an 'Owners' Plaza', with shops, cafés, a club
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `CLADmag_2025_H2_page_0063_HY_002` · 页 `page_0063` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_6/hybrid/shard_0/CLADmag_2025_H2/page_0063/evidence_nodes.jsonl`
   - 旧版原子节点：`A_004`
   - bbox：`[[94.0, 528.0, 463.0, 682.0]]`

````text
This distinctive 42,000-seat stadium, designed by global giants Gensler, is partially submerged into the earth to keep well clear of flight paths immediately above. The result is a striking sunken arena, with a massive structural arch adding to the drama - as well as making this a symbolic gateway to Cairo. On arrival, fans of Egypt's biggest club Al-Ahly will be welcomed into an 'Owners' Plaza', with shops, cafés, a club
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“球场下沉式设计与航空净空约束”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】Gensler为何将一座42000座体育场部分埋入地下？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #119 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问下沉式体育场为何能满足机场附近航空净空高度的限制
3. **具体重写目标**：问下沉式体育场为何能满足机场附近航空净空高度的限制。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #120 · `auto_legacy_expansion::DLRmagazine_176_EN::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`DLRmagazine_176_EN`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in DLRmagazine_176_EN, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Applications in which valuable goods or even human lives depend on accurate positional information in emergen- cies require exceptionally reliable navigation systems. This is the case, for example, with automatic aircraft landings in poor weather conditions or autonomous driving. To achieve the necessary level of reliability, data from a variety of sensors – such as inertial sensors and cameras – are analysed and integrated with GNSS data. These multi- sensor solutions combine the strengths of different sensor types, mitigate the weaknesses of individual sensors and ensure safety through redundancy. In the data fusion process, researchers account for the error characteristics of each sensor to derive the most reliable positioning information possible. Both conventional sensors and novel sensors developed at DLR, based on quantum technology, are considered in this process.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `DLRmagazine_176_EN_page_0009_HY_006` · 页 `page_0009` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_6/hybrid/shard_0/DLRmagazine_176_EN/page_0009/evidence_nodes.jsonl`
   - 旧版原子节点：`D016`
   - bbox：`[[1273, 413, 1555, 634]]`

````text
Applications in which valuable goods or even human lives depend on accurate positional information in emergen- cies require exceptionally reliable navigation systems. This is the case, for example, with automatic aircraft landings in poor weather conditions or autonomous driving. To achieve the necessary level of reliability, data from a variety of sensors – such as inertial sensors and cameras – are analysed and integrated with GNSS data. These multi- sensor solutions combine the strengths of different sensor types, mitigate the weaknesses of individual sensors and ensure safety through redundancy. In the data fusion process, researchers account for the error characteristics of each sensor to derive the most reliable positioning information possible. Both conventional sensors and novel sensors developed at DLR, based on quantum technology, are considered in this process.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“关键导航场景对高可靠GNSS的要求”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么自动降落等安全关键应用对定位信息可靠性有特别高的要求？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #120 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问高价值/生命关键导航服务为什么需要 GNSS 的完整性/可用性保证
3. **具体重写目标**：问高价值/生命关键导航服务为什么需要 GNSS 的完整性/可用性保证。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #121 · `auto_legacy_expansion::DLRmagazine_176_EN::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`DLRmagazine_176_EN`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in DLRmagazine_176_EN, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
The local mission control centre (LMOC) is positioned at the last safe deployment site, housed within a mobile container nearly seven metres in length. It is connected to the GMOC and commands the aid transporter. The remote control is operated primarily through automation along a pre-planned route, with the vehicle continuously transmitting its position and 360-degree environmental data to the LMOC. To facilitate this, the vehicle is equipped with a radar antenna, perception sensors, depth cameras and a lidar system, akin to those used on lunar or Martian rovers. Technological support is provided by the DLR spin-off Roboception. There is also a landing pad on the vehi- cle’s roof for drones that can gather supplementary information. The team in the command centre monitors all activities live on a screen.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `DLRmagazine_176_EN_page_0012_HY_006` · 页 `page_0012` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_2/hybrid/shard_1/DLRmagazine_176_EN/page_0012/evidence_nodes.jsonl`
   - 旧版原子节点：`D010`
   - bbox：`[[396, 549, 736, 716]]`

````text
The local mission control centre (LMOC) is positioned at the last safe deployment site, housed within a mobile container nearly seven metres in length. It is connected to the GMOC and commands the aid transporter. The remote control is operated primarily through automation along a pre-planned route, with the vehicle continuously transmitting its position and 360-degree environmental data to the LMOC. To facilitate this, the vehicle is equipped with a radar antenna, perception sensors, depth cameras and a lidar system, akin to those used on lunar or Martian rovers. Technological support is provided by the DLR spin-off Roboception. There is also a landing pad on the vehi- cle’s roof for drones that can gather supplementary information. The team in the command centre monitors all activities live on a screen.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“地面远程任务中心与运输车控制”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】本地任务控制中心如何与全球任务中心配合指挥援助运输车？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #121 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：描述本地任务控制中心如何远程监督车辆或运输系统，限定本段实际操作
3. **具体重写目标**：描述本地任务控制中心如何远程监督车辆或运输系统，限定本段实际操作。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #122 · `auto_legacy_expansion::IDU-41f597b3-c201-4fa7-8cac-466610c36a27::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`IDU-41f597b3-c201-4fa7-8cac-466610c36a27`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in IDU-41f597b3-c201-4fa7-8cac-466610c36a27, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Araujo et al. (2016) revived this policy-driven approach when they studied whether a period of catch-up growth in the early 2000s in Latin America and the Caribbean (LAC) was driven by `good policies' or `good luck' from high commodity prices. Other analyses built on Araujo et al. (2016) to explore country- and region-specific growth episodes. For example, results from Haile and Moller (2018) pointed to the importance of financial deepening, macro policy, and infrastructure for previously poorly understood growth accelerations in the West African Economic and Monetary Union (WAEMU). Geiger et al. (2019) revealed that typical growth correlates explain the exceptional growth performance of Ghana up to 2010 but not afterwards. They interpret this as an abatement of structural improvements in the economy and an increasingly cyclical growth performance. $^7$
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `IDU-41f597b3-c201-4fa7-8cac-466610c36a27_page_0006_HY_002` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_3/hybrid/shard_1/IDU-41f597b3-c201-4fa7-8cac-466610c36a27/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_002`
   - bbox：`[[184.0, 370.0, 914.0, 590.0]]`

````text
Araujo et al. (2016) revived this policy-driven approach when they studied whether a period of catch-up growth in the early 2000s in Latin America and the Caribbean (LAC) was driven by `good policies' or `good luck' from high commodity prices. Other analyses built on Araujo et al. (2016) to explore country- and region-specific growth episodes. For example, results from Haile and Moller (2018) pointed to the importance of financial deepening, macro policy, and infrastructure for previously poorly understood growth accelerations in the West African Economic and Monetary Union (WAEMU). Geiger et al. (2019) revealed that typical growth correlates explain the exceptional growth performance of Ghana up to 2010 but not afterwards. They interpret this as an abatement of structural improvements in the economy and an increasingly cyclical growth performance. $^7$
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“拉美经济增长与政策/外部运气归因”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为何拉美2000年代增长加速需要区分政策改善与外部经济条件的贡献？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #122 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问拉美增长研究如何将政策影响与外部运气区别，避免由相关直接推断因果
3. **具体重写目标**：问拉美增长研究如何将政策影响与外部运气区别，避免由相关直接推断因果。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #123 · `auto_legacy_expansion::IDU-41f597b3-c201-4fa7-8cac-466610c36a27::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`IDU-41f597b3-c201-4fa7-8cac-466610c36a27`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in IDU-41f597b3-c201-4fa7-8cac-466610c36a27, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Economists use several methods to investigate country-level growth performances. For example, filtering techniques allow separating cyclical shocks from long-term growth that is in line with an economy's underlying potential (Hodrick and Prescott, 1981) . Growth accounting decomposes growth into contributions from production factors, like capital and labor, and productivity growth (Hulten, 2010) . Other decomposition techniques are widely used to investigate to what extent productivity improvements are due to structural change, e.g., workers moving to more productive sectors (Timmer and de Vries, 2009; McMillan et al., 2014) or firm dynamics (Brown et al., 2018; Diao et al., 2021) . Most of those methods are part of a standard toolkit to analyze country-level growth performance and, for example, part of the World Bank growth diagnostics guidelines (CEM 2.0).
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `IDU-41f597b3-c201-4fa7-8cac-466610c36a27_page_0004_HY_002` · 页 `page_0004` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_6/hybrid/shard_0/IDU-41f597b3-c201-4fa7-8cac-466610c36a27/page_0004/evidence_nodes.jsonl`
   - 旧版原子节点：`A_003`
   - bbox：`[[184.0, 387.0, 916.0, 609.0]]`

````text
Economists use several methods to investigate country-level growth performances. For example, filtering techniques allow separating cyclical shocks from long-term growth that is in line with an economy's underlying potential (Hodrick and Prescott, 1981) . Growth accounting decomposes growth into contributions from production factors, like capital and labor, and productivity growth (Hulten, 2010) . Other decomposition techniques are widely used to investigate to what extent productivity improvements are due to structural change, e.g., workers moving to more productive sectors (Timmer and de Vries, 2009; McMillan et al., 2014) or firm dynamics (Brown et al., 2018; Diao et al., 2021) . Most of those methods are part of a standard toolkit to analyze country-level growth performance and, for example, part of the World Bank growth diagnostics guidelines (CEM 2.0).
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“短期经济波动与长期增长趋势分离”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】增长研究为什么要用滤波法把周期性冲击与长期潜在增长分开？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #123 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问经济增长研究为什么区分短期波动和长期增长趋势
3. **具体重写目标**：问经济增长研究为什么区分短期波动和长期增长趋势。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #124 · `auto_legacy_expansion::Luminous Garden Agnes Northrop and the Women of Tiffany Studios::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`Luminous Garden Agnes Northrop and the Women of Tiffany Studios`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in Luminous Garden Agnes Northrop and the Women of Tiffany Studios, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
at the University of Pennsylvania, but two years after his father's death, James succumbed to pneumonia and died just before his twenty-first birthday. At forty-four years old, Sarah had sole control of the family's holdings. Competing with the likes of Frick in a tough, male-dominated business, she showed herself to be a force. She founded additional companies and tripled the business's profits, managing mines and coke plants in Pennsylvania, Tennessee, Virginia, and West Virginia. By 1912, Sarah Cochran, dubbed the nation's “coal queen,” was one of the wealthiest women in the eastern United States.6
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `Luminous Garden Agnes Northrop and the Women of Tiffany Studios_page_0014_HY_001` · 页 `page_0014` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_3/hybrid/shard_1/Luminous Garden Agnes Northrop and the Women of Tiffany Studios/page_0014/evidence_nodes.jsonl`
   - 旧版原子节点：`A_003`
   - bbox：`[[266.0, 492.0, 827.0, 658.0]]`

````text
at the University of Pennsylvania, but two years after his father's death, James succumbed to pneumonia and died just before his twenty-first birthday. At forty-four years old, Sarah had sole control of the family's holdings. Competing with the likes of Frick in a tough, male-dominated business, she showed herself to be a force. She founded additional companies and tripled the business's profits, managing mines and coke plants in Pennsylvania, Tennessee, Virginia, and West Virginia. By 1912, Sarah Cochran, dubbed the nation's “coal queen,” was one of the wealthiest women in the eastern United States.6
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“Sarah Cochran家庭变故与资产控制”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】哪些家庭事件使Sarah Cochran在44岁时独自掌管家族资产？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #124 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 Sarah Cochran 家庭事件如何改变资产/庄园的管理，检查上下文的人名指代
3. **具体重写目标**：问 Sarah Cochran 家庭事件如何改变资产/庄园的管理，检查上下文的人名指代。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #125 · `auto_legacy_expansion::arxiv_1508_02357::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`arxiv_1508_02357`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in arxiv_1508_02357, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Figure 1 shows the steps that the pipeline uses to find signals and measure their significance. The input to the pipeline is the detector's calibrated strain data [36, 37] . In addition to possible signals, the strain data contains two classes of noise: a primarily stationary, Gaussian noise component from fundamental processes such as thermal noise, quantum noise, and seismic noise coupling into the detector [5] and non-Gaussian noise transients of instrumental and environmental origin [38, 34] . To eliminate the worst periods of detector performance, data quality investigations [39, 40, 41, 33] are used to characterize detector data into three general classes: (i) the data is polluted with enough noise that the data should be discarded without being searched, (ii) the data can be filtered, but candidate events that lie in intervals of poor data quality should be discarded, or vetoed , due to the presence of a instrumental or environmental artifacts, or (iii) the data is suitable for astrophysical searches. Data quality investigations are conducted independently of the search pipeline (by looking only at detector performance), as well as by determining the effect of instrumental artifacts on the noise background of the search pipeline. After removing data that is not suitable for astrophysical searches, the pipeline begins its analysis, following the remaining steps shown in Figure 1 .
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `arxiv_1508_02357_page_0003_HY_002` · 页 `page_0003` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_2/hybrid/shard_0/arxiv_1508_02357/page_0003/evidence_nodes.jsonl`
   - 旧版原子节点：`A_004`
   - bbox：`[[140.0, 566.0, 1048.0, 1110.0]]`

````text
Figure 1 shows the steps that the pipeline uses to find signals and measure their significance. The input to the pipeline is the detector's calibrated strain data [36, 37] . In addition to possible signals, the strain data contains two classes of noise: a primarily stationary, Gaussian noise component from fundamental processes such as thermal noise, quantum noise, and seismic noise coupling into the detector [5] and non-Gaussian noise transients of instrumental and environmental origin [38, 34] . To eliminate the worst periods of detector performance, data quality investigations [39, 40, 41, 33] are used to characterize detector data into three general classes: (i) the data is polluted with enough noise that the data should be discarded without being searched, (ii) the data can be filtered, but candidate events that lie in intervals of poor data quality should be discarded, or vetoed , due to the presence of a instrumental or environmental artifacts, or (iii) the data is suitable for astrophysical searches. Data quality investigations are conducted independently of the search pipeline (by looking only at detector performance), as well as by determining the effect of instrumental artifacts on the noise background of the search pipeline. After removing data that is not suitable for astrophysical searches, the pipeline begins its analysis, following the remaining steps shown in Figure 1 .
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“引力波搜索流程的探测器应变输入”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】引力波搜索流水线用什么原始测量数据作为输入，并如何区分潜在信号与噪声？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #125 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问引力波搜索流程如何从应变数据开始构造候选事件；指出处理顺序
3. **具体重写目标**：问引力波搜索流程如何从应变数据开始构造候选事件；指出处理顺序。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #126 · `auto_legacy_expansion::arxiv_1508_02357::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`arxiv_1508_02357`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in arxiv_1508_02357, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
The search requires that signals are observed with consistent parameters in the detector network. First, any triggers that occur during times of instrumental or environmental artifacts, as determined by the input data quality metadata, are vetoed . To be considered a candidate event, triggers must be observed with a time of arrival difference less than or equal to the gravitational-wave travel time between detectors, with an additional window to account for uncertainty in the measurement of the time of
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `arxiv_1508_02357_page_0006_HY_005` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_1/arxiv_1508_02357/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_010`
   - bbox：`[[140.0, 1347.0, 1048.0, 1537.0]]`

````text
The search requires that signals are observed with consistent parameters in the detector network. First, any triggers that occur during times of instrumental or environmental artifacts, as determined by the input data quality metadata, are vetoed . To be considered a candidate event, triggers must be observed with a time of arrival difference less than or equal to the gravitational-wave travel time between detectors, with an additional window to account for uncertainty in the measurement of the time of
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“引力波触发器的网络一致性与数据质量剔除”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】多台引力波探测器的候选触发器进入符合分析前需满足哪些一致性条件？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #126 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问探测器网络时间一致性和数据质量筛选如何减少虚假引力波触发
3. **具体重写目标**：问探测器网络时间一致性和数据质量筛选如何减少虚假引力波触发。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #127 · `auto_legacy_expansion::arxiv_1510_04615::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`arxiv_1510_04615`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in arxiv_1510_04615, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Initial and advanced LIGO/Virgo rate estimates are ob- tained using gravitational waveform models for a given source with binary component masses $m_1$ and $m_2$ at red- shift $z$ . Our standard waveform model IMRPhenomC from Santamaria et al. (2010) includes inspiral, merger, and ringdown, and is tuned to numerical relativity simulations of non-precessing BH-BH mergers with aligned spins. We have verified explicitly that we obtain essentially identi- cal rate estimates using an effective-one-body waveform model (more specifically, EOBNRv2; Pan et al. 2011). Mild differences between EOBNRv2 and IMRPhenomC only show up in the highest mass bins, where the rates are so low that statistical fluctuations dominate over un- certainties due to the gravitational waveform model. Pan- narale et al. (2013) demonstrated that finite-size effects introduce negligible errors ( $\lesssim 1\%$ ) in SNR calculations for BH-NS binaries, and therefore the IMRPhenomC model is also applicable to BH-NS rate estimates. We also use the IMRPhenomC waveforms for NS-NS binaries, since in this case the signal seen by advanced detectors is dom- inated by the early inspiral, where finite-size effects are negligible. The IMRPhenomC model includes higher har- monics in the waveform amplitude, resulting in a slight reduction of the inspiral amplitude compared to a simple quadrupole-formula estimate, and therefore in a slight de- crease in the predicted detection rates. All of our rate calculations neglect spins, and therefore they should be considered as conservative lower limits (cf. Dominik et al. 2015 for a more detailed discussion of waveform models and of the effect of spins).
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `arxiv_1510_04615_page_0003_HY_010` · 页 `page_0003` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_0/arxiv_1510_04615/page_0003/evidence_nodes.jsonl`
   - 旧版原子节点：`A_012`
   - bbox：`[[644.0, 143.0, 1159.0, 811.0]]`

````text
Initial and advanced LIGO/Virgo rate estimates are ob- tained using gravitational waveform models for a given source with binary component masses $m_1$ and $m_2$ at red- shift $z$ . Our standard waveform model IMRPhenomC from Santamaria et al. (2010) includes inspiral, merger, and ringdown, and is tuned to numerical relativity simulations of non-precessing BH-BH mergers with aligned spins. We have verified explicitly that we obtain essentially identi- cal rate estimates using an effective-one-body waveform model (more specifically, EOBNRv2; Pan et al. 2011). Mild differences between EOBNRv2 and IMRPhenomC only show up in the highest mass bins, where the rates are so low that statistical fluctuations dominate over un- certainties due to the gravitational waveform model. Pan- narale et al. (2013) demonstrated that finite-size effects introduce negligible errors ( $\lesssim 1\%$ ) in SNR calculations for BH-NS binaries, and therefore the IMRPhenomC model is also applicable to BH-NS rate estimates. We also use the IMRPhenomC waveforms for NS-NS binaries, since in this case the signal seen by advanced detectors is dom- inated by the early inspiral, where finite-size effects are negligible. The IMRPhenomC model includes higher har- monics in the waveform amplitude, resulting in a slight reduction of the inspiral amplitude compared to a simple quadrupole-formula estimate, and therefore in a slight de- crease in the predicted detection rates. All of our rate calculations neglect spins, and therefore they should be considered as conservative lower limits (cf. Dominik et al. 2015 for a more detailed discussion of waveform models and of the effect of spins).
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“黑洞并合率估计的波形模型和红移参数”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】研究估计初代与先进LIGO并合率时使用了哪些波形及源参数？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #127 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 LIGO/Virgo 事件率估计使用哪些波形模型和源红移量
3. **具体重写目标**：问 LIGO/Virgo 事件率估计使用哪些波形模型和源红移量。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #128 · `auto_legacy_expansion::arxiv_1510_04615::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`arxiv_1510_04615`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in arxiv_1510_04615, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Methods II and III predict nonzero rates out to a total redshifted mass of 400 M $_\odot$ . This is a much higher total BH-BH binary mass than what is conventionally expected from normal stars, where by “ normal ” stars we mean stars with initial mass below 150 M $_\odot$ . Until recently, this value was believed to be the upper mass limit on star forma- tion, at least in non-zero metallicity environments. Thus far all the predictions for compact object merger rates from Population I and Population II stars have been lim- ited to stars of mass $<150$ M $_\odot$ . The recent discovery of stars estimated to be initially as massive as $\sim$ 200 – 300 M $_\odot$ (e.g., Crowther et al. 2010 ) in the relatively high metal- licity environment of the S Doradus cluster in the LMC ( $Z\approx0.6$ Z $_\odot$ ) has shaken these beliefs. The first study of BH-BH merger rates from these very massive stars has already been proposed (Belczynski et al. 2014 ). However, in the current work our models are limited to stars with initial mass below 150 M $_\odot$ and we nonetheless find merg- ers as massive as 400 M $_\odot$ in our calculations. Two factors are responsible for this surprising result: the inclusion of very low-metallicity models, and our use of the full grav- itational waveform in our analysis. The former allows for the formation of massive BH-BH binaries from Population
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `arxiv_1510_04615_page_0006_HY_009` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_1/hybrid/shard_1/arxiv_1510_04615/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_013`
   - bbox：`[[645.0, 966.0, 1159.0, 1478.0]]`

````text
Methods II and III predict nonzero rates out to a total redshifted mass of 400 M $_\odot$ . This is a much higher total BH-BH binary mass than what is conventionally expected from normal stars, where by “ normal ” stars we mean stars with initial mass below 150 M $_\odot$ . Until recently, this value was believed to be the upper mass limit on star forma- tion, at least in non-zero metallicity environments. Thus far all the predictions for compact object merger rates from Population I and Population II stars have been lim- ited to stars of mass $<150$ M $_\odot$ . The recent discovery of stars estimated to be initially as massive as $\sim$ 200 – 300 M $_\odot$ (e.g., Crowther et al. 2010 ) in the relatively high metal- licity environment of the S Doradus cluster in the LMC ( $Z\approx0.6$ Z $_\odot$ ) has shaken these beliefs. The first study of BH-BH merger rates from these very massive stars has already been proposed (Belczynski et al. 2014 ). However, in the current work our models are limited to stars with initial mass below 150 M $_\odot$ and we nonetheless find merg- ers as massive as 400 M $_\odot$ in our calculations. Two factors are responsible for this surprising result: the inclusion of very low-metallicity models, and our use of the full grav- itational waveform in our analysis. The former allows for the formation of massive BH-BH binaries from Population
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“不同方法推断超大质量双黑洞并合事件率”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么方法II/III预测的并合事件能够延伸到更高的总红移质量？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #128 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问不同估计方法为什么在较高红移质量范围内给出不同并合率预测
3. **具体重写目标**：问不同估计方法为什么在较高红移质量范围内给出不同并合率预测。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #129 · `auto_legacy_expansion::arxiv_1511_05955::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`arxiv_1511_05955`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in arxiv_1511_05955, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
is a sufficient statistic (see Appendix A 1 for a proof). We emphasize that likelihood ratios only compress data losslessly when the likelihoods used in the ratio are the true likelihoods. This scenario commonly breaks down in two ways. First, the hypothesis used in the likelihood might not be exactly $H$ . Examples include the signal hy- pothesis referring to a GW being present in the data but with the wrong waveform morphology and the noise hy- pothesis assuming that the non-Gaussian detector noise is Gaussian. Second, the functional form of the proba- bility distributions $P_{x|H}$ might be incorrect even if the hypothesis models are correct. In either case, as long as the implemented likelihood ratio is a good approxima- tion to the true one, we expect this information loss to be minimal.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `arxiv_1511_05955_page_0003_HY_011` · 页 `page_0003` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_0/arxiv_1511_05955/page_0003/evidence_nodes.jsonl`
   - 旧版原子节点：`A_014, A_015`
   - bbox：`[[105.0, 1183.0, 607.0, 1463.0], [636.0, 273.0, 1137.0, 341.0]]`

````text
is a sufficient statistic (see Appendix A 1 for a proof). We emphasize that likelihood ratios only compress data losslessly when the likelihoods used in the ratio are the true likelihoods. This scenario commonly breaks down in two ways. First, the hypothesis used in the likelihood might not be exactly $H$ . Examples include the signal hy- pothesis referring to a GW being present in the data but with the wrong waveform morphology and the noise hy- pothesis assuming that the non-Gaussian detector noise is Gaussian. Second, the functional form of the proba- bility distributions $P_{x|H}$ might be incorrect even if the hypothesis models are correct. In either case, as long as the implemented likelihood ratio is a good approxima- tion to the true one, we expect this information loss to be minimal.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“似然比为充分统计量的限定条件”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】何时把完整数据压缩为似然比是无损的，真实探测器中为什么可能违背该条件？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #129 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问似然比压缩只有在什么模型假设下是充分的
3. **具体重写目标**：问似然比压缩只有在什么模型假设下是充分的。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #130 · `auto_legacy_expansion::arxiv_1511_05955::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`arxiv_1511_05955`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in arxiv_1511_05955, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
with respect to another detector's data stream before do- ing coincidence. If this timeshift is greater than the time- of-flight between the detectors for a GW, then the GW- induced correlation of the data streams becomes non- astrophysical in our model. Thus, any events found in coincidence among the detectors can be modeled as non- Gaussian (commonly Poisson-distributed) noise glitches that occur simultaneously but independently in the de- tectors. In summary, timeslides provide a method for approximating the noise-only background rate of our de- tectors using real detector data, and as a result, we com- monly refer to our analysis data as the “ 0-lag ” data $^4$ .
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `arxiv_1511_05955_page_0006_HY_009` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_2/hybrid/shard_1/arxiv_1511_05955/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_010`
   - bbox：`[[635.0, 106.0, 1137.0, 386.0]]`

````text
with respect to another detector's data stream before do- ing coincidence. If this timeshift is greater than the time- of-flight between the detectors for a GW, then the GW- induced correlation of the data streams becomes non- astrophysical in our model. Thus, any events found in coincidence among the detectors can be modeled as non- Gaussian (commonly Poisson-distributed) noise glitches that occur simultaneously but independently in the de- tectors. In summary, timeslides provide a method for approximating the noise-only background rate of our de- tectors using real detector data, and as a result, we com- monly refer to our analysis data as the “ 0-lag ” data $^4$ .
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“背景估计中的探测器时间平移方法”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么引力波搜索估计偶然符合背景时要把探测器数据流错开超过光传播时延？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #130 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问引力波背景估计为何对不同探测器数据流做时间平移
3. **具体重写目标**：问引力波背景估计为何对不同探测器数据流做时间平移。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #131 · `auto_legacy_expansion::climate_change_with_ml::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`climate_change_with_ml`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in climate_change_with_ml, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Low-carbon electricity sources are essential to tackling climate change. These sources come in two forms: vari- able and controllable. Variable sources fluctuate based on external factors; for instance, solar panels pro- duce power only when the sun is shining, and wind turbines only when the wind is blowing. On the other hand, controllable sources such as nuclear or geothermal plants can be turned on and off (though not in- stantaneously 6 ). These two types of sources affect electricity systems differently, and so present distinct opportunities for ML techniques.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `climate_change_with_ml_page_0005_HY_005` · 页 `page_0005` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_3/hybrid/shard_1/climate_change_with_ml/page_0005/evidence_nodes.jsonl`
   - 旧版原子节点：`A_009`
   - bbox：`[[104.0, 688.0, 827.0, 811.0]]`

````text
Low-carbon electricity sources are essential to tackling climate change. These sources come in two forms: vari- able and controllable. Variable sources fluctuate based on external factors; for instance, solar panels pro- duce power only when the sun is shining, and wind turbines only when the wind is blowing. On the other hand, controllable sources such as nuclear or geothermal plants can be turned on and off (though not in- stantaneously 6 ). These two types of sources affect electricity systems differently, and so present distinct opportunities for ML techniques.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“可变与可调度低碳电力的供需平衡”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】可变发电源和可控发电源在电力系统调度中承担什么不同角色？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #131 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问可变低碳电力与可调度低碳电力在供需匹配上的区别
3. **具体重写目标**：问可变低碳电力与可调度低碳电力在供需匹配上的区别。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #132 · `auto_legacy_expansion::detr::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`detr`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in detr, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Bounding box loss. The second part of the matching cost and the Hungarian loss is $\mathcal{L}_{\text{box}}(\cdot)$ that scores the bounding boxes. Unlike many detectors that do box predictions as a $\Delta$ w.r.t. some initial guesses, we make box predictions directly. While such approach simplify the implementation it poses an issue with relative scaling of the loss. The most commonly-used $\ell_1$ loss will have different scales for small and large boxes even if their relative errors are similar. To mitigate this issue we use a linear combination of the $\ell_1$ loss and the generalized IoU loss [ 38 ] $\mathcal{L}_{\text{iou}}(\cdot,\cdot)$ that is scale-invariant. Overall, our box loss is $\mathcal{L}_{\text{box}}(b_i,\hat{b}_{\sigma(i)})$ defined as $\lambda_{\text{iou}}\mathcal{L}_{\text{iou}}(b_i,\hat{b}_{\sigma(i)})+\lambda_{\text{L1}}||b_i-\hat{b}_{\sigma(i)}||_1$ where $\lambda_{\text{iou}},\lambda_{\text{L1}} \in \mathbb{R}$ are hyperparameters. These two losses are normalized by the number of objects inside the batch.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `detr_page_0006_HY_002` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_1/hybrid/shard_0/detr/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_003`
   - bbox：`[[83.0, 320.0, 993.0, 641.0]]`

````text
Bounding box loss. The second part of the matching cost and the Hungarian loss is $\mathcal{L}_{\text{box}}(\cdot)$ that scores the bounding boxes. Unlike many detectors that do box predictions as a $\Delta$ w.r.t. some initial guesses, we make box predictions directly. While such approach simplify the implementation it poses an issue with relative scaling of the loss. The most commonly-used $\ell_1$ loss will have different scales for small and large boxes even if their relative errors are similar. To mitigate this issue we use a linear combination of the $\ell_1$ loss and the generalized IoU loss [ 38 ] $\mathcal{L}_{\text{iou}}(\cdot,\cdot)$ that is scale-invariant. Overall, our box loss is $\mathcal{L}_{\text{box}}(b_i,\hat{b}_{\sigma(i)})$ defined as $\lambda_{\text{iou}}\mathcal{L}_{\text{iou}}(b_i,\hat{b}_{\sigma(i)})+\lambda_{\text{L1}}||b_i-\hat{b}_{\sigma(i)}||_1$ where $\lambda_{\text{iou}},\lambda_{\text{L1}} \in \mathbb{R}$ are hyperparameters. These two losses are normalized by the number of objects inside the batch.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“DETR中的边界框匹配与损失构造”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】DETR的边界框损失为什么不采用传统锚框的相对偏移表示？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #132 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 DETR 中边界框损失包含哪些项或如何用于匈牙利匹配；公式需完整符号上下文
3. **具体重写目标**：问 DETR 中边界框损失包含哪些项或如何用于匈牙利匹配；公式需完整符号上下文。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #133 · `auto_legacy_expansion::detr::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`detr`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in detr, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Transformers were introduced by Vaswani et al. [ 47 ] as a new attention-based building block for machine translation. Attention mechanisms [ 2 ] are neural net- work layers that aggregate information from the entire input sequence. Trans- formers introduced self-attention layers, which, similarly to Non-Local Neural Networks [ 49 ] , scan through each element of a sequence and update it by ag- gregating information from the whole sequence. One of the main advantages of attention-based models is their global computations and perfect memory, which makes them more suitable than RNNs on long sequences. Transformers are now
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `detr_page_0003_HY_005` · 页 `page_0003` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_2/hybrid/shard_1/detr/page_0003/evidence_nodes.jsonl`
   - 旧版原子节点：`A_009`
   - bbox：`[[47.0, 731.0, 572.0, 877.0]]`

````text
Transformers were introduced by Vaswani et al. [ 47 ] as a new attention-based building block for machine translation. Attention mechanisms [ 2 ] are neural net- work layers that aggregate information from the entire input sequence. Trans- formers introduced self-attention layers, which, similarly to Non-Local Neural Networks [ 49 ] , scan through each element of a sequence and update it by ag- gregating information from the whole sequence. One of the main advantages of attention-based models is their global computations and perfect memory, which makes them more suitable than RNNs on long sequences. Transformers are now
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“Transformer全局注意力对图像表示的作用”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】Transformer注意力机制如何汇聚输入序列中不同位置的信息？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #133 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问全局自注意力如何帮助 DETR 编码图像中远距离对象关系
3. **具体重写目标**：问全局自注意力如何帮助 DETR 编码图像中远距离对象关系。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #134 · `auto_legacy_expansion::entropy::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`entropy`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in entropy, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
The next increase in complexity would involve trigram frequencies but no more. The choice of a letter would depend on the preceding two letters but not on the message before that point. A set of trigram frequencies $p(i,j,k)$ or equivalently a set of transition probabilities $p_{ij}(k)$ would be required. Continuing in this way one obtains successively more complicated stochastic pro- cesses. In the general $n$ -gram case a set of $n$ -gram probabilities $p(i_1,i_2,\dots,i_n)$ or of transition probabilities $p_{i_1,i_2,\dots,i_{n-1}}(i_n)$ is required to specify the statistical structure.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `entropy_page_0006_HY_008` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_5/hybrid/shard_0/entropy/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_009`
   - bbox：`[[275.0, 680.0, 1053.0, 828.0]]`

````text
The next increase in complexity would involve trigram frequencies but no more. The choice of a letter would depend on the preceding two letters but not on the message before that point. A set of trigram frequencies $p(i,j,k)$ or equivalently a set of transition probabilities $p_{ij}(k)$ would be required. Continuing in this way one obtains successively more complicated stochastic pro- cesses. In the general $n$ -gram case a set of $n$ -gram probabilities $p(i_1,i_2,\dots,i_n)$ or of transition probabilities $p_{i_1,i_2,\dots,i_{n-1}}(i_n)$ is required to specify the statistical structure.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“香农的二阶字母依赖与三元频率”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】在香农人工语言的二阶近似中，当前字母概率如何依赖前两个字母？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #134 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问二阶或三元字母模型如何根据前两个字母选择后一个字母
3. **具体重写目标**：问二阶或三元字母模型如何根据前两个字母选择后一个字母。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #135 · `auto_legacy_expansion::entropy::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`entropy`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in entropy, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
$H$ should be continuous in the $p_i$ . 2. If all the $p_i$ are equal, $p_i = \frac{1}{n}$ , then $H$ should be a monotonic increasing function of $n$ . With equally likely events there is more choice, or uncertainty, when there are more possible events. 3. If a choice be broken down into two successive choices, the original $H$ should be the weighted sum of the individual values of $H$ . The meaning of this is illustrated in Fig. 6 . At the left we have three
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `entropy_page_0010_HY_013` · 页 `page_0010` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_2/hybrid/shard_1/entropy/page_0010/evidence_nodes.jsonl`
   - 旧版原子节点：`A_014`
   - bbox：`[[153.0, 686.0, 781.0, 797.0]]`

````text
$H$ should be continuous in the $p_i$ . 2. If all the $p_i$ are equal, $p_i = \frac{1}{n}$ , then $H$ should be a monotonic increasing function of $n$ . With equally likely events there is more choice, or uncertainty, when there are more possible events. 3. If a choice be broken down into two successive choices, the original $H$ should be the weighted sum of the individual values of $H$ . The meaning of this is illustrated in Fig. 6 . At the left we have three
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“信息熵的连续性与等概率最大不确定性公理”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】香农为不确定度函数H提出了哪些基本公理？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #135 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 Shannon 信息熵公理怎样要求概率的连续性和均匀概率下的不确定性最大值
3. **具体重写目标**：问 Shannon 信息熵公理怎样要求概率的连续性和均匀概率下的不确定性最大值。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #136 · `auto_legacy_expansion::gNtSaU-1511.05999v3::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`gNtSaU-1511.05999v3`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in gNtSaU-1511.05999v3, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
The solution for the wave parameters $h_{\circ}$ , $e$ and $\psi$ , and hence, the waveforms $\boldsymbol{\xi}$ and $\tilde{\boldsymbol{\xi}}$ , can be obtained by maximizing the likelihood functional in Equations 3.3 - 3.4 . For un-constraints case when all the wave param- eters are free, it is straightforward to show that the so- lutions for the network responses are given by the pro- jections of the data vectors $(\mathbf{w}, \tilde{\mathbf{w}})$ on the network plane. As described above the un-modeled burst analysis can be constrained to search for GW signals with various po- larization states. In general case, the constrained likeli- hood problem is hard to solve analytically and the nu- merical solutions are computationally prohibitive. To solve this problem, we apply the phase transformation in Equation 3.5 to the data vectors $\mathbf{w}$ and $\tilde{\mathbf{w}}$ . This transformation reveals the underlying polarization pat- tern $\{\mathbf{w}_{+}, \mathbf{w}_{\times}, \tilde{\mathbf{w}}_{\times}\}$ smeared by the detector noise. The detector responses can be reconstructed directly from this pattern. The solutions for different polarization states can be obtained by imposing the polarization con- straints in Table I . As follows from Equations 3.10 - 3.12 , for linear ( $e=0$ ) and circular ( $e\pm1$ ) waves the com- ponents $\boldsymbol{\tilde{\xi}}_{\times}=0$ and $\boldsymbol{\xi}_{\times}=0$ respectively. Therefore, the reconstructed responses for the loose linear polar- ization constraint are $(\boldsymbol{\xi}_{+}=\mathbf{w}_{+}, \boldsymbol{\xi}_{\times}=\mathbf{w}_{\times}, \boldsymbol{\xi}_{\times}=0)$ and for the loose circular polarization constraint they are $(\boldsymbol{\xi}_{+}=\mathbf{w}_{+}, \boldsymbol{\xi}_{\times}=0, \tilde{\boldsymbol{\xi}}_{\times}=\tilde{\mathbf{w}}_{\times})$ . The solution for linear waves is $(\boldsymbol{\xi}_{+}=\mathbf{p}_{+}, \boldsymbol{\xi}_{\times}=\mathbf{p}_{\times}, \tilde{\boldsymbol{\xi}}_{\times}=0)$ where $\mathbf{p}$ are the projections of $\mathbf{w}_{+}+\mathbf{w}_{\times}$ on their average vector. The analytic solutions for the other polarization constraints are straightforward to find and we do present them here. Such significant simplification of the inverse problem is possible due to the polarization transformations intro- duced in this paper. It enables rapid searches over the entire sky and reconstruction of source coordinates in real time.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gNtSaU-1511.05999v3_page_0006_HY_002` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_1/gNtSaU-1511.05999v3/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_009`
   - bbox：`[[634.0, 398.0, 1138.0, 1217.0]]`

````text
The solution for the wave parameters $h_{\circ}$ , $e$ and $\psi$ , and hence, the waveforms $\boldsymbol{\xi}$ and $\tilde{\boldsymbol{\xi}}$ , can be obtained by maximizing the likelihood functional in Equations 3.3 - 3.4 . For un-constraints case when all the wave param- eters are free, it is straightforward to show that the so- lutions for the network responses are given by the pro- jections of the data vectors $(\mathbf{w}, \tilde{\mathbf{w}})$ on the network plane. As described above the un-modeled burst analysis can be constrained to search for GW signals with various po- larization states. In general case, the constrained likeli- hood problem is hard to solve analytically and the nu- merical solutions are computationally prohibitive. To solve this problem, we apply the phase transformation in Equation 3.5 to the data vectors $\mathbf{w}$ and $\tilde{\mathbf{w}}$ . This transformation reveals the underlying polarization pat- tern $\{\mathbf{w}_{+}, \mathbf{w}_{\times}, \tilde{\mathbf{w}}_{\times}\}$ smeared by the detector noise. The detector responses can be reconstructed directly from this pattern. The solutions for different polarization states can be obtained by imposing the polarization con- straints in Table I . As follows from Equations 3.10 - 3.12 , for linear ( $e=0$ ) and circular ( $e\pm1$ ) waves the com- ponents $\boldsymbol{\tilde{\xi}}_{\times}=0$ and $\boldsymbol{\xi}_{\times}=0$ respectively. Therefore, the reconstructed responses for the loose linear polar- ization constraint are $(\boldsymbol{\xi}_{+}=\mathbf{w}_{+}, \boldsymbol{\xi}_{\times}=\mathbf{w}_{\times}, \boldsymbol{\xi}_{\times}=0)$ and for the loose circular polarization constraint they are $(\boldsymbol{\xi}_{+}=\mathbf{w}_{+}, \boldsymbol{\xi}_{\times}=0, \tilde{\boldsymbol{\xi}}_{\times}=\tilde{\mathbf{w}}_{\times})$ . The solution for linear waves is $(\boldsymbol{\xi}_{+}=\mathbf{p}_{+}, \boldsymbol{\xi}_{\times}=\mathbf{p}_{\times}, \tilde{\boldsymbol{\xi}}_{\times}=0)$ where $\mathbf{p}$ are the projections of $\mathbf{w}_{+}+\mathbf{w}_{\times}$ on their average vector. The analytic solutions for the other polarization constraints are straightforward to find and we do present them here. Such significant simplification of the inverse problem is possible due to the polarization transformations intro- duced in this paper. It enables rapid searches over the entire sky and reconstruction of source coordinates in real time.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“引力波极化波形的似然最大化求解”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】如何通过最大化似然函数估计引力波幅度与偏振参数？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #136 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问似然最大化如何估计引力波振幅和偏振参数；需给定变量符号定义
3. **具体重写目标**：问似然最大化如何估计引力波振幅和偏振参数；需给定变量符号定义。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #137 · `auto_legacy_expansion::gNtSaU-1511.05999v3::2`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`RECOVER_FORMULA_CONTEXT_OR_EXCLUDE`。
- **文档与节点状态**：`gNtSaU-1511.05999v3`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in gNtSaU-1511.05999v3, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
$$\begin{array} { r } { \left[ \begin{array} { l } { \left( w [ i ] \cdot e _ { + } [ i ] \right) } \\ { \left( w [ i ] \cdot e _ { \times } [ i ] \right) } \end{array} \right] = \left[ \begin{array} { c c } { \left| f _ { + } [ i ] \right. } & { 0 } \\ { 0 } & { \left| f _ { \times } [ i ] \right| } \end{array} \right] \left[ \begin{array} { l } { h _ { + } [ i ] } \\ { h _ { \times } [ i ] } \end{array} \right] . \eqno ( 2 . 8 ) } \end{array}$$ where $\mathbf{e}_{+}$ and $\mathbf{e}_{\times}$ are the unit vectors along $\mathbf{f}_{+}$ and $\mathbf{f}_{\times}$ respectively. Note, the $2 \times 2$ matrix in Eq. 2.8 character- izes the network sensitivity to the two GW polarizations. The maximum likelihood ratio statistic is calculated by substituting the solutions into $\mathcal{L}[\mathbf{h}]$ . The result can be written as
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gNtSaU-1511.05999v3_page_0003_HY_007` · 页 `page_0003` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_6/hybrid/shard_0/gNtSaU-1511.05999v3/page_0003/evidence_nodes.jsonl`
   - 旧版原子节点：`A_013, A_014`
   - bbox：`[[135.0, 991.0, 605.0, 1045.0], [105.0, 1056.0, 606.0, 1195.0]]`

````text
$$\begin{array} { r } { \left[ \begin{array} { l } { \left( w [ i ] \cdot e _ { + } [ i ] \right) } \\ { \left( w [ i ] \cdot e _ { \times } [ i ] \right) } \end{array} \right] = \left[ \begin{array} { c c } { \left| f _ { + } [ i ] \right. } & { 0 } \\ { 0 } & { \left| f _ { \times } [ i ] \right| } \end{array} \right] \left[ \begin{array} { l } { h _ { + } [ i ] } \\ { h _ { \times } [ i ] } \end{array} \right] . \eqno ( 2 . 8 ) } \end{array}$$ where $\mathbf{e}_{+}$ and $\mathbf{e}_{\times}$ are the unit vectors along $\mathbf{f}_{+}$ and $\mathbf{f}_{\times}$ respectively. Note, the $2 \times 2$ matrix in Eq. 2.8 character- izes the network sensitivity to the two GW polarizations. The maximum likelihood ratio statistic is calculated by substituting the solutions into $\mathcal{L}[\mathbf{h}]$ . The result can be written as
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“引力波极化公式矩阵表达”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。选中证据主要是数学公式，符号定义和上下文不足，不能直接把原始LaTeX表达式当成完整答案。 【建议重写题目】所给公式如何表示两种极化分量与天线响应的关系？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #137 行号。**目标操作**：`RECOVER_FORMULA_CONTEXT_OR_EXCLUDE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：公式孤岛，缺符号定义与前后推导；补公式上文或排除该 evidence，禁止原始 LaTeX 当答案
3. **具体重写目标**：公式孤岛，缺符号定义与前后推导；补公式上文或排除该 evidence，禁止原始 LaTeX 当答案。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：公式符号和前后推导缺失时不能把 LaTeX 直接作为答案，必须补上下文或排除。

**完成门槛**：
补齐变量定义及必要前后关系或将该条排除；严禁将无解释公式视为标准答案。

---

### #138 · `auto_legacy_expansion::gw150914_detection::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_WITH_VISUAL_EVIDENCE_OR_EXCLUDE`。
- **文档与节点状态**：`gw150914_detection`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in gw150914_detection, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
FIG. 4. Search results from the generic transient search (left) and the binary coalescence search (right). These histograms show the number of candidate events (orange markers) and the mean number of background events (black lines) in the search class where GW150914 was found as a function of the search detection statistic and with a bin width of 0.2. The scales on the top give the significance of an event in Gaussian standard deviations based on the corresponding noise background. The significance of GW150914 is greater than $5.1\sigma$ and $4.6\sigma$ for the binary coalescence and the generic transient searches, respectively. Left: Along with the primary search (C3) we also show the results (blue markers) and background (green curve) for an alternative search that treats events independently of their frequency evolution (C2 + C3). The classes C2 and C3 are defined in the text. Right: The tail in the black-line background of the binary coalescence search is due to random coincidences of GW150914 in one detector with noise in the other detector. (This type of event is practically absent in the generic transient search background because they do not pass the time-frequency consistency requirements used in that search.) The purple curve is the background excluding those coincidences, which is used to assess the significance of the second strongest event.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gw150914_detection_page_0006_HY_007` · 页 `page_0006` · 类型 `COMPOSITE`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_1/gw150914_detection/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_012`
   - bbox：`[[101.0, 1206.0, 1135.0, 1453.0], [119.0, 794.0, 1113.0, 1190.0]]`

````text
FIG. 4. Search results from the generic transient search (left) and the binary coalescence search (right). These histograms show the number of candidate events (orange markers) and the mean number of background events (black lines) in the search class where GW150914 was found as a function of the search detection statistic and with a bin width of 0.2. The scales on the top give the significance of an event in Gaussian standard deviations based on the corresponding noise background. The significance of GW150914 is greater than $5.1\sigma$ and $4.6\sigma$ for the binary coalescence and the generic transient searches, respectively. Left: Along with the primary search (C3) we also show the results (blue markers) and background (green curve) for an alternative search that treats events independently of their frequency evolution (C2 + C3). The classes C2 and C3 are defined in the text. Right: The tail in the black-line background of the binary coalescence search is due to random coincidences of GW150914 in one detector with noise in the other detector. (This type of event is practically absent in the generic transient search background because they do not pass the time-frequency consistency requirements used in that search.) The purple curve is the background excluding those coincidences, which is used to assess the significance of the second strongest event.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“GW150914瞬变与双星并合搜索的背景对比”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】GW150914在两种独立搜索中对应的候选统计量和背景分布如何比较？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #138 行号。**目标操作**：`REGENERATE_WITH_VISUAL_EVIDENCE_OR_EXCLUDE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：复合图注：问瞬变/双星并合两种搜索如何展示背景显著性；必须检视图像和图注
3. **具体重写目标**：复合图注：问瞬变/双星并合两种搜索如何展示背景显著性；必须检视图像和图注。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：必须核实图像/图注联合证据，评测若只允许纯文本 node 则排除依赖图形读数的题。

**完成门槛**：
实际图像与图注一致，并且当前检索单元能访问图像；图像若不可用不得作为正式 Gold Evidence。

---

### #139 · `auto_legacy_expansion::gw150914_detection::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`gw150914_detection`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in gw150914_detection, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
On September 14, 2015, at 09:50:45 UTC, the LIGO Hanford, WA, and Livingston, LA, observatories detected the coincident signal GW150914 shown in Fig. 1 . The initial detection was made by low-latency searches for generic gravitational-wave transients [ 41 ] and was reported within three minutes of data acquisition [ 43 ] . Subsequently, matched-filter analyses that use relativistic models of com- pact binary waveforms [ 44 ] recovered GW150914 as the most significant event from each detector for the observa- tions reported here. Occurring within the 10-ms interve-
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gw150914_detection_page_0002_HY_002` · 页 `page_0002` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_1/hybrid/shard_0/gw150914_detection/page_0002/evidence_nodes.jsonl`
   - 旧版原子节点：`A_006, A_007`
   - bbox：`[[74.0, 181.0, 448.0, 220.0], [469.0, 74.0, 842.0, 220.0]]`

````text
On September 14, 2015, at 09:50:45 UTC, the LIGO Hanford, WA, and Livingston, LA, observatories detected the coincident signal GW150914 shown in Fig. 1 . The initial detection was made by low-latency searches for generic gravitational-wave transients [ 41 ] and was reported within three minutes of data acquisition [ 43 ] . Subsequently, matched-filter analyses that use relativistic models of com- pact binary waveforms [ 44 ] recovered GW150914 as the most significant event from each detector for the observa- tions reported here. Occurring within the 10-ms interve-
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“GW150914首次双探测器检出时间”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】GW150914在何时由哪两个LIGO台站共同检测到？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #139 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 GW150914 首次被两座 LIGO 台站探测的 UTC 时间和事件名称
3. **具体重写目标**：问 GW150914 首次被两座 LIGO 台站探测的 UTC 时间和事件名称。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #140 · `auto_legacy_expansion::gw150914_gr_test::1`

- **综合判定**：`REJECT`；**优先级**：`P0_BLOCK_AND_SOURCE_REVIEW`；**修复动作**：`EXCLUDE_FROM_FACTUAL_QA`。
- **文档与节点状态**：`gw150914_gr_test`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`review_status`, `answer_status (if present)`, `benchmark_membership (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in gw150914_gr_test, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
R. Stone, 86 K. A. Strain, 36 N. Straniero, 66 G. Stratta, 57,58 N. A. Strauss, 79 S. Strigin, 48 R. Sturani, 121 A. L. Stuver, 6 T. Z. Summerscales, 129 L. Sun, 85 P. J. Sutton, 92 B. L. Swinkels, 34 M. J. Szczepa ´ nczyk, 98 M. Tacca, 30 D. Talukder, 59 D. B. Tanner, 5 M. T ´ apai, 97 S. P. Tarabrin, 8 A. Taracchini, 29 R. Taylor, 1 T. Theeg, 8 M. P. Thirugnanasambandam, 1 E. G. Thomas, 44 M. Thomas, 6 P. Thomas, 37 K. A. Thorne, 6 K. S. Thorne, 77 E. Thrane, 114 S. Tiwari, 12 V. Tiwari, 92 K. V. Tokmakov, 107 C. Tomlinson, 87 M. Tonelli, 18,19 C. V. Torres 4, 86 C. I. Torrie, 1 D. T ¨ oyr ¨ a, 44 F. Travasso, 32,33 G. Traylor, 6 D. Trifir ` o, 21 M. C. Tringali, 90,91 L. Trozzo, 131,19 M. Tse, 10 M. Turconi, 52 D. Tuyenbayev, 86 D. Ugolini, 132 C. S. Unnikrishnan, 100 A. L. Urban, 16 S. A. Usman, 35 H. Vahlbruch, 17 G. Vajente, 1 G. Valdes, 86 M. Vallisneri, 77 N. van Bakel, 9 M. van Beuzekom, 9 J. F. J. van den Brand, 62,9 C. Van Den Broeck, 9 D. C. Vander-Hyde, 35,22 L. van der Schaaf, 9 J. V. van Heijningen, 9 A. A. van Veggel, 36 M. Vardaro, 41,42 S. Vass, 1 M. Vasuth, 38 R. Vaulin, 10 A. Vecchio, 44 G. Vedovato, 42 J. Veitch, 44 P. J. Veitch, 104 K. Venkateswara, 133 D. Verkindt, 7 F. Vetrano, 57,58 A. Vicer ´ e, 57,58 S. Vinciguerra, 44 D. J. Vine, 49 J.-Y. Vinet, 52 S. Vitale, 10 T. Vo, 35 H. Vocca, 32,33 C. Vorvick, 37 D. Voss, 5 W. D. Vousden, 44 S. P. Vyatchanin, 48 A. R. Wade, 20 L. E. Wade, 134 M. Wade, 134 M. Walker, 2 L. Wallace, 1 S. Walsh, 16,8,29 G. Wang, 12 H. Wang, 44 M. Wang, 44 X. Wang, 71 Y. Wang, 50 R. L. Ward, 20 J. Warner, 37 M. Was, 7 B. Weaver, 37 L.-W. Wei, 52 M. Weinert, 8 A. J. Weinstein, 1 R. Weiss, 10 T. Welborn, 6 L. Wen, 50 P. Weßels, 8 T. Westphal, 8 K. Wette, 8 J. T. Whelan, 102,8 D. J. White, 87 B. F. Whiting, 5 D. Williams, 36 R. D. Williams, 1 A. R. Williamson, 92 J. L. Willis, 135 B. Willke, 17,8 M. H. Wimmer, 8,17 W. Winkler, 8 C. C. Wipf, 1 H. Wittel, 8,17 G. Woan, 36 J. Worden, 37 J. L. Wright, 36 G. Wu, 6 J. Yablon, 83 W. Yam, 10 H. Yamamoto, 1 C. C. Yancey, 63 M. J. Yap, 20 H. Yu, 10 M. Yvert, 7 A. Zadrozny, 112 L. Zangrando, 42 M. Zanolin, 98 J.-P. Zendri, 42 M. Zevin, 83 F. Zhang, 10 L. Zhang, 1 M. Zhang, 120 Y. Zhang, 102 C. Zhao, 50 M. Zhou, 83 Z. Zhou, 83 X. J. Zhu, 50 M. E. Zucker, 1,10 S. E. Zuraw, 103 and J. Zweizig 1
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gw150914_gr_test_page_0003_HY_001` · 页 `page_0003` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_1/hybrid/shard_0/gw150914_gr_test/page_0003/evidence_nodes.jsonl`
   - 旧版原子节点：`A_002`
   - bbox：`[[104.0, 103.0, 1137.0, 579.0]]`

````text
R. Stone, 86 K. A. Strain, 36 N. Straniero, 66 G. Stratta, 57,58 N. A. Strauss, 79 S. Strigin, 48 R. Sturani, 121 A. L. Stuver, 6 T. Z. Summerscales, 129 L. Sun, 85 P. J. Sutton, 92 B. L. Swinkels, 34 M. J. Szczepa ´ nczyk, 98 M. Tacca, 30 D. Talukder, 59 D. B. Tanner, 5 M. T ´ apai, 97 S. P. Tarabrin, 8 A. Taracchini, 29 R. Taylor, 1 T. Theeg, 8 M. P. Thirugnanasambandam, 1 E. G. Thomas, 44 M. Thomas, 6 P. Thomas, 37 K. A. Thorne, 6 K. S. Thorne, 77 E. Thrane, 114 S. Tiwari, 12 V. Tiwari, 92 K. V. Tokmakov, 107 C. Tomlinson, 87 M. Tonelli, 18,19 C. V. Torres 4, 86 C. I. Torrie, 1 D. T ¨ oyr ¨ a, 44 F. Travasso, 32,33 G. Traylor, 6 D. Trifir ` o, 21 M. C. Tringali, 90,91 L. Trozzo, 131,19 M. Tse, 10 M. Turconi, 52 D. Tuyenbayev, 86 D. Ugolini, 132 C. S. Unnikrishnan, 100 A. L. Urban, 16 S. A. Usman, 35 H. Vahlbruch, 17 G. Vajente, 1 G. Valdes, 86 M. Vallisneri, 77 N. van Bakel, 9 M. van Beuzekom, 9 J. F. J. van den Brand, 62,9 C. Van Den Broeck, 9 D. C. Vander-Hyde, 35,22 L. van der Schaaf, 9 J. V. van Heijningen, 9 A. A. van Veggel, 36 M. Vardaro, 41,42 S. Vass, 1 M. Vasuth, 38 R. Vaulin, 10 A. Vecchio, 44 G. Vedovato, 42 J. Veitch, 44 P. J. Veitch, 104 K. Venkateswara, 133 D. Verkindt, 7 F. Vetrano, 57,58 A. Vicer ´ e, 57,58 S. Vinciguerra, 44 D. J. Vine, 49 J.-Y. Vinet, 52 S. Vitale, 10 T. Vo, 35 H. Vocca, 32,33 C. Vorvick, 37 D. Voss, 5 W. D. Vousden, 44 S. P. Vyatchanin, 48 A. R. Wade, 20 L. E. Wade, 134 M. Wade, 134 M. Walker, 2 L. Wallace, 1 S. Walsh, 16,8,29 G. Wang, 12 H. Wang, 44 M. Wang, 44 X. Wang, 71 Y. Wang, 50 R. L. Ward, 20 J. Warner, 37 M. Was, 7 B. Weaver, 37 L.-W. Wei, 52 M. Weinert, 8 A. J. Weinstein, 1 R. Weiss, 10 T. Welborn, 6 L. Wen, 50 P. Weßels, 8 T. Westphal, 8 K. Wette, 8 J. T. Whelan, 102,8 D. J. White, 87 B. F. Whiting, 5 D. Williams, 36 R. D. Williams, 1 A. R. Williamson, 92 J. L. Willis, 135 B. Willke, 17,8 M. H. Wimmer, 8,17 W. Winkler, 8 C. C. Wipf, 1 H. Wittel, 8,17 G. Woan, 36 J. Worden, 37 J. L. Wright, 36 G. Wu, 6 J. Yablon, 83 W. Yam, 10 H. Yamamoto, 1 C. C. Yancey, 63 M. J. Yap, 20 H. Yu, 10 M. Yvert, 7 A. Zadrozny, 112 L. Zangrando, 42 M. Zanolin, 98 J.-P. Zendri, 42 M. Zevin, 83 F. Zhang, 10 L. Zhang, 1 M. Zhang, 120 Y. Zhang, 102 C. Zhao, 50 M. Zhou, 83 Z. Zhou, 83 X. J. Zhu, 50 M. E. Zucker, 1,10 S. E. Zuraw, 103 and J. Zweizig 1
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“GW150914作者和机构名单”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。本段是作者署名与机构编号列表，不承载题目声称的因果或技术关系，属于严重的证据类型错配。 【建议重写题目】这份论文的作者名单中是否列出了某位指定研究人员？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #140 行号。**目标操作**：`EXCLUDE_FROM_FACTUAL_QA`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：纯作者/机构名单，不是可回答因果问题的证据；排除
3. **具体重写目标**：纯作者/机构名单，不是可回答因果问题的证据；排除。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：此来源是目录/日程/作者/索引类，不足以作为因果知识型 gold。默认 `EXCLUDE_OR_PARK`；只有明确改造成表格/元数据检索任务且 schema、评价指标允许才考虑保留。

**完成门槛**：
该条退出事实型 Gold QA（留审计记录）；若改为元数据任务需有新的明确任务类型、验证过的表格/目录源及可评分答案。

---

### #141 · `auto_legacy_expansion::gw150914_gr_test::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`gw150914_gr_test`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in gw150914_gr_test, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
In Newtonian gravity, binary systems move along circular or elliptical orbits with constant orbital period [4, 5] . In GR, binary systems emit GWs [6, 7] ; as a consequence, the bi- nary’s orbital period decreases over time as energy and angu- lar momentum are radiated away. Electromagnetic observa- tions of binary pulsars over the four decades since their dis- covery [8, 9] have made it possible to measure GW-induced orbital-period variations $\dot{P}_{\rm orb}\sim-10^{-14}-10^{-12}$ , confirming the GW luminosity predicted at leading order in post-Newtonian (PN) theory [10] (i.e., Einstein's quadrupole formula) with exquisite precision [11, 12] . Nevertheless, even in the most relativistic binary pulsar known today, J0737-3039 [11] , the orbital period changes at an effectively constant rate. The or- bital velocity $v$ relative to the speed of light $c$ is $v/c\sim2\times10^{-3}$ , and the two neutron stars in the system will coalesce in $\sim85\,{\rm Myr}$ .
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gw150914_gr_test_page_0006_HY_002` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_1/gw150914_gr_test/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_003`
   - bbox：`[[104.0, 374.0, 608.0, 760.0]]`

````text
In Newtonian gravity, binary systems move along circular or elliptical orbits with constant orbital period [4, 5] . In GR, binary systems emit GWs [6, 7] ; as a consequence, the bi- nary’s orbital period decreases over time as energy and angu- lar momentum are radiated away. Electromagnetic observa- tions of binary pulsars over the four decades since their dis- covery [8, 9] have made it possible to measure GW-induced orbital-period variations $\dot{P}_{\rm orb}\sim-10^{-14}-10^{-12}$ , confirming the GW luminosity predicted at leading order in post-Newtonian (PN) theory [10] (i.e., Einstein's quadrupole formula) with exquisite precision [11, 12] . Nevertheless, even in the most relativistic binary pulsar known today, J0737-3039 [11] , the orbital period changes at an effectively constant rate. The or- bital velocity $v$ relative to the speed of light $c$ is $v/c\sim2\times10^{-3}$ , and the two neutron stars in the system will coalesce in $\sim85\,{\rm Myr}$ .
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“广义相对论中引力波辐射使轨道周期缩短”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么广义相对论预言双星系统轨道周期会逐渐减小？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #141 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问广义相对论中引力波辐射为什么导致双星轨道周期缩短
3. **具体重写目标**：问广义相对论中引力波辐射为什么导致双星轨道周期缩短。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #142 · `auto_legacy_expansion::gw150914_properties::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`gw150914_properties`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in gw150914_properties, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
As the BHs get closer to each other and their velocities increase, the accuracy of the PN expansion degrades, and eventually the full solution of Einstein's equations is needed to accurately describe the binary evolution. This is accomplished using numerical relativity (NR) which, after the initial breakthrough [32–34] , has been improved continuously to achieve the sophistication of modeling needed for our purposes. The details of the ringdown are primarily governed by the mass and spin of the final BH. In particular, the final mass and spin determine the (constant) frequency and decay time of the BH's ringdown to its final state [35] . The late stage of the coalescence allows us to measure the total mass which, combined with the measurement of the chirp mass and mass ratio from the early inspiral, yields estimates of the individual component masses for the binary.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gw150914_properties_page_0003_HY_005` · 页 `page_0003` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_6/hybrid/shard_0/gw150914_properties/page_0003/evidence_nodes.jsonl`
   - 旧版原子节点：`A_009`
   - bbox：`[[102.0, 864.0, 604.0, 1256.0]]`

````text
As the BHs get closer to each other and their velocities increase, the accuracy of the PN expansion degrades, and eventually the full solution of Einstein's equations is needed to accurately describe the binary evolution. This is accomplished using numerical relativity (NR) which, after the initial breakthrough [32–34] , has been improved continuously to achieve the sophistication of modeling needed for our purposes. The details of the ringdown are primarily governed by the mass and spin of the final BH. In particular, the final mass and spin determine the (constant) frequency and decay time of the BH's ringdown to its final state [35] . The late stage of the coalescence allows us to measure the total mass which, combined with the measurement of the chirp mass and mass ratio from the early inspiral, yields estimates of the individual component masses for the binary.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“PN近似在双黑洞接近并合时失效”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】黑洞接近并合时为什么需要数值求解爱因斯坦方程而不能继续仅依赖后牛顿近似？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #142 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问黑洞接近并合时为什么后牛顿近似精度下降
3. **具体重写目标**：问黑洞接近并合时为什么后牛顿近似精度下降。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #143 · `auto_legacy_expansion::gw150914_properties::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`gw150914_properties`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in gw150914_properties, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Before discussing parameter estimates in detail, we consider how the inference is affected by the choice of the compact-binary waveform model. From Table I , we see that the posterior estimates for each parameter are broadly consistent across the two models, despite the fact that they are based on different analytical approaches and that they include different aspects of BBH spin dynamics. The models' logarithms of the Bayes factors, $288.7\pm0.2$ and $290.3\pm0.1$ , are also comparable for both models: the data do not allow us to conclusively prefer one model over the other [ 89 ] . Therefore, we use both for the Overall column in Table I . We combine the posterior samples of both distributions with equal weight, in effect marginalizing over our choice of waveform model. These averaged results give our best estimate for the parameters describing GW150914.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `gw150914_properties_page_0006_HY_004` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_4/hybrid/shard_1/gw150914_properties/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_008`
   - bbox：`[[101.0, 891.0, 604.0, 1280.0]]`

````text
Before discussing parameter estimates in detail, we consider how the inference is affected by the choice of the compact-binary waveform model. From Table I , we see that the posterior estimates for each parameter are broadly consistent across the two models, despite the fact that they are based on different analytical approaches and that they include different aspects of BBH spin dynamics. The models' logarithms of the Bayes factors, $288.7\pm0.2$ and $290.3\pm0.1$ , are also comparable for both models: the data do not allow us to conclusively prefer one model over the other [ 89 ] . Therefore, we use both for the Overall column in Table I . We combine the posterior samples of both distributions with equal weight, in effect marginalizing over our choice of waveform model. These averaged results give our best estimate for the parameters describing GW150914.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“波形模型选择对黑洞参数后验的影响”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】更换紧致双星波形模型会如何改变黑洞参数的后验估计？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #143 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问不同引力波波形模型如何影响 GW150914 的参数后验分布
3. **具体重写目标**：问不同引力波波形模型如何影响 GW150914 的参数后验分布。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #144 · `auto_legacy_expansion::hallmarks_of_aging::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`hallmarks_of_aging`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in hallmarks_of_aging, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Global studies on the transcriptional landscape of aged tissues have also emphasized the relevance of inflammatory pathways in aging (de Magalhaes et al., 2009; Lee et al., 2012) . Over-activation of the NF- $\kappa$ B pathway is one of these transcriptional signatures of aging and conditional expression of an NF- $\kappa$ B inhibitor in the aged skin of transgenic mice causes the phenotypic rejuvenation of this tissue, as well as the restoration of the transcriptional signature corresponding to young age (Adler et al., 2007) . Likewise, genetic and pharmacological inhibition of NF- $\kappa$ B signaling prevents age-associated features in different mouse models of accelerated aging (Osorio et al., 2012; Tilstra et al., 2012) . A novel link between inflammation and aging derives from the recent finding that inflammatory and stress responses activate NF- $\kappa$ B in the hypothalamus and induce a signaling pathway that results in reduced production of gonadotropin-releasing hormone (GnRH) by neurons (Zhang et al., 2013) . This GnRH decline can contribute to numerous aging-related changes such as bone fragility, muscle weakness, skin atrophy and reduced neurogenesis. Consistently, GnRH treatment prevents aging-impaired neurogenesis and decelerates aging development in mice (Zhang et al., 2013) . These findings suggest that the hypothalamus may modulate systemic aging by integrating NF- $\kappa$ B-driven inflammatory responses with GnRH-mediated neuroendocrine effects.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `hallmarks_of_aging_page_0018_HY_003` · 页 `page_0018` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_1/hallmarks_of_aging/page_0018/evidence_nodes.jsonl`
   - 旧版原子节点：`A_007`
   - bbox：`[[221.0, 737.0, 784.0, 1044.0]]`

````text
Global studies on the transcriptional landscape of aged tissues have also emphasized the relevance of inflammatory pathways in aging (de Magalhaes et al., 2009; Lee et al., 2012) . Over-activation of the NF- $\kappa$ B pathway is one of these transcriptional signatures of aging and conditional expression of an NF- $\kappa$ B inhibitor in the aged skin of transgenic mice causes the phenotypic rejuvenation of this tissue, as well as the restoration of the transcriptional signature corresponding to young age (Adler et al., 2007) . Likewise, genetic and pharmacological inhibition of NF- $\kappa$ B signaling prevents age-associated features in different mouse models of accelerated aging (Osorio et al., 2012; Tilstra et al., 2012) . A novel link between inflammation and aging derives from the recent finding that inflammatory and stress responses activate NF- $\kappa$ B in the hypothalamus and induce a signaling pathway that results in reduced production of gonadotropin-releasing hormone (GnRH) by neurons (Zhang et al., 2013) . This GnRH decline can contribute to numerous aging-related changes such as bone fragility, muscle weakness, skin atrophy and reduced neurogenesis. Consistently, GnRH treatment prevents aging-impaired neurogenesis and decelerates aging development in mice (Zhang et al., 2013) . These findings suggest that the hypothalamus may modulate systemic aging by integrating NF- $\kappa$ B-driven inflammatory responses with GnRH-mediated neuroendocrine effects.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NF-κB炎症信号和衰老机制”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】老龄组织的转录组研究为何突出NF-κB相关炎症通路？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #144 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 NF-κB 相关炎症信号如何与组织老化相关，勿擅自宣称治疗效果
3. **具体重写目标**：问 NF-κB 相关炎症信号如何与组织老化相关，勿擅自宣称治疗效果。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #145 · `auto_legacy_expansion::hallmarks_of_aging::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`hallmarks_of_aging`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in hallmarks_of_aging, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
The sirtuin family of NAD-dependent protein deacetylases and ADP-ribosyltransferases has been studied extensively as potential anti-aging factors. Interest in this family of proteins in relation to aging stems from a series of studies in yeast, flies and worms reporting that the single sirtuin gene of these organisms, named Sir2 , had a remarkable longevity activity (Guarente, 2011) . Overexpression of Sir2 was first shown to extend replicative lifespan in Saccharomyces cerevisiae (Kaeberlein et al., 1999) , and subsequent reports indicated that enhanced expression of the worm ( sir-2.1 ) and fly ( dSir2 ) orthologs could extend lifespan in both invertebrate model systems (Rogina and Helfand, 2004; Tissenbaum and Guarente, 2001) . These findings have recently been called into question, however, with the report that the lifespan extension originally observed in the worm and fly studies was mostly due to confounding genetic background differences and not to the overexpression of sir-2.1 or dSir2 , respectively (Burnett et al., 2011) . In fact, careful reassessments indicate that overexpression of sir-2.1 only results in modest lifespan extension in C. elegans (Viswanathan and Guarente, 2011) .
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `hallmarks_of_aging_page_0006_HY_005` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_2/hybrid/shard_0/hallmarks_of_aging/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_010`
   - bbox：`[[299.0, 997.0, 1054.0, 1339.0]]`

````text
The sirtuin family of NAD-dependent protein deacetylases and ADP-ribosyltransferases has been studied extensively as potential anti-aging factors. Interest in this family of proteins in relation to aging stems from a series of studies in yeast, flies and worms reporting that the single sirtuin gene of these organisms, named Sir2 , had a remarkable longevity activity (Guarente, 2011) . Overexpression of Sir2 was first shown to extend replicative lifespan in Saccharomyces cerevisiae (Kaeberlein et al., 1999) , and subsequent reports indicated that enhanced expression of the worm ( sir-2.1 ) and fly ( dSir2 ) orthologs could extend lifespan in both invertebrate model systems (Rogina and Helfand, 2004; Tissenbaum and Guarente, 2001) . These findings have recently been called into question, however, with the report that the lifespan extension originally observed in the worm and fly studies was mostly due to confounding genetic background differences and not to the overexpression of sir-2.1 or dSir2 , respectively (Burnett et al., 2011) . In fact, careful reassessments indicate that overexpression of sir-2.1 only results in modest lifespan extension in C. elegans (Viswanathan and Guarente, 2011) .
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“sirtuin酶家族与潜在抗衰老机理”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】sirtuin作为NAD依赖酶为什么被研究为潜在抗衰老因子？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #145 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 sirtuin 的 NAD 依赖酶活性与衰老研究有何联系；区分实验观察与疗法
3. **具体重写目标**：问 sirtuin 的 NAD 依赖酶活性与衰老研究有何联系；区分实验观察与疗法。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #146 · `auto_legacy_expansion::nist_ai_rmf_1_0::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`nist_ai_rmf_1_0`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in nist_ai_rmf_1_0, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
• enhanced processes for governing, mapping, measuring, and managing AI risk, and clearly documenting outcomes; • improved awareness of the relationships and tradeoffs among trustworthiness char- acteristics, socio-technical approaches, and AI risks; • explicit processes for making go/no-go system commissioning and deployment deci- sions; • established policies, processes, practices, and procedures for improving organiza- tional accountability efforts related to AI system risks; • enhanced organizational culture which prioritizes the identification and management of AI system risks and potential impacts to individuals, communities, organizations, and society; • better information sharing within and across organizations about risks, decision- making processes, responsibilities, common pitfalls, TEVV practices, and approaches for continuous improvement; • greater contextual knowledge for increased awareness of downstream risks; • strengthened engagement with interested parties and relevant AI actors; and • augmented capacity for TEVV of AI systems and associated risks.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `nist_ai_rmf_1_0_page_0024_HY_003` · 页 `page_0024` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_1/hybrid/shard_1/nist_ai_rmf_1_0/page_0024/evidence_nodes.jsonl`
   - 旧版原子节点：`A_006`
   - bbox：`[[217.0, 506.0, 1062.0, 1003.0]]`

````text
• enhanced processes for governing, mapping, measuring, and managing AI risk, and clearly documenting outcomes; • improved awareness of the relationships and tradeoffs among trustworthiness char- acteristics, socio-technical approaches, and AI risks; • explicit processes for making go/no-go system commissioning and deployment deci- sions; • established policies, processes, practices, and procedures for improving organiza- tional accountability efforts related to AI system risks; • enhanced organizational culture which prioritizes the identification and management of AI system risks and potential impacts to individuals, communities, organizations, and society; • better information sharing within and across organizations about risks, decision- making processes, responsibilities, common pitfalls, TEVV practices, and approaches for continuous improvement; • greater contextual knowledge for increased awareness of downstream risks; • strengthened engagement with interested parties and relevant AI actors; and • augmented capacity for TEVV of AI systems and associated risks.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“NIST AI RMF的治理与衡量目标”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】NIST AI RMF预期如何改善组织在治理、映射、测量和管理AI风险方面的流程？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #146 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 NIST AI RMF 的 GOVERN/MAP/MEASURE/MANAGE 如何支持风险文档记录
3. **具体重写目标**：问 NIST AI RMF 的 GOVERN/MAP/MEASURE/MANAGE 如何支持风险文档记录。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #147 · `auto_legacy_expansion::nist_ai_rmf_1_0::2`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`nist_ai_rmf_1_0`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in nist_ai_rmf_1_0, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
Artificial intelligence (AI) technologies have significant potential to transform society and people's lives – from commerce and health to transportation and cybersecurity to the envi- ronment and our planet. AI technologies can drive inclusive economic growth and support scientific advancements that improve the conditions of our world. AI technologies, how- ever, also pose risks that can negatively impact individuals, groups, organizations, commu- nities, society, the environment, and the planet. Like risks for other types of technology, AI risks can emerge in a variety of ways and can be characterized as long- or short-term, high- or low-probability, systemic or localized, and high- or low-impact.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `nist_ai_rmf_1_0_page_0006_HY_001` · 页 `page_0006` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_0/hybrid/shard_0/nist_ai_rmf_1_0/page_0006/evidence_nodes.jsonl`
   - 旧版原子节点：`A_004`
   - bbox：`[[176.0, 194.0, 1059.0, 430.0]]`

````text
Artificial intelligence (AI) technologies have significant potential to transform society and people's lives – from commerce and health to transportation and cybersecurity to the envi- ronment and our planet. AI technologies can drive inclusive economic growth and support scientific advancements that improve the conditions of our world. AI technologies, how- ever, also pose risks that can negatively impact individuals, groups, organizations, commu- nities, society, the environment, and the planet. Like risks for other types of technology, AI risks can emerge in a variety of ways and can be characterized as long- or short-term, high- or low-probability, systemic or localized, and high- or low-impact.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“AI社会收益与特有风险”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】为什么AI技术巨大应用潜力同时伴随可信度和风险治理需求？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #147 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 NIST AI RMF 认为 AI 社会收益与特有风险为何应并行考虑
3. **具体重写目标**：问 NIST AI RMF 认为 AI 社会收益与特有风险为何应并行考虑。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

### #148 · `auto_legacy_expansion::nvidia_2026_annual_report::1`

- **综合判定**：`REJECT`；**优先级**：`P0_QA_FIX_REQUIRED`；**修复动作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
- **文档与节点状态**：`nvidia_2026_annual_report`；`single_evidence`；`BOUND_TO_EXISTING_LEGACY_NODE`；节点最终校验：**未完成**。
- **需要审核的字段**：`question`, `gold_answer_draft`, `gold_evidence_draft (verify before reuse)`, `question_design (if present)`, `difficulty`, `review_status`, `answer_status (if present)`。

**原 Question：**
````text
What causal, technical, or comparative relationship does the selected passage establish in nvidia_2026_annual_report, and what stated condition or consequence qualifies it?
````

**原 Gold Answer：**
````text
As part of our Board and management's comprehensive review of current corporate governance practices, our Board amended our Bylaws in 2024 to let stockholders owning at least 15% of our shares, and who have owned such shares continuously for at least one year, to request a special meeting of stockholders. Those requestors must also satisfy the disclosure, timing and other requirements set forth in our Bylaws intended to ensure that stockholders receive adequate, timely, and accurate information in connection with a special meeting. Our Board believes that this special meeting right strikes a balance between enabling urgent action and protecting the Company and its stockholders from narrow, short- term interests.
````

**对应的候选 Evidence（定位信息 + 原文）**：

1. `nvidia_2026_annual_report_page_0050_HY_001` · 页 `page_0050` · 类型 `TEXT`。
   - 来源位置：`/home/ka_anthropomatik/ka_dv3352/Project/EvidenceNet/output/hybrid_node_v2_61078/embedding_geometry/batch_5/hybrid/shard_1/nvidia_2026_annual_report/page_0050/evidence_nodes.jsonl`
   - 旧版原子节点：`A_002`
   - bbox：`[[80.0, 106.0, 1147.0, 264.0]]`

````text
As part of our Board and management's comprehensive review of current corporate governance practices, our Board amended our Bylaws in 2024 to let stockholders owning at least 15% of our shares, and who have owned such shares continuously for at least one year, to request a special meeting of stockholders. Those requestors must also satisfy the disclosure, timing and other requirements set forth in our Bylaws intended to ensure that stockholders receive adequate, timely, and accurate information in connection with a special meeting. Our Board believes that this special meeting right strikes a balance between enabling urgent action and protecting the Company and its stockholders from narrow, short- term interests.
````

**已经识别的具体问题与原因（先前 AI 审核批注，仍须核查来源）：**

> 【判定：REJECT｜题目设计不合格】证据主题是“股东15%持股要求下的公司治理规则”，但问题只用文档ID和“selected passage”指向隐藏段落，并要求概括任意claim/mechanism/result；不具备无需先知道证据即可理解的检索意图，也无法建立唯一、可评分的gold answer。答案基本是在复写原段落，未抽取出可被简短、明确评分的目标命题；如果段落有多项事实，当前问题还会导致多种都合理的回答。 【建议重写题目】NVIDIA在2024年对允许股东要求召开特别会议的持股门槛作出了什么调整？ 【处理】基于这段文字重新抽取简明答案，核对关键条件与数字后重新配对证据；当前不应作为正式QA gold。

**给 Codex 的逐条处理指令：**

1. 按完整 `draft_id` 定位此条，不要只依赖 #148 行号。**目标操作**：`REGENERATE_STANDALONE_QA_FROM_EVIDENCE`。
2. 按以下主题生成一个不依赖 selected passage 和 document_id 即可独立理解的新问题，并以证据中最短完整事实撰写答案：问 NVIDIA 报告中的 15% 股东持股门槛如何关联公司治理规则（需核对具体规则）
3. **具体重写目标**：问 NVIDIA 报告中的 15% 股东持股门槛如何关联公司治理规则（需核对具体规则）。禁止用 “selected passage” 或文档 ID 代替真实检索问题；答案必须只答这个目标，禁止直接复制整段。
4. **保留判断**：优先把原 evidence 视为选题线索，重新生成独立可回答的问句；重新验证该 evidence 足以支持 Gold Answer，否则补充/更换证据。

**完成门槛**：
去模板化 Q / 精简可核验 A / 全部 Evidence 逐条 entailment / canonical ID 核验 / 人工复核；仅此后才可进入 benchmark。

---

## 4. 给 Codex 的交付文件和验证报告格式

Codex 完成后，请输出：

1. 修复后的 JSONL，新文件名含版本号，原始文件不覆盖；
2. `qa_fix_diff.jsonl`：每条输出 `draft_id`、`old_*`、`new_*`、`changed_fields`、`source_verified`、`canonical_node_ids`、`verification_notes`；
3. `qa_review_triage.csv`：每条状态、需要人审原因、source page、节点映射状态、是否排除；
4. 审计摘要：哪些条目完成可自动修复、哪些还需要原始 PDF/人工核验、哪些由于资料本身不合格被剔除，以及去重后的有效 QA 数目。

**决策禁止事项**：禁止仅凭本报告中的字句覆盖解析器真实输出；禁止自动添加不存在的事实；禁止修改证据而保留原 canonical mapping 不重验；禁止在没有 PDF/节点源的情况下声称 `VERIFIED`；禁止悄悄删去 REJECT 样本而不保留审计日志。

## 5. 附件与元数据

- 本文件每个条目的事实依据来自上传的原始 JSONL 证据文本，具体问题与部分修订建议来自同批 AI 审核记录；所有提议需要后续验证。
- 机器可读清单：`codex_qa_issue_manifest.jsonl`（每行一个完整 QA 修复任务，包括原证据全文、定位、操作与建议修订）。
- 检索索引：`codex_qa_issue_index.csv`（便于先按优先级及 Action 对脚本做分组处理）。

输入文件 SHA256：原始 `37f02157832680be03e50e07dce5ae66cd19c62aabbc70496c90cf0ee7505789`；AI review `ac159134f51e48eec1cf1b75196efbc6678c498a68003226bb9dbbcea56498af`。请 Codex 检查接收到的输入是否同一版本。