# 受限 flow 修复与窗口检索：集成记录

日期：2026-10-04。状态：D-032 shadow，使用显式实验参数，未替换既有基线。

## 改动

- Node generation：`run_relation_first_corpus_shadow.py --recovery-policy bounded-v1`。
  重复 source ID 只在已有归属之间进行一次模型选择，允许 `UNRESOLVED`；随后再次执行完整原校验。
  不补造缺失归属，不把缺失片段塞入 page furniture。删除失效 continuation 时记录原内容。
  零文本页面保留视觉组件，输出 PAGE_CONTEXT，并标记 `text_recovery_required`。
  所有修复页保留 `partial`、`flow_review_required` 和修复审计；checkpoint 与 edge adapter 传递这些字段。
- Local edge generation：主 anchor 必须有效；每条 supporting anchor 单独校验和记录。
  一个额外引文失败不会丢弃主引文有效的关系；直接 caption 的既有约束继续生效。
- Candidate generation：`run_v7_dense_candidate_shadow.py --long-text-policy window`。
  512-token 窗口、64-token 重叠，保存 unit text 中的精确字符位置和命中窗口；节点端点保持原 ID。
  使用最大窗口余弦得分，不创建窗口 bbox。默认仍是截断，可显式选择窗口策略。
  lexical 在同一 eligible unit 集合重算；lexical/dense/hybrid 每个 scope 使用相同最终候选预算。
  hybrid 交替取两路排名并去重；这些候选均未经过语义核验。

## 已完成的验证

28项相关测试通过：8项受限修复测试、14项既有 relation-first 测试、3项窗口/预算测试、3项 adapter 测试。
窗口测试使用本地真实 tokenizer，检查长文本尾部、Unicode 字符位置和截断对照。

[完整快照 tokenizer 检查](../../EdgeGeneration/output/window_tokenization_check_20261004/summary.json)：
296个 eligible 单元生成317个窗口；3个超长单元分别有5209、783、4097 tokens，分为12、2、10个窗口。
全部单元的非空白字符均被窗口覆盖，每个窗口不超过512 tokens。这项检查未计算 embedding 或语义指标。

[49页冻结回复回放](../output/bounded_recovery_integrated_replay_20261004/summary.json)：

| 项目 | 结果 |
| --- | ---: |
| 原有效 flow 保持不变 | 34 |
| 重复归属修复 | 5 |
| 零文本视觉分支 | 3 |
| 仍失败 | 7 |
| 结构校验通过 | 42/49 |
| 同一批局部关系提议，修复前 → 修复后 | 37 → 39 |

这里复用历史模型回复与历史重复归属选择，只验证代码兼容性与结构约束。
42/49 不代表49页重新推理的成功率，更不代表语义准确率；视觉分支也不等于恢复了图中文字。
原始回复与选择文件的哈希保存在回放结果中。

## GPU 集成检查

HoReKa2 `dev-gpu-h100` 两项作业均已 COMPLETED，退出码0：
45658（三页35B集成检查，2 GPU，3分51秒），45659（窗口检索，1 GPU，11秒）。

[三页实际推理结果](../output/bounded_recovery_smoke_45658/shard_0/summary.json)：

| 页面 | 原v7状态 | 新结果 |
| --- | --- | --- |
| Hallmarks of Aging p18 | flow_failed | 受限模型修复2个重复归属，结构有效；partial，2个视觉组件没有候选关系 |
| NASA JPEG | flow_failed | 保留1个视觉组件，结构有效；partial，仍需恢复文字 |
| GW150914 p2 | partial | 结构有效，保留1条局部关系；拒绝3个不匹配的 supporting anchors，仍partial |

这是新模型推理的集成检查，3/3结构有效、0/3完整通过。
聚合字段 `validation_failed_pages: 3` 当前把所有非complete页面都计入，不能解释为3个flow失败。
对GW本次同一份模型回复分别运行旧/新anchor验收：旧策略保留0条，新策略保留1条。
新策略的修复与拒绝记录符合预期，但模型仍会用省略号改写引文，尚未解决源引文生成问题。

[窗口检索结果](../../EdgeGeneration/output/window_candidates_dev_45659/summary.json)：
296单元、317窗口，3个超长单元均不再截断；dense候选2885对，lexical候选2403对，重合1142对。
lexical/dense/hybrid各600对（每个scope 200对），已检查去重、端点、命中窗口原文位置、向量有限值及局部关系排除。
[后验检查](../../EdgeGeneration/output/window_candidates_dev_45659/postrun_checks.json)记录：
与旧截断dense运行2870对相比，共同2726对、新增159对、移出144对；
136个候选对的最佳窗口至少一端来自非首窗口，其中135对跨文档。
这些数字证明后部文本参与了检索，不能证明新增候选正确或关系召回提高。
108行审核样本仍无独立语义标签。

从仓库根目录复现（每次按 job ID 创建独立输出）：

```bash
sbatch current/slurm/evidence_nodes/run_bounded_recovery_dev.sbatch
sbatch current/slurm/edge_generation/run_window_candidates_dev.sbatch
```

## 解释边界

重复归属选择仍需独立审核；没有新语义 GT。窗口最大分数可能偏向长节点，目前使用小快照精确检索，
不把它当作可扩展的 ANN 实现。图像代理文本仍是有来源的 caption，不能替代直接看图。
后续比较应对三路相同预算候选做盲审，统计有效关系数、类型和方向正确率后再决定是否扩大使用。
