# Article bridge pilot v1：运行与来源审查

结论：具体事件导航出现局部正向信号，但尚未通过接入正式 pipeline 的验收条件。固定开发案例的跨文章候选覆盖没有变化；新增加的候选集中于同一个 GW150914 事件。不能据此宣称检索质量提升。

## 实际运行

GPU 69626 正常完成，退出码 0，耗时 23 分 11 秒；报告任务 69627 生成结果。模型调用合计 111 次（含重试），记录的调用时间约 22 分 25 秒。输入为 11 个文章／片段、218 个原始 node，其中 215 个 eligible；210 个有缓存向量，5 个保留词法回退。163 条阅读边和 180 对文章内结构候选保留。

44 对核验：

| 原始状态 | 数量 | 解读 |
|---|---:|---|
| ACCEPT | 11 | 8 条跨文章，3 条文章内；均须来源审查 |
| REJECT | 1 | 核对后发现此例是错误拒绝 |
| UNCERTAIN | 21 | 不能当作正确负例 |
| FORMAT_PENDING | 11 | 全部是状态策略冲突，不是 JSON 解析损坏 |

开发集 28 对：7 ACCEPT、15 UNCERTAIN、6 FORMAT_PENDING。
新案例 16 对：4 ACCEPT、1 REJECT、6 UNCERTAIN、5 FORMAT_PENDING。
新案例由 4 对全局独有、5 对 subject 独有、7 对共同候选组成；独有池大小不同，不能把它包装为等量独有样本的精度实验。

## 路由变化

两组各有每个 eligible node 8 个有向跨文章目标。全局候选去重后 1383 对，subject 候选 1387 对：1379 对相同，全局独有 4 对，subject 独有 8 对，联合 1391 对。因此两组候选总体非常接近，主体导航对原有排序影响较小。

固定开发集共有 14 对跨文章案例，其中两组均覆盖 10 对；这 10 对包含正例、负例及未解决案例，不是 10 个正确结果，也不是检索 Recall。已接受的 4 对已知跨文章 GW 正例（08365、07887、08362、08073）两组均已召回，没有新增已知正例覆盖。

subject 独有的 8 对全部位于 GW150914 三篇论文之间。其中冻结核验抽到 5 对，模型接受 4 对、拒绝 1 对。来源检查显示：

- `BRIDGE_3364c623191b`：C2+C3 搜索中的 GW150914 显著性 → 该事件的 source-frame 质量 posterior 图，关联成立，但解释中的跨论文 Fig.1 引用说法错误。
- `BRIDGE_d3b9c2f8fb24`：快速演化／强场动力学描述 → source-frame 质量估计，关联成立。
- `BRIDGE_39c15b987862`：搜索显著性图 → waveform 模型比较及合并后的参数估计，关联成立。
- `BRIDGE_00a40f64eb0b`：GR 强场约束 → 该次观测期间的校准不确定性，属于同事件的两个方面；校准属于仪器条件，不应称为天体源的物理属性。
- `BRIDGE_a474afc1b03d`：搜索显著性图 → GR 残差／色散检验，两端明确讨论 GW150914，符合 `RELATED_VIA_SUBJECT`，模型却以“分析方面不同”为由拒绝。它在无形中额外要求了共同方法／结果，与冻结关系定义不符。

另外 3 对未做模型核验，仅在此次助手来源审查中判断其共享 GW150914 事件有依据；不计入最终接受边。上述来源判断均为助手开发审查，不是独立专家标签，不给出无偏 precision/recall。

## 图表来源绑定有效，但收益范围小

共有 8 条 SUPPORTED 上下文绑定，去重后仅对应 3 个目标 node。其中两个目标图注已经直接写出 GW150914；真正新增消解的目标只有 properties 论文的 Fig.1 质量 posterior 图。

关键链条：

`properties page_0006 HY_007` 原文明确写出 GW150914，并说 “as shown in Table I and Fig. 1” → 同一论文 `page_0006 HY_008` 原始质量 posterior 图 → 通过事件 GW150914 联系 detection 论文的搜索结果图。

`TYPED_08073` 已接受；查看原图后，目标确实是 source-frame 分量质量的 posterior 分布。此次 aspect 没有把上下文段落的 36/29 数值直接冒充图内局部陈述。三个涉及绑定的原图已检查，接受边的本地锚点、直接 subject mentions 和 context anchors 均通过原文切片／crop SHA 与成员归属校验。哈希校验只能证明来源完整性，不能替代语义判断。

通用 LIGO SNR>12 阈值 `TYPED_05820`、设计噪声 `TYPED_05882`，以及只共享 CERN 的 `TYPED_00270` 未被升级为具体事件／项目边。不过它们输出 UNCERTAIN，不能据此统计正确拒绝率。

## 主要问题

### 1. 身份索引碎片化，直接漏掉原文明确的项目关联

AHEAD 被分成 `PROJECT:ahead` 与 `PROJECT:ahead project`。
`TYPED_04478` 的救援叙述最后明确写出 “AHEAD is ready to take its next steps”，另一端是 AHEAD project 的参与机构；两个 literal keys 不同，核验器拿到的 shared_bindings 为空。模型进一步错误解释为原文未写出项目名。

UMBRELLA 又被分成 `umbrella`、`the umbrella project`，以及原始 parsing 中的 `umrella` 拼写。不能悄悄改写原文，但应把原始 mention 与经来源支持的规范身份分开。目前“只做大小写／空白归一化”过于保守。

六个 subject keys 实際仅围绕 GW150914、AHEAD、UMBRELLA 三个主体。只有 GW150914 跨多个文章单元，因此全部 3 条文章导航边都是三篇 GW 论文两两相连；本轮没有验证多领域杂志之间的跨文章项目关联。

### 2. 状态协议将语义判断包装成格式失败

44 对中 32 对没有 shared binding。程序强制这类案例只能 UNCERTAIN，但 Qwen 有 11 对返回了可解析的 REJECT，重试后仍被校验器标成 `missing_binding_is_unresolved`／FORMAT_PENDING。这里应分别记录索引覆盖、模型语义判断和协议有效性，不能把它当作 JSON 故障，更不能悄悄算成正确负例。

EVENT/PROJECT 的首轮限定本身也使方法、平台、Open Science policy 等其他关系无法参与。这是实验范围／覆盖限制，不是这些原文无关系的证据。32 对未绑定造成当前结果不足以评估一般语义 edge 的完整性。

### 3. 关系判断及元数据仍不稳定

11 条接受边在“同一具体事件／项目的两个内容方面”层面均有合理来源依据，但存在 1 条明确的来源解释错误及若干需修正／澄清的条件：

- `BRIDGE_3364c623191b` 说目标 Fig.1 被 source text 引用；实际 source text 引用自己论文的 Fig.4，目标 Fig.1 由 properties 论文内部的独立上下文绑定确定。两段来源链被混为一段。
- `TYPED_08362`、`TYPED_07887` 的质量 aspect 未保留 detector-frame 标签，原文实际明确标注该参考系。
- `TYPED_08012` 应分别标注 primary C3、alternative C2+C3、binary coalescence 的条件，避免把 4.4σ 与 >4.6σ／>5.1σ 混在笼统的“匹配显著性”说明里。
- `BRIDGE_00a40f64eb0b` 的关系解释应将仪器校准条件与天体源参数区别开。

此外，上下文绑定重复：8 条绑定只有 3 个目标；`by_node[subject_id]` 的字典赋值会选择最后一条绑定，未显式保留多条并列来源理由。这需要来源优先级／合并规则，而非依赖输出顺序。

## 下一步建议

按项修复，保持这轮原始输出冻结：

1. 先解决带原文证据的规范身份合并。回归 AHEAD／AHEAD project、UMBRELLA／the UMBRELLA project；OCR 拼写只在有可靠同文章来源时建立 alias，不泛化为随意模糊匹配。
2. 将索引覆盖状态与最终模型判断分开，重放 11 个状态冲突案例，验证不是通过改计数掩盖失败。明确 `RELATED_VIA_SUBJECT` 允许不同分析方面，保留 `BRIDGE_a474afc1b03d` 错拒案例。
3. 对 local 与 context provenance 分别校验；保留参考系、搜索类别、条件，去重并保留所有必要绑定来源。重点回归 `BRIDGE_3364c623191b`、08362、07887、08012。
4. 上述问题解决后，新增真正共享同一项目但措辞不同的多领域文章对，继续使用同预算对照，再进行冻结查询检索评测。当前数据只证明单个事件的局部候选收益。

目前不通过 adoption gate：固定已知案例覆盖未提升，且接受边含来源解释错误。没有运行 query retrieval，不报告 Recall@k／nDCG 提升。

## 审查产物

结果目录：`EvidenceNet/output/article_bridge_pilot_v1_20261012/`。

- `viewer.html`：展开文章导航理由、原始 node 成员、图片、绑定与所有决定。
- `audit/source_review.jsonl`：接受边、错拒、身份漏边、状态冲突及重点负例审查。
- `audit/subject_only_candidate_review.jsonl`：8 对 subject 独有候选的来源审查。
- `audit/review_summary.json` 与 `audit/artifact_sha256.json`：审查计数及原始结果指纹。

原始模型输出、冻结 manifest 和运行代码未修改，未提交新 GPU 试验。
