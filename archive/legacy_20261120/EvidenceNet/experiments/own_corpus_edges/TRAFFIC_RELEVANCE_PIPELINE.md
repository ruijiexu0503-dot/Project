# 交通预测与土地覆盖：完整节点 pipeline 与语义诊断

2026-10-14 CPU 迁移：因 GPU 任务 75097 被 AssocGrpGRESMinutes 阻挡，按用户授权迁移剩余流程。75097、75099、75100 已取消；CPU 75113（建图／召回）已启动，75114（Qwen 实测）、75115（通过耗时门槛后全量验证）及 CPU 报告已提交。详见 `TRAFFIC_CPU_MIGRATION.md`。下述 GPU 提交记录用于追溯，不代表仍在运行。

2026-10-14 更新：节点数组 7 个分片正常完成；第 5 分片因 HTVGNN 第 8 页一条非完整 Qwen JSON 失败，原建图任务 73754 因 140/160 页而停止。恢复任务 74742 已完成，恢复分片 20 页全部审计通过；160 页现已齐全。重新提交建图 75097、报告 75099。小型固定节点诊断 75096 和汇总 75100，协议见 `SUBJECT_GATE_DIAGNOSTIC_V1.md`。以下原提交记录保留用于追溯。

2026-10-13。输入 `data/incoming/paper_relevance_urban_traffic_20261013`。输出 `EvidenceNet/output/paper_relevance_urban_traffic_20261013`。

## 数据适用性

已读取六篇论文的 Dolphin 摘要及引言，并查看 STTN 原始第一页。前三篇为交通预测综述、STTN 和 HTVGNN；后三篇分别是 Fiji 土地覆盖变化、FUSU 城市土地利用变化分割数据集、基于 EuroSAT 的土地覆盖图像分类。

适合用于“宽泛主题相似是否导致误连”的诊断，但不是现成的节点对负例标注集。交通预测论文之间不保证任意段落都相关；土地覆盖论文之间存在潜在正例；跨组也可能存在具体机制对应。不得将目录中的 relevance_group 直接转换成边标签。组标签不进入候选选择或模型提示。

Dolphin 已完成 6 篇论文全部 160 页：87/12/16/14/24/7 页，无失败页。输入适配保留 45 个 visual、45 个表格、164 个标题；710 个 atom 被标记为 furniture/元数据，另有 671 个 text 和 87 个 caption。标题单独保留用于结构和展示；参考文献、页眉页脚、水印及摘要前的作者前置信息不进入正文 evidence。该角色规则还需抽查，不是完美的自动文档角色分类器。

## 已提交任务

- 73753：hybrid-v2 evidence node generation，8 个 20 页分片，最多同时运行 2 个，每分片 2 GPU、4 小时时限。
- 73754：afterany:73753，先检查全部节点覆盖与有效 Qwen 决策，再建立阅读图、语义候选并核验；任何节点页不完整则停止。2 GPU、6 小时时限。
- 73755：afterany:73754，生成完成或部分状态报告及 HTML。

提交后节点任务 PENDING/Priority，后续任务等待依赖。时限不是预计耗时。已有 parsing 复用，不重复调用 Dolphin。模型和原有检索 baseline 不变。

## 阶段与输出契约

1. `prepare_traffic_relevance_nodes.py`：核对 Dolphin 状态和 geometry，按相同 1600 像素上限从原 PDF 重渲染，检查画布尺寸；冻结输入、代码、页面及来源 hashes。
2. 复用 `run_vldocir_nodes.py` 的 describe/candidates/decide/assemble，实际采用 embedding + geometry + Qwen hybrid-v2。检查每个 atom/fragment/visual 覆盖一次、表格保留、结构元素排除，不将 Qwen 失败 fallback 当成功。
3. `run_traffic_relevance_graph.py assemble`：将多模态 evidence node、原始 crop 和生成描述导入图；每篇论文作为单一文章。标题保留在 pages 元数据。阅读边使用 Dolphin 顺序派生并明确标记；跨相邻页 NEXT 仅表示导航，不是句子合并或语义连续性的验证。
4. `candidates`：每个不同文档对最多 24 对候选，每篇内部最多 12 对，端点度数限制减少重复命中。最多 432 对；保存所有选中候选。使用固定向量模型，视觉描述用于召回。不是所有可能节点对的穷尽图。
5. `verify`：仅测试具体方法机制、数据集对应及有明确条件的测量比较；不要求共同 EVENT/PROJECT，明确拒绝只有宽泛主题的关联。模型独立陈述两端内容，再给对应机制和限制；原图用于视觉判断，两端锚点分别校验。最终边仍是 MODEL_PROPOSAL_SOURCE_REVIEW_REQUIRED，不是人工正确标签，不声称已解决旧的自由 pair 判断误连问题。
6. `report`：生成 `graph/summary.json`、`REPORT.md`、`viewer.html`。查看节点成员、原图与描述、标题、阅读边、语义边，以及拒绝/不确定结果。日志和中间产物保留，支持发现具体失败阶段。

## 使用前的门槛

10 项相关测试通过；160 页适配 bbox 检查和冻结输入 hash 检查通过。2026-10-14 节点已完成；完整语义建图仍待运行，不能宣称可以正式替换 pipeline。

跑完可用于候选与节点来源复核。需从原文检查跨组接受边、组内拒绝边、表格/图像归属和目录/作者误收。冻结人工式审查的节点对后，才能开展前述“自动主体硬门槛 vs 补齐主体的上限 vs 非共同主体具体关系”诊断；此次先准备完整节点和具体关系候选，并未完成该上限对照。检索收益仍需独立 query/evidence 标注。
