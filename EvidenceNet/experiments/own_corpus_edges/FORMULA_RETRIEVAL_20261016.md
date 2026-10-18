# 公式专用检索：原公式与可追溯原文上下文

2026-10-16。CPU任务 **81022**，32核、48GB、45分钟上限，不占GPU，不调用生成模型。
输出：`EvidenceNet/output/formula_retrieval_v1_20261016/`。提交时未有结果。

## 问题

P12的STTN公式节点成员有`role=equ`，且eligible=true；但普通文字过滤后只剩
`quad`，没有达到4词门槛，未生成检索视图。原始公式没有丢失，丢的是检索入口。
本轮保持evidence node、普通文字/表格/视觉检索表示及候选融合规则，单独改变公式表示。

## 三组对照

| 组 | 公式处理 | 视图数 | 可检索节点数 |
| --- | --- | ---: | ---: |
| baseline | 旧窗口规则 | 2223 | 1204 |
| formula_raw | 独立公式类型、原LaTeX、确定性数学记号标签 | 2243 | 1235 |
| formula_context | formula_raw + 有来源的原文上下文 | 2389 | 1235 |

语料共有105个合格公式成员、103个含公式节点；69个公式成员找到至少一段上下文，
共146个context视图。baseline的formulas=0统计只表示未运行专用处理，不表示原语料没有公式。
可检索节点增加31个是恢复短公式表示的预期变化，不能宣称三组节点覆盖完全相同；
raw与context节点覆盖一致，用于分离上下文作用。

## 规则

1. 以`role=equ`或formula/equation类型识别，跳过普通文字最低词数门槛。
2. 原LaTeX与source member、offset完整保留，标记`evidence_kind=FORMULA`。
3. 仅在检索展示中清理OCR重复波浪号/空白。L1范数、求和、积分等记号由正则识别；
   不猜变量含义、不把相同记号当作语义等价，也不直接以公式编号或记号建立跨文章边。
4. 使用已知同文章、同页、唯一NEXT邻接，加引入句/where解释的语言线索提取上下文。
   NEXT来自parser/source导航，并非已确认阅读语义，故上下文只是检索辅助，需来源审核。
5. 明确Eq./Equation编号引用只有在同文章编号唯一时才能绑定；该引用允许跨页，
   邻接上下文不允许跨页。未知文章归属不借用外部上下文。
6. 上下文单独记录node_id/member_id/offset/原文，不替代公式原文或两端证据。
   每段context形成一个视图，避免大量邻近正文再次稀释公式。

P12实际绑定：前句“Mean absolute loss are adopted to train the model.”，
后句“where ... is the groundtruth traffic speeds.”；两段均在原文中，不是模型描述。

## 评估与限制

CPU float32 Qwen3-Embedding-0.6B，仅作embedding；普通窗口复用冻结向量，新公式视图统一编码。
候选生成沿用原多通道RRF、文章路由和预算。报告原始默认预算结果以及同数量K候选前缀，
K=min(1301,三组原生候选数)。所有候选完成后才读取开发标签。
检查26个核心正例、27个难负例的候选覆盖；2个导航正例和3个不确定案例单独记录。
每例保留最佳视图、余弦和初始池RRF排名；候选不是语义边，未测query检索收益。

13项相关测试通过：短公式保留、记号识别、原文offset、上下文归属、跨文章隔离、
唯一公式编号、歧义邻接、未知文章限制、非公式表示不变等。准备后逐一核对105个
公式成员和所有上下文span均来自冻结原文。输入、模型和代码SHA256已保存。

实现：`scripts/formula_retrieval_views.py`与`scripts/run_formula_retrieval_comparison.py`。
运行：`current/slurm/traffic_relevance/formula_retrieval_cpu.sbatch`。
当前仅shadow对照，未覆盖旧实验或生产图，尚未把公式上下文传给语义核验器。
