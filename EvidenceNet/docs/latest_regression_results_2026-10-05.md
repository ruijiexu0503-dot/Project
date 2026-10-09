# 最新49页回归结果

检查日期：2026-10-05。节点作业46209的7个数组任务、后续候选作业46210全部COMPLETED，退出码0。
输入49/49页均有结果，覆盖25份文档；这不是1048页全页推理。
[逐页对照与机器可读记录](../output/latest_regression_46209/regression_review_20261005.json)。

## 节点结果

| 指标 | 冻结v7 | 最新实际推理 |
| --- | ---: | ---: |
| 完整通过 | 29 | 32 |
| partial | 5 | 9 |
| flow失败 | 15 | 8 |
| 结构有效 | 34/49 | 41/49 |
| 局部图文关系 | 37 | 42 |

9个partial全部来自flow复核：6页重复归属修复、3页零文本视觉分支。
视觉分支没有恢复文字；不能把这3页计作完整文档理解成功。
原15个flow失败页中，10页现在结构有效、5页仍失败；同时有3个原完整页回退为flow失败：

- CERN 2022 p17：遗漏 `A_001::F001`、`A_002::F001`。
- CLAD p63：输出不存在的 `A_014::F001`。
- DLR p9：遗漏 `D003::F001`。

另有2个原完整页因本次需要重复归属修复而转为partial，不是flow失败。
8个flow失败页的主要问题是4页漏片段、2页非法/错类型ID、1页非法结构角色`table`、1页continuation自环；
CERN 2022 p6同时还有无效continuation。当前bounded修复只针对重复归属，不覆盖这些错误。
CERN 2022的两个样本页均失败，因此本轮24/25份文档有结构有效节点输出。

已逐页核对，49页原图内容及输入atoms/visuals保持一致。但旧结果为冻结CPU运行，新结果为GPU重新生成，
并非仅改变验收规则的严格消融；新成功或回退不能全部归因于某个单独改动。

## 引文与局部关系

旧v7有7条关系因引文无法唯一匹配而拒绝；本轮没有引文/片段ID验收拒绝，42条接受关系均带主片段ID。
复查42个主引文及78个supporting spans（含主引文）均对应候选原文的精确字符位置。
Hallmarks的两个已审核logo记为reviewed_noncontent_visual，保留节点并跳过正文关系候选。

42对37是覆盖范围变化后的总数。在两次均结构有效的31页上，局部关系是28→29。
这些结果支持“原文定位错误减少”的工程结论，不证明关系类型、方向或图文关联语义正确。

## 候选结果

[adapter汇总](../../EdgeGeneration/output/latest_regression_edges_46210/snapshot/manifest.json)：
41页导入、8页跳过，500个组件，42条局部关系，无未知端点关系、无缺失视觉资产。

[窗口检索汇总](../../EdgeGeneration/output/latest_regression_edges_46210/window_candidates/summary.json)：
330个eligible单元生成369窗口，5个超长单元无截断；lexical2692对、dense3261对、重合1318对。
lexical/dense/hybrid各600对，每个scope200对。213个dense候选对至少一端命中非首窗口。
复查了窗口原文位置、端点一致性、有限向量、三路去重与已知局部关系排除。

节点集合已改变，因此不能直接将此次3261对与旧2885对解释为检索质量提升。
仍无独立语义标签，无法报告precision或recall。

## 耗时和后续判断

节点7批累计作业运行1小时56分17秒，使用2张GPU，分配GPU时间约3.88 GPU小时；候选阶段23秒。
不含排队；节点均值约142秒/页（含各批模型启动）。机械外推1048页约41.5小时墙钟/83 GPU小时，
只适用于相同2GPU配置和样本复杂度，未含新增解析、排队与全量检索，不是可靠的全量工期预测。

建议先解决3个回退页及缺失/非法ID处理，再扩大到全页推理。
保持源片段严格覆盖，不通过自动塞入page_furniture来提高通过率。
全量前仍需解析缓存来源核验，以及避免完整窗口相似度矩阵的检索实现。
1048页全量模型推理尚未提交，现有49页失败输出全部保留。

## Follow-up correction

The subsequent [assignment repair and semantic audit](assignment_patch_and_semantics_2026-10-05.md)
finds semantic errors despite exact source-span grounding. It records opt-in v2
fixes, 23 source-reviewed local relations, and queued GPU tests 48023/48027.
The frozen metrics in this report remain historical; exact anchors are not semantic GT.
