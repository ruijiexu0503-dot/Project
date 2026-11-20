# 四组端到端比较：证据定位、噪声和输入成本

状态：用户于2026-10-29明确要求将精确定位、低噪声、少token设为主目标。
本文是待实现/冻结的实验协议，不代表四组answer LLM已运行或取得新成绩。

## 1. 目标与四组

目标是在证据充分、答案及引用正确的前提下，减少送入LLM的无关内容和在线成本。
不将“候选页找到了”“给的token少”或“生成了一句短摘要”单独当成成功。

| 组 | 索引/导航 | 原始证据可见性 |
| --- | --- | --- |
| A 无EvidenceNode/无edge | 原始parser块或固定窗口 | 保留原文、表格、图注、原图定位；不得偷用EvidenceNode生成的片段 |
| B 有EvidenceNode/无edge | 语义节点检索 | 与A相同原始模态，增加节点组织，不增加无关信息通道 |
| C 有EvidenceNode/有edge | B加预先冻结的图导航 | 原文anchor与必要上下文真正进入reader，不只返回page ID |
| D 论文模型同库对照 | ColNomic基础原图检索 | 候选页后接同等来源、同预算的片段/区域定位器，不强制整页输入 |

D是本地同query/同库ColNomic加共同reader，不是作者官方Ctx/Ensemble/回答系统。
作者官方388548页检索结果单列参考；本地518页不能直接声称优于官方全集。
无node的传统page_windows结果可附录保留；主要node消融应保持视觉信息一致。

## 2. 检索单位与最终输入单位分开

- 页面：官方检索评测单位，照常报告Recall/nDCG/AP及RecallAll。
- reader证据：可追溯的完整句、段落、表格行列片段、公式及变量定义、图像区域及必要caption。
- 先定位再打包；主实验不默认把Top5整页全文/图像全部塞给LLM。
- 整页输入可保留为单独成本/效果基线，不可故意只给D整页而允许A/B/C精确定位。
- “最小充分”不是“最短”：不得丢否定、主体/年份、人群、单位、表头、图例、公式条件或代词指代。
- 当前局部证据不足时允许补充相邻段/图表区域；扩展和无法在预算内保持完整的情况必须记录。
- 不在句子/单词中间硬截断，不以生成摘要替代所有原文。生成描述只作为导航提示。

## 3. 同预算质量与质量—成本曲线

首轮固定query split策略（全部关闭）；未来开启时对四组一致，不能只给C额外子query。
冻结query、语料revision、gold、answer模型/版本、prompt、采样和输出上限。

建议预注册证据文本预算：512 / 1024 / 2048 / 4096 tokens。
预算包括实际传入的证据文本、标题/范围、短引用标签及关系导航说明；不把metadata免费排除。
固定system/query/prompt模板另列，并报告完整序列化输入的真实总token数。
不强制填满预算；允许因证据不充分而弃答，弃答及失败仍计入完整query分母。

多模态单独锁定图像输入策略：建议最多2个区域，同一processor与像素/patch限制；
最终具体像素/visual-token设置须按所选模型实测后冻结，不能假装图片数等于token数。
报告实际视觉token及处理后尺寸；不能获得真实视觉token时标记unknown，提供像素/patch量而非填0。
比较同一文本与图像预算下的效果，并给出多个预算点的质量—成本关系。

## 4. 必须区分三种token成本

1. `reader_input`：最终回答LLM实际收到的所有文本、特殊标记、图像token；按该模型tokenizer/processor或API usage计算。
2. `online_total`：拆query、选择路径、定位/验证片段、回答等全部在线LLM输入/输出；同时记录调用数与时延。
3. `offline_total`：解析、node/edge生成、embedding的成本，独立报告，不能混进单次query也不能隐去。

BGE的512-token窗口或0.6B tokenizer计数不能代替最终answer模型成本。
报告每query、平均、中位数及P95；成本低但质量下降不能宣称全面改进。

## 5. 评测指标及标注边界

主报告同时包含：

- 官方页面检索：Recall@5、nDCG@5、mAP@5、RecallAll@5及候选覆盖。
- 答案正确性、必要信息完整性、可核查引用支持率、弃答率。
- 实际进入reader的证据充分性：问题所需的各部分是否真的在输入里，而非只在候选页里。
- reader输入tokens、视觉tokens/patch、片段数、重复原文量、在线总成本。
- edge独有的新增正确证据、anchor进入reader比例、沿边找到却被打包丢弃的比例。

页面gold不标注整页每个span的相关性，不能直接据此计算噪声率。
官方element/bbox可作覆盖定位线索，但不等于完整且无误的语义必要证据标注。
人工独立复核的源片段区分：直接回答证据 / 必要解释上下文 / 无关或重复噪声 / 尚未判定。
噪声token比例只在已复核源文本上统计，并同时公开复核覆盖率和unknown比例；
没有bbox/span真值时不得编造定位precision。重复与无关分别记录，不把必要定义当noise。
答案评分、gold、复核意见仅用于事后评测，不进入选择器或边生成。
已有24题仅作开发回归；最终泛化结论需要另冻结的未看过query。

## 6. reader输入与审计sidecar分离

reader只接收紧凑且统一格式的证据，例如短标签[E1]、必要主体/年份和原文。
完整UUID、hash、长JSON和全部搜索路径放sidecar，不无差别塞入prompt。
sidecar必须能恢复实际reader输入：

- query/arm/budget，模型/tokenizer/processor身份，完整序列化输入hash及实际token计数；
- 每条片段的doc/page、可选node、source span offsets或bbox、原始内容hash；
- 哪些文字是原文、哪些是生成的导航说明；后者不是独立事实证据；
- 选择/去重/舍弃原因、必要上下文扩展、超预算或未覆盖的事项；
- 对C记录seed→edge→target→具体span/crop，并检查所引用anchor是否实际进入最终输入；
- 最终答案使用的引用ID与原文支持情况。

## 7. 当前实现缺口（2026-10-29）

`run_vldocir_evidence_rerank.py`只有固定D候选的2/8片段BGE实验；其token计数来自BGE，
没有四组answer reader或reader-token成本测量。它可作为定位器开发参考，不能冒充本协议已实现。
`run_vldocir_edge_embedding.py`的page候选+两窗BGE也不是完整图使用/回答评测。
本协议下一步需要实现统一证据打包与预算计量，再接同一回答LLM；尚未提交该四组GPU任务。
