# 冻结无edge baseline的AP补充评测

2026-10-16。直接读取`vldocir_no_edge_v1_20261011`保存的六组页面得分，未重新调用模型，
没有修改只读baseline。24个问题、518页及官方gold保持一致，逐问题检查完整页面评分覆盖。

AP是单问题指标，mAP是平均值。这里沿用六问题类型宏平均。
AP@k = 前k名各相关页处Precision的和 / 全部相关页数R；full AP使用完整518页排名。
另在JSON报告分母min(R,k)的截断AP，避免定义混淆。并列分数沿用原评测器的页面ID排序。

| 方法 | mAP@3 | mAP@5 | mAP@10 | 完整排名mAP |
| --- | ---: | ---: | ---: | ---: |
| page_mean | 45.49% | 51.32% | 55.18% | 56.07% |
| page_windows | 60.07% | 61.63% | 65.53% | 66.90% |
| parser_atoms | 58.68% | 60.03% | 61.66% | 63.39% |
| parser_atoms_visual | 60.42% | 62.29% | 64.39% | 65.40% |
| hybrid_text | 58.68% | 60.03% | 61.66% | 63.39% |
| hybrid_visual | 61.11% | 62.78% | 64.35% | 65.75% |

hybrid_visual相较parser_atoms_visual的mAP@5增加0.4861个百分点；24个问题中
1个提高、1个降低、22个相同。完整mAP增加0.3466个百分点，2胜3负19平。
不能由此宣称稳定优势。完整mAP最高是page_windows，不是hybrid_visual；不同截断
指标的排序确有差异，冻结的edge对照对象不因此悄悄更换。

结果目录：`EvidenceNet/output/vldocir_baseline_ap_20261016/`，包含REPORT.md、comparison.json
（逐问题、逐类型、截断与完整AP、配对变化）和输入SHA256清单。
实现：`scripts/evaluate_vldocir_ap.py`。3项独立数学用例通过，覆盖重复页面、截断分母、无命中及空gold。

```bash
python EvidenceNet/scripts/evaluate_vldocir_ap.py
```

本次只补算已有排名的指标，不比较作者全库模型、不建立edge、不重新选择语料。
