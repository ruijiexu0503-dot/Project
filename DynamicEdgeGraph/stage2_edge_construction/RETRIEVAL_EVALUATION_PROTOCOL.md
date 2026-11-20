# DynamicEdgeGraph Retrieval Evaluation Protocol

本项目的主评价目标是 **Evidence Retrieval Performance**。Clustering、prototype context、Edge similarity、簇内方差和方向敏感性只作为诊断，不单独构成研究成功。

## 冻结共同条件

- 24-query / 518-page VL-DocIR Pilot；相同 Query、page ID、去重与 Gold Evidence。
- 同一 query-independent Pilot Candidate Union、同一初始 Seed、同一 hop 限制、候选/证据预算、页面聚合和最终排序流水线。
- Gold 仅可在最终评测、失败审计或独立测试报告中读取；不得进入静态图、prototype、cluster 或 scorer 参数。
- 主指标：RecallAll@5、nDCGAll@5；同时报告 Recall@3/5/10、nDCG@3/5/10、New Gold Pages Recovered、实际评分 Edge 数、候选/目标页数、耗时和内存。

## 统一消融

| ID | 方法 | 唯一变化 | 目标问题 |
|---|---|---|---|
| A | No-edge Retrieval | 冻结 `hybrid_visual` | 普通检索基线 |
| B | Graph + Target-only | 固定图邻接，Query–Target score | 图连接本身是否有用 |
| C | Graph + Original Directed Edge | 同 B 的图/Seeds/预算，加入原始 E0-MidDiff channel | Edge 表示是否有独立贡献 |
| D | Graph + Clustering / Prototype Context | 同 C，固定无监督 cluster/prototype 路由或上下文 | clustering context 是否有额外贡献 |
| E | Graph + Dynamic Edge Updating | 同 C，覆盖完整的 prototype-conditioned Edge | dynamic updating 是否有额外贡献 |

`ColNomic-7B` 只作为同 Pilot 外部模型横向对照；不同规模的论文结果单列为 Published Reference，绝不填入本表。

## 当前门槛与开发纪律

当前 B/C 固定融合相对于 A 出现 Top-5 Gold 页意外损失。先完成 Ranking/Fusion Failure Audit、保存每题页面 ranking 与 edge trace，并固定无意外损失的融合契约；在此之前不报告 D/E 的检索提升。

Prototype 更新后的 2048 维 whole-edge L2 向量不再是可逆 MidDiff。检索时其前/后 1024 维只能作为 independently-normalized shared-like / directed-like channels。若更新仅覆盖采样 Edge，retriever 必须拒绝与 full Candidate Union 中的原始 Edge 混用。

若未来需要学习 scorer、QKV 或 prototype 参数，必须预先建立独立 Train / Validation / Test Query 划分；24-query Pilot 仅作为开发结果，不能一边反复调参一边宣称最终泛化性能。
