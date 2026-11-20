# Query-adaptive v1：实现、对照和执行状态

## 目标和当前状态

实现2026-10-30讨论的三个方向：部分支持与充分支持分离、缺失要求驱动搜索、bridge导航和最终证据分离。未改写旧预测或部署；还没有新的GPU结果，不能声称准确率提升。

入口 `scripts/run_query_adaptive_evidence.py`；策略与协议 `scripts/query_evidence_policy.py`；测试 `tests/test_query_adaptive_evidence.py`。

## 新流程

1. 仅将query传给规划调用，生成1–8个requirements（scalar/set/comparison及约束），不暴露候选或gold。
2. 每个原文packet单独评估：missing/partial/sufficient，原子事实subject/scope/attribute/value及span引用。value必须存在于单个引用span，subject和scope是原文literal或空（未解决），不能把总体率配成年份率。表格整体及OCR换行保持不变。
3. 选文按新增事实而非新增requirement。相同要求下不同年份、数值、实体的互补事实继续保留；不因一段covers就关闭整个要求。未知主体/时间的事实不跨packet去重。最终仍保留整packet，不夸称实现句级压缩。
4. 另一次调用只看实际选出的原文，检查其联合支持是否充分。列表必须有完整性依据才能标sufficient；不能依赖未选候选或常识补足年份。审查输出仍是模型估计，不是独立gold。
5. 在1024-token选文集合上得到剩余缺口，据此判断冻结图的一跳路径。导航prompt包括原始source anchors及已有关系字段（当前description多为PENDING，不能当成事实）。允许bridge无直接答案事实也继续探索。
6. 对接受的目标取原文并评分、更新选文及缺口，再执行第二跳。已访问节点不重复。bridge只有拥有可用事实才可能进入reader；不会因导航通过被强行加入。
7. 最终输出512/1024/2048/4096四档原文、来源、集合充分性判断、路径、拒绝理由、未解决项。没有回答模型。

## 对照与范围

- fixed：复用此前固定池879个query-packet，修复覆盖选择。按原固定池base_score作最后tie-break。
- navigation：seed10、graph_adaptive、dense_exposure_matched。最后一组dense前缀的node数与图路径实际向模型暴露的节点数相同，包括查看anchor后拒绝的节点；不能只计算成功遍历节点而隐去搜索成本。
- 三个navigation arm共用query计划、逐packet评分缓存与审查缓存；相同输入不重复推理。所有实际调用（包括失败重试）的输入/输出tokens、耗时按阶段记录。成本是共享运行的实际总量，不是每个arm独立部署的精确账单。
- 当前冻结图187条语义边，阅读顺序层未导入。24题两跳包络最大16个nodes，仅Ce 4f问题有第二跳新增节点。这是图可达性限制，不因新方法更改gold或强加边。
- 最大候选包络40，超过则prepare明确失败，不默默裁剪邻居；实际数据不触发。图导航是双向访问已有边，不创建新语义关系。
- 初始召回仍复用既有完整query的embedding排名；未加子query embedding召回。本轮改变需求规划和路径选择，不混入新的encoder。

## 来源与恢复

所有tasks/edges/code/tokenizer冻结哈希；edge原文anchor按原始member哈希与偏移核对。每个LLM调用记录完整输入、raw输出、校验错误与tokens，原子保存；规划、评分、审查、导航分别恢复。query完成记录绑定manifest/model/mode，拒绝陈旧结果。

25分钟软时间预算在模型加载前开始，生成前检查；不能中断已进行的一次生成。dev时限45分钟；未完成保存断点。全量报告始终保留24题分母，smoke成功不等于完整实验完成。

## 验证和smoke

新增10项测试＋原有16项测试通过。包括：同要求互补事实保留、错误sufficient不抹去其他新事实、枚举不完整拒绝、跨packet/不连续引用拒绝、假年份和假数值拒绝、只用选中原文审查、bridge缺失直接答案仍能二跳找到证据、不强制bridge进入reader、循环防止、调用断点/时间预算。

真实源文本回归使用Federer和A2063G的旧失败packet，手工support fixture验证选择规则可在1024tokens内保留补充证据；不把这些手工fixture测试解释为LLM已经正确。

24题prepared inputs已生成：`EvidenceNet/output/query_adaptive_evidence_v1_20261030`。

远端独立目录：`remote_runs/query-adaptive-20261030`。两组smoke：
- fixed：A2063G问题，验证总体率与年份具体率的区分。
- navigation：Ce 4f问题，按图结构选择唯一存在二跳新增节点的题，检查路径与缺口控制。

每组dev4GPU/45分钟。提交脚本：

```bash
bash remote_runs/query-adaptive-20261030/submit_smoke.sh
```

当前脚本及远端preflight通过；SSH返回Permission denied，尚未提交、没有任务号。先检查smoke输出格式、语义判断和调用成本，再决定全24题续跑；旧结果全部保留。

## 最后同步阻塞更新

新增请求完整日志字段后，本地最终26项测试全部通过。远端已部署的算法/输入与此前preflight相同，但最后的3文件同步（runner、manifest、deployment.sha256）尚未执行：自动审批服务因usage limit未能完成审核，工具明确未执行操作。这不是判定操作不安全，也不是测试失败。不得绕过审批或将远端版本描述为最终同步完成；没有新任务号。恢复审批后需同步本地deployment中的3个文件，重新preflight，再提交smoke。
