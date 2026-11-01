# EvidenceNet edge 建立：模型切换交接与实验账本

更新日期：**2026-10-28，Europe/Berlin**（后续更新见第10–11节；旧任务表为当时快照）。任务状态是本次查询快照，不是实时监控。

本文供接手模型直接读取。覆盖 10 月 11–27 日跨文章 edge 主线，按逻辑实验记录，重试/续跑不重复计为新实验。更早的 node generation 历史保留在原实验目录。数字来自已存在的报告、代码和本次取回的结果；不能把“做过方案”“代码实现”“任务完成”“效果验证”“已接入默认入口”混为一谈。

## 0. 给接手模型的最短交接

> 用户要的是原始文件 → Dolphin 解析 → 多模态 node generation → 文章归属/阅读顺序 → 候选召回 → edge 验证/导出 → 最终搜索的完整 pipeline。允许复用已冻结的上游节点，但必须说明哪些阶段没有重新跑。
>
> 优先阅读本文、`scripts/run_evidence_edge_pipeline.py`、`experiments/vldocir/PIPELINE_COMPARISON_20261025.md`。不要凭旧 README 的“尚未运行”覆盖后来已下载的结果，也不要拿 prepare 阶段的零分报告当失败结果。
>
> 当前 edge 默认 encoder 已是 **Qwen3-Embedding-8B**，不是早期 0.6B；verifier 是 **Qwen3.5-35B-A3B**。原 node 保留，多种检索片段只是 view。默认 verifier 使用原文/图注/表格锚点与原图；不会自动开启所有 context/scope/切句实验。
>
> 已修工程问题包括候选名额重复、eligible 内容泄漏、精确图表指针的候选保护、原文锚点、部分来源角色丢失等。尚未解决的是语义判断泛化、公式范围/角色、多节点阅读顺序可靠性，以及稳定的最终检索收益。
>
> 新增描述约束对照 **5215455** 已提交、PENDING（见第11节）。此前任务：公式结构/角色对照 **5215293**、阅读修复 smoke **5215323**，本次查询仍 PENDING。旧评估 **5212511 已取消**，因为其前置构图分片失败；不能继续等待它产出结果。具体恢复入口及限制见第 7 节。
>
> 保留原始预测、标签、输入 hash、失败记录。不要自动把相关性当作支持、把引用关系当作语义关系、把 source-grounded/格式有效当作语义正确。本文中的开发集提升不能宣传为独立测试或官方全库成绩。

## 1. 当前真正实现的 pipeline

```text
文件 / HTML 渲染页
  → Dolphin 原文、表格、公式、图像、caption 与几何位置
  → hybrid 多模态 EvidenceNode（原 node ID / 原成员 / 原图保持）
  → article membership + reading flows
       └─ NEXT / PREVIOUS：阅读结构，独立于语义边
  → eligibility 与 source role 审核
  → 多个 source-mapped retrieval views
  → dense / lexical / identifier 等候选 + 文章路由 + 有界配额
       └─ 原文图表引用候选：独立来源和方向
  → Qwen 两端原始证据核验
  → related / review / rejected 等分流
       └─ bibliography / administrative 来源另审
  →（独立实验）离线 edge 描述与 embedding
  → query 匹配已有索引、候选扩展、统一重排、最终检索指标和路径
```

### 1.1 默认入口与实验开关

以 [run_evidence_edge_pipeline.py](scripts/run_evidence_edge_pipeline.py) 的实际 `config` 为准：

| 项目 | 当前实现/边界 |
| --- | --- |
| 默认 embedding | `--embedding-profile qwen3-8b`；新向量须与模型、pooling、输入文本、维度及 hash 匹配，不能与 0.6B 混空间 |
| 节点筛选 | 需要 eligible、document 与已确认 article；排除节点另存，不抹掉原证据 |
| 默认预算 | `budget=1301`，escape 96，reference 96；这是配置起点，不是全规模通用最优值 |
| verifier | matched control、原始多模态、700 输出 tokens、最多两次、无额外 scope/context 扩张 |
| 图像与 caption | 图不是仅给一张图片：合格的原文/caption/表格会进入证据目录，另附原 node crop；具体某个 node 是否有 caption 仍须查看 input，不能假定全部都有 |
| 默认关闭的实验 | `text_scope`、`formula_context_expansion`、`resolved_citation_lane`、`reference_context_lane`、`contiguous_reading_lane` |
| 导出语义 | 对称 `RELATED` 模型提案，`evidence_propagation_allowed=false`；不是已证实 SUPPORTS 图 |
| 导出保护 | 无有效输出→review；导航缺 checked identity→review；DIRECT_COMPLEMENT 无已核实 source pointer→review；两端缺原始证据→review；reference/行政来源另分流 |

注意：核验实验输出的 E/N，与最终正式导出的 RELATED 数量不一定相同。图出口的保守检查会把一些实验中的“接受”转入 review；不能直接把 verifier FP 数等同于已导出错边数。

### 1.2 用户已经确定的需求

- edge 必须离线提前建立；query 来时使用已有表示，不重新 embedding 全部文档/node/edge。允许研究 query-time 匹配、门控或重排，但要单独记录成本。
- 想尝试的是 **edge embedding**，不是仅换 node embedding。开放关系描述无需被固定语义类型完全覆盖；仍需来源、范围与是否可用于证据传播的约束。
- “每个 node 都产生 edge”的对照已澄清为：**每个合格 node 都召回候选，验证通过才建边**，不是强制每 node 至少一条边，也不是全体 node 两两枚举。
- 图→文或文→图可以因语义角色有不同解释。宽泛 RELATED 保持对称；明确 REFERENCES 的方向由原文指针决定，两者不要共用一个方向标签。
- 论文 bibliography 与图表原文指针都要与语义边分开，但它们也是不同问题。来源分流实现不代表完整书目身份解析/跨论文引用图已全部完成。
- 阅读顺序已有独立机制，但**不保证每个 node 都有 NEXT**；当前 single-document 实验是 page-local flows，不能声称形成贯穿所有页的完整链。

## 2. 问题台账：哪些已解决，哪些只是部分改善

“已修”限定在相应代码/回归样本范围，不表示所有材料上永不失败。

| 编号 | 问题与证据 | 已做处理 | 当前判断 |
| --- | --- | --- | --- |
| P01 | 正例已经在初选池，却因文章路由、每文章对预算或多通道融合被丢弃 | 逐层记录去向；修复 escape 配额重复；保护明确图表引用 | **工程缺陷已修，候选覆盖部分改善**；不是 verifier 修复 |
| P02 | 行视图把 logo、署名、页眉导航重新带回检索 | 统一 member eligibility，生成描述标为 retrieval-only | **已修当前实现**；21 条不合格视图被去除 |
| P03 | 96 个 escape 名额中 82 个已在常规候选里 | 只计真正新增 pair，固定总预算 | **已修**；真实新增 14→96，恢复 P01 样本 |
| P04 | 图号方向乱猜，`6.1` 被截成 `6`，caption 与正文语义方向混淆 | 唯一同文章原文 pointer→caption；保留层级编号、来源与方向 | **已修明确唯一匹配场景**；隐式图文关系仍需核验 |
| P05 | “同主题/同机构/图像相似”被误当同实体或同主张；N22 从遥感外观猜 EuroSAT | evidence/navigation 分层、原文身份锚点、review 出口 | **部分解决**：严格旧实验消掉 6 个已知 FP，但宽泛/all-node 组仍会复发 |
| P06 | 四种细关系类型容纳不了同对象、方法复用或主张对应 | 对称 RELATED、可选语义标签、开放描述实验 | **没有被“增加类型”解决**；新标签包真实集反而退化，见 E17 |
| P07 | 模型重新抄 quote 因换行/HTML/空白而失效，或串到另一端 | endpoint-owned 短 ID、raw span offset/hash、有限可审计修复 | **锚点工程明显改善**；语义解释仍可能不忠于 quote |
| P08 | Dolphin 换行、断词和短否定被截断；整段内容稀释局部语义 | 原文保留、readable view、物理行/句子/窗口对照，短 span 不静默删掉 | **保真工程已做，效果问题未解决**；行不是句子，逐行并非稳定更优 |
| P09 | 纯 text 漏掉不同父模型中的共享组件；放宽后又把 generic 类别错连 | text_scope、readable、局部 span 对齐及无图对照 | **未解决稳定平衡**；真实召回升、合成表现降，有 decision/reason 矛盾 |
| P10 | 公式 context 选了相邻其他公式、残句和大段无关背景 | 按单 node 收集同页唯一 NEXT 上的定义原文，不借邻居公式当解释 | **输入选择局部修复**；F015 恢复，F033 仍错；同页限制也漏跨页定义 |
| P11 | 公式字母不同/相同被当作含义不同/相同；子式被说成完整等价 | 结构与角色/单位/条件分开；新 30 合成+14真实对照 | **待验证**；保守 parser 仅 5/105 真实记录可解析，不能替代 embedding |
| P12 | 基础公式广泛出现，易形成高密度重复图 | 按文档计频率的共享结构索引、每 node 候选上限 | **CPU 原型已验证有界性**；真实语义收益与搜索效用未验证 |
| P13 | 原解析的 `reference` 角色被适配器统一变成 text | 保留精确 source_atom_ids 对应角色，bibliography/混合来源另审 | **当前适配与来源分流已修**；不意味着 187 条剩余边全部正确 |
| P14 | “no competing interests”被当“no financial support”；“obtained or waived”被强化为 obtained | 保留原文，分离纯声明；列入语义审计 | **未解决条件/否定/谓词忠实性** |
| P15 | edge 与 query 无关仍给目标页加分，挤掉相关页 | 保护 dense core、query gate、离线 edge embedding + 统一 BGE 对照 | **旧 boost 明确失败**；新 embedding 小收益尚不能归因于关系本身 |
| P16 | 单篇论文提示却要求拆独立文章；表格页给 standalone、标题漏归属；失败缓存永远复用 | 独立 single-work 修复提示、精确缺失 ID 反馈、保留失败历史 | **原因定位且代码已测，GPU smoke 待完成**；原校验器未放松 |
| P17 | GPU job 完成被当全实验完成，或本地 prepare 报告被当最终结果 | 完整度、invalid、输入 hash、阶段分开；本交接优先使用实际结果快照 | **报告规约已建立**；接手仍需查实时状态 |

## 3. 实验账本 A：早期建边设计（10/11–10/15）

这些实验语料、标签口径不同，不能沿时间线把所有数字拼成一条准确率提升曲线。

| 实验 | 设置与已核查结果 | 说明了什么 / 不能说明什么 | 来源 |
| --- | --- | --- | --- |
| A01 context v1 | 49 页、550 immutable nodes；0.6B＋BM25＋双向 BGE；192-token windows；RELATED_CONTEXT 均为未验证提案 | 相似度可生成候选，但家具/画面风格也高分；0.8 未校准，不能当语义概率。本次未重算其逐边统计 | [记录](experiments/own_corpus_edges/CONTEXT_EDGES.md) |
| A02 context v2 | 同材料；完成后有 14 个 source-reference、17 个模型接受 RELATED_CONTEXT；源审查找到 4 个明确错误、5 个宽泛主题链接 | eligibility、结构候选和原图核验有用，但 ACCEPT 不等于正确；25 个 ACCEPT 曾因锚点失败 | [v2](experiments/own_corpus_edges/CONTEXT_EDGES_V2.md)、[v3 对 v2 的复核](experiments/own_corpus_edges/CONTEXT_EDGES_V3.md) |
| A03 context v3 | 同 120-pair 队列；原文 ID + critic；去掉上面的 4 个错误及 5 个主题链接，但 6 个较可信旧链接仅留 3 个，且无跨文档边 | 严格 critic 降 FP 同时过度拒绝同事件的互补事实；同模型 critic 不是独立审查 | [v4 对 v3 的复核](experiments/own_corpus_edges/CONTEXT_EDGES_V4.md) |
| A04 context v4 | 同队列；允许同具体事件/项目的互补事实；双端字面身份，caption 几何去重；检测到 PAIR_01285 重复提取 | 类型和范围更清楚；别名与未命名目标覆盖仍保守。本次未重新审计其最终全量准确率 | [记录](experiments/own_corpus_edges/CONTEXT_EDGES_V4.md) |
| A05 独立事实抽取 | 80 假设/105 nodes；直接组 ACCEPT29、FORMAT_PENDING20；事实组 ACCEPT14、FACT_PENDING32、FORMAT_PENDING13，45/80 被抽取/协议挡住 | 未证明先抽事实更好；中间表示/协议会制造漏边，不能只数最后 ACCEPT | [复核](experiments/own_corpus_edges/FACT_GROUNDED_EDGES_V1_REVIEW.md) |
| A06 typed edge | 旧 6 个较可信例都恢复；旧 10 个漏例中 5 个产边、4 个未抽中、1 个格式失败；仍有错归因、重复 caption、机构混作事件 | 类型扩展提高覆盖但未保证精度；未被抽中不是模型拒绝；本文不把抽样审查冒充全图 precision | [复核](experiments/own_corpus_edges/TYPED_EDGES_V1_REVIEW.md) |
| A07 article bridge v1 | 44 decisions：ACCEPT11、REJECT1、UNCERTAIN21、FORMAT_PENDING11；111 model requests | 引用/事件绑定可用但覆盖和格式瓶颈大；无 query 检索评测 | [报告](output/article_bridge_pilot_v1_20261012/REPORT.md) |
| A08 bridge binding v2 | 3 canonical subjects；28 SUPPORTED bindings；57 derived 候选边，16 个开发样本可推导 | 绑定可扩展弱关联；derived 数量不是正确率，identity 还需核验 | [报告](output/article_bridge_binding_v2_20261012/REPORT.md) |
| A09 bridge identity v3 | CPU replay、0 新调用；一个 SUPPORTED→UNRESOLVED；cross edges 仍57，已发布开发例12/可推导16 | 修复一处身份误归并不自动解决候选路由损失 | [报告](output/article_bridge_identity_v3_20261012/REPORT.md) |
| A10 bridge routing v4 | global8 发布8个开发例、article8为12、round-robin8为15；protected8+4为16，预算同时提高50% | 保护基础召回与引导通道有帮助；增益不能脱离预算变化谈公平优越性 | [报告](output/article_bridge_routing_v4_20261012/REPORT.md) |
| A11 expanded v5 | 25 文档、49 页、550 nodes；528 eligible、296 unconfirmed；36 SUPPORTED、2 MENTION_ONLY bindings | 扩语料暴露归属和绑定覆盖限制；不是语义准确率结果 | [报告](output/article_bridge_expanded_v5_20261012/REPORT.md) |
| A12 subject gate 诊断 | 6 个方法对含3正例，3个全在即使 oracle EVENT/PROJECT gate 也无法通过的范围；独立方法核验接受3、拒绝3 | 同事件/项目不能作为所有方法对应的硬门槛；subject gate 与 method correspondence 的任务不同 | [报告](output/subject_gate_diagnostic_v1_20261014/REPORT.md) |
| A13 hierarchical retrieval 小试 | 6文章、174候选；方法正例1/3，与原自然召回1/3相同；难负例0/3；0 Qwen调用 | 过滤负候选不等于找回缺失正例；候选改进和 verifier 改进要分开 | [报告](output/hierarchical_edge_retrieval_v1_20261014/REPORT.md) |
| A14 旧方案 vs 四细类型 | 相同且标签一致37例：旧方案32/37，TP10/FN4/FP1；四类型29/37，TP6/FN8/FP0 | 更细的标签/表示/规则组合更保守，漏连增加；不能单独归因于“类型数量” | [报告](output/previous_edge_schemes_current_suite_v1_20261015/REPORT.md) |
| A15 多模态表示三臂 | 14对；description、raw、mixed 的 TP/FN 分别7/2、7/2、9/0，FP均0；reference raw/mixed各有2FP，description为0 | 原图＋描述能补信息，也会误识别引用；普通文本/模型相同的小开发对照 | [报告](output/split_taxonomy_modality_comparison_v1_20261015/REPORT.md) |
| A16 自然候选核验 | 48/48处理，19 INVALID、22 REJECT_UNCERTAIN、4 EXPLAINS、3 SUPPORTS；导出9条提案 | 输出协议/锚点明显影响可用性；处理完成不是语义判断全部有效 | [报告](output/retrieved_evidence_edges_pilot_v2_20261015/REPORT.md) |
| A17 全 node 图文诊断 | 40对，源审范围内20TP/19TN/0FP/0FN、1歧义；11条解释需缩窄/修正；CLAD节点条件8/8/7/8视觉链接 | node完整证据有帮助，但“决策正确”与“解释忠实”要分别评估；高度定向样本，非普遍零错误 | [记录](experiments/own_corpus_edges/TEXT_MULTIMODAL_DIAGNOSTIC_V2.md) |

## 4. 实验账本 B：候选召回、表示和 embedding

除注明外，以下 26 正例/27 难负例为旧开发候选覆盖口径；**2/27 是负例进入候选，不是最终误连 2 条**。

| 实验 | 设置 / 结果 | 结论与边界 | 来源 |
| --- | --- | --- | --- |
| B01 候选基线回放 | 分层1301候选：10/26；整node旧策略10152候选：7/26；同预算global cosine：6/26；初选41186对覆盖24/26 | 只增加候选总量未必找回重要pair；大量损失在筛选/配额阶段 | [报告](output/previous_edge_schemes_current_suite_v1_20261015/REPORT.md) |
| B02 whole/window/sentence | 同1301预算：9/26、10/26、9/26；P01句子余弦升高但仍落选；初选均24/26 | 局部表示改善特定匹配不等于最终候选改善；P01并未因512上限截断 | [实验](experiments/own_corpus_edges/RETRIEVAL_TEXT_VIEWS_20261016.md) |
| B03 generic BGE 候选重排 | baseline10/26；BGE4/26、负0/27；检索+BGE RRF9/26、负2/27 | 网页相关性模型不自动适合作node关系筛选；不能把减少负候选当全面改善 | [报告](output/edge_selector_reranker_v1_20261016/REPORT.md)、[对称版](output/edge_selector_reranker_symmetric_v1_20261016/REPORT.md) |
| B04 node级去重 | 初选 unique pool 41186→50872，最终仍10/26 | 增大初选覆盖机会没有消除后续预算瓶颈 | [报告](output/node_dedup_edge_retrieval_v1_20261016/REPORT.md) |
| B05 formula raw/context | 同1284预算：raw10/26→context11/26；初选24→25；负均2/27；找回P12 | context 对公式候选有局部增益；分母26不是26个公式pair，未验证出边 | [报告](output/formula_retrieval_v1_20261016/REPORT.md) |
| B06 line-aware 增补 | 保留2223旧views，增9816单行/4行views；同1301预算10→12/26，负均2/27；P04/05/07/17/26入，P09/10/21出 | 局部文字能增加召回，同时改变竞争；不可把物理行当新node或句子 | [实验](experiments/own_corpus_edges/LINE_AWARE_AND_ALL_NODE_MM_RESULTS_20261017.md) |
| B07 eligibility + escape + reference | 同1301预算，12→12→13→18/26，负始终2/27；恢复P01、P18–P22 | 名额重复和显式指针未受保护是确定的工程问题；候选修复没有调用Qwen | [报告](output/edge_candidate_allocation_repair_v2_20261017/REPORT.md) |
| B08 citation/context/连续段落通道 | 同1301预算18→18→19→20/26；新增P08/P23/P24、移除P26；负2/27、navigation2/2 | 具体漏例可恢复；这些额外通道仍是实验、默认未开启。“覆盖全部20个E”依赖当时另一轮固定pair标签，不能当新端到端成绩 | [实验](experiments/own_corpus_edges/REMAINING_EDGE_REPAIR_20261018.md) |

### B09 encoder 模型对照（10/20）

相同 source views/候选预算策略，仅换 dense encoder；实际去重后 pair 数 1278–1316，并非每臂恰好相等。新口径为 strong29 + weak2，与前面26正例不能直接拼接。

| Encoder | strong /29 | 全 links /31 | no-link 候选 /25 | 实际 pairs |
| --- | ---: | ---: | ---: | ---: |
| Qwen3-Embedding-8B | 16 | 16 | 1 | 1278 |
| Qwen3-Embedding-4B | 14 | 14 | 1 | 1302 |
| Qwen3-Embedding-0.6B | 14 | 14 | 1 | 1301 |
| GTE-Qwen2-1.5B-instruct | 14 | 14 | 1 | 1316 |
| GTE-large-en-v1.5 | 14 | 14 | 1 | 1281 |
| BGE-large-en-v1.5 | 12 | 12 | 1 | 1291 |
| mxbai-embed-large-v1 | 12 | 12 | 2 | 1315 |
| BGE-en-icl | 13 | 13 | 1 | 1291 |

所有模型 weak 均0/2。8B 在该开发候选比较中最好，并已成为默认 profile；这不证明全部问题来自 embedding，更不证明最终检索最佳。

来源：[8B/4B](output/edge_embedding_model_comparison_horeka_v1_20261020/REPORT.md)、[0.6B/GTE-Qwen](output/edge_embedding_model_comparison_v3_20261020/REPORT.md)、[英文模型](output/edge_embedding_english_models_v1_20261020/REPORT.md)、[BGE-en-icl](output/edge_embedding_english_large_v2_20261020/REPORT.md)。

### B10 Dolphin 三路召回（10/18）

相同 1301 预算：control 正例10/26、负候选2/27、navigation2/2；physical_line 为12/26、2/27、1/2；softwrap_bounded 为11/26、2/27、2/2；three_lane_rrf 为15/26、3/27、2/2。融合后仍漏11例：9例受 selector 配额影响、1例未进初选、1例受融合预算影响。**这只是候选覆盖，不是最终 edge 或搜索准确率**，不能与其他通道的改进直接相加。来源：[summary](output/dolphin_three_lane_retrieval_v2_20261018/summary.json)。

## 5. 实验账本 C：关系判断、纯文字和局部匹配

### C01 宽泛关系、全 node 图文与严格分层（10/17）

固定103对，其中58个人工复核的临时标签：31正、25负、2歧义。只在56个可评分标签上算二分类：

| verifier | TP | FN | TN | FP | precision | recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| broad mixed | 29 | 2 | 19 | 6 | .829 | .936 |
| all-node multimodal | 31 | 0 | 18 | 7 | .816 | 1.000 |
| strict layered | 28 | 3 | 25 | 0 | 1.000 | .903 |

全 node 图文找回P11/P26、修正N20，但新增N16/N26错误，N22依然从外观臆测 EuroSAT 身份。严格分层修正N04/N21/N22，但P01虽然接受，错误写成 CONTRASTS_WITH，理由其实是两者一致。全 node 图文另有3个大表格自然样本格式失败（420-token限制），不在上述58个标签中；分层组无此失败。reference 模型输出6个方向全为A_TO_B，其中至少5个实际是B_TO_A，应由原文指针确定方向。

结论：原图能补证据，也能诱发身份幻觉；严格分类减少错连但损失召回。不能把这批零FP宣传为普遍解决。来源：[图文与行实验](experiments/own_corpus_edges/LINE_AWARE_AND_ALL_NODE_MM_RESULTS_20261017.md)、[分层](experiments/own_corpus_edges/LAYERED_EDGE_VERIFIER_20261017.md)。

### C02 context 提示词反向否决与修复（10/20）

旧提示要求“若移除 endpoint evidence 会移除关系，则 NO_LINK”，逻辑写反：真实依赖端点的关系反而受罚。10/20已对 control/treatment 共同修复。旧P12加context后 E→NO 的结果因此有混杂，修正后两组均为E；不要拿旧运行当新提示的公平对照。[诊断目录](output/edge_context_failure_audit_20261020/)。

### C03 路由 context / text scope（10/20，5204553）

103对，四臂共236个唯一请求；31正、25负、2歧义，其余45没有评分标签。按内容为54 prose、43视觉/表格、6公式；“有截图”不等于内容是视觉。

| 臂 | useful TP /31 | useful FP /25 | invalid /103 |
| --- | ---: | ---: | ---: |
| control | 26 | 0 | 4 |
| multimodal_context | 27 | 0 | 4 |
| text_scope | 30 | 1 | 4 |
| text_readable | 30 | 2 | 3 |

text_scope 有一个负例 invalid，因此不能用25−1推导TN24，报告TN为23。放宽scope提高开发正例召回，同时引入错误；不支持所有节点默认打开。来源：[结果](../migration/horeka-edge-context-20261020/results/summary.json)。

### C04 新标注40对（10/21）

F009从E复核为U；评分排除F009/F037/F038/F039/F040，剩35对=11E+6N+18NO。保留原始标注，使用单独review版本，不覆盖历史。

| 臂 | strict correct /35 | strict E /11 | negative FP /18 |
| --- | ---: | ---: | ---: |
| control | 28 | 10 | 1 |
| multimodal_context | 28 | 10 | 1 |
| text_scope | 26 | 9 | 3 |
| text_readable | 26 | 9 | 3 |

context使F015从NAV降为NO；F013把指标介绍当直接证据，F033混淆MAPE/RMSE，F016理由过强。这批视觉4正6负的宽泛判断10/10，不等于视觉问题普遍解决。与旧集node不重叠，但文档重叠；标签是人工/助手复核的临时判断，多次调参后已是开发集。

来源：[复核结果](../migration/horeka-edge-fresh-20261021/reviewed_summary.json)、[原始数据](../data/benchmarks/evidence_edges_fresh_v1_20261021/)、[review标签](../data/benchmarks/evidence_edges_fresh_v1_20261021_review/reference.jsonl)。

### C05 真正纯 text：真实与合成分别测（10/22，5206010/5206005）

所有请求 `images=[]`。真实58对、56可评分（29正27负，F009/F038为U）；旧N13因文本为空在推理前排除，14个无标签自然候选未纳入。合成32对、30可评分（16正14负，S017/S031为U）。

| 集合 / 臂 | correct | TP | TN | FP | FN |
| --- | ---: | ---: | ---: | ---: | ---: |
| 真实 control | 45/56 | 18 | 27 | 0 | 11 |
| 真实 scope | 50/56 | 27 | 23 | 4 | 2 |
| 真实 readable | 50/56 | 26 | 24 | 3 | 3 |
| 真实 swapped control | 45/56 | 18 | 27 | 0 | 11 |
| 合成 control | 29/30 | 15 | 14 | 0 | 1 |
| 合成 scope | 25/30 | 13 | 12 | 2 | 3 |
| 合成 readable | 25/30 | 13 | 12 | 2 | 3 |
| 合成 swapped control | 28/30 | 14 | 14 | 0 | 2 |

真实旧39对宽泛正确32→36→36，新17对13→14→14；但新集strict正确11→9→10。相同19个新prose对（17可评分），此前带图control宽泛17/17、strict16/17，真正纯text降为13/17、11/17。不能据此泛化为“所有多模态优于文字”。

交换端点后真实 broad 有4/58翻转，exact一致51/58、broad一致54/58；合成31/32一致。S027/S028换行ELU全组正确；S029/S030的 `did\nnot` 已被模型读到，错在关系判准，不能归咎于没读回车。S012混淆W权重矩阵和土壤水分；S022 Adam/dropout出现理由否定但决策NAV。scope误接OLD_N26、N03、F020、F024；readable修F024但漏F007。正式出口会把缺identity的NAV送review，因此模型FP不等于最终图FP；严格identity也会拒绝一些有用导航。

这里的readable是完整句重排，**不是逐句检索**。来源：[完整结果](../migration/edge-text-results-20261022/RESULTS.md)。

### C06 真正行/句/窗口匹配（10/22，5206944）

8B views：窗口96/stride72、物理行、句子；选top2匹配并附相邻完整句。固定pair全部核验，不受其是否进入候选影响。真实82个端点、3321候选、预算200；合成54端点、1431候选、预算100，均不是全语料候选评测。

| view | 真实候选正 /29 | 负候选 /27 | 真实核验正确 /56 | TP / FN（FP均0） | 新集strict /17 | 合成核验 /30 |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| window | 20 | 1 | 51 | 24 / 5 | 14 | 27 |
| physical line | 19 | 1 | 49 | 22 / 7 | 15 | 29 |
| sentence | 22 | 1 | 50 | 23 / 6 | 14 | 27 |

真实view数130/811/374；合成候选正均16/16，负候选5/14、4/14、5/14，核验均FP0。所有输出有效。句子候选覆盖较好、窗口真实核验较好、物理行合成较好：**没有一种粒度稳定胜出**。更多views取最大值本身有机会偏差，需要控制预算。

最终来源：[远端取回报告](../migration/horeka-edge-granularity-20261022/results/report.json)。注意 `output/edge_granularity_v1_20261022/report.json` 是旧prepare零处理报告，不能用它评价最终结果。

### C07 宽泛关系＋语义标签（10/22，5207019）

90对已处理；真实58中51valid/7invalid（7个全在可评分56内），合成32全valid，其中一个U上abstain不计入30评分。固定相同pair/模型/window96证据，改了prompt、schema、validator，不能单独归因于标签数量。

| 集合 / 臂 | correct | TP | TN | FP | FN | invalid（评分内） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 真实 matched window baseline | 51/56 | 24 | 27 | 0 | 5 | 0 |
| 真实新标签 | 45/56 | 21 | 24 | 3 | 1 | 7 |
| 合成 baseline | 27/30 | 13 | 14 | 0 | 3 | 0 |
| 合成新标签 | 27/30 | 15 | 12 | 2 | 1 | 0 |

新标签输出计数：CONTRADICTION7、SHARED_COMPONENT_OR_ENTITY27、CLAIM_CORRESPONDENCE11、DEFINITION_APPLICATION1；没有独立标签gold，不能算类型准确率。83个valid的evidence_use为conflict7/navigation36/none40。

结论：真实下降，合成只是召回/错连交换；没有证据证明“多加关系类型”解决问题。invalid必须留在分母。最终来源：[本次取回report](../migration/edge_handoff_snapshot_20261027/semantic_relation/report.json)，原本地 `output/semantic_relation_trial_v1_20261022/report.json` 也是过期prepare报告。

## 6. 实验账本 D：公式与最终检索

### D01 公式 context 五臂（5213537，已完成）

14真实对（6旧+8fresh），70输出、58唯一请求，全valid，24分33秒。这些样本已用于调试，不再是独立测试。fresh8中4正4负：

| 臂 | fresh strict /8 | accepted FP /4负 | useful TP /4正 |
| --- | ---: | ---: | ---: |
| control | 5 | 1 | 4 |
| legacy context | 5 | 1 | 3 |
| selected context | 6 | 1 | 4 |
| math policy | 6 | 1 | 4 |
| combined | 5 | 2 | 4 |

selected/math/combined找回F015；F033 MAPE↔RMSE全部仍错；F013错误把跨文档“as follows”当直接互补；combined新增F034投影矩阵与Hadamard mask错连。F016即使接受标签可用，理由仍忽略T/V区别，源图B确实缺T，不能当OCR错误擅自补写。

context现在只从同页、唯一双向NEXT、最多2个相邻节点中选原文定义，不拿邻居公式冒充解释；保留source offsets。F015 A恢复3段846字符（HY006/HY010），B的where原本就在端点内。F033去掉邻近MAE和跨页背景，但同页限制也漏掉潜在有用的跨页y定义。结论是**局部输入修复有效，扩大上下文不稳定，公式语义问题未解决**。

来源：[实际五臂可视化](output/formula_context_trial_results_20261027/index.html)、[取回结果](../migration/horeka-formula-context-repair-20261026/results_5213537_20261027/formula_context_repair_v1_20261026/)、[诊断记录](experiments/own_corpus_edges/FORMULA_CONTEXT_DIAGNOSIS_20261026.md)。旧 `formula_context_diagnosis_20261026` 页面是历史诊断，不是五臂最终结果。

### D02 公式结构、变量角色与常见模板（5215293，等待GPU）

14真实+30合成，两臂88输出计划。分别判断结构对应、变量角色/单位/条件、语义范围、是否同一研究主张，并给开放描述与source IDs。这些诊断维度不是重新强制生产edge固定分类。

CPU保守parser在105真实记录仅解析5个、4个bucket、0跨文档提案；55个unknown涉及尾部公式编号。合成30对中22可解析、22结构判断正确、8unknown，不能把22/22解释成全量完美。1000node/100伪文档的常见公式压力测试，将990000个跨文档有向可能pair限制为4000提案，只证明候选有界，未验证语义。

处理原则：可自由重命名时AB/BA可同模板，但固定矩阵角色时不意味着交换律；x+x与u+v不是同一变量约束；sqrt(x²)=x需要非负条件；E=mc²与y=ax²可同形而非同义。基础公式高频并不意味着错误，需要分开记录“关系可信度”和“区分度/搜索价值”。保留embedding召回，parser unknown不可直接判NO。

来源：[设计与提交状态](experiments/own_corpus_edges/FORMULA_STRUCTURE_SEMANTICS_20261027.md)、[runner](scripts/run_formula_semantics_trial.py)、[结构索引](scripts/formula_structure_index.py)。暂无GPU效果结论。

### D03 来源角色修复（10/23）

213旧边重新分流：187 semantic proposals、17 reference_review、9 administrative_review。适配器曾把reference统一变成text；按精确source_atom_ids恢复原角色。不是简单删除26条，也不表示剩187条全部正确。same-topic、否定/条件、机构/研究身份等仍需核验。角色过滤后，旧query候选图与baseline不同的query由2/24降至1/24。

来源：[报告](output/edge_role_repaired_v1_20261023/REPORT.md)、[逐边复核](output/edge_repair_review_20261023/index.html)。

### D04 旧edge boost：搜索质量下降（10/22）

24queries、518页、1088候选、213RELATED，同一轮no-edge与edge：

| 指标（%） | no edge | edge boost |
| --- | ---: | ---: |
| Recall@3 | 75.00 | 64.58 |
| Recall@5 | 83.33 | 83.33 |
| Recall@10 | 89.58 | 89.58 |
| RecallAll@5 | 66.67 | 66.67 |
| nDCG@5 | 72.14 | 68.78 |
| mAP@5 | 63.82 | 59.97 |
| mAP@10 | 65.39 | 61.54 |
| 全库mAP（518） | 66.76 | 62.90 |

逐query AP@5：1胜5负18平，Recall@5/@10每query均未变。30条接受路径涉及11queries；另8同页、5低query相似度、2预算拒绝。LighTDiff/MIRNet gold位次[1,2]→[3,4]，GTN remission [2,3]→[4,5]；mutation [2]→[1]。问题主要是重排挤压，而非top5完全找不到gold。

AP@k分母用全部gold页；报告按6类、每类4query宏平均。同轮baseline与更早冻结分数最大差.0123518，原因未确立，勿跨轮精确归因。结果证明该boost配置失败，不能证明任何edge检索都失败。来源：[完整结果及路径](../migration/vldocir-edge-20261022/results/search/RESULTS.md)。

### D05 相同query/库的 ColNomic 比较（10/23）

24条query文本、518page IDs、图像hash与gold一致。

| 方法（%） | Recall@5 | nDCG@5 | RecallAll@5 | mAP@5 |
| --- | ---: | ---: | ---: | ---: |
| ColNomic-7B | 79.17 | 71.28 | 66.67 | 65.83 |
| hybrid no-edge | 83.33 | 72.14 | 66.67 | 63.82 |
| hybrid edge boost | 83.33 | 68.78 | 66.67 | 59.97 |

hybrid对ColNomic AP@5为9胜6负9平：Recall更高但AP不更好。这里只是本地ColNomic基础复现，不是官方ensemble/context/rerank或官方全库成绩。来源：[匹配比较](output/vldocir_matched_comparison_20261023/REPORT.md)。

### D06 query edge gate（5209174）

作业COMPLETED 0:0、21分29秒，只完成gate阶段。35条中16valid、19invalid；valid为9UNSUPPORTED、3PARTIAL、2DIRECT、2BRIDGE。19失败重试raw完全相同，35/35不是准确率。输入来源32semantic/2reference/1administrative。

7个允许目标都已在dense Top10，24个query的gate候选集与dense Top20完全相同；相同固定页BGE及tie-break下，代码上必然同排名。955个BGE pair未处理，完整status=false，不能宣称已有新搜索成绩。后续BGE权重已在新实验准备前修好，旧“缺权重”说明不是永久现状。

来源：[复核](output/query_edge_gate_review_20261025/summary.json)、[可视化](output/query_edge_gate_review_20261025/index.html)、[取回说明](../migration/horeka-query-edge-repair-20261023/README.md)。

### D07 离线edge embedding五臂（5211803，最终报告已取回）

固定187条G0语义候选边、24queries/518pages，不是重新跑node/edge生成。A_node、B_current、C_pair、D_relation、E_endpoint；离线关系描述不输入query或qrels。dense core10、候选页预算20、最多扫描100；8B pair双序AB/BA，描述失败fallback到pair text保留边，endpoint192tokens/description64。

BGE对同一页使用相同的两个冻结0.6B命中窗口，取最大分；新edge通道8B，不能说全系统baseline都已经8B。1535个rerank pairs已完成。

| 臂（%） | Recall@3 | Recall@5 | nDCG@5 | RecallAll@5 | mAP@5 | Recall@10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A_node | 79.17 | 81.25 | 78.22 | 70.83 | 73.06 | 95.83 |
| B_current | 79.17 | 81.25 | 78.22 | 70.83 | 73.06 | 95.83 |
| C_pair | 79.17 | 83.33 | 79.21 | 70.83 | 73.47 | 95.83 |
| D_relation | 79.17 | 83.33 | 79.21 | 70.83 | 73.47 | 95.83 |
| E_endpoint | 79.17 | 83.33 | 79.21 | 70.83 | 73.47 | 95.83 |

相对A，C/D/E各自Recall@5 +2.0833百分点、mAP@5 +0.4167百分点、nDCG@5 +0.9883百分点；AP@5均1胜0负23平。C/D/E均24个query候选集发生变化，B为0。

**有小幅最终指标提升，但不能归功于edge关系描述：endpoint对照E得到同样成绩。** 还需逐query路径、描述失败及语义质量审计；本次下载并核对报告hash，不等于独立重跑全评估。不可与D04不同重排配置的分数直接宣称净提升，也不是官方全集成绩。此前5211791只跑10条edge smoke，证明流程执行，不提供检索指标。

来源：[最终报告](../migration/edge_handoff_snapshot_20261027/edge_embedding/REPORT.md)、[精确指标](../migration/edge_handoff_snapshot_20261027/edge_embedding/results.json)、[完成状态](../migration/edge_handoff_snapshot_20261027/edge_embedding/status.json)。

### D08 sparse vs 每node候选：完整建边对照（尚无最终搜索结果）

准备5212509已完成37分40秒。当前冻结试验是24queries/518pages/7291缓存nodes，**仍不是官方全集**。对照现有稀疏候选与每个eligible node召回top1再取union，使用同一verifier，再比较node、reading、sparse、all-node及ColNomic+BGE。复用node缓存，不伪称从文件重新跑node generation。

构图数组5212510的16分片现已全部FAILED，评估5212511已取消。已逐项核查的前7分片各387语义pair已处理，但invalid分别2/4/2/3/5/2/5；其他分片要分别查checkpoint，不能因为同类失败就假定语义结果全部完整。

前7文档发现25个阅读membership失败页、50尝试，其中33次是single-work应保留一个article group；另有coverage/title约束问题。失败缓存会被原调用复用，原样重跑不能修复。新独立修复保留失败历史，只复用精确有效缓存，采用single-work提示、缺失ID反馈，不放松validator。两页smoke 5215323仍排队；通过格式也不代表阅读顺序语义准确。

来源：[实验设计](experiments/vldocir/PIPELINE_COMPARISON_20261025.md)、[冻结部署记录](../migration/horeka-vldocir-pipeline-compare-20261025/SUBMISSION.md)、[修复脚本](scripts/repair_vldocir_single_work_reading.py)。部署记录的旧submitted文字不优先于最新调度快照。

## 7. 当前任务状态、环境与恢复顺序

2026-10-27 深夜本次实时查询：公式5215293与阅读修复5215323均PENDING，reason=Priority；调度器预计**2026-10-28 22:50、23:10，德国时间**开始。这只是预测，不是保证，且没有后台每小时监控。

| Job | 当前状态 | 能否已有最终结论 |
| --- | --- | --- |
| 5207019_0/_1 | COMPLETED | 语义类型扩展结果见C07 |
| 5209174 | COMPLETED，gate-only | 35条处理完成但全搜索没跑完，见D06 |
| 5211791 | COMPLETED | 10-edge smoke，仅流程检查 |
| 5211803 | COMPLETED，55:32 | edge embedding指标见D07 |
| 5212509 | COMPLETED，37:40 | 构图准备，不是全实验完成 |
| 5212510_0…15 | 全FAILED，1:0 | 已定位阅读阶段故障，缓存可部分复用 |
| 5212511 | CANCELLED，未开始 | 旧依赖评估不会再产结果 |
| 5213537 | COMPLETED，24:33 | 公式context结果见D01 |
| 5215293 | PENDING | 新公式语义对照未有GPU结果 |
| 5215323 | PENDING | 两页阅读修复未有GPU结果 |

### 7.1 QoS与提交恢复

dev QoS本次核实限制MaxSubmitJobsPU=4、MaxJobsPU=1。首次报QOSMaxSubmitJobPerUserLimit发生在预占续跑提交时，主公式job实际上已提交；打印顺序曾掩盖这个事实。已经仅取消确定无法运行的旧pending评估5212511，用户held任务5170719_1/_2没有动。不要看到提交错误就重复提交主任务。

使用 [recover_qos_submit.sh](../migration/horeka-formula-semantics-20261027/recover_qos_submit.sh)：验证冻结部署、入口/出口都打印已有job、优先缺失阅读smoke；主任务queued/running时不抢占续跑名额。仅明确终态且checkpoint核实未完成时允许一次续跑。这是按需工具，不是常驻守护。恢复逻辑8测试及原提交逻辑3测试通过；不意味着GPU实验通过。原冻结bundle未改。[取消审计](../migration/horeka-formula-semantics-20261027/cancelled_stale_evaluate_5212511.json)。

### 7.2 机器与文件位置

- 原项目共享根：`/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project`，本地账号`ka_dv3352`，本次会话hk2n1989。
- Horeka账号：**dv3352，没有ka_**；远端根：`/hkfs/home/project/hk-project-p0025545/dv3352/Project`。直接在Horeka找本地`/hfs2`会报不存在。
- 本次可用SSH control socket：`/tmp/evidencenet-formula-semantics-510795`。socket是主机本地的临时状态，换主机或过期后要重新检查；不要反复让用户认证已有可复用连接。
- 新公式远端目录：`remote_runs/formula-semantics-20261027/EvidenceNet/output/formula_structure_semantics_v1_20261027`。
- 阅读smoke输出：同包`EvidenceNet/output/single_work_reading_smoke_20261027/`，页ID为`PAGE_da445026dbecf823`、`PAGE_11d5f79a1fcbbb80`。
- 本次已取回最终语义/embedding报告：[快照目录](../migration/edge_handoff_snapshot_20261027/)。[remote_audit.json](../migration/edge_handoff_snapshot_20261027/remote_audit.json)记录UTC时间、远端原路径及4文件SHA256，均核对一致。
- Python环境：项目根`.venv-magazine-exp1/bin/python`，常用`PYTHONPATH=EvidenceNet:EvidenceNet/scripts`。
- 密码/动态验证码只在用户终端输入，不写入文档、代码、日志或聊天。

### 7.3 接手后下一步

1. 先查5215293/5215323状态和checkpoint；不要重复提交、不要等已取消5212511。
2. 公式完成后分别报告14真实与30合成、每臂valid/invalid、误连/漏连、结构与语义范围错误。特别查看F033、F034、角色固定/重命名与常见模板负例。
3. 阅读smoke完成后复核两页完整归属和NEXT顺序；若通过，再恢复各分片缺失阅读结果，复用精确有效语义缓存。不要盲目原样重跑16个worker。
4. 所有分片节点覆盖、语义有效性、阅读结构完整度验收后，才提交替代评估；候选规模/无效输出也要入报告。
5. D07逐query审计唯一AP提升来自何页/何路径，以及C/D/E为何同分；以endpoint对照判断是否真有“关系”增益。
6. 对纯text保留保守窗口control，scope/readable/更多类型都不可直接升级默认；建立新的文档隔离测试集，保留旧集作开发回归。
7. 公式结构索引继续作为补充候选、unknown回退embedding；先提高带编号真实公式解析覆盖，再讨论扩大构图。

## 8. 必须保留的案例记忆

| Case | 已知问题与解释边界 |
| --- | --- |
| P01 | GraphWaveNet训练后结构固定；候选配额已修，但接受后仍可能错标“对比”；候选与语义类型分开验收 |
| P02/P09/P10 | 不同父模型共享具体方法可构成有用导航，不能强求同一父模型/事件 |
| P08 | DCRNN与[8]的局部原文绑定不是完整跨论文书目解析 |
| P11/P12 | 历史标签随rubric调整；P12共享L1可有用，但不代表同一完整目标/模型；旧context反向veto有混杂 |
| P18–P22 / P23 / P24 | 显式图号候选保护、后续node指针与相邻机制分别补召回；相邻不是自动有语义关系 |
| P26 | generic AI定义对stroke项目：宽泛positive与严格NO口径不一致，不能不说明标签变化就算改进 |
| N16 / N22 | CERN机构/月相同不等于同事件；卫星图外观不能证明EuroSAT身份 |
| F009 | E→U，评分排除，保留原始与review两版；新40例最终排除5例，不是旧口径4例 |
| F006 | landuse/landcover共享定义在整段纯text仍漏；若宣称粒度实验修复，须先查逐例预测 |
| F020/F024 | 部分文字预测理由与决策相反；不能只看解释“听起来合理” |
| F013 | 指标定义与别处as-follows不构成跨文档直接指针 |
| F015 | 选择性原文定义context可恢复，宽泛背景反而稀释 |
| F016 | 字母/下标差异需按原图与角色解释，不能把源公式差异自动“纠错” |
| F033 | MAPE与RMSE同属误差指标但不等价，所有已完成公式context臂仍误接 |
| F034 | projection与Hadamard masking都可描述为“组合”，过度抽象会错连 |
| S012/S022/S027–S030 | 同字母不同角色、理由/决策矛盾、换行否定与关系判准错误要分别诊断 |

Nxx、Fxx、Sxx来自不同数据集，旧Nxx还常有OLD_前缀；不要仅凭编号合并记录。

## 9. 评估口径与防止再次丢失记忆

- **候选recall ≠ verifier recall ≠ 导出edge precision ≠ 最终检索收益。** 每次说明测的是哪一级。
- E/N/NO/U、宽泛useful与strict类型不是同一目标；不能混合不同标签版本的分母。invalid不丢弃，单列并留在应评分分母。
- 图文“prose node”与真正`images=[]`纯文字不同；caption、原图、上下文是否输入要查实际请求。
- 相同query、page IDs、图片hash、gold、候选预算、reranker窗口与tie-break，才适合公平对照。指标还须记录AP分母与宏平均方式。
- 当前所有24query/518页成绩都是小规模复用试验，不是VL-DocIR官方全集。要官方评测须完整官方split/库/协议，不能用Hugging Face仓库名替代证明。
- 已反复看过的旧/新手标样本都视为开发材料；合成集验证预设失败模式，不能替代真实未见文档测试。
- 解释忠实性、关系标签正确性、来源锚点有效性与可传播性分别记录。模型说“same”不能当作已验证身份。
- 结果优先级：完整实际预测/最终报告＋输入hash > 已取回结果快照 > 历史总结 > 提交脚本/prepare报告。多个报告冲突时追溯来源，不自动选择最好看的数字。
- 下次更新本文时记录日期、job、输入/标签版本、模型/prompt、样本数、valid/invalid、指标、具体修复/退化案例、是否已接入默认pipeline；失败实验也保留。

可直接看的页面：[早期漏/错边](output/edge_failure_examples_20261016/index.html)、[真实纯text](output/real_text_edges_v1_20261022/index.html)、[合成纯text](output/synthetic_text_edges_v1_20261022/index.html)、[来源与错边复核](output/edge_repair_review_20261023/index.html)、[query gate](output/query_edge_gate_review_20261025/index.html)、[公式五臂](output/formula_context_trial_results_20261027/index.html)。尚未完成的公式结构页面若存在，仅是输入/计划预览，不能当结果。


## 10. 2026-10-28 后续诊断：自由关系的效果归因修正

本次继续取回逐例输出后发现，C07真实51/56→45/56的变化包含：5个baseline正确正例因字面quote不匹配变invalid、新增3FP、找回2正例，净−6。7个invalid原始输出全部RELATED且都是gold正例；主要为省略号拼接、断词规范化或移除公式标记，不是7次拒绝语义关系。不能将总分下降全部归因于关系表达能力。N07/N08对不同数据集共享Sentinel-2的判断还涉及新旧“有用边”定义差异；N16无依据合并CERN事件是实质错连。详见[语义逐例诊断](../migration/edge_handoff_snapshot_20261027/semantic_relation/DIAGNOSTIC_20261028.md)。

D07开放描述187条全格式有效（186 DESCRIBED/1 INSUFFICIENT），但176条在实际encoding时被裁至64 tokens，存在共同点保留、差异限制被截掉的问题，也有无依据合并same study。D相对C改变19/24个候选集合，但C/D/E最终top5逐页顺序对所有24query完全相同：此实验关系只用于候选，不参与最终BGE评分。图仍固定旧G0，只覆盖184/518页。结论应为“尚无开放描述额外收益证据”，不是“自由edge已被证明更差”。详见[描述与路径诊断](../migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/DIAGNOSTIC_20261028.md)。

## 11. 2026-10-28：描述约束已实现，漏召回已逐例审计

新增独立bounded-v2 profile：A/B事实分开、具体连接与limitations必填、来源ID不抄quote；完整AB/BA输入≤512且关系不截断，超长有限重写，失败/INSUFFICIENT使D逐字等于C。加模型/prompt/预测完整性校验，28项测试通过。已提交独立Horeka任务**5215455**（accelerated，当前PENDING，暂无开始估计）；187边/24queries/518页，其余控制不变。语义事实正确性仍需审计，不把格式有效当正确。见[实现与实验说明](experiments/vldocir/BOUNDED_EDGE_DESCRIPTIONS_20261028.md)。

D组top5漏8个gold页、涉及7queries，其中6个已入20候选但排6–9，2个不在G0且没入候选。实际问题包含错误窗口（Graf看不到表格、implant只给标题）、截断图描述、复合query未分别召回，以及官方证据页/跨页图定位疑点。Warrior Falls p7、mA3 p6、implant p3、NGC3256 p6须人工复核；源文件和原图hash核对表明不是本地统一页码偏移。保留official gold和分数，不直接改标注。40个query–gold page关联命中数：A top5/10/20=31/38/39，C/D/E=32/38/38（不能与宏平均Recall百分比混用）。见[8例原图可视化](../migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/missing_gold_audit.html)及[完整审计](../migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/MISSING_GOLD_AUDIT_20261028.md)。

## 12. 2026-10-28：六个候选内低排名页的进一步诊断

不能把六个官方gold页全部当真实答案排序失败：implant所问1.2cm实际p4已rank1，mA3所问20个haplotypes实际p7已rank1（另gold p9 rank2），NGC3256真正数值所在p2/p11已rank1/2；官方标注页疑点继续单列。

真实输入问题进一步定位：Federer页16个窗口中直接总结连续两年赢Wimbledon/US Open的7187页内dense排第3，被top2裁掉；Graf页44窗口中明确奥运金铜牌的7293排第8，表格年份7283排第25，top2选到其他赛事段落；phonon页仅5个窗口，Figure6的描述被截断且无后续窗口，仅扩大K无法恢复。优先在固定候选内改完整证据选择与图/表内容，再独立测子问题/跨页证据贡献重排；不要用gold页加分。

另做唯一预设CPU对照：固定D的20候选，dense全排名与BGE候选排名等权RRF k=60，无调参，排序后才用gold评分。Recall@5 83.33→81.25，mAP@5 73.47→69.24，AP5为5胜6负13平。Graf7→4、phonon6→5，但Federer8→11并有其他退化，因此不部署简单融合。[回放记录](../migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/rrf60_fixed_candidates_diagnostic.json)。这是已检查开发query的诊断，不是新holdout成绩。
