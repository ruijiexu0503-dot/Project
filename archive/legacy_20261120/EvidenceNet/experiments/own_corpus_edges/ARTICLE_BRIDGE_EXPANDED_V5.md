# V5 扩展文档压力测试

2026-10-13 提交 GPU 任务 **73129**，CPU 报告任务 **73130**（afterany）。提交后 GPU 状态 PENDING / Priority。2 GPU，分区 gpu-h200、gpu-h200-8、gpu-h100，时限 4 小时，时限不是预计运行时长。

入口：`EvidenceNet/scripts/run_article_bridge_expanded_v5.py`。
结果：`EvidenceNet/output/article_bridge_expanded_v5_20261012`（目录日期沿用前一日准备批次）。

## 冻结范围

25 个文档标识、49 页、550 个原有 evidence node，其中 528 个 eligible。相较 bridge v1 增加 14 个文档标识，包括建筑杂志、气候与机器学习、衰老研究、信息论、艺术材料、NIST AI RMF、NVIDIA 年报及 NASA 图像材料。NASA PDF/JPEG 是同一内容的不同载体，不能算两个独立主题。使用既有抽样 parsing/node 结果，不代表处理 25 份完整文档；部分材料可能已出现在更早实验中，不是独立盲测集。

## 流程

重新运行文字主体提取 → 明确图表引用绑定 → 别名验证 → 独立 node/subject 验证 → v3 来源身份校验 → v4 候选对照。复用既有向量缓存，原始 visual crop 继续用于绑定检查。EVENT/PROJECT 类型范围不变，概念和通用方法缺少链接也会作为覆盖限制报告；纯图像没有文字身份时不强行生成主体。

按相同 12 候选预算比较 global12 与 global8 + 4 主体候选。本轮严格比较跨文档候选，不把同一文档里隔离的节点误称为不同文章。已确认的文章内部关系单独写出，阅读顺序保留。

296 个节点的文章边界没有可靠确认，逐节点隔离，不用于文章上下文身份传播。这会降低别名归一化及图表绑定的召回，必须和语义算法错误分别统计；不能据此声称已测试好这些材料的文章分割或文章内部关系。

## 检查与结果审查

23 项相关单元测试通过。使用临时目录和模拟空主体输出完成整个流程检查，验证无主体材料能够结束、每节点 12 个候选以及候选确实跨文档；模拟输出已清除，不是实验结果。

运行后查看 `summary.json`、`index_errors.jsonl`、`boundary_issues.jsonl`、`reference_issues.jsonl`、`raw_node_subject_bindings.jsonl`、`node_subject_bindings.jsonl` 和两组 `edges_*.jsonl`。`node_source_review_queue.jsonl` 按文档包含有绑定及无绑定节点，检查漏检、错误绑定、目录/作者/背景误收，以及图像身份来源。抽样队列不是专家标签，也不能代替全部输出的审查。

不自动替换正式 pipeline 或检索 baseline；检索质量仍需查询级评测。CPU 报告在 GPU 失败后也会生成部分状态，报告存在不代表任务完整成功。
