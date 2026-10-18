# 冻结 baseline 后的 edge 设计建议

日期：2026-10-11。状态：设计建议，尚未实现或提交新的 edge 实验。
基准：`vldocir_no_edge_v1_20261011`，见 [BASELINE.md](BASELINE.md)。

## 结论

保留现有 EvidenceNode 作为真实端点。文章、章节、段落与阅读流首先作为归属信息；
文章内部保持两类边：`reading_order` 和 `semantic`。
段落与文章的关系由具体 source span / node 关系支撑，不因同属一篇文章、
相邻或 embedding 相似就自动成为语义边。
跨文章与文章内语义使用相同的可追溯端点协议，但分开候选范围、预算和评估。

新增信息写入独立 sidecar，引用冻结 node ID，不重切、合并或重新生成 baseline 节点。
跨页同一句若分属两个冻结节点，可以增加已验证的续接关系，不修改节点成员。

## 历史结果给出的约束

1. [当前文章图契约](../document_article_graph/README.md)已区分文章归属、NEXT 和
   语义边，但端点仍为 component，尚未接入 Hybrid evidence_nodes ID。
   `PAGE_LOCAL_ONLY` 不能冒充整篇文章；同一篇文章也不一定同一 reading flow。
2. [跨文章候选诊断](../../../EdgeGeneration/docs/cross_article_evidence_2026-09-17.md)：
   447 单元、97,275 个可能对，diverse top-10 得到 3,621 对，保留 4/4 暂定阳性；
   普通 top-10 保留 3/4。只有七条历史标签，这不是语义精度结论。
3. [ANN 诊断](../../../EdgeGeneration/docs/ann_candidate_pilot_2026-09-16.md)：
   文章均值向量 top-20 漏掉全部三个暂定阳性文章对；各路 top-3 并集保留 3/3。
   因此文章路由不能阻断 evidence-node 的直接召回。
4. [逐标签语义复核](../../../EdgeGeneration/docs/relation_policy_ablation_v1.md)
   的实际输出 `EdgeGeneration/output/relation_policy_ablation_v1/summary.json`：
   24 个真实对最终为 1 RELATED、22 UNRELATED、1 INVALID。
   合成控制 4 正/4 负全部符合预期，也不能代替真实样本的精度与召回评估。
5. [视觉 prompt 对照](../../docs/prompt_comparison_and_archive_2026-10-06.md)：
   更严格文字提示仍有 3 个明确错误，支持关系从 13 降到 9。
   错误包括借用同页其他图片的内容、用 logo 支持数值结果、图注挂错对象。
   必须核验目标 crop，不能只相信生成描述或整页推理。
6. `EvidenceNet/output/split_taxonomy_relation_typing/comparison.md`：
   将 REFERENCES 与语义功能拆开，27 个已知相关的 oracle 对上，Qwen3.5
   类型＋方向正确率从 33.3% 到 66.7%，Qwen3.6 从 40.7% 到 63.0%。
   类型准确率仍低于多数类基线，REFERENCES F1 仅 33.3% / 46.2%。
   这支持协议拆分，不支持宣称已能准确地从大候选池生成边。

## 各层如何建边

### 文章归属先行

为节点另存 `document_id / article_id / section_id / paragraph_id / flow_id` 及
`assignment_status`、source members；不存在可靠归属时允许 null/UNRESOLVED。
经确认的单篇论文可使用 document-level article ID；杂志必须先做文章分割，
不同文章可能同页，同一文章也可能跨页或跳转续页。
标题保留为结构上下文，footer、页码、logo 不进入 evidence 端点。

旧 component 边迁移必须按 source_atom_id / fragment_id / offset 匹配。
若一个 component 覆盖多个节点，依赖原边的支持 span 决定具体端点；若没有
可唯一解析的锚点则延后。禁止 ID 后缀猜测和把旧边广播到所有映射节点。
若边两端已经合成一个 node，只保留内部来源关联，不生成 self-loop。

### 阅读顺序

`NEXT(A,B)` 表示同篇、同一 flow 的真实后继，是有向边。
候选来自 parser reading order、栏结构与文章边界；几何用于局部约束，
不能按全页 y/x 排序跨文章连线。图注、脚注、侧栏各自维护 flow。
初轮允许正文形成不完整链，禁止为凑齐链条连接不确定端点。

跨页使用源尾部、目标头部、章节与续页标记核验，区分：
`SAME_SENTENCE / SAME_ARTICLE_NEW_NODE / SAME_ARTICLE_NO_EDGE / NEW_CONTENT / UNCERTAIN`。
只有前两者创建 NEXT，第三者只更新归属。跨页候选不能永远局限相邻物理页；
杂志的明确 continued-on/from 页码可另开候选路由。续页指示属于结构元数据，
不把其页码当作 evidence。反向查找前文可以走 NEXT 的入边，但不改边的方向。

### 文内 node 与段落关系

段落不是必须新增的第二套检索节点。一个源段落可能对应多个 evidence nodes，
一个复合 node 也可能覆盖多个源块；用 paragraph membership 和精确 span 表达。
段落间先有 NEXT，再按实际支持片段建立语义关系。

候选取独立路由的有界并集：同 flow 的少量前后节点、跨页边界、明确图表/方程/
章节指代、同篇较远位置的 dense 或 lexical 命中。几何只是局部候选信号。
先判断是否存在可说明的关系，再选类型和方向；可多标签，也允许无关系。

建议第一轮先启用可独立核验的关系：

| 关系 | 判定要求 |
|---|---|
| `REFERENCES` | 源中有实际指代，且能解析到目标节点；先建立文章内 Figure/Table/Equation/Section 目标索引，避免引用实际指向第三个 node |
| `NEXT.continuation_kind=same_sentence` | 源文本确实续接同一句/同一截断内容；作为 NEXT 的属性保存，不重复计权；不能由“相关段落”推出 |
| `CAPTION_FOR` / `ILLUSTRATES` | 精确图注范围与目标 crop 的附着或可见内容对应；已经在同一复合 node 内时不外建边 |

功能关系沿用历史 taxonomy：`SUPPORTS`、`EXPLAINS_OR_ELABORATES`、`MODIFIES`、
`CONTRASTS_WITH`，另保留 NONE/UNCERTAIN。先单独验证前两类；后两类历史上
各只有一个可评样本且均未识别正确，不作为首轮自动接受的默认类别。
支持数据需要匹配对象、指标、条件、时间与范围。解释与配图不是独立事实佐证。
不另铺开矛盾、因果等细分标签，避免把不同条件下的陈述误判为冲突。
显式指代与语义功能可以同时存在，应分别记录。

### 跨文章、跨文档

先从 node 直接检索跨 article 候选，再补 article profile 和 lexical 路由。
可把 top-10、每目标文章最多 2 个候选作为开发起点，但这只是待验证预算，
不能当成从四个阳性样本中得出的最优参数。不要全量两两 Qwen 推理。

每个候选给出两端真实内容、所在文章/章节和精确锚点。Qwen 判断“具体关联
在哪里、是什么、方向如何”；同关键词、同实体、同主题仅作为检索依据。
模型判定后仍需抽样源文复核，第二次调用同一模型不等于独立人工标注。

文章 A 与 B 的语义关系从已接受的 a_i → b_j 聚合，保留具体 supporting_edge_ids、
类型、方向和支持 span。汇总视图不代表 A/B 的所有段落相关，也不增加额外重复权重。
暂定文章归属无法确认时，不声称跨 article；可保留明确的 cross_document 信息。

文献 `CITES` 复用 OfflineCitationGraph 的 citation mention + bibliography +
DOI/arXiv 等解析。它证明引用，不证明支持；不能从文章引用广播所有段落边。
段落引用某篇文章也不意味着目标中的任意段落就是支持端点。

## Edge 记录与核验

每条记录包括 baseline_id、端点 node IDs、family/type/direction、article/flow scope、
两端 source span IDs/字符偏移或视觉 crop hashes、候选来源、模型/prompt/输入版本，
以及 ACCEPT/REJECT/UNCERTAIN 和具体依据。模型 confidence 不当成校准后的概率。
上下文可辅助判断，但不能以第三个节点内容替代本边端点的证据。

验证覆盖：端点存在、支持 span 属于端点、方向和范围有效、无 self-loop/重复、
阅读顺序无环与跨 flow 误接、article 聚合可回溯、furniture 不作为证据。
覆盖与 JSON 验证通过不等于语义关系正确；必须另报人工/源文审阅质量。

## 接入检索的实验顺序

1. 先补 frozen-node adapter、文章/段落/flow sidecar 和 node-level 检索 trace。
   当前 evaluator 最终只写 page scores，虽然内部算过 unit scores；需要在独立输出
   缓存 node/window 分数和命中 provenance，并确认重新聚合能复现 frozen page ranking。
2. B0 保持冻结的 hybrid_visual；B1 仅 NEXT；B2 仅显式指代/跨页 CONTINUES；
   B3 仅文内语义；B4 仅跨文章证据边；最后才测试组合。CITES 有充分源信息时单列消融。
3. 首轮从相同的命中节点出发，只扩一跳，限制每 seed 和每目标页扩展预算。
   保留原始检索信号；邻居也按相同 encoder 判断 query relevance，再加有限的边信号。
   不把无关的高 degree 节点、整篇文章或所有相邻页面无条件升分。
   语义方向保留；是否允许反向检索遍历作为独立且预先固定的策略。
4. 增加同预算的普通相邻页、embedding kNN 扩展对照，必要时增加同 degree 的随机边负控，
   检验提升是否仅来自多拿页面。参数在独立开发集上确定，不按这 24 个查询逐题调参。
5. 同时报告 Recall/nDCG、RecallAll/nDCGAll、六类型拆分、配对差异、edge 源文精度、
   人工标注候选召回、错误扩展率、验证次数和延迟。标签仅用于评估。

## 冻结结果对实验重点的提示

hybrid_visual 的 RecallAll@5：

| 查询类型 | RecallAll@5 | 查询数 |
|---|---:|---:|
| 单页单证据 | 100% | 4 |
| 单页多证据 | 100% | 4 |
| 相邻跨页 | 100% | 4 |
| 近距离非相邻页 | 25% | 4 |
| 远距离跨页 | 50% | 4 |
| 跨文档 | 25% | 4 |

因此跨页配套证据和跨文章证据值得优先验证；NEXT 是必要基础，但仅邻接扩展
未必解决当前弱项。同页边对上下文组织有用，单靠同页遍历不能带来新的页面召回。
以上每类仅四条，属于开发诊断，不构成可推广的结论。数据源是冻结的
`retrieval/hybrid_visual_metrics.json`，不是新的实验成绩。
