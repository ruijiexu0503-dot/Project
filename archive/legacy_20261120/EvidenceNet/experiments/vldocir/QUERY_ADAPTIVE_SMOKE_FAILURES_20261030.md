# Query-adaptive smoke：5219198 / 5219199

两组均在assessment阶段遇到连续两次校验失败后退出。exit75目前将协议失败和时间检查点混用了；这里不是25分钟预算，也不是45分钟Slurm超时。没有最终证据选择、集合审查或导航调用，不能评价edge收益。

|任务|样本|耗时|阶段结果|
|---|---|---|---|
|5219198|A2063G|9m37s|1个plan有效；16个assessment调用中15个有效、1个两次失败|
|5219199|Ce4f|5m05s|1个plan有效；4个assessment调用中3个有效、1个两次失败|

原始快照、日志与SHA：`migration/query_adaptive_smoke_5219198_5219199_20261030`。

## A2063G

planner生成两个scalar要求（2019率、2024Q1率），又生成重复的set要求“提供两个时间点的数值”。P015表格的两次输出均正确引用2019=75.2、2024.1-3=81.4，三个要求都标sufficient，但set项exhaustive=false，触发 `list completeness requires explicit exhaustive evidence`。

数值提取是积极的中间信号，不是完整选文改善。现有协议将固定两个时间点比较与未知成员的开放枚举混用，还允许一个附加标志使整个packet/题目中断。

## Ce4f

planner在局域化对比之外增加两项set要求，指定光谱、能带、XPS/UPS依据。这些并不是问题明确提出的条件，会让后续搜索追逐凭空增加的缺口。

P009第一次输出把原文拼成带省略号的value；第二次仍有非原文literal的scope（theoretical/comparative）及拼接比较表达。校验分别报value不在单一span内、scope/subject非原文。这等于在引入span ID之后，又通过subject/scope/value字段重新引入严格抄写负担。

此外原文先说两种材料具有localized occupied/unoccupied Ce4f states，再区分CeVO4中的V3d/O2p extended states。模型将extended states直接用于Ce4f局域化要求，仍有物理对象混淆风险，不能直接认定语义判断正确。

## 应修复的方向（本次仅诊断，尚未改动冻结实验）

- query计划只保留问题明确要求或回答必需的原子要求；区分比较与枚举，防止新增特定实验手段。
- source grounding使用稳定来源ID/offset；语义标签与原文选择分开。不能单纯放松字符串规则后接受未经核对的年份、数值或物理对象。
- requirements独立校验与记录：单项失败保留其他有效项，但未校验项仍标unknown/error，不能宣称query完成。
- error信息需定位requirement与field；区分协议失败、时间预算断点、完整成功的退出状态。
- 保留旧输出与缓存，另开修复版本，不把失败JSON就地改成成功。
