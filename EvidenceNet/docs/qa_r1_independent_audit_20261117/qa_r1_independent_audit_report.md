# Node-first QA r1 — 独立证据审核与 Codex 修复清单

> 审核范围：用户提交的3份文本 JSONL（38 条 auto-accepted QA、41 条 independent model reviews、41 条 final gate decisions）；仅基于提供的 evidence_text 及 metadata 做语义审核。未访问 HoreKa2 原始 PDF、全部 retrieval corpus 或实际模型的日志，故不声称完成原始 PDF 级核验或全库无捷径证明。

## 执行结论

- 原自动池：38 条 `FINAL_ACCEPT_AUTOMATIC`；已接受池类别：Single 9 / Cross-page 13 / Cross-document 16。
- **本次严格文本语义审计建议**：**22 KEEP / 13 REVISE / 3 REMOVE**。这是审核建议，不是重新跑完所有自动验证的最终Gold接受率。
- 41 条已有Gate：38 ACCEPT、3 REJECT_OR_REVISE（009/017/022）。本次报告不把这3条当成38条已接受QA再评价；这3条的复审理由与本次发现的失败类型相符，但因未提供完整QA记录，不做独立逐证据审核。
- **跨页 13条**：6 KEEP / 6 REVISE / 1 REMOVE。**跨文档16条**：7 KEEP / 7 REVISE / 2 REMOVE；这是提高证据推理质量的建议性分类。

## 五个系统性问题

1. **默认布尔字段≠可验证执行痕迹**：38 条模型review均标记 `each_gold_node_required=true` 和 `single_node_shortcut_found=false`，但其中 **22条（9 single+13 cross-page）的顶层 `necessity_test` 仍是 null / Reserved for independent review**。跨文档16条虽有摘要解释，但没有 per-node deleted-context 的结果或 corpus-wide shortcut检索日志。不能把模型判断等同于已执行可重复的全库消融。
2. **Claim-level grounding 占位符**：38 条 `answer_claims[].claim_text` 均为 “Answer component N” 类占位，不能审计实际答案的哪一个原子断言由哪些证据支持。必须按真实子句生成 claim→node→source span。
3. **伪多跳与拼接型题目**：大量QA只是把不同节点各自的事实用and连接；形式上的多node必要性（问题人为枚举两/三件事）不等于自然的组合推理。需将真实bridge、comparison、aggregation、cross-domain analogy分层报告。
4. **因果/来源误归属**：#024 把现有新数据集说成支持先前Beyer & Wacker(2023)孟加拉结果；#043 把质量推断作为“检测且符合GR”的必需逻辑环节；#044 混合不同搜索管线。
5. **自动映射ID与检索索引一致性未被三份文件证实**：新语料节点ID如 `real_002_batch_02_Spinoff.2022_page_0003_EU_007` 且映射状态 AUTO_MAPPED_EXACT_SOURCE_ELEMENT。要在实际 frozen retrieval corpus 中逐条验证ID是否存在、text/hash与图数据库一致；只根据命名/来源JSON不能保证已在生产索引。

## 逐条审核（全部38条已接受池）

### nodefirst_v2_r1::001 — KEEP (single_node)

**Question**：What spaceflight need motivated NASA to test indoor agriculture?

**Gold Answer**：Generating oxygen and growing food in space.

**Evidence Nodes**：`real_002_batch_02_Spinoff.2022_page_0003_EU_007`

**独立审核**：证据直接指出NASA测试室内农业的动机：在太空制造氧气与种植食物。答案完整。

**建议修改**：保留；标记为低复杂度 single-node fact。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::002 — KEEP (single_node)

**Question**：What was the Mars Helicopter intended to demonstrate?

**Gold Answer**：The viability and potential of heavier-than-air vehicles on Mars.

**Evidence Nodes**：`real_003_batch_03_NASA_Spinoff_2021_page_0002_EU_001`

**独立审核**：证据直接说明火星直升机验证火星上重于空气飞行器的可行性；Perseverance 被 OCR 成 river，但不影响答案。

**建议修改**：保留 QA，OCR 错字记录在 source-quality 日志，不应据此统一拒收。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::003 — KEEP (single_node)

**Question**：How does the Hubble image area compare with the full Veil Nebula?

**Gold Answer**：About 2 light-years are shown; the nebula spans about 110 light-years.

**Evidence Nodes**：`real_006_batch_06_Spinoff2018_page_0002_EU_005`

**独立审核**：同一段给出图像覆盖约2光年和星云总跨度110光年，两数值正确。

**建议修改**：保留；分类为单节点对比检索。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::004 — KEEP (single_node)

**Question**：What heats Europa’s subsurface ocean, and how many flybys were planned?

**Gold Answer**：Jupiter’s tidal forces create internal friction; 45 flybys were planned.

**Evidence Nodes**：`real_007_batch_07_Spinoff2017_page_0002_EU_005`

**独立审核**：同一段同时支持木星潮汐加热机制及计划45次飞掠；属于双事实同节点，不是多跳 bridge。

**建议修改**：保留，reasoning_type由 bridge 改为 composite_fact 或 fact。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::005 — KEEP (single_node)

**Question**：Which Hubble operational anniversary was celebrated in 2015?

**Gold Answer**：Its 25th year in operation.

**Evidence Nodes**：`real_008_batch_08_Spinoff2016_page_0006_EU_002`

**独立审核**：证据明确写2015年庆祝哈勃空间望远镜运行25周年。

**建议修改**：保留；属于容易的实体/年份事实题，注意难度分层。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::006 — KEEP (single_node)

**Question**：How was the night-side Earth image assembled?

**Gold Answer**：Suomi NPP data from April and October 2012 were mapped over existing Earth imagery.

**Evidence Nodes**：`real_009_batch_09_Spinoff2015_page_0002_EU_006`

**独立审核**：证据支持Suomi NPP卫星2012年4月和10月观测数据与已有地球影像叠加。

**建议修改**：保留，略微澄清是合成的地球暗侧模拟视图。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::007 — KEEP (single_node)

**Question**：How did the Spinoff 2012 introduction say exploration creates Earth benefits?

**Gold Answer**：Researchers and entrepreneurs build Earth applications on exploration, spacecraft, and aviation technology.

**Evidence Nodes**：`real_011_batch_11_Spinoff2012_page_0007_EU_004`

**独立审核**：正文支持将航空航天探索技术发展成地面应用，问题和答案匹配；但题目概括性较强。

**建议修改**：保留但标为低判别力/概念题；避免同一泛化主题过度采样。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::008 — KEEP (single_node)

**Question**：What hardware did STS-117 deliver to the ISS?

**Gold Answer**：The S3/S4 truss segments and another pair of solar arrays.

**Evidence Nodes**：`real_016_batch_16_basic_version_07_page_0003_EU_002`

**独立审核**：STS-117运送S3/S4桁架段及另一组太阳能电池阵列均有直接证据。

**建议修改**：保留。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::010 — KEEP (single_node)

**Question**：What human factors were credited for aviation and spaceflight advances?

**Gold Answer**：Hard work, perseverance, and willingness to overcome setbacks.

**Evidence Nodes**：`real_020_batch_20_spin03_page_0005_EU_001`

**独立审核**：硬工作、坚持及克服挫折在证据中明确，但属于前言宣传性陈述，检索难度和科研性偏低。

**建议修改**：可以保留在简单题配额，优先考虑后续更技术性的同节点替代。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::011 — REVISE (cross_page)

**Question**：Why do variable low-carbon sources need buffers, and what can ML improve?

**Gold Answer**：Their output follows external conditions while supply must match demand; ML improves forecasting, scheduling, control, and markets.

**Evidence Nodes**：`climate_change_with_ml_page_0005_HY_005`, `climate_change_with_ml_page_0006_HY_001`

**独立审核**：跨页必要性不成立：第6页的单个证据已描述可变电源输出波动、缓冲设备以及ML在预测/调度/控制/市场上的作用；第5页并非回答必需。另外答案“supply must match demand”当前两段未逐字明确。

**建议修改**：改写成第5页独有信息与第6页独有信息之间的真正跨页问题，或直接降为 single-node；纠正未经明示的供需断言。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::012 — REVISE (cross_page)

**Question**：What changes decarbonize electricity, and how can ML support balancing?

**Gold Answer**：Expand low-carbon supply, reduce existing fossil emissions, act broadly, and improve forecasts, schedules, control, and markets.

**Evidence Nodes**：`climate_change_with_ml_page_0005_HY_003`, `climate_change_with_ml_page_0006_HY_001`

**独立审核**：两页各回答一个独立的子问：低碳转型措施、ML平衡工具。事实基本有支持，但更多是拼接清单，跨页推理关系弱。

**建议修改**：要求具体的因果/条件桥接，例如从化石备用机组过渡到储能时ML如何帮助，并重新抽取必要证据。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::013 — REVISE (cross_page)

**Question**：How does DETR avoid duplicate predictions, and what implements its detector?

**Gold Answer**：Hungarian matching gives each target a unique prediction; a CNN, transformer, and feed-forward network implement the detector.

**Evidence Nodes**：`detr_page_0003_HY_004`, `detr_page_0006_HY_003`

**独立审核**：问题说DETR怎样避免重复预测，答案只写Hungarian matching确保每个目标有唯一匹配；原文同时强调全局交互/置换不变集损失，唯一匹配本身不足以完整解释去重机制。

**建议修改**：补全全局set prediction及双边匹配的作用，或将问题精准改为 Hungarian matching 如何保证唯一匹配 + DETR架构。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::014 — KEEP (cross_page)

**Question**：Why is a transformer suitable for DETR, and why add positions?

**Gold Answer**：Self-attention gives global interaction; positions restore spatial information to a permutation-invariant transformer.

**Evidence Nodes**：`detr_page_0003_HY_005`, `detr_page_0006_HY_006`

**独立审核**：第3页解释全局自注意力优势，第6页解释置换不变性及位置编码需要，问答和各页互补。

**建议修改**：保留；可以把问题聚焦到 DETR 如何同时利用 global context 与 spatial position。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::015 — KEEP (cross_page)

**Question**：What makes AI risk socio-technical, and what RMF gains are expected?

**Gold Answer**：Changing data, context, people, and system interactions complicate failures; gains include governance, accountability, information sharing, and TEVV.

**Evidence Nodes**：`nist_ai_rmf_1_0_page_0006_HY_003`, `nist_ai_rmf_1_0_page_0024_HY_003`

**独立审核**：AI风险的社会技术性质与RMF可能带来的治理/问责/TEVV改进分别有证据，逻辑统一在同一框架内。

**建议修改**：保留；将答案中多项收益分配到具体claim，而非占位 Answer component。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::016 — KEEP (cross_page)

**Question**：How does the AI RMF connect responsible practice and evaluation?

**Gold Answer**：It aligns development with human-centered values; future work measures bottom-line trustworthiness gains.

**Evidence Nodes**：`nist_ai_rmf_1_0_page_0006_HY_005`, `nist_ai_rmf_1_0_page_0024_HY_001`

**独立审核**：第6页解释负责任AI的价值导向，第24页明确说NIST计划未来评估RMF效果。

**建议修改**：保留；答案用 will evaluate / plans to measure，避免暗示效果已经测得。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::018 — KEEP (cross_page)

**Question**：Why are detector-frame masses redshifted, and what source masses were inferred?

**Gold Answer**：Redshift rescales mass by 1+z; GW150914 source masses were about 36 and 29 solar masses.

**Evidence Nodes**：`gw150914_properties_page_0003_HY_006`, `gw150914_properties_page_0006_HY_007`

**独立审核**：红移质量m=(1+z)m_source及36/29太阳质量来自不同页面，形成相关联的公式和具体实例。

**建议修改**：保留；如需精确Gold，可在答案加上原文给出的置信区间。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::019 — REVISE (cross_page)

**Question**：What governs ringdown, and how were two waveform families handled?

**Gold Answer**：Final mass and spin govern ringdown; consistent results were combined with equal weight.

**Evidence Nodes**：`gw150914_properties_page_0003_HY_005`, `gw150914_properties_page_0006_HY_004`

**独立审核**：第一页解释ringdown频率/衰减由末态质量自旋控制；第二页解释两种波形模型后验等权汇合。两个事实都对，但问题是并列拼接，没有说明为何模型平均与ringdown存在必要联系。

**建议修改**：重建围绕模型选择不确定性如何影响最终黑洞参数/ringdown解释的跨页问题；若无证据桥，拆成两题。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::020 — REVISE (cross_page)

**Question**：How do telomere dysfunction and inflammaging differ?

**Gold Answer**：Telomere attrition is cell-intrinsic damage; inflammaging is a systemic inflammatory state.

**Evidence Nodes**：`hallmarks_of_aging_page_0006_HY_002`, `hallmarks_of_aging_page_0018_HY_002`

**独立审核**：原文E0证明端粒耗损是衰老标志，但没有直接把它定义成“cell-intrinsic damage”；E1支持系统性炎症。答案的对比维度带有额外推断。

**建议修改**：改为原文直接支持的“端粒耗损与炎症性衰老分别涉及什么变化”，不要仅靠常识强加cell-intrinsic分类。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::021 — KEEP (cross_page)

**Question**：Which interventions target histones and inflammatory-neuroendocrine signaling?

**Gold Answer**：Histone-complex or demethylase manipulation extends invertebrate lifespan; NF-kB inhibition or GnRH restoration slows mouse phenotypes.

**Evidence Nodes**：`hallmarks_of_aging_page_0006_HY_004`, `hallmarks_of_aging_page_0018_HY_003`

**独立审核**：组蛋白甲基化/去甲基酶干预寿命与NF-kB、GnRH在小鼠衰老干预证据相互独立，比较维度明确。

**建议修改**：保留；注意物种与具体干预结果不等同，Gold答复应保持原文限制。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::023 — KEEP (cross_page)

**Question**：What limitation motivates growth regressions, and what can they still do?

**Gold Answer**：Standard diagnostics rarely identify policy drivers; regressions compare countries and policy correlates without proving causality.

**Evidence Nodes**：`IDU-41f597b3-c201-4fa7-8cac-466610c36a27_page_0004_HY_003`, `IDU-41f597b3-c201-4fa7-8cac-466610c36a27_page_0006_HY_001`

**独立审核**：前一页说明既有方法难以识别政策驱动因素，后一页说明增长回归能做国家比较但不能代替因果识别。

**建议修改**：保留，建议用“哪些既有方法的限制与增长回归的非因果用途形成对照”收紧问题。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::024 — REMOVE (cross_page)

**Question**：How does the growth-data resource support the Bangladesh comparison?

**Gold Answer**：Its 150-country, 1970–2019 coverage permits placing Bangladesh’s improvements in the global top 5% of 15-year periods.

**Evidence Nodes**：`IDU-41f597b3-c201-4fa7-8cac-466610c36a27_page_0004_HY_005`, `IDU-41f597b3-c201-4fa7-8cac-466610c36a27_page_0006_HY_004`

**独立审核**：重大出处关系错误：E0介绍“本文”新建的约150国1970–2019数据集，并明确它基于Beyer和Wacker(2023)等前人研究；E1描述的孟加拉国top 5%结果是Beyer和Wacker(2023)的先前研究。证据不支持“新数据资源使这一旧研究结论成为可能”。

**建议修改**：废弃现有因果/资源支持问题；若要保留，必须换成“本文的数据集覆盖什么范围，前人对孟加拉国发现了什么”的非因果对比，且应重新判断是否仅为拼接。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::025 — REVISE (cross_page)

**Question**：What redundancy does DLR use for positioning and remote-vehicle control?

**Gold Answer**：It fuses GNSS with other sensors and uses multiple communications links plus automatic stopping.

**Evidence Nodes**：`DLRmagazine_176_EN_page_0009_HY_006`, `DLRmagazine_176_EN_page_0012_HY_012`

**独立审核**：两页分别谈GNSS多传感器融合和SHERP多通信链路。答案中的“失联自动停车”是fail-safe机制，不等同redundancy；将不同系统统称为一种冗余设计过度概括。

**建议修改**：明确区分导航传感器冗余、通信链路冗余和失联安全停机，聚焦共同的可靠性维度。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::026 — KEEP (cross_document)

**Question**：What SNR did the initial GW150914 search report, what optimal coherent SNR did the later parameter analysis obtain, and why was the latter higher?

**Gold Answer**：The initial search reported an SNR of about 24. The parameter analysis obtained 25.1 (+/-1.7) because it sampled a larger parameter space more finely.

**Evidence Nodes**：`gw150914_gr_test_page_0006_HY_001`, `gw150914_properties_page_0006_HY_006`

**独立审核**：E0给GW150914观测SNR约24，E1给后续最优相干SNR 25.1±1.7与更大、更细参数搜索的解释。存在具体可比数值与原因。

**建议修改**：保留；在全语料检索可能同时含两数值的其他节点，记录可能的alternative gold set。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::027 — KEEP (cross_document)

**Question**：What supports both GW150914’s reality and consistency with GR?

**Gold Answer**：A false-alarm probability below 2e-6 and no significant deviation in dedicated GR tests.

**Evidence Nodes**：`gw150914_detection_page_0006_HY_005`, `gw150914_gr_test_page_0006_HY_004`

**独立审核**：搜索显著性与GR符合性测试从不同文档提供互补结论，问答直接有依据。

**建议修改**：保留；可将显著性具体表述为在分析时长内p<2e-6，避免与其他分析的p混淆。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::028 — KEEP (cross_document)

**Question**：Which final-black-hole quantities determine ringdown frequency and decay time, and how did the GW150914 analysis test their consistency across inspiral and post-inspiral data?

**Gold Answer**：The final black hole’s mass and spin determine ringdown frequency and decay time. The analysis compared mass and spin predicted from the inspiral with post-inspiral estimates and checked the post-peak signal against the least-damped quasi-normal mode.

**Evidence Nodes**：`gw150914_properties_page_0003_HY_005`, `gw150914_gr_test_page_0006_HY_005`

**独立审核**：一个节点给末态质量/自旋决定ringdown频率与衰减时间，另一节点给GW150914跨inspiral/post-inspiral的检验，是有意义的机制到实验桥接。

**建议修改**：保留；修正文中轻微OCR错误，不影响关键证据。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::029 — KEEP (cross_document)

**Question**：How do modeled and generic GW searches address noise differently?

**Gold Answer**：Matched filtering uses templates plus vetoes and backgrounds; the generic search finds coincident excess power without a waveform model.

**Evidence Nodes**：`arxiv_1508_02357_page_0003_HY_001`, `gw150914_detection_page_0006_HY_002`

**独立审核**：两个独立文档对比有波形模板的matched filtering与无指定波形的coincident excess power搜索，维度合理且直接可支撑。

**建议修改**：保留；题目改成“对波形模型与噪声背景的处理差异”更精确，避免暗示两者都提供同等的噪声抑制机制。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::030 — REVISE (cross_document)

**Question**：Why do population forecasts model cosmic history while event analysis separates source mass?

**Gold Answer**：Forecasts need star formation, metallicity, and sensitivity; event mass is redshifted by 1+z.

**Evidence Nodes**：`arxiv_1510_04615_page_0003_HY_002`, `gw150914_properties_page_0003_HY_006`

**独立审核**：资料分别涉及星形成/金属丰度下的总体种群预测和单事件的宇宙学红移质量，确有研究对象差异；但题目问“为什么需要”两套方法，证据并没有给出这种必然因果。

**建议修改**：改成明确比较各分析的目标变量和前提，而非无证据的“Why”; 若仅并列知识点则降为aggregation slice。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::031 — REVISE (cross_document)

**Question**：What can compression lose, and what does the GW statistic combine?

**Gold Answer**：It can lose hypothesis information; the statistic combines coherent signal energy and residual noise.

**Evidence Nodes**：`arxiv_1511_05955_page_0003_HY_004`, `gw150914_detection_page_0006_HY_003`

**独立审核**：数据处理不等式说明统计压缩可能损失假设信息，GW检索统计量使用相干能量与残差噪声；证据没有证明实际η_c的损失性质，也没有将两者连成推理关系。

**建议修改**：不要把一般信息论原理当作该GW检测统计量的具体理论推导；寻找直接将DPI用于该统计量的节点，否则拆题或做显式并列比较。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::032 — KEEP (cross_document)

**Question**：In coherent gravitational-wave localization, what defines the reconstructed sky position, and what cross-site observations constrain GW150914 to a ring and help resolve its geometry?

**Gold Answer**：The reconstructed sky position is the maximum of a likelihood statistic over sky coordinates. For GW150914, the observed time delay constrains a ring, while amplitude and phase consistency between sites helps resolve the source geometry.

**Evidence Nodes**：`gNtSaU-1511.05999v3_page_0006_HY_003`, `gw150914_properties_page_0003_HY_007`

**独立审核**：第一个文档明示最大似然定位，第二个文档给时间延迟环及幅相约束；共同说明具体定位过程。

**建议修改**：保留。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::034 — KEEP (cross_document)

**Question**：How do DETR training and reinforcement-learning feedback differ?

**Gold Answer**：DETR uses supervised targets and Hungarian matching; RL interacts and receives reward.

**Evidence Nodes**：`detr_page_0003_HY_004`, `ML1_11_Reinforcement_Learning_1_page_0006_HY_004`

**独立审核**：DETR双边监督匹配与RL交互奖励信号形成清晰的监督来源对比，事实基本充分。

**建议修改**：保留为跨领域comparison题，不要将其描述为依赖推理链的multi-hop。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::036 — KEEP (cross_document)

**Question**：Does matching electricity use with renewable energy prove it was carbon-free?

**Gold Answer**：No; NVIDIA reports a renewable match, while renewable energy is not necessarily carbon-free.

**Evidence Nodes**：`nvidia_2026_annual_report_page_0050_HY_006`, `climate_change_with_ml_page_0005_HY_008`

**独立审核**：NVIDIA陈述可再生能源采购/发电匹配100%用电，另一文档指出renewable不必然carbon-free，足以推断不能以match声明证明零碳。

**建议修改**：保留；明确match属于账面匹配，不是每小时电网供电都零碳。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::038 — REVISE (cross_document)

**Question**：For the monopole search and the Galactic-centre pulsar survey, which physical effect made the standard detection regime unsuitable, and what replacement strategy was used in each case?

**Gold Answer**：Highly ionizing monopoles lose energy before reaching the calorimeter, so the search used forward-neutron and pixel-cluster triggers. Ionized gas time-broadens pulsar pulses at standard radio frequencies, so the survey observed at 8–12 GHz where scattering is weaker.

**Evidence Nodes**：`CERNCourier2025JanFeb-digitaledition_page_0006_HY_007`, `CERNCourier2026MayJun-digitaledition_page_0006_HY_022`

**独立审核**：单极子触发器与银心脉冲星观测的确都体现物理信号损失导致标准检测方式失效，但两领域之间无现实依赖；是人为选择的跨主题类比题，作为Graph Stress Gold的生态有效性弱。

**建议修改**：如保留，应归为cross-domain analogy专门分层、减少比例；优先寻找同领域关联的跨文档证据。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::039 — REMOVE (cross_document)

**Question**：How does past Galactic-centre activity differ from the pulsar problem?

**Gold Answer**：Fermi lobes indicate past activity; ionized gas scatters and broadens pulsar signals.

**Evidence Nodes**：`CERNCourier2022NovDec-digitaledition_page_0006_HY_021`, `CERNCourier2026MayJun-digitaledition_page_0006_HY_022`

**独立审核**：两个资料只共同涉及银河系中心：过去活动证据与脉冲星传播散射没有真正对照或桥接。第一个证据OCR明显污染（“Strong films”“Fermi galaxies”等）。

**建议修改**：重采样另一组能共享明确研究问题或因果桥的证据；先隔离并校验受损的源段。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::041 — REVISE (cross_document)

**Question**：Why should causal block models and growth regressions not be read alike?

**Gold Answer**：Blocks encode directed causality; growth regressions are descriptive, not causal identification.

**Evidence Nodes**：`CyberPhysicalModelingChapter4_page_0006_HY_001`, `IDU-41f597b3-c201-4fa7-8cac-466610c36a27_page_0006_HY_001`

**独立审核**：不同领域文档有可比的因果性解释，但结构建模中的单向函数连接本身不等于实证因果识别；答案容易让人误读两者处在同一可比较的因果证明层级。

**建议修改**：将对比精确限定为“建模中显式有向关系表示”与“增长回归不能替代因果识别”；不能暗示Block自带真实因果证据。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::043 — REVISE (cross_document)

**Question**：What three layers establish GW150914 as a detected event consistent with GR?

**Gold Answer**：Search significance, source-mass inference, and dedicated GR consistency tests.

**Evidence Nodes**：`gw150914_detection_page_0006_HY_005`, `gw150914_properties_page_0006_HY_007`, `gw150914_gr_test_page_0006_HY_004`

**独立审核**：将source-mass inference列为“确立检测且符合GR”的必要验证层欠合理：质量推断是源属性表征，不是检测显著性或GR检验的必要逻辑步骤。三文档的必要性由题目预设的三层构造出来。

**建议修改**：若保留，改成“GW150914的统计显著性、源属性和GR检验分别报告什么”，并明确此为multi-source event dossier/aggregation而非严格多跳。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::044 — REVISE (cross_document)

**Question**：How do noise controls, significance, and theory tests form a validation chain?

**Gold Answer**：Bad data are removed, significance is measured empirically, and waveform tests check GR.

**Evidence Nodes**：`arxiv_1508_02357_page_0003_HY_002`, `gw150914_detection_page_0006_HY_005`, `gw150914_gr_test_page_0006_HY_004`

**独立审核**：E0描述某匹配滤波搜索管线的data-quality控制，E1描述另一GW150914搜索显著性，E2是GR检验；现有Question称之为一个连续validation chain，容易把不同分析方法误当作同一流程。

**建议修改**：重新标明是不同分析环节/独立交叉验证证据，或寻找同一pipeline的直接来源形成真实链路。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::045 — REVISE (cross_document)

**Question**：Why do population forecasts, event inference, and gravity tests need distinct models?

**Gold Answer**：They model cosmic populations, redshifted event parameters, and departures from GR.

**Evidence Nodes**：`arxiv_1510_04615_page_0003_HY_002`, `gw150914_properties_page_0003_HY_006`, `gw150914_gr_test_page_0006_HY_005`

**独立审核**：三个节点可分别描述种群预测、红移质量推断和GR偏离检验，但并未论证为何必须使用“不同模型”；答案仅罗列研究任务，论证不足。

**建议修改**：将why改为“各自解决什么不同分析问题”，标为multi-source comparison/aggregation；若想保留why，增加各模型不可互换的证据。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

### nodefirst_v2_r1::050 — REMOVE (cross_document)

**Question**：How do entropy, data processing, and a GW statistic lead from uncertainty to detection?

**Gold Answer**：Entropy defines uncertainty, data processing limits compression, and the statistic combines coherent energy with residual noise.

**Evidence Nodes**：`entropy_page_0010_HY_011`, `arxiv_1511_05955_page_0003_HY_004`, `gw150914_detection_page_0006_HY_003`

**独立审核**：entropy节点只是提出“如何测量不确定性”的问题，未给出熵的定义或公式；DPI与GW η_c的具体联系也未由所给文本证明。“从不确定性到检测”的三段推理链为人为拼接。

**建议修改**：删除当前Gold；若要构造信息论到GW的真实三跳，应找熵定义、数据处理边界和适用于该GW statistic的直接推导桥接。

**原审核状态**：FINAL_ACCEPT_AUTOMATIC；原模型复审=True

## 给Codex的执行指令

1. 逐个 draft_id 精确匹配，不要按行号假定原始 Pilot 中38个连续。保留 r1 数据，输出 r2 新版本；原本的 38 个 `FINAL_ACCEPT_AUTOMATIC` 不得被本报告直接覆盖。
2. 先处理 `REMOVE` 的 #024 / #039 / #050，和 `REVISE` 的 #011 / #013 / #030 / #031 / #043 / #044 等高风险项；以 evidence span 为依据修题，无法真正修复时自动重采样。
3. 重新建立 **answer_claims 真实原子断言**，不再用“Answer component 1/2”。保存每条 claim 在各来源节点的精确文本span（以及PDF/page image若需要）。
4. 对每个multi-node QA运行并保存 **node deletion** 过程与全库潜在 shortcut 检索：逐个删除Node后让独立judge仅根据剩余Evidence回答，记录 completeness/sufficiency，而不是只保存true/false。
5. 建立至少两种质量标签：`evidence_sufficiency` 与 `integrative_reasoning`。前者是Gold是否支持答案，后者是问题是否需要跨证据的解释/比较/推理；不能靠人为枚举不相关的小事实得到cross-document优质Gold。
6. 核对 Node 映射与 **真正被评估的 frozen retrieval index**：ID存在、source JSON路径存在、page和source element匹配、文本或内容hash一致，映射结果输出可核查日志。此项完全可以自动执行，不引入逐条人工批准。
7. 审查训练/生成/评估泄漏：如候选来源依赖当前图边，应单独标记，不得通过图偏置选Gold。保留修复前后真实通过率、抽样次数与拒绝原因。
8. 只在 r2 再次通过所有自动化验证后写入新 Gold；未通过、待校验及别名替换保持明确状态。更新后只从真正合格池按20/30/50抽样，不为了比例放宽门槛。

## 关于数据限制

- 原始三份文件只覆盖 38 ACCEPT 的完整QA和41条 review/gate决策，不包括 30条 balanced export的原文件；因此我不能独立核实那30条的具体组成、选择逻辑及所有Evidence ID与final检索库是否一致。
- 原始PDF和整个HoreKa2节点库未包含在本次上传中；本审核中`KEEP`是“按已提供的证据文本可接受”的候选判断，不等同于已经过源PDF与全库捷径的最终定论。
