# Query-adaptive v2 smoke：5219501 / 5219502

两组均已执行完所有选择/审查阶段并保存partial结果，但仍有未通过协议校验的requirement，故exit2（不是时间预算或GPU启动失败）。原始快照：`migration/query_adaptive_v2_smoke_5219501_5219502_20261030`，包含结果、请求、raw输出、日志和SHA。

|任务|样本|耗时|状态|
|---|---|---|---|
|5219501 fixed|A2063G|25m42s|partial_validation，17个packet–requirement未验证|
|5219502 navigation|Ce4f|10m03s|partial_validation，3个不同packet–requirement未验证（在三个arm重复报告共9条）|

## 已发生的改善

- 规划不再生成重复set或额外光谱要求；两题分别只保留两个明确年份/材料要求。
- A2063G的1024预算选择P015数据表+P018图注+P016表注，共837tokens。表格真实包含2019=75.2、2024.1-3=81.4；选中集合审查认为两项充分。旧覆盖选择只有214tokens总体76.6%和趋势描述。本次确实保留了此前遗漏的端点数值，但不是edge收益，也不是完整实验成功。
- Ce4f在1024选择P013正文、P024结论及P015图注，共998tokens，包含CePO4局域化与CeVO4更宽/混合的相关原文。初始seed集合审查认为充分，trace为`selected_sources_sufficient`，没有navigation调用；因此没有真实两跳搜索结果，不可宣称edge救回。

## 当前协议问题

失败重试中全部状态冲突都是 `missing` 配非空facts。模型常用facts解释背景和为什么没有答案，例如“研究覆盖2019–2024，但没有分年率”；这属于缺证据说明，程序却将所有facts解释为正向支持。两组分别产生35、12次该校验错误，浪费了重试。

下一版应区分support与background/absence observations，保留原始输出，不将missing背景自动升级partial，更不能计入支持gain。应检查来源引用后把非支持说明明确存入诊断字段，missing仍不贡献reader选择。

## 另一个审查问题

A2063G 2048/4096预算选择同一表格再加两段，共1267tokens。模型却将Q1 2024降为partial，理由是“2024.1-3未明确写first quarter”。这是同一表格在更大上下文下的不一致判断；日历一季度与1–3月的等价表达不应被错误当成缺证据。不能只凭LLM的sufficient/partial标签宣称真实覆盖改变。512预算放不下整表，选330tokens背景/图表注，审查正确保留partial。

## 成本统计问题

输出成本文件显示固定组89次调用却仅178输入tokens、导航31次调用却仅62输入tokens，显然是每次计2。待核对运行时tokenizer返回结构；这些input_tokens不可用于成本对比或声称输入便宜。evidence_tokens由encode原文得到，837/998是另一个计数路径，不受此问题直接影响。

本次仅核对结果并归档，没有修改冻结预测、没有提交新任务。仍需修复缺证据说明分类、审查等价表达与input token计数后再复测。

已用实际Horeka环境确认：`apply_chat_template(tokenize=True)`返回BatchEncoding，键为input_ids和attention_mask，len为2；示例实际input_ids长度31。必须按input_ids长度计数，且同步修复prompt长度上限判断。旧记录保留并标注计数错误，不能直接改成推测值。
