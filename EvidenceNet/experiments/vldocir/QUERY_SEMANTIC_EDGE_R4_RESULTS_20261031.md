# Query semantic edge r4 结果审计（2026-10-31）

## 结果来源和范围

用户给定的本地 output 根目录目前只有 prepared inputs，没有两个 navigation 输出目录。实际最新结果位于 Horeka `remote_runs/query-semantic-edge-v1-r4-20261030/EvidenceNet/output/query_semantic_edge_v1_20261030/`。

已读取并保存完整本地快照：`migration/query_semantic_edge_r4_review_20261031/`，包括 results、部署代码、日志、任务号和 snapshot_sha256.json。tasks/edges 对照 manifest 的 SHA 校验通过。本次没有改算法或提交新任务。

最新任务：endpoint 5219744；semantic 5219745。两个 smoke_status 均 complete，预测 complete=true，无遗留 validation issues。只指定 Federer 一题，不是全量24题；status 的 complete_queries=1/total_queries=24，剩余23题未处理，不应当成23题失败。

## 真实结果

问题：In which Grand Slam tournaments did Roger Federer win titles in both 2004 and 2005?

两组各自的 seed10、graph_adaptive、dense_exposure_matched 在每个预算下相同，且两组之间全部12条对应 records 完全相同。

|预算|endpoint文本tokens|semantic文本tokens|选中packet|两项需求审查|
|---|---:|---:|---|---|
|512|435|435|P000、P021|均 sufficient|
|1024|435|435|P000、P021|均 sufficient|
|2048|1309|1309|P000、P019、P021|均 sufficient|
|4096|1309|1309|P000、P019、P021|均 sufficient|

P000 原文明确说明 Federer 2004 年获 Australian Open、Wimbledon、US Open；P021 原文明确说明2005年获 Wimbledon、US Open，另外两项未入决赛。这两段确实足以支持共同赛事为 Wimbledon 与 US Open。没有运行最终回答模型。

两段对应原始 node rank 1 和6，都在初始Top10内。这是旧“单赛季表被误当成两年证据”问题的来源选择改善，不是edge召回收益。

## 描述接线修复，但导航未执行

187条边已关联186条 DESCRIBED、1条 INSUFFICIENT，不再全部 PENDING。协议有效不等于关系人工核验。

但是两组的第一条trace都是 `hop=1, stop=selected_sources_sufficient`：

- 初始Top10被判充分，未调用 navigation。
- 无新增访问节点，暴露/访问集合均为10个seed。
- 无 route_joint_audit，没有 graph_adaptive_joint 实际结果。
- 因此本轮不能评价描述是否改善路线选择，也不能据此断言语义edge无效。

部署实现预备了描述进入LLM路线判断与联合核验的接口，但本轮没有执行到这些分支。该查询流程也没有运行query-edge向量相似度排序；不要把描述接入等同于已完成完整edge embedding检索方案。

## 成本与协议

每组14次生成：query_plan 1、plan_review 1、assessment 10、selected_set_audit 2；无重试错误。每组累计输入15358 tokens，输出4096 tokens。生成耗时endpoint约340.52秒、semantic约332.90秒；不是Slurm总墙钟耗时，不应解释为semantic提速。

输入计数已不再是每次2 tokens的旧错误。最终435 tokens只是最后来源文本，不包含上述规划/判断成本。

## 剩余问题：预算增大，重复来源被当成新事实

2048/4096预算加入P019整张2004年获胜赛事表，文本从435增至1309 tokens，约3.01倍。它重复给出P000已覆盖的三项大满贯，还带入多项非大满贯赛事、比分、对手等当前问题不需要的信息。

部署 `query_semantic_edge_policy.py::fact_key()` 以 `(requirement, packet_id, span_ids)` 标识事实，pack计算来源ID层面的gain。不同packet即使表达同一事实仍算新增，且pack没有对已充分集合做删除冗余的复核。因此来源去重尚不等于语义去重。

不能退回旧二元covers“一命中就结束”，否则又会漏部分支持。建议以已选来源集合为条件判断剩余packet的边际支持，区分补全事实、消歧、独立佐证和纯重复；最后做删除测试，在支持不变时去掉冗余来源。

P019的孤立table文本没有直接出现Federer姓名，但assessment解释称其显式列出Federer战绩。最终集合有P000上下文，因此不能据此说最终答案错；它仍提示孤立支持判定中身份来源需要更严格记录。

## 下一步

1. 保留Federer作为来源选择回归，不再把它单独作为导航效果测试。
2. 在全部开发题上记录seed阶段是否缺证据以及图内可达性；观察真正触发导航的题。不要人为删去正确seed或按gold补边制造收益。
3. 可控合成图测试rank10入口、两跳bridge、错实体/错年和循环，只作为机制测试，独立于真实指标。
4. 如另做强制一跳诊断，明确单列arm；不要与按充分性停止的正式策略混报。
5. 在同图、同seed、匹配暴露与预算下对比endpoint/semantic，并记录描述实际进入了多少次调用；再单独验证向量路线排序和联合支持。
6. 修复语义冗余与来源身份归属后，再评估“同等充分性下减少tokens”。本轮没有新的Recall/AP评测，不能宣称优于ColNomic或官方全集。
