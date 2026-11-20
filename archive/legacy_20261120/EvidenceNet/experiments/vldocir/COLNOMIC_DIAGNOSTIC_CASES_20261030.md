# ColNomic 在四个诊断问题上的表现

2026-10-30重新读取历史完整分数，未调用GPU、未改变gold或候选库。对照是我们在相同24query/518页pilot上使用HF发布的ColNomic-7B原图检索器的两次运行（H100 82567与Horeka A100 5199443），不是作者在388548页全集上的逐题官方排名，也不是Ctx/Rerank/Ensemble。

官方定义与模型来源：
- https://huggingface.co/datasets/anonymous-8421/VL-DocIR （页级评测；公开总体结果）
- https://huggingface.co/nomic-ai/colnomic-embed-multimodal-7b （原图/问题多向量检索器）

读取两个scores文件并核对各自result manifest SHA256；每组24×518分数无重复且完整，采用原评测器的页面ID平局排序。复算8项ColNomic逐题AP@5与原metrics.json完全一致。两次运行这四题gold排名相同，其他非gold排名和总体指标略有差异，未混用总体结果。

|问题|ColNomic gold页排名|原无edge hybrid_visual gold页排名|ColNomic Recall@5|原节点 Recall@5|ColNomic AP@5|原节点 AP@5|
|---|---|---|---:|---:|---:|---:|
|Federer 2004/2005共同大满贯|2004文p1=6；2005文p2=4|同两页=1、12|50%|50%|12.50%|50.00%|
|A2063G阳性率变化|p5=1|p5=2|100%|100%|100%|50%|
|Graf奥运奖牌及年份|p1=1，p2=2|p1=1，p2=3|100%|100%|100%|83.33%|
|CePO4/CeVO4 Ce4f局域化|p4=2，p8=5|p4=1，p8=2|100%|100%|45%|100%|

AP@5分母是该query全部gold页数。Federer两张gold均进入ColNomic Top10，但原无edge节点组的第二张gold排名12，尚未进入Top10。注意这是页面排名，不是Top10 EvidenceNode排名；不可混用。

## 对当前问题的解释

A2063G、Graf两题，ColNomic和我们的原始节点检索都已把gold页召回；旧query覆盖选择却丢弃了具体年份率或其他奖牌。主要缺陷发生在来源选择，不需要先靠新增edge才能修好。

Federer在Top5层面两者各漏一张gold页，但漏的不是同一张；Top10时ColNomic完整。我们固定候选实验已含明确2004和2005原文，之后错误地只保留单赛季表格，说明排序和证据充分性是两个不同问题，需要分别修正。

Ce4f原始节点检索的gold页排名优于ColNomic，因此这一题不能作为“ColNomic完全找不到，edge救回”的例子。它被选为新版导航smoke，是因为该冻结图只有这题存在一跳之外的第二跳新节点；这是代码/路径测试，不预先保证收益。

这些逐题页级成绩不代表最终LLM答案正确，也没有说明ColNomic能以同样少的tokens返回完整段落证据。新版应检验：召回不丢的前提下，是否保留充分且更少的原文；不能把“只给几百tokens”单独当成提升。

机器可读数据：`EvidenceNet/output/span_edge_audit_20261030/colnomic_case_comparison.json`。
复现（从Project目录）：`python EvidenceNet/output/span_edge_audit_20261030/reproduce_colnomic_cases.py`。
