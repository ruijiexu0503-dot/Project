# Query：如何利用已有图检索与选择证据

更新：2026-11-01。负责在线 query 使用，不负责把测试 query 写入离线图。

## 代码入口与流程

[脚本分类索引](SCRIPTS.md) 包含导航、证据选择、评价及历史依赖四组。

- 语义导航实验入口：`run_query_semantic_edge_v2.py`；策略为 `query_semantic_edge_policy_v2.py`，共享逻辑为 `query_semantic_edge_core.py`。这是当前迭代入口，不等于已验证最优的生产方案。
- Query 自适应与选文：`run_query_adaptive_evidence_v2.py`、`query_evidence_policy_v2.py`；前序对照为 `run_query_evidence_selection.py`、`run_span_evidence_selection.py`。
- Top10 种子沿边对照：`run_top10_node_navigation.py`。Query 拆解探索：`run_query_split_probe.py`。
- `query_edge_gate.py` 是 query 条件下判断既有路线的协议，属于在线使用图；其结构和引用校验不等于语义正确性证明。
- HF 同条件对照：`run_hf_evidence_comparison.py`。相关指标工具放在 `03_evaluation/`。

工作链：query/需求 → 检索种子 → 读取 incident edges → 判断目标端能增加什么 → 访问目标原文 → 选择片段并检查预算。必须区分“有边”“访问过”“选入最终证据”“改善了答案支持”，不能只以走边次数宣称收益。

## 已有结果说明了什么

依据 [HF 结果报告](results/hf_evidence_comparison_review_20261101/REPORT.md) 和 [建边调整计划](docs/vldocir/EDGE_CONSTRUCTION_PLAN_AFTER_HF_20261101.md)。范围是 24 个 query、518 页开发 pilot。

| 页面排名指标 | H0 ColNomic | N node similarity |
|---|---:|---:|
| Recall@5 | 79.17% | 83.33% |
| Recall@10 | 91.67% | 89.58% |
| AP@5 | 65.83% | 63.82% |
| AP@10 | 69.45% | 65.39% |
| Top10 gold 页齐全 | 21/24 | 19/24 |

N 没有使用 edge。它提高了部分 Top5 召回，但没有全面胜过 H0。H1 是从 H0 每页选一个 node 后做证据选择，并非整页输入，因此 H1 失败不等于页面检索失败。

共同完成的 13 题、1024 token 预算下，H1 有 4 题被模型判充分，S 有 3 题；平均文本 token 分别约 223.62 和 277.38。该“充分”不是独立人工答案准确率。S 没有完整页面排名，不能声称有 edge 的 AP 提升。

前序语义导航 v2 的 13 个完成案例中：8 题缺证据且种子没有语义关联边，3 题初始充分，2 题进入导航。semantic 接受的 1 条边没有改变最终选文。该冻结子图没有载入 reading layer，所以不能由此判断完整 NEXT/PREVIOUS 图无效。

## 接下来应改什么

1. 先拆开页面命中、页内 node 定位、目标可达、导航决策和最终选文五个损失来源。
2. 检查 NEXT/PREVIOUS 真正进入实验图，记录结构边和语义边的使用情况。
3. 决策必须看目标端新增的证据，防止把源端已回答的内容算成目标收益。
4. 相同 query、检索库、初始种子、预算和 selector 下比较无边、结构边、结构加语义边；同时保留 H0 页面排名基线。
5. 保存 query、seed rank、edge ID、方向、目标原文、接受/拒绝原因、最终 span、token 和来源页；明确哪些 gold 是由 edge 新找回的。

这些是下一步验收要求，不表示代码已全部完成。当前任务范围可以停在证据文本选择，不必先运行最终回答 LLM。

## 继续工作时先读

- [HF 比较要求](docs/vldocir/HF_COMPARISON_REQUIREMENTS_20261031.md)
- [语义边实现交接](docs/vldocir/QUERY_SEMANTIC_EDGE_IMPLEMENTATION_HANDOFF_20261030.md)
- [语义边 v2 结果](docs/vldocir/QUERY_SEMANTIC_EDGE_V2_RESULTS_20261031.md)
- [下一步改进](docs/vldocir/QUERY_SEMANTIC_EDGE_NEXT_STEPS_20261031.md)
- [Query 使用审计](docs/vldocir/QUERY_USAGE_DETAILED_AUDIT_20261030.md)
- [四组证据效率对照](docs/vldocir/FOUR_ARM_EVIDENCE_EFFICIENCY_20261029.md)

原测试位于 `EvidenceNet/tests/test_query_*.py` 等文件；本目录不复制测试和模型。执行及部署路径规则见 [总说明](../README.md)。
