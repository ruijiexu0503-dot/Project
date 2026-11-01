# 受约束开放关系描述与漏召回审计（2026-10-28）

用户要求：限制自由关系描述的范围，并检查未召回例子的真实原因。保持离线建边/embedding；query时不重新生成整图。

## 已完成实现

新增 `scripts/bounded_edge_descriptions.py`，通过 `run_vldocir_edge_embedding.py prepare --description-policy bounded-v2` 启用；legacy保留用于历史复现。新实验独立输出，不覆盖旧图、标签和预测。

关系语义仍是自由文本，不增加SUPPORT/CONTRAST等固定分类。四字段schema保持`description/cited_span_ids/limitations/status`，约束为：

- description分别写`A:`事实、`B:`事实、`Connection:`具体连接；使用来源document/page/span IDs明确归属。
- limitations必须非空，写出差异、条件、单位/变量角色、身份不确定性，不把共享类别推成等价/支持，不把共同机构/月份/局部[7]推成同一研究。
- 不要求模型抄quote或编offset，避免上一组省略号/断词触发字面引文失败。
- 真实embedding tokenizer验证完整AB/BA输入均≤512 tokens；端点仍各192 tokens，与C/E控制一致。超长返回实际长度、要求保留约束重写，最多3次；不会从关系句中截断。
- 无效描述或INSUFFICIENT时，D输入逐字等于C，不把错误说明/证据不足说明编入向量。旧代码的fallback文本污染仅在新profile修复，旧结果保持可复现。
- 固定policy/prompt/input hashes，拒绝旧profile预测、重复ID、修改的输入/模型tokenizer；嵌入manifest冻结description_predictions hash，避免report引用事后修改的描述。

程序验证的是格式、来源ID和长度，**不是自动证明语义蕴含**。身份/条件正确性仍要审计实际生成结果。严格模板也可能增加invalid/fallback，须如实计数，不能删掉后算成绩。

本地28项相关pytest全部通过；187边/24query完整prepare通过。新description仍未有GPU结果。

## 独立GPU实验

已提交Horeka **5215455**，当前PENDING (Priority)，暂无可用预计开始时间。partition=accelerated，4GPU，3小时上限；没有新增预占续跑job，没有修改原5215293/5215323。

冻结187条G0、24queries、518页、dense core10、候选预算20、扫描100、相同8B encoder与固定页面BGE。此次只变更描述合同/完整保留/回退；尚未把关系文字加入最终BGE，以免同时改变多个因素。原official gold不变，已知标注疑点随报告说明。

- 本地包：[migration目录](../../../migration/horeka-edge-bounded-20261028/)
- 远端：`/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs/edge-bounded-20261028`
- 输出：上述目录下`EvidenceNet/output/vldocir_edge_bounded_v2_20261028`
- 部署校验通过，提交脚本有锁、job记录和intent，避免重复提交。只复用原包数据和已验证共享权重，代码覆盖限runner＋新模块。
- 完成后检查description_diagnostics中的invalid/statuses/truncated/实际附加描述数，再与旧D及同轮C/E比较。若超时只根据checkpoint按需续跑，不重新生成完成记录。

## 未召回结果审计

完整[原图可视化](../../../migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/missing_gold_audit.html)、[逐例报告](../../../migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/MISSING_GOLD_AUDIT_20261028.md)、[结构化数据](../../../migration/edge_handoff_snapshot_20261027/edge_embedding/diagnostics/missing_gold_audit.json)。

D的top5漏8个query–gold page关联、涉及7queries：6个已入20候选但排6–9；另2个不在候选且G0无该页。没有“gold页有G0边但仅因edge排名/预算未入选”的漏例。

- Federer：部分正确赛事证据在窗口，但跨年份交集需联合比较，仍排8。
- phonon：图描述窗口截到半句话，另一个窗口是不同图；BGE不看原图，排6。
- Graf奖牌：正确表格在页上，BGE实际看Wimbledon/Federation Cup段落，排7。
- implant：只给BGE两个标题；原图跨页，所问E面板在下一页而gold只标前页。
- SN H0pe p13：dense20外且G0缺页，整query同时问另一个研究，考虑query子问题召回。
- Warrior Falls p7：dense17被edge候选替换，但原图是电影发行，答案在另一个已找回gold p4。
- mA3 p6：原图是近交系；问题所问20个野生haplotypes在p7。
- NGC3256 p6：gold框与最大intrinsic速度不对应，数值在p2/p10/p11，待复核。

官方questions/evidences与冻结gold一致，revision一致；核查文件SHA256匹配HF缓存LFS ETag，11张原图与官方tar成员hash一致。证据支持官方证据选择/跨页定位疑点，不支持本地统一页号偏移。保留official指标，人工review单列，不直接改gold刷分。

40个query–gold page关联的命中数（不是宏平均Recall）：A top5/10/20为31/38/39，C/D/E均32/38/38。除了top5多1页，还须披露top20少1页（可疑Warrior p7）。

优先解决页面内部证据选择、表格/跨页图完整性，再独立测关系辅助重排；仅修改关系描述不能修复BGE根本看不到答案的问题。
