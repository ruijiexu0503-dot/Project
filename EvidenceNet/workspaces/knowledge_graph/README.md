# Knowledge graph：独立的关系预测研究目录

更新：2026-11-01。这个目录单独承载 ULTRA/TRIX 等关系预测、entity overlay 和核验数据工作。它是现有 edge pipeline 的候选增强分支，目前不是已证明更优的替代方案。

## 已实现和未实现

[脚本索引](SCRIPTS.md)：`prepare_kg_link_prediction.py` 已完成图准备、文档级拆分、审计、TSV、候选 schema、盲审样本与 manifest。`entity_hub_overlay.py` 是已有实体覆盖实验的关联入口，不是 ULTRA/TRIX runtime。

现有准备脚本固定了 ULTRA 和 TRIX checkpoint/commit；以实际脚本及 manifest 为准。历史研究计划中的可用性描述可能早于该更新。固定权重信息不等于已成功运行模型，也不等于已得到可靠评测。

当前没有在本次整理中运行或提交 KG GPU 作业，没有新增 MRR/Hits@K 结果。

## 真实审计结果

[原始 REPORT](results/kg_link_prediction_pilot_v1_20261101/REPORT.md)、[audit.json](results/kg_link_prediction_pilot_v1_20261101/audit.json)、[manifest.json](results/kg_link_prediction_pilot_v1_20261101/manifest.json)。

| 项目 | 结果 |
|---|---:|
| nodes / 文档 / 页 | 7291 / 32 / 518 |
| 旧 RELATED 提案 | 213 |
| 覆盖端点 | 366（5.02%） |
| 孤立 node | 6925 |
| reading assignment | 9（0.12%） |
| train / valid / test 文档 | 23 / 3 / 6 |
| 隔离的跨 split 边 | 58 |

旧 RELATED 是模型提案，不是人工金标。未标注 pair 是 unknown，不应自动当负例。reading artifacts 的状态是 `coverage_limited_do_not_mark_global_ready`。

## 标注进度和真值边界

已生成 [72 对盲审样本](results/kg_link_prediction_pilot_v1_20261101/blind_review_pairs.jsonl)。此前人工式阅读核验工作仍在进行；**本次目录整理没有交付完成的 72 对标签文件**，不能将其写成已完成真值。

后续由 AI 审核的标签必须明确标成 model-reviewed silver，保留原文证据、判断理由、不确定项和人工复核状态，不能称为 human gold。已阅读中发现跨栏 OCR 混合、重复/异常文本和图片文字归属问题，需要区分“原页面存在关系”与“当前 node 可以支持关系”。这些观察尚不是冻结的正式标注结论。

[annotations/README.md](annotations/README.md) 定义新的标注归档位置。先固定标签，再打开 proposer key 做分层统计，避免让提案来源影响判断。不要改写原始 blind pairs 或 manifest。

## 后续实现顺序

1. 完成两端原文/必要页面核验，分别标 pair 是否值得连、描述是否正确、是否有 OCR 污染；不确定例排除主结论。
2. 确认拆分后再生成逆边，保留跨 split 隔离；查询 gold 不进入训练图。
3. 在独立运行目录接入官方 runtime，输出统一 candidate schema；模型分数只是 proposer 信号。
4. 同一候选预算和 verifier 下比较现有候选与 KG 候选，记录质量和新增覆盖。
5. 再接 query 的同条件检索/证据选择评测，证明是否救回原来漏掉的证据及 token 成本。

72 对选定样本不是完整 KG 真值集合；即使完成审核，也不能据此直接声称全图 MRR、Hits@K 或召回率有效。CBLiP 等后续模型先单独建实现与协议说明，不能混记成已有结果。

## 文件归属约定

新 KG 专用实现可放在本目录的 `implementation/`；在接入前明确包导入、测试和远端打包方式。已有 preparation 和 entity overlay 保持原源码路径，通过链接访问，避免双份代码分叉。新实验产物放独立版本目录，不覆盖这份 phase1 快照。

- [研究计划](docs/vldocir/KG_LINK_PREDICTION_RESEARCH_PLAN_20261101.md)
- [原专项测试](../../tests/test_kg_link_prediction.py)
- [与离线建边的接口](../edge_construction/README.md)
- [最终 query 评测接口](../query/README.md)
