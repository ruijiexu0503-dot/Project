# Evidence node 内容关联实验

日期：2026-10-11。独立输出：`EvidenceNet/output/node_context_edges_v1_20261011/`。

端点是上一轮自己的 49 页、550 个多模态 evidence node。原始文本、表格、图注、
图片 crop、生成描述及原始 node ID 全部保留。复用上一轮的文章归属和 277 条
阅读边，包含 1 条跨页边；42 页归属通过结构检查，7 页仍未解决。

## 实际实现

每个原文 member 与生成描述分别创建检索窗口，192 个 BGE tokenizer tokens、
160 stride，全量窗口无固定首段截断。窗口保存 member ID 和原始字符偏移，
仅作检索表示，不新增图节点。过滤空白和不足 4 个有效词的 member，记录在
`excluded_members.jsonl`，这会排除孤立的通用标题，也可能漏掉短公式或短图注。
标题、章节和生成描述不能冒充原文证据。

使用已有 Qwen3-Embedding-0.6B 编码各窗口，验证并应用 tokenizer 的 EOS 模板，
取最后 token 的归一化向量；BM25 则补充精确词汇匹配，忽略 HTML 标签。
对每个窗口独立召回原文/描述两种通道中同文章及其他文章/归属未定的候选，
每通道最多 4 个，每目标文章最多 2 个。候选直接来自全库 evidence nodes，
不通过文章均值向量提前删除文章。候选 node pair 去重，各表示组合最多保留
两个窗口对，避免只保留一个通道。此轮未实现专门的视觉向量、实体链接或引用解析。

BAAI `bge-reranker-v2-m3`，固定 revision
`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`，分别评分 A→B 和 B→A，
取两个 logits 均值后 sigmoid。该模型训练目标是检索相关性；它在我们的
node-to-node 数据上的适用性需要源文审阅。分数不是已校准概率，也不能证明支持、
矛盾或图像内容对应。

初轮采用 0.8 的探索性门槛，不按最终结果重新调参。候选可以没有边；每节点
每 scope 最多 4 条、每目标文章最多 2 条，双端都受预算约束。只生成对称的
`semantic/RELATED_CONTEXT`，不自动生成 SUPPORTS 等强关系。该门槛和预算是
开发起点，不是已验证的最优设置。

每条边记录两端原文或描述窗口及精确偏移、匹配通道、双向分数、模型版本。
原文锚点必须精确匹配其 member。描述锚点明确标记为 `GENERATED_DESCRIPTION`，
不作为已核验的视觉证据；只要端点含视觉，`visual_verification=PENDING`。
所有关联边 `RERANKER_SELECTED_UNVERIFIED`、`human_review=PENDING`。
文章关联仅汇总有可靠且不同 article ID 的跨文章/文档 node 边。

## 运行和复核

`run_node_context_edges.py` 支持 prepare → candidates → score → report。
原始节点文件和快照有 SHA256 检查。report 可展示部分结果，complete 仅指全部
候选完成评分，不代表质量合格。可视化保留 node 成员、原图、描述、页面位置，
对称边无方向箭头。输出 candidates、scored_pairs、semantic_edges、article_edges、
summary、graph_data 和 index.html。Slurm launchers 放在忽略的
`current/slurm/edge_generation/`，任务 ID 记录在输出 jobs.json。

验证包括真实 BGE 模型 CPU 前向、154 项 EvidenceNet 测试、脚本和前端语法检查。
先复核跨文章内容关联、描述依赖、同词异义误连和重复转述，再考虑接入检索。
本轮未测检索质量；边数增加不能视为检索提升。

模型参考：[BAAI 官方 model card](https://huggingface.co/BAAI/bge-reranker-v2-m3)。
