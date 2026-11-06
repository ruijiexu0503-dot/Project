# EvidenceNet 阶段汇报：Copilot 可视化实施任务书

> 日期：2026-11-06  
> 仓库：ruijiexu0503-dot/Project；工作分支：feature/evidence-edges（以本地 Git 为准）  
> 目标：做一套 **可现场演示、能逐个展开 24 Query 的研究进度汇报**。不是重新做 Retrieval / 建图。  
> 优先级：**交互式 Query Explorer > 三组检索对照 > Edge/模型与阶段成果 > 静态汇报材料**。  
> 状态：这是**待实现需求**，不是声称可视化已完成。具体数值先和本地最终产物核对。

## 0. 开始之前：先盘点数据，不要直接臆造图

1. 执行 git status、确认分支及最新脚本；**本地 Copilot 的新改动可能尚未 push，GitHub 远端不保证最新**。以本地真实产物为准。
2. 读取下方数据源；对于不存在、字段不齐、版本不匹配的数据，写入 DATA_INVENTORY.md，明确标记 unavailable，不得用假数据填图。
3. **本轮只做报告/可视化**。不得再调用 Qwen embedding、reranker、LLM、GPU/CPU Slurm Retrieval，不修改 frozen Node/Edge/Query、旧实验结果或生产 Navigation。
4. 先做一份 canonical join/aggregation 数据层（用 question_id、node_id、edge_id、direction、arm 对齐），图表必须只读这层。
5. 所有可视化显示数据版本、样本量、预算、评价定义及证据来源；相互不具可比性的实验不得放在同一个“模型胜负”排行榜里。

## 1. 建议的输入（逐项核验目录和 schema）

| 作用 | 现有相对路径/文件 | 注意 |
|---|---|---|
| 原始 24 Query | migration/vldocir_trace_inputs_20261023/queries.jsonl | question_id、question、question_type |
| Node 全量 | migration/vldocir-edge-20261022/results/nodes.jsonl | document/page、node_type、members、图表/公式文本描述 |
| 冻结可检索宇宙 | EvidenceNet/output/kg_link_prediction_pilot_v2_20261102/candidate_universe.jsonl | 只展示 eligible 6,520 |
| 原始 Node Navigation | EvidenceNet/output/top10_node_navigation_20261029/navigation.jsonl | 过滤后 Dense rank；保留 raw vs eligible 差异 |
| Query→Edge 统一图 | EvidenceNet/output/query_edge_utilization_replay_v1_20261105/route_records.jsonl | 方向、anchors、provenance、eligibility |
| Query×Arm 每条路径的决定 | EvidenceNet/output/query_edge_utilization_replay_v1_20261105/route_decisions.jsonl | arm、action、reason、features、source/target rank |
| 每 Query/Arm 停止日志 | EvidenceNet/output/query_edge_utilization_replay_v1_20261105/budget_ledger.jsonl | stop_reason、scanned、selected、budget |
| Phase-1 汇总 | EvidenceNet/output/query_edge_utilization_replay_v1_20261105/summary.json | R1/R2 的候选统计 |
| Query 路径审查 | EvidenceNet/output/query_edge_utility_manual_review_v1_20261105/review_cards.jsonl；EvidenceNet/output/query_edge_utility_remaining_review_v1_20261105/review_cards.jsonl | 12+22 的**AI 初审或盲审材料**；不是独立人工 Gold |
| Answer-state 诊断 | EvidenceNet/output/answer_requirement_sufficiency_audit_v2_20261106/query_requirement_diagnostics.jsonl；EvidenceNet/output/evidence_state_semantic_adjudication_v3_20261106/ | AI-assisted / heuristic 状态，不能说成运行中真实决策 |
| D0/D1 | EvidenceNet/output/missing_requirement_retrieval_d1_v1_20261106/query_results.jsonl、d0_vs_d1_diagnostics.jsonl、summary.json | 24-query 真实检索结果 |
| 预算对齐 D0/D0+/D1 | EvidenceNet/output/budget_matched_dense_control_v1_20261106/budget_matched_diagnostics.jsonl、summary.json | **优先使用其实际字段**，不凭本任务书重新计算 |
| Oracle 与 Gold（**仅后评估**） | EvidenceNet/output/graph_retrieval_oracle_feasibility_v3_20261104/query_coverage_matrix.jsonl | 不参与检索/排序重放 |
| Custom 111 数据准备 | EvidenceNet/output/custom_vldocir_subset_v1_20261106/ | 只显示 dataset-ready；**111-query Retrieval 尚未完成** |
| 旧六臂+rerank、布局模型比较 | 查找此前确切输出与报告 | 找不到原始指标就显示 unavailable，不照抄传闻 |

如果本地文件已更名或多个版本并存，打印实际定位结果；不要静默改成看似正确的文件名。

## 2. 交付形式

请实现一个 **离线可用的交互式 Web Dashboard**，能够在 Mac/HoReKa2 的 VS Code 端口转发后展示；优先 Python 只读数据构建器 + 本地 HTML/CSS/JS/SVG（可用已安装的 Plotly/Cytoscape/pyvis/Streamlit，但不能依赖在线 CDN）。如果环境无法新增依赖，回退为静态 index.html + 预生成 JSON + 原生 SVG。**不要因为选框架耽误交付。**

建议新目录：
- EvidenceNet/visual_reports/progress_20261106/
  - README.md、DATA_INVENTORY.md
  - build_report_data.py（只读）、tests/、data/（仅可复现派生视图）
  - index.html 及本地 assets/（页面可离线使用）
  - figures/（可直接贴 PPT 的 PNG 或 SVG）
  - PRESENTATION_OUTLINE.md（10 页左右的汇报结构）
  - QUERY_CASEBOOK.md（所有 Query 的目录及重要案例说明）
- 派生 JSON、HTML 允许输出到新的工作目录，但**不能重写** EvidenceNet/output 下的任何既有产物。
- 持久化 Git 时避免提交 GB 级数据、原始 PDF 或敏感 HPC 绝对路径；大 JSON 可列入 .gitignore，保留重建脚本。

## 3. Dashboard 首页：实验背景 + 结果比较（现场能讲明白）

**A. 研究问题图**：Parsing / multimodal Evidence Node → Dense Search → Top-10 → Query-conditioned Edge inspection → 新 Node / 重复 Node / Reject / Stop。对当前没有正式实施的机制画虚线并标注 proposed，不做假执行动画。

**B. 数据规模与阶段成果时间轴（用已验证数字）**：
- 32 文档、约 518 页面、7,291 raw Nodes、冻结 6,520 eligible Nodes（区别解释清楚；如 517/518 页面口径不同给脚注）。
- 阅读结构边与 Qwen/KG Edge 的来源、总量、可达量、准入状态分开展示。Qwen 与 KG noisy 重叠不应重复计数。
- 24 Query / 六种证据结构；原 24 为开发集。
- 从布局、Node/Graph Construction、Edge Verification、Retrieval Pilot、Phase-1 Query–Edge Replay、Evidence-State Audit、D1、Budget-matched Control、Custom 111 Dataset Preparation 形成时间线。
- **Custom 111 只标记为 sampled/prepared，不能称 benchmark 已经跑出成绩。**

**C. 三个预算可比的 Retrieval Arms（主比较）**：
- D0 Dense Top-10；
- D0+ Dense Top-13；
- D1 Dense Top-10 + 3 Missing-Requirement Nodes。
- 展示 24-query 数据的分组柱状图，三行：Gold page complete **17/24、17/24、19/24**；bbox-supported complete **11/24、12/24、12/24**；AI-assisted requirement complete **13/24、13/24、15/24**。以上为已报告数，**运行构建器时要用 summary 复核，冲突则以产物为准并记录**。
- 切换百分比/数量、每 Query 变化表、D1 新增 72 Node 在 Dense rank 桶中的分布（已报告 9 个 rank11–13、21 个 14–20、42 个 21+，请复核）。
- 文案：Page Gain 不等于 Answer Gain；AI-assisted requirement 不是人工真值；样本 24，很小，不能宣布显著优势。
- 按 structure 显示结果（如果该评估源有 question_type）。没有就不要编数字。

**D. “模型/组件”与“策略”分开比较**：
- 检索策略：D0/D0+/D1、R1_static/R2_target_only/R2_anchor_proxy；它们不是独立训练模型。
- 模型/模块：冻结 Node/Query embedding（checkpoint 以协议文件为准，例如 D1 报告的 Qwen3-Embedding-8B）、可用的 BGE reranker 历史结果、Qwen 语义关系提议、KG-new 候选审核；可以画 Pipeline/component table，不强行让不同任务的分数同台竞技。
- 可选布局检测 DETR vs YOLO、关系判断的 stage metrics，**只有发现原始评估文件且同任务同数据时才能画模型对比图**。
- R1/R2 candidate 统计（历史报告：R1 25 selected、12/24 查询、8 个 Dense20 外 Target；R2 target-only 25/12/4；R2 anchor 20/9/2），明确 selected=inspected、**admitted=false**，不是 Evidence Recall 或 Precision。
- 旧六臂经 BGE rerank 后 Top-10 一致属于一项独立历史 Pilot，不与 24-query D0/D1 coverage 混为一图。

## 4. 核心：24 个 Query 的交互式检索过程 Explorer（必须逐条可看）

**查询导航**：左侧 24 条 Question，显示完整 query text、question_id、structure、D0/D0+/D1 的指标状态、是否存在 Top10 incident Edge；支持搜索和按结构/效果/有无 Edge 过滤。24 条不能只取有 Edge 的 12 条；**没有 Edge 的 Query 也必须展示 Top10 和明确的 zero-route stop**。

**每条 Query 画一个真实的 Graph/Flow**：

- 左侧固定 Top-10 Seed Nodes，编号 #1 到 #10；卡片显示 node_id、Dense rank、document/page、TEXT/TABLE/FIGURE/FORMULA/COMPOSITE、原文摘要，点击展开 member 和完整文本、bbox/anchor（如存在）。
- 右侧 Target Nodes：显示**从这些 seed 出发的全部有向 incident route**（来自 route_records / route_decisions join，不只 show selected，也不漏 rejected/unknown）。Edge 可能连接两个 Seed，必须去重渲染节点但保留不同 edge/direction。
- 同一 Target 多条 Edge 只画一个目标节点，但每条边单独保留边 ID、方向和 provenance。支持横向布局、Zoom/Pan/搜索、高亮选择与滚动查看，不要让长文档文字覆盖节点。
- 颜色/线型双编码：Qwen original、KG-new、Reading；eligibility=allowed/unknown/denied；选中、拒绝、link_existing、inspect、重复、无候选。提供图例和文字标签，不能只靠颜色。
- 点击 Edge 显示 source/target anchor quote、granularity、bbox、relation_text、conditions、limitations、eligibility_reason、source/target dense rank、具体 R1/R2 action、reason、features（如 query_target_score、overlap、anchor_proxy_applicable）。
- 显示 Dense Top10、Top13、Top20 边界和新 Target rank（不要把 Top20 外等同 Gold）。
- 可以切换 R1、R2 target-only、R2 anchor proxy；每种 arm **使用已经保存的 route_decisions，不在前端重新排序模拟决策**。重叠 route 只计一次实例，保留每个 arm 的独立 action。
- 每条 Query 附一个折叠的 **D0 → D0+ → D1** 比较面板：原始 10 节点，Top13 多的 3 个，D1 选出的 3 个 Subquery 节点（若实际 query_results schema 可取得）；展示具体 subquery、原始 Dense rank、是否已在 Dense Top13、三组 Gold/bbox/AI diagnostic（evaluation-only），支持点击节点看原文。
- 没有原始路线顺序或重放事件的地方，**不伪造逐毫秒“实时检索过程”**：用 deterministic replay ordering 或以“离线排序视图”标注，而不是动画冒充实测过程。

**可以设置三种视图**：
1. Evidence List：Top10 排序 + 每个 Node 的局部邻接表；
2. Edge Graph：十个 Seed 与其可达 Target 的交互图；
3. Decision Trace：按 arm 排序的全部 route/action/reason/预算状态、最终停点。

## 5. 暂停点 / Stop Point：这是汇报重点

必须为**每条 Query、每个 Arm**绘制终止/暂停的真实理由，至少有：

- 没有 candidate route：no_usable_route；
- denied：eligibility_denied；
- unknown：research_inspection_only_not_admitted（不能标记 validated/allowed）；
- query anchor / relation 不适用：source_anchor_or_relation_not_query_applicable；
- route inspection budget 6：inspection_budget_full；
- unique target budget 3：unique_target_budget_full；
- target 已在 Dense20：target_already_in_dense20_composition_only（是 link_existing，不是新证据）；
- duplicated target：duplicate_target_provenance_merged；
- stop_reason: no_usable_route / inspection_or_link_candidates_selected（来自 budget ledger）。

可视化方式：每 Query/Arm 的 **Decision Funnel**：Top10 seeds → incident routes → filters/rejections → inspected/link_existing → terminal stop；使用 ledger 和 decisions 精确算数量。每条边旁可以标记“被拦截在哪一道 gate”。如果 summary stop_reason 只是笼统“selected”，不能进一步推断“证据充分所以停止”。

另做一个**单独的非执行层**显示 EvidenceState diagnostic（supported/partial/missing/uncertain，AI-assisted）和未来可能的 Stop / Independent Retrieval / Graph choice。**严禁把这层叠到真实 R1/R2 的执行轨迹中，也不得声称 R3 已在 24 Query 上运行。**

## 6. 重点案例：老师现场演示至少 5 个

用 query_id 实际查找对应问句，不能猜 ID，演示顺序推荐：
1. **KPMG director-election**：混合表格的正确行与 Auditor ratification Edge 错位，KG-new denied；突出 anchor granularity/eligibility gate。
2. **Federer 2004/2005**：Dense Top10 已含完整答案；D1 Gold page gain 不等于 Answer Gain；展示有价值的 Stop/avoid redundancy。
3. **CNN**：D1 得到 bbox-supported，但同预算 Dense Top13 也得到，不是 D1 独有收益。
4. **Steffi Graf**：已报告 D1 相比 Dense Top13 获得 AI-assisted Requirement 增益；展示具体 requirement 和新增 Node（重新核对 JSON）。
5. **Revolve phone**：同样展示 D1 的独有 Requirement 增益与原始 rank。
6. 如有合适的 **跨文档 Query（NGC3256 vs SN H0pe）**：展示一个主题内的 Edge 无法跨越到另一主题；说明何时独立检索更合理。可选。

可视化绝不将 AI 审查结果变为正式正例；每例都应有一句“观察 / 尚未证明什么”。

## 7. 演示与汇报材料输出

产出 **10 页左右的简洁中文汇报提纲**（可以方便迁移到 PPT）：
1. Problem & Motivation：Long-document multimodal evidence retrieval。
2. Pipeline 与研究范围（Parsing/Node/Graph/Query）。
3. Corpus and benchmark（32 docs, 24 dev queries, custom 111 prepared）。
4. 模型/模块和检索策略比较（不要混为一个“模型排名”）。
5. Graph inventory / validity / reachability。
6. R1/R2 Route Inspection & stop reasons。
7. D0 vs D0+ vs D1：相同预算的量化结果。
8. 24 Query Explorer 演示（可现场点击 Query）。
9. Case studies：KPMG、Federer、Steffi Graf / Revolve。
10. Limitations & Next steps：Gold page ≠ answer gain、unknown edges、24-query 小样本、111-query 还未跑、拟验证 hybrid route。

额外交付：
- 至少 5 张可直接嵌入幻灯片的独立 PNG/SVG（pipeline、stage timeline、三组覆盖对比、edge funnel、真实 Query graph）。
- 一份 QUERY_CASEBOOK.md：**24 Query 一行目录**，每条的 question_id、query text、Top10 seed ids、edge count、stop reason、D0/D0+/D1 差异；至少 5 条写成半页详细案例。
- 一个页面的 Methodology & Limitations：解释所有指标和状态，引用产物相对路径及 SHA256。
- 运行指南：只需 1～2 条命令启动本地展示/生成静态产物；如果依赖缺失要给最小 fallback。

## 8. 数据模型与基本质量要求

聚合数据记录建议有：
- Query: question_id, question, structure, top10/top13/top20, retrieval_arm_outcomes, requirement_diagnostics。
- Node: node_id, document_id, page, type, excerpt, member_evidence, dense_rank。
- Route: edge_id, oriented_source_id, oriented_target_id, direction, source_kind, eligibility, relation, anchors, arm_decisions。
- Decision: question_id, arm, route_key, action, reason, sort_order, inspected, selected, admitted(false)。
- Stop: question_id, arm, stop_reason, scanned, selected, budget, rejected_reasons。
- Evaluation: metrics_by_arm + per_query; 标注 gold/AI-assisted 的评价范围。

必须做的单元/完整性检查：
1. 24 Query 全量覆盖，Top10 每条 10 个 eligible 且 unique Node；
2. 所有 edge 端点可解析，方向与 anchor 不互换；
3. 计数一致：全图 oriented edges、Query 触达的 routes、各 arm 处理的 decisions 分开，不混计；
4. denied 永远不能画成 admitted；unknown 标记 inspection-only；admitted 字段如果 false 则全程不改变；
5. 对每 Query/Arm，Decision reason 统计与 budget ledger 相符；没有候选也要展示 stop；
6. D0/D0+/D1 预算检查 10/13/13（实际 D1 新增若不足 3，明示）；
7. Evaluation-only Gold 不得影响 Query/Edge 决策视图；
8. 三组指标取自同一 version、同一语料和同一指标口径；
9. 对没有 Graph Edge 的 Query，页面仍正常；
10. 所有 24 Query 导航、五个重点案例、图表离线运行通畅。

## 9. 推荐工作顺序（直接做，不要只写方案）

**P0（最优先）**：核实输入 → build_report_data.py + 数据审计 → 最小可运行 24 Query Explorer（Top10 + incident edge + arm decision + stop）。

**P1**：加入 D0/D0+/D1 分组图、R1/R2 对比图、case studies 的 detail panels；每条 Query 可以切换可视化。

**P2**：补充阶段成果时间轴、模型/模块对照、5 张汇报图和约 10 页 PPT 提纲。

每阶段请实际运行脚本并完成截图/HTML 本地检查；不要做空框架或无数据的 demo。最终回复必须包含：完成文件列表、启动命令、真实已可视化 Query 数、缺失数据项、截图或页面位置、测试结果、哪些图表仍受数据不足限制。

**关键界限：不宣称 Graph 已提高 Recall，不将 inspect 画成正式检索，不声称 R3 已验证，不把 custom 111 当成已出成绩，不混用不同向量模型/宇宙的结果。**
