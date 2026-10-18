# P08、P23、P24 漏连修复（2026-10-18）

本轮保持 1,301 个唯一 node pair 的总预算，不调用 Qwen、不修改 node、历史结果或
生产图。三条新通道只决定 pair 是否进入后续核验，并不直接创建语义边。

## 三种失败和修复

### P08：数字引用使方法身份丢失

一端直接写出 DCRNN 的双向扩散公式；另一端只写 `[8]` 采用 forward/backward
diffusion。原召回虽然 dense 和 BM25 都双向命中，仍在相关文章组合中排第 190。

修复规则只使用同文章原文：收集 `ACRONYM [n]` 绑定，再把同一文章中孤立的 `[n]`
解析为该 acronym。这里由其他原文得到 `[8] = DCRNN`。在已选文章组合内，对共享
解析后命名实体的 pair，按每个 endpoint 的 retrieval score 保留前 4 个；4 与原选择器
的 endpoint degree cap 一致。每条解析保存 acronym 出处、引用节点和字符位置。
这让 P08 进入候选。它仍需核验两端具体主张，不能因为共享 DCRNN 就自动连边。

### P23：图号指针被切到后续独立 node

正文 node 描述 Q/K/V、scaled dot product 和双向时间依赖；图像 node 是 Figure 4。
直接指针 `Fig. 4 illustrates...` 位于后续短 node，因此两个目标 endpoint 本身没有
图号匹配。

修复规则从已经唯一匹配的原文图表指针出发，在同页、同文章内向前扩展最多 6 个
reading-order 内容 node，保存 pointer、caption target 和 order distance。P23 距指针
4 个 order，因而进入候选。这个通道表达“这些内容可能是被该指针总结的上下文”，
最终关系仍需回到原图和原文核验。

### P24：连续解释被文章内 8 对上限截掉

两个文本 node 同页、同栏、阅读顺序连续，边界在 y=563 处相接：前一段提出 force
feedback，后一段说明 torque-controlled motors 如何让控制杆产生机械阻力。原多通道
匹配双向都很强，但它在整篇文章内排第 23。

修复规则为已确认文章中的同页节点建立候选：reading order 相邻、order 差不超过 2、
横向覆盖至少 50%，两个 bbox 垂直相接或重叠。该规则共得到 144 对，P24 被恢复。
这仍是候选通道；普通相邻段落不必然有语义边。

## 固定预算结果

| 候选策略 | 旧正例覆盖 | 难负例进入候选 | 导航正例 |
|---|---:|---:|---:|
| 上一轮 v2 | 18/26 | 2/27 | 2/2 |
| + 数字引用实体通道 | 18/26 | 2/27 | 2/2 |
| + 图表指针上下文 | 19/26 | 2/27 | 2/2 |
| + 连续阅读节点 | **20/26** | **2/27** | **2/2** |

逐例变化更重要：最终新增 P08、P23、P24，移除 P26。命名实体通道不是“没有收益”，
而是 P08 与 P26 一进一出。固定 pair 的严格核验对 P08/P23/P24 均判为
`EVIDENCE_LINK`，对 P26 判为 `NO_LINK`；P26 只在通用 AI 定义与具体卒中项目之间
存在宽泛概念重叠。因此按严格证据边口径，候选集覆盖当前 26 例中的全部 20 个
`EVIDENCE_LINK` 案例。

剩余六个旧正例为：P02、P09、P10（严格核验为 `NAVIGATION_LINK`）以及
P11、P12、P26（严格核验为 `NO_LINK`）。它们不应通过降低 evidence gate 混入强证据图。
如果需要方法探索图，P02/P09/P10 应在独立 navigation layer 评估。

## 验证和边界

- 新通道规模：resolved entity 524、reference context 222、contiguous reading 144。
- 每个 arm 都是 1,301 个不同 pair；标签只在候选文件及 SHA256 冻结后读取。
- 11 项测试通过，覆盖文章内引用隔离、引用 provenance、上下文窗口、版面连续条件、
  固定预算、eligibility、图号层级解析和原向量对应。
- 当前数字来自反复使用的 development regression suite。规则是在检查 P08/P23/P24
  后设计的，因此不能作为无偏泛化提升；需要按文章划分的新材料测试。
- 固定 pair 核验来自另一轮 shadow 实验，不是这次候选生成后的端到端推理。
- P08 的核验关系为 claim correspondence/contrast；P23、P24 为 explanation/elaboration。
  模型给出的 A/B 方向受输入端点随机化影响，正式导出时必须转换回 node ID 方向。

实现：`scripts/repair_remaining_edge_candidates.py`。
有效输出：`output/remaining_edge_candidate_repair_v2_20261018/`，其中
`case_coverage.json` 给出逐例变化，三个 `*_candidates.jsonl` 保留所有来源证据和选择原因。
