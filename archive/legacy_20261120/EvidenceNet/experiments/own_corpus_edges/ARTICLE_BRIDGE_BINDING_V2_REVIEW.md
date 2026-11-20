# Article bridge binding v2：结果复核

任务 70052 已完成（exit 0，8 分 09 秒），报告任务 70053 已完成。结果目录：`EvidenceNet/output/article_bridge_binding_v2_20261012`。本次复核不修改冻结代码、模型输出或 baseline。

## 结论

独立 node→subject 绑定及别名归一化修复了部分开发案例，但绑定仍有假阳性，路由仍会丢失合理关联，不能据此替换正式 pipeline，更没有检索提升的证据。本次为输出、原始文本及来源链复核，并非独立盲评，也未逐一重新检查全部图片。

## 实际结果与可比性

- 7 个别名判定均为 SAME，形成 3 个主体；UMBRELLA 的展示名选成了 OCR 拼写 `UMRELLA`，需修正展示名选择策略，保留原始拼写溯源。
- 30 个绑定：28 SUPPORTED、1 BACKGROUND、1 NOT_ABOUT_SUBJECT。28 中含 1 个错误接受的诊断探针；实际参与图构建的自然绑定为 27。
- 47 个开发案例：16 个可推导共同主体弱关联，31 个没有共同的已验证主体。后者属于覆盖不足，不能算正确拒绝。
- 对同一批旧 44 个案例：旧 11 ACCEPT 均可推导；另有 1 UNCERTAIN（AHEAD）及 1 错误 REJECT（GW 图表→GR 测试）转为可推导。新增的 3 个开发案例亦可推导。这个变化不等于独立准确率提升。
- 最终生成 57 条跨文章 `RELATED_VIA_SUBJECT`。其评估范围与上一版 11 ACCEPT 不同，不能直接比较边数来衡量提升。这些边只表示共同主体，不表示支持、因果、数值相等或跨文章引用。
- 37 次模型调用，累计约 440 秒；上一版 111 次、约 1345 秒。流程工作内容不同，暂不能作为严格速度 benchmark。

## 必须解决的问题

### 1. 主体绑定仍会凭空引入事件

`arxiv_1510_04615_page_0003_HY_009` 原文仅为约 20 Hz 与 advanced LIGO design noise curve 一致，引用 Shoemaker et al. 2010，没有 GW150914，也没有提供上下文来源。模型却判为 SUPPORTED，理由声称它是 GW150914 的仪器校准证据。校验器接受了真实局部文本，但没有检查该文本是否真的证明主体身份。

该探针只带 `negative_binding_probe`，被排除在图构建之外，因此没有污染当前 57 条边；这不代表算法成功拒绝了错误绑定。另两个探针（通用 SNR 阈值、CERN Open Science）判定合理。3 个探针不足以估计总体假阳性率。

下一步应要求可核验的主体身份依据：局部明确指称，或同文章内明确指向本节点的上下文链。仅有主题相关的局部引用不足以支持绑定。无名字图表应允许明确图号引用链，而不是一律排除。

### 2. 新路由增加关联，也丢失关联

相同每节点 8 个候选预算下，global 1383 对，article-first 1391 对；新增 14、移除 6。14 个新增全在 GW150914 文章簇内，不能推广到其他主题。新增中 7 个集中连接 properties/page_0006/HY_002（仪器校准），提示固定方面多样性策略会形成偏置。

移除的 6 对中至少 2 对按共同事件弱关联定义仍合理：

- detection/page_0006/HY_006 ↔ gr_test/page_0006/HY_006。
- detection/page_0006/HY_007 ↔ gr_test/page_0006/HY_004。

其他 4 对涉及通用方法或背景，不能仅凭未绑定就认定删除正确。后续需同时衡量新增收益和漏召回，避免只统计新增。

### 3. 开发案例修复不等于最终图已收录

AHEAD 的 `TYPED_04478` 现在能在开发回放中推导，但它是文章内部的边，没有进入跨文章候选，也不在保护的文章内部候选中。因此这条漏边尚未端到端修复。

16 个可推导开发案例中，只有 8 个进入 article-first 跨文章候选；其余包括 4 个文章内部案例及 4 个未被路由召回的跨文章案例。需要分别检查绑定、候选召回和最终写图，不能混为一个成功指标。

## 建议的后续顺序

1. 加主体身份来源校验，先回归通用噪声曲线这一假阳性，同时保留正确的无名字图表上下文绑定。
2. 统一将文章内部和跨文章的已验证关系写入相应图层，检查 AHEAD 的完整链路。
3. 调整候选预算与多样性策略，用已丢失的合理候选做回归，观察校准节点集中问题。
4. 再扩展多个独立主体簇，并进行固定查询集检索评测；当前 `retrieval_gain=NOT_EVALUATED`。

主要依据：`summary.json`、`routing_summary.json`、`node_subject_bindings.jsonl`、`development_decisions.jsonl`、`v1_node_edge_decisions.jsonl`、`candidate_deltas.jsonl`、`units.jsonl`、`protected_intra_article_candidates.jsonl`、`canonical_subjects.jsonl`。
