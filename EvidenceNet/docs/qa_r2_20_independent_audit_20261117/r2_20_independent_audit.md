# Node-first QA r2 — 20 条正式平衡 Gold 的独立复审

> 数据范围：仅用户上传的 `Pasted text(20261117-161612).txt`（20 条 JSONL，均声称 FINAL_ACCEPT_AUTOMATIC）。
> 审核范围：实际上传的 Question / Gold Answer / Evidence Text / Answer Claims / 映射字段 / 自动审核记录。未访问 HoreKa2 原始 PDF 或完整 frozen retrieval index，因此本报告的 `PASS` 仅指**文本级 QA 内容可接受**，不是最终 PDF/全库捷径认证。

## 结果摘要

| 指标 | 本次结果 |
|---|---:|
| 上传记录数 | 20 |
| 类别分布 | Single 4 / Cross-page 6 / Cross-document 10 |
| 内容级 PASS | 16 |
| 内容级 REVISE | 4 |
| 至少一处 Claim Span 错误/不充分 | 14/20 |
| 字符区间校验 | 98/98 正确 |
| Cross-document 两文档/三文档 | 9/1 |
| Cross-document 涉及引力波/相关文档 | 7/10 |

**解释**：字符切片存在并不等于能支持对应 claim，`answer_claim_grounding_pass=true` 与片段语义质量存在冲突。REVISE 的问题是 QA 内容或跨证据整合本身仍需修改；PASS 里仍有大量 claim-level 元数据需修补。原始 JSONL、Gate 状态不作修改。

## 共性问题与建议优先级

1. **P0｜修补 Claim-to-Span**：14 条至少一处引用错节点、错内容或引用过短。应逐 claim 校验 `supporting_evidence_indices`、原文 span 的准确语义蕴含，不能只验证 `evidence_text[start:end] == span_text`。详见各 ID。
2. **P0｜修复 4 条内容问题**：`015`、`016`（伪跨页整合）、`029`（问题要求噪声背景处理但引用不完整）、`041`（跨领域因果概念硬拼接）。修复失败就重采样，不应直接进入最终 gold。
3. **P1｜减少统计依赖**：`011` 与 `012` 共享同一 `climate_change_with_ml` p6 gold node；`030` 与 `045` 共享两份 gold nodes，后者还附加一份 GR 文档。可以保留两题作为语义不同的候选，但小型独立评测集宜二选一或在统计中按 cluster 处理。
4. **P1｜采样覆盖偏置**：10 条跨文档中 7 条涉及引力波；18 篇新期刊没有得到充分覆盖；4 条 Single Node 均是 NASA 前言/封面类内容。若用于评估全语料 Graph，需按文档/题材/模态多样性重新分层抽样。
5. **P1｜跨文档子配额**：20 条样本按初始 35% 双文档 + 15% 三文档以上目标应为 7/3，但本文件是 9/1。一级 20/30/50 通过，不代表细分配额也通过。
6. **P2｜审核记录可复现性**：`shortcut_retrieval.executed=true, found=false` 只证明已记录的候选检查没找到捷径，不能证明整个语料中不存在。若要求全库结论，应保存冻结索引版本、检索参数、Top-K 与替代候选的语义判定。
7. **分类口径**：Multi-evidence comparison ≠ strict multi-hop reasoning。`027`、`030`、`034`、`045` 等可以是有效跨文档比较/补充证据题，但不应自动标为因果链或多跳。

## 逐条结果

| ID | 类别 | 内容审核 | Claim Span | 简评 |
|---|---|---|---|---|
| 001 | single_node | **PASS** | 需修复 | Evidence Text 明确支持太空生产氧气和种植食物作为 NASA 室内农业研究动机 |
| 002 | single_node | **PASS** | 需修复 | 火星直升机用途与答案相符 |
| 003 | single_node | **PASS** | 需修复 | 同一 caption 提供 Hubble 图片跨度 2 光年和整个 Veil Nebula 110 光年 |
| 004 | single_node | **PASS** | 需修复 | 同一段确实包含 Jupiter tidal heating 和计划 45 flybys |
| 011 | cross_page | **PASS** | 本次未发现明显错误 | p5 明确区分 variable 与 controllable sources |
| 012 | cross_page | **PASS** | 本次未发现明显错误 | p5 的非即时低碳转型与现存电厂减排要求 + p6 的 spinning reserve、储能和 ML 缓冲机制，能构成具体问题 |
| 013 | cross_page | **PASS** | 本次未发现明显错误 | DETR p3 支持全局推断和 Hungarian matching |
| 014 | cross_page | **PASS** | 需修复 | p3 对 Transformer 全局注意力的解释和 p6 对位置编码的说明相互补充 |
| 015 | cross_page | **REVISE** | 需修复 | 问题同时问社会技术风险原因和 RMF 的预期收益 |
| 016 | cross_page | **REVISE** | 需修复 | p6 描述负责任 AI 的原则，p24 描述 NIST 未来评估框架有效性的计划 |
| 026 | cross_document | **PASS** | 需修复 | ~24 与 25.1(+/-1.7) SNR 及后者更高的原因构成真正的事件级比较。c1 错误指向 25.1 的 E1，没有指向 E0 的 SNR ~24。 |
| 027 | cross_document | **PASS** | 需修复 | E0 解释检测显著性及假警率，E1 描述 GR 一致性 |
| 028 | cross_document | **PASS** | 需修复 | E0 支持最终黑洞质量/自旋控制 ringdown |
| 029 | cross_document | **REVISE** | 需修复 | Q 明确要求比较 waveform assumptions 与 noise-background treatment |
| 030 | cross_document | **PASS** | 本次未发现明显错误 | 两个文档分别给 population forecast 的 cosmic history/metallicity 建模和单事件 mass-redshift 退化 |
| 032 | cross_document | **PASS** | 需修复 | E0 提供 sky location 的最大似然定义，E1 给 GW150914 时延环以及跨站 amplitude/phase 几何约束，属于方法→事件应用关系。c2 span 仅 wave |
| 034 | cross_document | **PASS** | 需修复 | DETR 的监督标签/Hungarian matching 与 RL 的交互式奖励训练存在清晰对比维度，可以算跨文档 comparison，但不是多跳。c2 错指 E0 DETR 的 Hung |
| 036 | cross_document | **PASS** | 需修复 | NVIDIA 的 100% 电力消费 renewable matching 不能单独证明所有电力使用必然碳零排放 |
| 041 | cross_document | **REVISE** | 本次未发现明显错误 | 结构建模中的 causal/unidirectional blocks 与政策回归的 causal identification 是两个不同层次的“因果” |
| 045 | cross_document | **PASS** | 本次未发现明显错误 | 三份来源各自给出 population、event inference、GR testing 的不同分析目标 |

## 逐条详细批注

### 001 — single_node / PASS
**Question**：What spaceflight need motivated NASA to test indoor agriculture?
**Gold Answer**：Generating oxygen and growing food in space.
**Gold Nodes**：real_002_batch_02_Spinoff.2022_page_0003_EU_007
**审核**：Evidence Text 明确支持太空生产氧气和种植食物作为 NASA 室内农业研究动机；但是 c1 span 错引到农场配方。
**Codex 动作**：将 c1 evidence_spans 改成以 The need to generate oxygen and grow food in space inspired NASA to test indoor agriculture techniques 开头的原文。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 002 — single_node / PASS
**Question**：What was the Mars Helicopter intended to demonstrate?
**Gold Answer**：The viability and potential of heavier-than-air vehicles on Mars.
**Gold Nodes**：real_003_batch_03_NASA_Spinoff_2021_page_0002_EU_001
**审核**：火星直升机用途与答案相符；c1 span 仅引用 on the Red Planet，不能单独证明验证目标。OCR 的 Perseverance river 是邻接错误，不影响当前答案。
**Codex 动作**：c1 span 扩展为 The helicopter will demonstrate the viability and potential of heavier-than-air vehicles on the Red Planet；OCR 异常单独记日志。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 003 — single_node / PASS
**Question**：How does the Hubble image area compare with the full Veil Nebula?
**Gold Answer**：About 2 light-years are shown; the nebula spans about 110 light-years.
**Gold Nodes**：real_006_batch_06_Spinoff2018_page_0002_EU_005
**审核**：同一 caption 提供 Hubble 图片跨度 2 光年和整个 Veil Nebula 110 光年；c1 错标成 110 光年段。
**Codex 动作**：分别用 this image shows an area roughly 2 light years across 与 entire nebula is 110 light years across 作为 c1/c2 的 evidence spans。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 004 — single_node / PASS
**Question**：What heats Europa’s subsurface ocean, and how many flybys were planned?
**Gold Answer**：Jupiter’s tidal forces create internal friction; 45 flybys were planned.
**Gold Nodes**：real_007_batch_07_Spinoff2017_page_0002_EU_005
**审核**：同一段确实包含 Jupiter tidal heating 和计划 45 flybys；两个 Claim Span 均错误落在 surface.，且原文表述潮汐加热是 believed。
**Codex 动作**：分别定位 Tidal forces from Jupiter's immense gravity are believed ... 和 would conduct 45 flybys；将答案改为 Jupiter's tidal forces are believed to cause internal friction ...，保留历史任务计划的时态。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 011 — cross_page / PASS
**Question**：Variable and controllable low-carbon sources differ operationally. What makes variable sources harder to dispatch, and which buffer transition and ML capabilities are described for accommodating them?
**Gold Answer**：Variable sources fluctuate with external conditions, whereas controllable sources can be turned on and off. Their output is currently buffered partly by CO2-emitting coal and gas spinning reserves, while storage is expected to take over that role; ML can support the transition through forecasting, scheduling, control, and electricity-market design for variable supply and flexible demand.
**Gold Nodes**：climate_change_with_ml_page_0005_HY_005; climate_change_with_ml_page_0006_HY_001
**审核**：p5 明确区分 variable 与 controllable sources；p6 解释 buffering、storage 替换与 ML 能力，两节点语义整合成立，修复了 r1 的单页捷径。但与 012 共享整个 p6 Gold Node，测试集内依赖较强。
**Codex 动作**：可保留；与 012 进行 near-duplicate / evidence reuse 检查，最好替换其中一题以增加跨页覆盖。
**Claim Span**：本次未发现明显错配。

### 012 — cross_page / PASS
**Question**：Because the transition to low-carbon electricity will not happen overnight, what must be done with existing emitting generation, and how can ML both reduce its interim emissions and help replace its buffering role?
**Gold Answer**：Emissions from existing CO2-emitting plants must be reduced during the transition. For the buffering now often supplied by coal and gas spinning reserve, ML can reduce standby-generator emissions and enable a shift toward storage by improving forecasting, scheduling, control, and electricity markets that accommodate variable supply and flexible demand.
**Gold Nodes**：climate_change_with_ml_page_0005_HY_003; climate_change_with_ml_page_0006_HY_001
**审核**：p5 的非即时低碳转型与现存电厂减排要求 + p6 的 spinning reserve、储能和 ML 缓冲机制，能构成具体问题；但与 011 共用同一 p6 Node，答案中 ML 部分大面积重叠。
**Codex 动作**：内容可保留；正式小规模平衡集最好与 011 二选一，或者重采样不同文章/Node；勿将两题当成独立难度样本。
**Claim Span**：本次未发现明显错配。

### 013 — cross_page / PASS
**Question**：In DETR's postprocessing-free set prediction, what two mechanisms address redundant detections, and which architecture components carry out the parallel detection pipeline?
**Gold Answer**：Global inference models interactions among all predictions to avoid redundancy, and Hungarian bipartite matching gives each target a unique match. DETR implements the parallel pipeline with a CNN backbone, an encoder-decoder transformer, and a feed-forward network that makes the final predictions.
**Gold Nodes**：detr_page_0003_HY_004; detr_page_0006_HY_003
**审核**：DETR p3 支持全局推断和 Hungarian matching；p6 支持 CNN / Transformer / FFN 架构，旧的重复预测解释已补齐。虽属机制+实现多证据检索，但不是严格推导式多跳。
**Codex 动作**：保留，标记为 cross_page_mechanism_implementation，而不是数学推导型 multi-hop。
**Claim Span**：本次未发现明显错配。

### 014 — cross_page / PASS
**Question**：Why is a transformer suitable for DETR, and why add positions?
**Gold Answer**：Self-attention gives global interaction; positions restore spatial information to a permutation-invariant transformer.
**Gold Nodes**：detr_page_0003_HY_005; detr_page_0006_HY_006
**审核**：p3 对 Transformer 全局注意力的解释和 p6 对位置编码的说明相互补充；但 c1 的 supporting_evidence_indices 被设置为 [1]，所选文字不支持 global interaction；c2 span 仅 Transformer encoder.。
**Codex 动作**：将 c1 指向 p3 的 aggregating information from the whole sequence/global computations；c2 指向 p6 的 permutation-invariant + fixed positional encodings 句。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 015 — cross_page / REVISE
**Question**：What makes AI risk socio-technical, and what RMF gains are expected?
**Gold Answer**：Changing data, context, people, and system interactions complicate failures; gains include governance, accountability, information sharing, and TEVV.
**Gold Nodes**：nist_ai_rmf_1_0_page_0006_HY_003; nist_ai_rmf_1_0_page_0024_HY_003
**审核**：问题同时问社会技术风险原因和 RMF 的预期收益；虽然各自得到证据支持，却只是并列摘录两个远距离段落，缺少明确、可核验的机制联系。c1/c2 spans 也过短，不能支持完整 claim。
**Codex 动作**：优先改为围绕具体社会技术风险如何对应 RMF 的治理/TEVV 措施设计可证实桥接；如果两处未给明确关系，就重新抽样。修复 span 后重新独立审核。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 016 — cross_page / REVISE
**Question**：How does the AI RMF connect responsible practice and evaluation?
**Gold Answer**：The RMF frames risk management as aligning AI design and use with human-centered and socially responsible values; NIST plans future work with the AI community to measure whether the framework improves trustworthiness.
**Gold Nodes**：nist_ai_rmf_1_0_page_0006_HY_005; nist_ai_rmf_1_0_page_0024_HY_001
**审核**：p6 描述负责任 AI 的原则，p24 描述 NIST 未来评估框架有效性的计划；问题使用 connect，实际证据没有给出二者之间的具体因果/实施链。c1 误指向 p24。
**Codex 动作**：需缩小题目以问能由两页共同证明的具体关系；否则重采样。c1 必须指向 p6 中 human centricity/social responsibility，c2 指向 p24 evaluations of effectiveness。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 026 — cross_document / PASS
**Question**：What SNR did the initial GW150914 search report, what optimal coherent SNR did the later parameter analysis obtain, and why was the latter higher?
**Gold Answer**：The initial search reported an SNR of about 24. The parameter analysis obtained 25.1 (+/-1.7) because it sampled a larger parameter space more finely.
**Gold Nodes**：gw150914_gr_test_page_0006_HY_001; gw150914_properties_page_0006_HY_006
**审核**：~24 与 25.1(+/-1.7) SNR 及后者更高的原因构成真正的事件级比较。c1 错误指向 25.1 的 E1，没有指向 E0 的 SNR ~24。
**Codex 动作**：c1 改 E0 的 observed signal-to-noise ratio (SNR) ~24；c2 保留 E1 且增加完整 25.1 +/-1.7 范围与 finer parameter space span。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 027 — cross_document / PASS
**Question**：What supports both GW150914’s reality and consistency with GR?
**Gold Answer**：The generic transient search found a false-alarm probability below 2e-6 during the analyzed observing time, while dedicated tests found no statistically significant departure from a binary-black-hole merger governed by the vacuum Einstein equations.
**Gold Nodes**：gw150914_detection_page_0006_HY_005; gw150914_gr_test_page_0006_HY_004
**审核**：E0 解释检测显著性及假警率，E1 描述 GR 一致性；是两个独立检验层面的多文档组合，不能标成严格 causal multi-hop。c1 合并两者却只指向 E1 的 Einstein field equations。
**Codex 动作**：把答案拆成 detection_significance E0 和 GR_consistency E1 两个 atomic claims，分别给对应 spans；类型标成 complementary_validation。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 028 — cross_document / PASS
**Question**：Which final-black-hole quantities determine ringdown frequency and decay time, and how did the GW150914 analysis test their consistency across inspiral and post-inspiral data?
**Gold Answer**：The final black hole’s mass and spin determine ringdown frequency and decay time. The analysis compared mass and spin predicted from the inspiral with post-inspiral estimates and checked the post-peak signal against the least-damped quasi-normal mode.
**Gold Nodes**：gw150914_properties_page_0003_HY_005; gw150914_gr_test_page_0006_HY_005
**审核**：E0 支持最终黑洞质量/自旋控制 ringdown；E1 支持 inspiral 与 post-inspiral 的一致性比较及 QNM，关系合理。但 c2 的 support indices 被误写成 [0]。
**Codex 动作**：c2 指向 E1 中 verify that mass and spin parameters ... / least-damped quasi-normal mode；整体保留。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 029 — cross_document / REVISE
**Question**：How do a modeled matched-filter search and a generic transient search differ in their use of waveform assumptions and noise-background treatment?
**Gold Answer**：Matched filtering uses templates plus vetoes and backgrounds; the generic search finds coincident excess power without a waveform model.
**Gold Nodes**：arxiv_1508_02357_page_0003_HY_001; gw150914_detection_page_0006_HY_002
**审核**：Q 明确要求比较 waveform assumptions 与 noise-background treatment；E0 对 matched filter、非平稳噪声和显著性评估有支持，但没有明确 vetoes；E1 只说明 generic transient search 不使用特定波形模型并识别 coincident excess power，未提供其噪声背景/显著性处理。c2 错指向 E0。
**Codex 动作**：删除未受证据支持的 vetoes，且要么将 Q 缩为 waveform assumptions 和 detection representations 的比较，要么补充 generic search 的背景估计节点；c2 必须指向 E1。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 030 — cross_document / PASS
**Question**：How does cosmological evolution enter a binary-black-hole population forecast, while cosmological redshift limits what a single gravitational-wave event directly reveals about source-frame mass?
**Gold Answer**：The population forecast explicitly models star-formation history and metallicity evolution over cosmic time, together with waveforms and detector sensitivity. For a single event, frequency redshift is degenerate with a mass rescaling, so the signal measures redshifted mass and luminosity distance directly but not redshift; converting to source-frame mass therefore requires the redshift relation m=(1+z)m_source.
**Gold Nodes**：arxiv_1510_04615_page_0003_HY_002; gw150914_properties_page_0003_HY_006
**审核**：两个文档分别给 population forecast 的 cosmic history/metallicity 建模和单事件 mass-redshift 退化；作为“宇宙学在不同分析尺度下扮演什么角色”的比较有效，但不是链式推理。
**Codex 动作**：保留可比性；与 045 有明显同节点/同事实重复，正式集合中建议限制同主题高度重合样本。
**Claim Span**：本次未发现明显错配。

### 032 — cross_document / PASS
**Question**：In coherent gravitational-wave localization, what defines the reconstructed sky position, and what cross-site observations constrain GW150914 to a ring and help resolve its geometry?
**Gold Answer**：The reconstructed sky position is the maximum of a likelihood statistic over sky coordinates. For GW150914, the observed time delay constrains a ring, while amplitude and phase consistency between sites helps resolve the source geometry.
**Gold Nodes**：gNtSaU-1511.05999v3_page_0006_HY_003; gw150914_properties_page_0003_HY_007
**审核**：E0 提供 sky location 的最大似然定义，E1 给 GW150914 时延环以及跨站 amplitude/phase 几何约束，属于方法→事件应用关系。c2 span 仅 waveform by an overall amplitude and phase，未引用 time delay/ring。
**Codex 动作**：将 c2 引文改为 The observed time delay ... allow us to localize the source to a ring ... 和 Phase and amplitude consistency allow us to untangle ...。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 034 — cross_document / PASS
**Question**：How do DETR training and reinforcement-learning feedback differ?
**Gold Answer**：DETR uses supervised targets and Hungarian matching; RL interacts and receives reward.
**Gold Nodes**：detr_page_0003_HY_004; ML1_11_Reinforcement_Learning_1_page_0006_HY_004
**审核**：DETR 的监督标签/Hungarian matching 与 RL 的交互式奖励训练存在清晰对比维度，可以算跨文档 comparison，但不是多跳。c2 错指 E0 DETR 的 Hungarian matching，完全没有指向 RL E1。
**Codex 动作**：c2 支持证据改为 E1 的 No supervision, just a reward signal / experience collected by interacting with environment；可细化 Q 为 supervision and feedback contrast。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 036 — cross_document / PASS
**Question**：Does matching electricity use with renewable energy prove it was carbon-free?
**Gold Answer**：No. NVIDIA reports an annual accounting match between renewable energy purchased or generated and electricity use at controlled sites; the other source states that renewable energy is not necessarily carbon-free.
**Gold Nodes**：nvidia_2026_annual_report_page_0050_HY_006; climate_change_with_ml_page_0005_HY_008
**审核**：NVIDIA 的 100% 电力消费 renewable matching 不能单独证明所有电力使用必然碳零排放；E1 指出 renewable 不必 carbon-free。结论逻辑成立，但应避免把年度能源匹配解释为每时每刻实际使用清洁电力。c1 错指 E1。
**Codex 动作**：c1 改为 NVIDIA E0 的 purchased or generated enough renewable energy to match 100% ...；答案明确 annual/accounting match 与 carbon-free proof 不等价。
**Claim Span**：必须修复（本次独立核查发现引用不足或错位）。

### 041 — cross_document / REVISE
**Question**：What does the block-modeling source mean by an explicitly causal representation, and what caution does the growth-regression source place on causal policy interpretation?
**Gold Answer**：The block-modeling source represents causality structurally through separated inputs and outputs, unidirectional block connections, and blocks as functions. The growth-regression source warns that regressions cannot substitute for causal identification of growth policies, although they can support comparative country analysis and assessment of policy complementarities.
**Gold Nodes**：CyberPhysicalModelingChapter4_page_0006_HY_001; IDU-41f597b3-c201-4fa7-8cac-466610c36a27_page_0006_HY_001
**审核**：结构建模中的 causal/unidirectional blocks 与政策回归的 causal identification 是两个不同层次的“因果”；当前问题只是分别解释两个段落，未说明两个框架具有可比较的共同任务或可验证桥接。虽然逐项事实对，但 Gold 关系偏人为。
**Codex 动作**：重新设计成“为何结构上标记因果不等于统计因果识别”的题目需要额外明确证据，否则建议更换为同一方法领域中具有真实比较维度的两篇文档。
**Claim Span**：本次未发现明显错配。

### 045 — cross_document / PASS
**Question**：What distinct quantity or hypothesis is targeted at three gravitational-wave analysis levels: population forecasting, single-event inference, and tests of general relativity?
**Gold Answer**：Population forecasting models the cosmic-time distribution of progenitors through star-formation and metallicity evolution, together with waveforms and detector sensitivity. Single-event inference measures redshifted mass and luminosity distance, while source-frame mass depends on redshift that the GW signal does not directly measure. GR tests target deviations such as coherent residuals, inconsistency between inspiral- and post-inspiral final-black-hole parameters, non-GR waveform coefficients, or dispersion.
**Gold Nodes**：arxiv_1510_04615_page_0003_HY_002; gw150914_properties_page_0003_HY_006; gw150914_gr_test_page_0006_HY_005
**审核**：三份来源各自给出 population、event inference、GR testing 的不同分析目标；多文档比较真实、并非三跳因果链。但前两份 Gold Nodes 与 030 完全重合，构成潜在样本相关性和事实重复。E0 只明确 SF/metallicity、waveforms/sensitivity，不要过度延伸 'cosmic-time distribution of progenitors'。
**Codex 动作**：保留为 multi-document comparative synthesis；与 030 进行覆盖去重/只保留一条或在更大数据集降权；E0 表述严格限定为模型纳入 SF history/metallicity evolution。
**Claim Span**：本次未发现明显错配。

## Codex 自动修复和重新审核要求

- 不覆盖原始 r2、r1 或 Pilot；创建 `r2_independent_review_fix_v1` 新版本。
- 先修复 claim spans 和 evidence_indices（引用必须包含真正支持 claim 的最小原文）；`char_start/char_end` 由匹配后的原文自动计算；不能只改布尔审核标签。
- 重新进行**独立**的 answer claim entailment、multi-node necessity、shortcut/alternative evidence 搜索，独立模型不能直接读取原有 PASS 作为真值。
- `015/016/029/041` 优先重新写题或重采样；并核查其中已重复的证据结构。
- 将 `011/012`、`030/045` 归入相关性 cluster，不把相同 gold nodes 的多条题当作独立证据覆盖；平衡导出时尽可能增补其他文章。
- 输出新旧对比报告、拒绝和重采样列表、claim-span audit、真实的文档/模态覆盖分布。
- 保留全自动审查，无需强制人工审核；但无法自动核验来源或完整 corpus 时用恰当的 UNKNOWN/INCOMPLETE，而不是声称全覆盖。

## 边界与说明

本次没有获得剩余 8 条自动接受池、独立评审 JSONL 或 validation summary，因此没有复核 28 条池整体，也没有实证核对 frozen node 索引的一致性。当前 `PASS` 为在上传的 evidence_text 内可接受，不表示对原始 PDF 的逐页鉴定。
