# 无 edge 检索 baseline

冻结 ID：`vldocir_no_edge_v1_20261011`。
本机快照位于 `EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011/`，
产物被 Git 忽略，文件和目录设为只读，SHA-256 清单用于完整性检查。

固定输入为 24 个查询、518 页、7,291 个 evidence nodes 和 262 个视觉组件。
数据集 revision 为 `40a1818110c20e9279bbb4a3b6283ceac2d631ba`；检索作业 `66352`。
六组输出、完整评分、评测标签、节点成员、图片描述、预处理页面与实际运行代码均保存。
Embedding 权重不重复复制，但记录其哈希；tokenizer 和模型配置保存到快照。
快照保留修复后的未提交代码，不能仅用原 Git commit 代替实际代码版本。

| 方法 | Macro Recall@5 | Macro nDCG@5 | Macro RecallAll@5 |
|---|---:|---:|---:|
| page_mean | 77.08% | 61.37% | 58.33% |
| page_windows | 72.92% | 68.01% | 54.17% |
| parser_atoms | 81.25% | 69.04% | 62.50% |
| parser_atoms_visual | 83.33% | 71.32% | 66.67% |
| hybrid_text | 81.25% | 69.04% | 62.50% |
| **hybrid_visual** | **83.33%** | **71.76%** | **66.67%** |

后续 edge 实验以 **hybrid_visual** 为直接对照。保持查询、检索库、节点及成员、
图片描述、embedding 权重、64-token 标题上下文、384-token 窗口、320-token stride、
页面聚合和评测指标不变，只增加 edge 扩展或图重排。
标签仅用于评测，不可用于生成 edge。实验输出另写目录，不覆盖 baseline。
本轮为小规模选定语料 pilot，不能与作者的全库成绩直接比较。

从仓库根目录检查：

```bash
python EvidenceNet/scripts/verify_retrieval_baseline.py \
  EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011 --check-encoder
```

快照内的 `manifest.json` 与 `manifest.sha256` 固定文件内容。
复制的视觉描述只修改 crop 存储路径；描述文本、节点 ID 和 crop 哈希不变。
