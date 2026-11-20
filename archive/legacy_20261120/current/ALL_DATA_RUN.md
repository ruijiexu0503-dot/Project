# 全量数据测试：范围与启动记录

启动日期：2026-10-04；结果检查：2026-10-05。最新49页回归及候选作业均已完成：
32页complete、9页partial、8页flow失败，41/49页结构有效；发现3页从旧版complete回退到flow失败。
详见[结果报告](../EvidenceNet/docs/latest_regression_results_2026-10-05.md)。
**1048页全量模型推理尚未提交，不能把49页回归称为全页跑完。**

2026-10-06更新：固定输入的12视觉prompt对照52533未通过语义检查（明确错误3→3，正例保留7/7→6/7）。
按“效果好才扩大”的条件，本轮没有提交新的扩大测试。具体结果及旧实验归档见
[prompt对照报告](../EvidenceNet/docs/prompt_comparison_and_archive_2026-10-06.md)。

## 全量输入清单

[预检汇总](../EvidenceNet/output/all_data_preflight_20261004/summary.json)：
25份文档，共1048页/张，包括23份PDF的1010页、1份PPTX的37页、1张JPEG。
另外3个JSON是来源元数据。没有输入读取错误、没有完全相同文件的SHA-256重复。
NASA的JPEG与image-only PDF保留为两个来源/容器对照，不能按不同哈希推断内容独立。

[逐页清单](../EvidenceNet/output/all_data_preflight_20261004/pages.jsonl)记录源文件哈希、原始页号和缓存候选。
483页存在历史Dolphin输出，但缺少绑定原图的哈希，先视为待核验缓存，不能直接宣称可安全复用。
37张PPTX幻灯片的原生对象缓存与源文件哈希相符，但预览不保证真实渲染效果。
PDF原页与已有split-render页号不能混用。

预检可复现（使用新输出目录）：

```bash
parsing/.venv_vlm/bin/python current/audit_all_data.py \
  --output EvidenceNet/output/all_data_preflight_NEW
```

## 已提交的第一阶段

- 节点作业：**46209**，普通 `gpu-h100` 队列，数组0–6、最多同时1个任务。
  每批7页、2张GPU、上限2小时；预算停止后checkpoint可恢复。
  输入是现有49页回归集，覆盖全部25份文档；不重新运行parser。
- 节点策略：`bounded-v1`、`span-id-v1`、来源绑定的视觉角色审核表，每次推理最多1次常规尝试。
- 输出：`EvidenceNet/output/latest_regression_46209/shard_*/`。
- 后续候选作业：**46210**，依赖46209全部任务结束，最多1张GPU、30分钟上限。
  成功/partial节点导入adapter，再运行窗口dense、lexical、同预算hybrid候选。
  输出：`EdgeGeneration/output/latest_regression_edges_46210/`。
  使用afterany保留部分成功页的诊断价值；不能因后续作业运行完毕就忽略上游失败/缺失页。

恢复节点作业时可设置 `REGRESSION_ROOT=EvidenceNet/output/latest_regression_46209`，
并只指定待恢复的数组索引；不要覆盖冻结基线。入口：
`run_latest_regression_gpu.sbatch`、`run_latest_regression_edges.sbatch`。

## 扩大到1048页前的检查

1. 冻结source-page编号与解析来源，核验缓存；缺失或不可验证的解析走独立新输出。
2. 用49页本次实际耗时确定后续每批页数，分文档/类型报告完整、partial、失败和未运行数。
3. 全量检索前，将小快照精确检索改为分块计算或经过对照的ANN，避免完整窗口相似度矩阵和Python逐对遍历。
4. 输出节点、局部图文关系、候选边和失败台账；跨页文章归属、PPTX渲染、零文本OCR仍要明确记录限制。
5. 语义关系质量依赖独立审核。批处理成功、结构校验通过、候选数增加都不等于语义准确。

当前已请求用户选择并发/批次预算；在收到调整前，第一阶段采用保守的最多2张GPU配置。
没有一次性提交1048页的长时间推理，也没有覆盖现有结果。
