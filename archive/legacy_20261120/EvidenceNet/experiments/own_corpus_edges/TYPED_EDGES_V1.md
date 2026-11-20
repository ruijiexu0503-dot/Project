# 分类型 evidence-node 连边试验

实验：`typed_node_edges_v1_20261012`。入口：
`EvidenceNet/scripts/run_typed_node_edges.py`。输入复用 v3 的 49 页、550 个
不可变 evidence node；没有替换正式 pipeline 或 VL-DocIR 冻结 baseline。

任务已全部结束，来源复核及下一轮改进见 [结果复核](TYPED_EDGES_V1_REVIEW.md)。
下文保留实验设计与初始候选覆盖记录。

## 算法变化

1. 阅读顺序、显式引用与语义候选分别处理。保留原有 277 条阅读边，
   对可唯一定位的原文 marker 生成 REFERENCES，不把邻接当作语义成立。
2. 在原文 atom 上建立实体／事件标识倒排索引。名字相同只是候选；
   每个实体分别召回文章内、跨文章、跨文档和文章归属未解决的候选。
3. 文本与描述检索继续提供候选，另加入原始 crop 的视觉候选。
   本轮用本地 Qwen2.5-VL-7B 视觉特征的均值池化，每个 scope 取近邻；
   这是探索性视觉相似度，不是经过检索训练或校准的多模态 embedding，
   不与文本向量直接比较，也不直接决定边是否成立。
4. 每对节点按 SAME_ENTITY、CAPTION_FOR、EXPLAINS、RELATED_CONTENT
   分别判断；共享实体不是所有关系的通用前提。后三类也能连接没有实体名字的
   方法、公式、图像。分类型、scope、是否含图片和排名层次抽样。
5. 接受与拒绝使用同一个短 JSON 格式，均选原文片段或原始图片 ID。
   保存原文位置与 crop 哈希；生成描述不作为正面证据。格式失败记作
   FORMAT_PENDING，两次判断不一致记作 REVIEW_PENDING。
6. 最多抽 64 对接受／拒绝结果做不提供第一次结论的同模型复判，
   另一个措辞要求检查替代解释。这只检查一致性，不是独立模型或人工标签。
   人工仍须检查接受边和拒绝样本，随后才能报告质量。
7. 文章间边由有明确文章归属的跨文章 evidence-node 边汇总，保留节点边 ID。
   没有新增文章归属判断或跨页阅读推断。

## 初始覆盖与运行

56 个原始 crop 特征提取成功，形成 236 对视觉候选。最终有 8,804 个
关系假设，覆盖 530 个合格节点中的 518 个；12 个节点无候选，保持记录。
候选数不是已生成语义边数，同一节点对可以有不同关系假设。

320 个判断样本覆盖 285 个节点，类型为 EXPLAINS 26、CAPTION_FOR 27、
RELATED_CONTENT 171、SAME_ENTITY 96。Scope 为文章内 116、文章归属未解决 88、
跨文档 66、跨文章 50。旧 120 对中 110 对保留，另外 10 对因资格或
重复 caption 过滤；详细原因见 `candidate_diagnostics.json`。
旧 10 个漏边案例中 9 个在候选池，5 个进入本轮判断；未抽到不代表被拒绝。

| 阶段 | Job | 配置 |
|---|---|---|
| 原始图片候选 | 68433 | 1 GPU，已成功结束 |
| 分类型核验及盲复判 | 68434 | 2 GPU，4 小时时限，依赖候选成功 |
| 汇总与可视化 | 68436 | CPU，核验结束后运行，包括不完整结果 |

181 项测试通过，其中新增 5 项覆盖实体来源、原文定位、分层抽样、
拒绝锚点及格式失败。已进行助手来源复核，独立人工评测及检索增益尚未评估。

## 产物与复核

输出：`EvidenceNet/output/typed_node_edges_v1_20261012/`。
`index.html` 展示节点成员、描述、原图、页面位置、类型／方向／来源锚点；
`candidate_diagnostics.json` 与 `coverage.json` 记录候选覆盖；
`decisions/`、`repeat_decisions/` 保存完整判断；
`semantic_edges.jsonl`、`article_edges.jsonl` 是生成边；
`pending_repeat_disagreements.jsonl` 是分歧；`summary.json` 标记是否完成。

本轮是开发材料上的算法试跑，320 对是分层样本，不能推断整图精度或召回率。
仍沿用原有节点／文章分割，7 页归属问题及稀疏跨页阅读覆盖没有解决。
比较时应分别统计误连、漏连、待复核、格式失败、类型和方向，不能把
边数变多或同模型一致当作质量提升。检索提升需另外运行冻结查询评测。

```bash
source current/env.sh
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_typed_node_edges.py report \
  --output EvidenceNet/output/typed_node_edges_v1_20261012
```
