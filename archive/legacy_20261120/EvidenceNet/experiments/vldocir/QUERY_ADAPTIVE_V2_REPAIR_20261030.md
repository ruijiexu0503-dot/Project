# Query-adaptive v2：针对真实smoke失败的修复

旧任务5219198/5219199和v1代码、部署、缓存保持不变。新入口 `scripts/run_query_adaptive_evidence_v2.py`，策略 `scripts/query_evidence_policy_v2.py`。

## 修复内容

- query-only规划明确区分命名年份/材料的scalar要求和真正的开放枚举；不再建议追加重复集合要求，也不得凭空要求光谱、计算等实验手段。
- 独立query-only计划审查，逐项keep/reject并保存理由；审查不能生成新的要求。此处仍是LLM语义审查，不能保证模型绝不扩张任务。
- assessor改为 `meaning + span_ids`。meaning明确是解释而非原文/答案，不再要求subject/scope/value逐字匹配；最终reader仍取原始packet。严格验证引用归属及原文哈希。新增原文集合审查提醒区分物理属性真正所属的轨道、物种、材料、年份、人群。
- fact去重按(requirement,packet,span IDs)，解释换措辞不会凭空增加gain；同一表格可包含两个年份的合法注释，计为同一来源单元而不报协议错误。
- set被标sufficient但exhaustive=false时，仅保守降为partial并保留事实，记录normalization；不会自动将完整性改为true。
- 每项requirement独立校验。有效项保留，失败项标unknown；仅对失败项进行针对性重试。仍失败不会中断其他packet，但整题complete=false，partial记录明确标query_validation_complete=false。
- 选中集合审查同样隔离失败；不能引用未选packet。跨材料/年份的语义判断仍依赖审查，不能把span存在当作语义正确。
- Broker保存原始parsed_result与规范化result；恢复时重验原始内容，避免把包含validation_issues的派生结构错误当成模型原始JSON。
- 完整请求、原始输出、局部重试及耗时/token成本全部保存。
- smoke退出码区分：0完整、2协议失败/仍有未校验项、75时间断点。report区分complete/partial_validation/protocol_failure/time_checkpoint/unprocessed。

## 测试

新增9项v2测试，连同原有26项。覆盖真实失败输出的显式测试适配、集合降级、跨packet拒绝、有效项保留、单项重试、断点恢复、计划审查、只用已选source审查、partial结果不误计成功。

真实旧输出只在测试内转换为新schema来验证来源协议，不修改旧预测、不把旧失败标记成功，也不证明新LLM输出已经正确。语义效果必须由GPU复测确认。

## 部署

prepared inputs：`EvidenceNet/output/query_adaptive_evidence_v2_20261030`，24题，原候选和图包络未变。
远端：`/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs/query-adaptive-v2-20261030`。
本次部署成功，两组远端preflight通过。最后提交SSH仍返回Permission denied，因此没有新任务号。

在Horeka Project终端执行：

```bash
bash remote_runs/query-adaptive-v2-20261030/submit_smoke.sh
```

仍为A2063G fixed与Ce4f navigation两道smoke，各dev4GPU/45分钟，25分钟推理软预算。不直接扩大全24题。
