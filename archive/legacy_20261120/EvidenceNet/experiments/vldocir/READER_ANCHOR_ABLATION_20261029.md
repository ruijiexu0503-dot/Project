# 原文锚点进入 reader：首轮固定候选对照

2026-10-29，已在 CPU 上生成并校验。不是回答 LLM 的完成结果，不是正式四组端到端评测。

## 实现与复现

代码：`scripts/build_reader_anchor_ablation.py`、`scripts/validate_reader_anchor_packets.py`。
项目根目录执行：

```bash
.venv-magazine-exp1/bin/python EvidenceNet/scripts/build_reader_anchor_ablation.py --out /tmp/reader-anchor-reproduction
.venv-magazine-exp1/bin/python EvidenceNet/scripts/validate_reader_anchor_packets.py --out /tmp/reader-anchor-reproduction
.venv-magazine-exp1/bin/python -m pytest -q EvidenceNet/tests/test_reader_anchor_ablation.py
```

冻结结果：`EvidenceNet/output/reader_anchor_ablation_20261029/`。

- `index.html`：24题 × 4档预算，左右查看实际有边／无边原文输入。
- `packets.jsonl`：192条输入及选择、舍弃、原文位置、hash、edge路径和锚点覆盖。
- `reader_inputs.jsonl`：实际 Qwen3.5 chat 模板序列化输入及精确文本 token 数。
- `blinded_review.jsonl`：879个唯一 question–原文块，隐藏组别与排名、待标注。
- `manifest.json`、`validation.json`：源文件与代码hash、完整性检查。

B/C使用完全相同的旧D_relation每题20候选页。B用query词项IDF与缓存node dense排名RRF60；
C在同一分数上增加一次edge排名RRF60项。此权重是开发探针，不是已验证最优方案。
不是seed traversal：路径来源是旧实验global edge index，记录明确保留这一点。
无gold/答案参与选择；不重建node/edge/embedding。B的候选集同样来自旧图实验，因此不能宣称独立的无图端到端结果。

只传入完整原始parser member，包括原始HTML表格。读取edge锚点前校验member hash和字符offset，
不把800字符截断锚点直接作为证据，不把生成的visual description作为原始证据。
没有图片输入，也未解决跨member指代、跨块年份标题或表格行级裁剪；完整parser块不等于语义完整。
超过剩余预算的完整块跳过并记原因，不截断，也没有额外padding。
同页完全相同文本去重，跨文档相同文字保留，防止混淆主体。

## 执行结果

192条全部通过：原文一致性、相同候选页、证据预算、tokenizer计数与chat模板序列化一致性。
另3个单元测试通过，覆盖预算包含标签、不截断、重复范围、锚点源文件篡改拒绝。

|证据预算|B平均证据token|C平均证据token|B/C锚点覆盖数|B/C平均完整reader输入token|
|---|---:|---:|---|---|
|512|506.42|507.96|13 / 74|576.08 / 577.63|
|1024|1018.25|1018.21|26 / 134|1087.92 / 1087.88|
|2048|2041.71|2042.67|53 / 237|2111.38 / 2112.33|
|4096|4090.58|4090.75|91 / 427|4160.25 / 4160.42|

锚点分母为871个query–edge endpoint span记录，包含未被文本模式支持的锚点；它不是gold集合。
覆盖数增长是加分选择器的机械效果，不能解释为精确率、召回率或答案改善。
完整输入token使用Qwen3.5-35B-A3B实际tokenizer/chat模板，包含generation prefix，关闭thinking；
没有运行生成，不能称为实测GPU费用或API usage。两组相同query的固定模板开销相同。

## 直接查看输入发现的反例（开发者检查，非独立盲评）

### Federer：1024-token预算，边加分挤掉另一年份

问题：In which Grand Slam tournaments did Roger Federer win titles in both 2004 and 2005?

B的E3包括2004 Australian Open/Wimbledon/US Open，E5明确包含2005 Wimbledon/US Open。
C的E3仍有2004摘要，但后续变成2004 Australian Open、Wimbledon过程、Canada Masters等，
2005两个冠军的关键原文块未进入输入。这是“锚点覆盖更多，但多部分证据更不完整”的具体反例。
不能通过强行给已知2005段落加分修补测试题；需要对所有问题一致的query相关性与覆盖选择规则。

### Proxy voting：直接答案被推后

问题：How does the proxy voting work for the election of directors if the authority to vote is withheld for one or more nominees?

1024预算下，B的E1直接解释对未withheld nominees投FOR。
C把董事会推荐、Voting Agreement、董事会构成等置于前面，直接答案降到E6。
直接答案仍在，不代表已经发生答案错误；但说明edge相关性不能代替答案相关性。

### Graf：年份上下文仍可能缺失

完整member包含Barcelona silver medal叙述，却不保证同时带年份标题。
整块保存解决了人为硬截断，没有解决跨块语义上下文依赖。

## 结论与下一步

已接通原文anchor→最终reader输入，并能够精确复核哪些anchor丢失。
本轮不支持“有edge更精准”的结论，不能把直接edge加分部署为最佳pipeline。
下一轮应让edge提供待考察证据，使用共同query–原文相关性评分，并控制同内容冗余、主体与年份覆盖，
明确何时停止扩展。B/C必须使用同一选择器，避免C独享更强reader。
保持本轮结果冻结，另建版本；随后运行同一回答LLM并评估答案与引用，独立复核噪声。
尚未提交这192条的GPU回答任务；本轮是本地定位消融，不涉及新增集群任务。
