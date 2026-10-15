# Edge 开发前的检查点

2026-10-15。本次主分支提交保存节点生成修复和已经完成的无 edge 检索 baseline；后续连边工作放入 `feature/evidence-edges`。提交不包含本地数据、模型、结果、日志、集群 sbatch 或新的连边实验代码。

## 文章分割检查结论

**文章分割已有代码和独立入口，但未成为目前 Dolphin → hybrid-v2 evidence nodes 的自动执行阶段。** 不应把文章分组可视化、已知论文文档身份或候选检索分组当作已完成的杂志文章分割。

| 路线 | 实际行为 | 限制 |
| --- | --- | --- |
| [当前 hybrid-v2 节点驱动](../EvidenceNet/scripts/run_vldocir_nodes.py) | describe → candidates → decide → assemble，并审计节点来源覆盖 | 不调用文章分割，也不生成跨页文章归属。 |
| [确定性 EvidenceNet CLI](../EvidenceNet/evidence_graph/cli.py) | `build-nodes` / `run` 进入节点构建；`segment-content-units` 是独立命令 | 普通 `run` 不会自动执行分割。 |
| [独立内容分割](../EvidenceNet/evidence_graph/semantic_pipeline.py) | `run_content_unit_segmentation` 调用文章分割器 | semantic pilot 的 CERN 配置选项只决定是否读取既有 `hybrid_content_unit_assignments.jsonl`；缺失时抛错，不会自动补跑。 |
| [文章图阶段](../EvidenceNet/pipeline_steps/step2_c_document_article_graph.py) | 使用 component 快照、文档模式和显式跨页决定建立文章归属及阅读关系 | 是可选 shadow 阶段；不是 hybrid-v2 主驱动中的必经步骤。 |
| [来源匹配的文章展示](../EvidenceNet/scripts/viewer_article_membership.py) | 按 fragment / visual ID、文字和几何匹配已有 flow | 只导入或展示分组；拒绝的提议仍带拒绝标志，不能当作成功分割。 |

本地近期输入核对：六篇论文的 763 个节点用已知单论文文档身份。此前 550 个混合材料节点中，207 个属于已知单论文、174 个为 `PAGE_LOCAL_ONLY`、169 个为 `UNRESOLVED`。合计 1,313 个节点中，970 个有已知单论文身份；另外 343 个不能据此宣称完成了跨页文章分割。检查的是实际节点快照，不是分割准确率评测。

这些后续实验入口仍留在 edge 分支工作区：`run_traffic_relevance_graph.py` 对已知论文赋文档级身份，`run_own_corpus_edges.py` 有独立 ownership 阶段并有限复用旧跨页结果。它们并未使通用 hybrid-v2 驱动自动完成文章重建。

## 本次保存的无 edge 基线

- [冻结基线及指标](../EvidenceNet/experiments/vldocir/BASELINE.md)：24 个查询、518 页、7,291 个 evidence nodes；不含图扩展。节点内容和视觉描述继续冻结。
- [基线完整性检查器](../EvidenceNet/scripts/verify_retrieval_baseline.py)：校验文件清单与 SHA-256，可额外检查 embedding 权重。
- 检索 tokenizer 修复：保留已经切好的 token ID 窗口，只应用经过验证的 special-token 模板。
- 节点生成修复：对缺少 `decision` 字段的模型回复给出明确 schema 修正提示，保留原判断和输入 ID 覆盖要求。

## Edge 分支后续边界

优先保留分层召回与混合视觉输入作为开发方向，尚不替换冻结 baseline。文章身份、阅读顺序和语义边须独立保存。杂志文章分割／跨页归属需要明确接入、验证并把结果传到 hybrid EvidenceNode IDs；仅修改配置、展示页或将页内分组改名为 article 都不能完成此项工作。

当前连边实验、比较脚本及其测试和记录在新分支继续整理。本检查点不追溯删除 Git 历史中的旧 edge 实现，只保证本次新增提交不混入尚在开发的新连边方案。

## 提交前验证

- 设置 `PYTHONPATH=EvidenceNet` 后，所有已跟踪的 EvidenceNet 测试通过：145 passed。未把本次不提交的 edge 测试混入这个结果。
- 冻结无 edge baseline 的 10,852 个文件清单与哈希验证通过，输入仍为 24 查询、518 页、7,291 个节点。此次未额外读取 encoder 权重重新计算哈希。
- `git diff --check` 通过。数据、输出和本地集群 sbatch 的忽略规则保持有效；不移动运行中任务所需文件。
