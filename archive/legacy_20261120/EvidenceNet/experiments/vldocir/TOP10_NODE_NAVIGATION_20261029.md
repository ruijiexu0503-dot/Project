# Top10 EvidenceNode 出发的一跳搜索

用户确认：先召回Top10个node，从这10个入口各自沿已有edge寻找更好的证据。
本实验止于原文选择，不做最终回答；独立于已提交的固定池实验5217479，不修改该任务。

## 冻结定义

1. 复用24题的0.6B query-window缓存，用每个实际EvidenceNode的最高窗口分数排序。
   过滤独立索引的1529个parser标题；不会把Top10页、Top10窗口或标题当作Top10 node。
2. 所有10个入口均参与，沿真实邻接边取**全部一跳邻居**。不按邻居初始dense分数截前2条，
   不在全图搜索相似edge，也不要求目标原先在Top20中。
3. 本轮只导入已冻结的187条语义边；按RELATED关系作双向导航，记录A_to_B/B_to_A。
   阅读顺序目前有633条提案，但16份上游manifest均reading_ready=false，不混入已验证层。
4. 共享原文评分池=Top10种子+全部一跳邻居+等node数量的dense候选。
   Query–原文评分不暴露edge和原排名；另一独立调用才评估edge对query的导航价值。
5. 不使用gold建路径或选择起点；新邻居不继承seed分数，也没有统一edge加分。
6. 同一完整原文块、评分模型和预算控制用于所有组。只输入原文，生成visual description排除。
   初始检索可含视觉描述，但末端是文本实验；没有原文可评的node明确记录，不能声称完整多模态评测。

## 四个对照

|组|候选来源|
|---|---|
|seed10|仅最初10个node|
|dense_matched|按dense排名取N个node，N=Top10与一跳邻居的去重并集大小|
|seed10_neighbors|Top10 + 所有一跳邻居，不作query边门控|
|seed10_query_gated_neighbors|Top10 + 通过query边验证的邻居|

最终使用共同query需求覆盖选择器，预算512/1024/2048/4096。
node数量匹配不等于token/计算量相同，sidecar另记每组待评分原文token总量。
共享池只推理一次作为成本优化，不代表各组独立端到端调用成本相同。
同页的新node可能改善定位而不增加页面recall；页面gold不能直接充当node相关性标签。

## 已完成的CPU检查

24题共240个seed出现，25个seed有此语义图的邻接边。
7题能发现Top10之外的node，共12个query–新node，其中7个初始位于Top20之外。
这些是可达性计数，不是正确证据数量，不是排名改善。
原文评分任务共24条、261个query–member，最长输入18023模型tokens。

## 路径与结果

脚本：`scripts/run_top10_node_navigation.py`。
准备目录：`output/top10_node_navigation_20261029/`。

- `navigation.jsonl`：每题Top10、dense匹配集、全node初始排名、全部一跳路径和原文缺失项。
- `tasks.jsonl`：固定的评分与边验证输入。
- `reachability.json`、`paths.html`：已可查看的一跳路径审计。
- GPU完成后：`predictions/`、`selected.jsonl`、`ranked_paths.jsonl`、`status.json`。

`target_prebudget_node_rank`是共同原文评分后的粗粒度node排序。
`target_in_final_input`与`target_input_order`才表示各token预算下实际送入文本的情况。
不得把预算前排名第1却未打包的node称为最终Top1证据。
模型对需求覆盖的判断仍需复核；不以其自评分充当准确率。

## 执行

```bash
.venv-magazine-exp1/bin/python EvidenceNet/scripts/run_top10_node_navigation.py prepare
```

prepare要求新目录；现有冻结输入不要覆盖。模型阶段需要GPU，可断点续跑，每题保存结果。
新部署目录：`migration/horeka-top10-navigation-20261029/`。
写本文时尚未提交，不能沿用5217479作为这项实验的任务号。
