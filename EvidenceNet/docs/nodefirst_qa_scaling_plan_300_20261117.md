# Node-first QA 扩量执行规范：300 Gold（2026-11-17）

## 目的与边界

这是交给 Codex/Sol 在 HoreKa2 上**执行代码和任务**的规范；GitHub 中的本文件本身不会启动 HPC 作业。延续 r3 的**全自动** Source/Mapping + 独立模型语义审核，不引入人工逐条批准，不覆盖 Pilot、r1、r2、r3 的 JSONL 或 PDF。

**总体目标：先形成 300 条经自动 Gate 严格接受的 Gold QA；当前已完成前序处理的 PDF 现在即可使用，未完成的 PDF 随后在新 snapshot 纳入。** 新 PDF 不应阻止现阶段扩量。

### 当前 r3 参考盘点（来自用户提供的一份 r3 导出，非 HPC 上的全部数据）

- 该文件有 **17** 条，而不是 20 条，4 Single / 4 Cross-page / 9 Cross-document，17/17 的 FINAL_ACCEPT_AUTOMATIC。
- 31 个 Evidence 引用对应 26 个独立 Node，只有 14 个不同 document_id；4 个新期刊 Evidence 仅用于 Single-node，跨页/跨文档引用全部来自旧语料。
- 证据节点类型仅为 27 TEXT + 4 PARA；没有 TABLE、IMAGE 或 CAPTION 作为实际 Gold Evidence。
- 9 条跨文档含 8 条两文档和 1 条三文档。引力波文档被反复使用；011/012、030/045 存在 Gold Node 复用。
- 文件中全部 Claim Span 的字符偏移均与 evidence_text 字符串一致；**字符匹配不证明语义蕴涵**，需要保留独立 claim entailment。
- 17 条的 \`review.status\` 仍为 \`PENDING_INDEPENDENT_MODEL_REVIEW_R3\`，尽管 \`independent_review.review_pass=pass2\` 和 \`final_gate.status=FINAL_ACCEPT_AUTOMATIC\`。修复导出字段一致性，保留历史审计信息。
- 不应把这份 17 条当成自动满足 20/30/50 的 final balanced export；现有 r3 是否还有其他 QA，要在 HPC 检查实际文件。

## 1. 数据源与入库门槛

### A. 已完成的新期刊 PDF
\`\`\`text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pdfs
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/real_documents_v1_20261113/pipeline_to_nodes_v1_20261114/work
\`\`\`
用户报告已解析完成的 18 篇：real_001–real_013、real_015–real_018、real_020。此进度仅为参考，**运行时需检查实际文件、per-page checkpoint、可用 canonical nodes 和稳定 Node IDs**。real_019 在报告时尚未完成，real_014 状态不明，不能未经检查纳入。

### B. 旧语料
\`\`\`text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/documents.jsonl
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/pages.jsonl
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/node_vqa_reuse_v1_20261113/nodes.jsonl
\`\`\`
用户报告为 25 文档、49 页。Source Integrity、ID/PDF-Page/Bounding Box 引用与 Canonical Mapping 使用现有自动 gate；不因未获人工 PDF 签字而统一拦截；严重 OCR/不可定位证据需逐项隔离。

### C. 原有候选池（用于去重/错误分析，不能直接当新 Gold）
\`\`\`text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/all_qa_review_drafts_v1
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project/DynamicEdgeGraph/datasets/dense_magazine_candidates_v1
\`\`\`
已有 r1/r2/r3 accepted questions 也进入全局 dedup 索引；**不得仅更改 Question 字眼而重复计数**。

## 2. 数量、配额与分批

第一目标是 **300 条通过最终 Gate**，不是 300 个未经审核候选。按目标分布：

| Gold 类型 | 总数 |
|---|---:|
| Single-node | 60 |
| Cross-page（同文档不同页） | 90 |
| Cross-document | 150 |
| ├ 双文档 | 105 |
| └ 三文档及以上 | 45 |
| **合计** | **300** |

严格核算百分比：20/30/50；35/15 是占**总体**的比例，不是占跨文档子集的比例。现有 r3 去重后确实合格的题可以纳入 300，**不可仅因为 r3 文件标记 ACCEPT 就直接重复添加到新版本**。

**执行方式**：每个 batch 以 100 条合格 QA 为目标（20 single、30 cross-page、50 cross-doc，其中 35 双文档、15 三文档及以上）；分 3 个 batch，使用持久化候选队列、不限制候选生成尝试次数但设置 GPU/token/job 预算上限，失败原因和有效产出分别统计。优先完成前 100 条，独立诊断后再启动后续 batch；最终不得为凑 quota 降级 Gate。

若当前材料不足以形成 45 条真实三文档任务，**不要强行拼接**。保留未平衡的 accepted pool 和短缺报告，等后续 PDF 完成后再填补；final balanced export 只能统计真实符合类别和子类型定义的题。对不达标类别不要虚报完成。

## 3. 根本性采样修复：覆盖新 PDF、避免过拟合旧文档

当前 r3 新期刊只贡献 single-node，因此需要**修复 companion evidence discovery**，不能再只从旧语料找到多节点 Group：

1. 对每个 eligible corpus/document/modalities 建 deterministic seed pool，并按 **corpus × document × modality × category** 做分层采样；不是先生成大量容易的旧语料 QA 再筛选。
2. Cross-page 允许从**新期刊同一 PDF 的不同页**寻找互补事实，优先建立跨 2–10 页和 >10 页的覆盖，文档页数不足时记录失败而非伪造。
3. Cross-document 候选应覆盖 new–new、new–legacy、legacy–legacy。新旧之间仅在有真实实体/方法/技术/数据关系时合并；不能因“都属于 NASA”或主题词相近而硬连。
4. 对每批按 category 输出新/旧语料覆盖。若新期刊持续在 cross-page/cross-document 中为零，暂停跨文档大规模扩量，先修复候选发现及跨源检索路由。
5. 设置**软性覆盖约束**：单一文档占全部 Gold 不超过约 10%；单一文档对占 cross-doc 不超过约 10%；引力波主题总占比控制在约 20% 左右；对不够成熟的数据源报告例外，不做伪配额。
6. 对来源不同、但内容高度同源的转载与重复段落做 source-family 去重，避免伪跨文档必要性。
7. 真实 TABLE / IMAGE / CAPTION 可用时开展独立多模态抽样，参考目标：**至少 15–20% Gold 确实依赖非纯文本证据**（按可用性作为覆盖目标，不可假装 caption 就等于图像推理），保留 pixel/page-image-based verification。若 image/table canonical nodes 暂不可用，先报告缺口并修复上游，不得编造视觉答案。

## 4. 自动化质量 Gate（不引入人）

- 文档、页面、Node ID、bbox、来源、canonical alias、Source Integrity 校验；
- per-claim **准确语义支撑**：Claim -> Gold Node -> exact supporting span（字符位置匹配是必要非充分条件）；
- multi-node 逐节点删除测试，保留真实的 missing atomic claims 和前后证据集合；**题目问两个互不相关子问题不自动等于合格 multi-hop**；
- corpus-level single-node/单文档 shortcut 搜索：多路 lexical + frozen dense 检索，并测试候选是否能独立回答完整 Question；不能只做低质量 lexical Top-K 且把“未找到”当做“无捷径证明”；
- 对 multi-hop 必须显式写出桥接关系、依赖链、对比维度；no forced analogy；
- 与原始 r1/r2/r3、当前 batch 的 lexical + semantic dedup；
- 至少一个与生成器隔离的模型/Prompt 路径做二次审核，记录 reviewer model/version、实际输入输出和拒绝原因；
- Review 与 Final Gate 状态一致，保留 history：不要出现 FINAL_ACCEPT 同时主 \`review.status=PENDING\`；
- 独立反例或失败原因保留于 failed/skipped/quarantine，不得覆盖原始 QA；
- 避免训练/评估泄漏：QA 发现候选不能仅依赖将被测 Graph 已筛选的边；不得利用 Eval Gold 调整待评估 Graph。
- **区别 Retrieval supervision 和 Edge supervision**：多个 Gold Nodes 同时出现，不代表节点两两之间的任意组合都是 positive edges；必须另有逻辑依赖证据，避免把完整 Gold Set 转成假全连接边正例。

## 5. 新 PDF 渐进加入（不卡住当前生产）

以 **frozen corpus snapshots** 记录可用数据：

- **snapshot_A**：运行时检查通过的已有解析 PDF + 旧语料（开始 100/300 Gold 扩量）；
- **snapshot_B、C...**：新 PDF 完成解析、Node canonicalization、ID consistency 后才纳入，并记录实际新旧文档差异；继续候选采样，勿覆盖已有 QA。
- 不要把新旧 snapshot 的 Node IDs 默默复用到不同内容；如果 canonicalization 改了 Node ID，必须明确 alias remap 且重新验证。
- 每次语料扩充时，新文档可能带来 **新增单节点捷径/等价 Gold Sets**。对累积 Gold 做全库 shortcut / dedup recheck，而不是永久相信旧 snapshot 的“无捷径”。
- 如果用户后续要用这些 QA 训练 Query-conditioned Edge Router，先把 QA 按 **document/topic/source family** 分割 train/validation/test，再使用同组已知近重复题做 leakage 检测。Cross-document 题的全部文档必须遵循可复现的 split policy，不能仅随机按 QA 切分并泄漏相同证据到 Test。
- 第一批可为训练代码提供 100 条 smoke/pilot，达到约 **200–300 Gold** 再尝试轻量监督 Router；正式 Test 在训练和调参过程中冻结。

## 6. 最少输出文件与报告

创建独立的新目录，例如 \`DynamicEdgeGraph/datasets/nodefirst_qa_scale300_20261117/\`，遵从项目实际 layout，原有 r1/r2/r3 保持不变：

\`\`\`text
configs/scale300_config.json
source_inventory_by_snapshot.json
sampling_pool_by_corpus_modality.json
sampled_seeds.jsonl
companion_candidates.jsonl
qa_candidate_drafts.jsonl
qa_independent_reviews.jsonl
qa_gold_auto_accepted_pool.jsonl
qa_gold_balanced_20_30_50.jsonl
failed_or_skipped.jsonl
shortcut_and_alternative_gold_audit.jsonl
source_mapping_audit.jsonl
batch_001_report.md
batch_002_report.md
batch_003_report.md
coverage_and_bias_report.md
train_val_test_split_manifest.json
scaling_summary.md
\`\`\`

对每个 batch 输出：
1. attempts/valid/rejected/yield（不能把 after-filter PASS rate 冒充生成总体通过率）；
2. 目标/实际 Single、Cross-page、Cross-document、2-doc、3+-doc；
3. 覆盖 document_id、source corpus、source family、modalities、page distance、evidence size、reasoning type；
4. 复杂题单节点捷径、伪 multi-hop、来源问题、Mapping 问题、claim entailment 问题的分布；
5. 新引入 PDF 与新增 QA 的版本链接、节点映射变更；以及旧 Gold 因新单节点捷径失效的记录；
6. 指标和统计的独立可重跑校验脚本（e.g. counts, unique IDs, ratios）。

**不要把没有达到 300 接受标准的结果宣称完成；可以报告“截至当前 snapshot 有 N 条被接受、尚缺 M 条”并继续下一个可用 snapshot。**

## 7. 交给 Codex 的执行顺序

1. 审查现有 r3 所用 schema、来源和 pipeline 的真实代码，核对 r3 accepted pool 和用户提供的 17 条导出，修复 \`review.status\` 一致性；
2. inventory-only：检查当前可用 PDF、页级 checkpoint、canonical node pool、TABLE/IMAGE availability，冻结 snapshot_A；
3. 实现 corpus/document/modality-aware sampling 和 independent companion discovery（新期刊也可以 cross-page/cross-doc），在旧 Gold 上执行 dedup；
4. **先运行 Batch 1：100 条目标**，报告每个类别的成功率，审查新期刊为何以前没有提供多节点题；
5. 质量正常后运行 Batch 2 和 Batch 3，目标累计 300 条，遵守 Node/Doc/Topic 多样性和 20/30/50；
6. 将新 PDF 解析进度纳入后续 snapshot，不等待没有完成前序处理的 PDF；
7. 导出单独的 accepted_pool、balanced_gold、训练 split、自动审核统计和失败队列；避免把还没完成的 pending QA 算作 Gold。

## 非目标

- 不要求人工逐条审批；不以缺少统一人工 PDF 审核为阻断理由。
- 不因此修改项目的原始 PDF、既有 parse checkpoint 或已冻结的 Gold。
- 不为满足 quota 人为合成虚假的跨页/跨文档关系。
- 不声称 GitHub 文档已在 HoreKa2 执行；真正的扩量必须由具备 HPC 文件系统访问的 Codex/Sol 执行。
