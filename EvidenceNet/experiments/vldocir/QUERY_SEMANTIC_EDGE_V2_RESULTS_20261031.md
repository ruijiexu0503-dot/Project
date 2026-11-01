# Query semantic edge v2：实际边利用审计

审计日期2026-10-31。输入为用户指定Horeka目录 `remote_runs/query-semantic-edge-v2-20261031/EvidenceNet/output/query_semantic_edge_v2_20261031/`。读取时结果并未全量完成，以下只代表本次快照，不推测未完成题目的结果。

快照：`migration/query_semantic_edge_v2_review_20261031/`，含results、当时部署scripts、logs、JobID、文件SHA及audit_summary.json。本次没有改pipeline或提交任务。

## 核心结论

已完成题中，edge没有改变最终选文。不同于r4，本轮确实发生了一次semantic沿边访问；但访问理由引用的是入口已知信息，目标没有补上所需证据。

|每组24题|endpoint|semantic|
|---|---:|---:|
|协议完成|13|13|
|无新邻居而停止|8|8|
|初始充分而停止|3|3|
|完成题中进入导航的题|2|2|
|实际跟随路线|0|1|
|保存protocol_failure|3|3|
|保存time_checkpoint|3|3|
|未处理|5|5|

13题×3arm×4预算=156组对应记录，两方法所选ID、原文与tokens完全相同。各方法的graph_adaptive与seed10在13×4=52个组合上选中ID也全部相同。没有有效联合组的最终arm。

1024预算下，有5个已完成query最终输出0 tokens。因此complete表示执行/协议完成，不表示问题证据已经找齐。

## 1. 最大阻断：缺证据时，入口根本没有边

对8个no_unvisited_graph_neighbors案例逐一检查，Top10 seed集合关联的边数全部为0，不仅是邻居已经访问完。

当前图187边、321个端点node；准备器继续使用这张冻结图。manifest显示阅读顺序层未导入（upstream reading_ready=false）。这不是用户完整图构建pipeline的全量能力评估。

这些案例涉及代理投票条款、公司财务、设备尺寸、模型FPS、化石植物等。改gate prompt、放松相似度或多走一跳均不能穿过不存在的边。

3个初始充分案例为A2063G、Ce4f及Chambers示意图问题，合理停止不应被视为缺陷。本轮主问题不能再统一归因为“停止太早”。

## 2. 唯一访问路线：来源和目的地的增量被混淆

query：比较omega0=1.45J与1.7J条件下，n_ph(t)第一次峰值如何随g变化。

路线：`REL_753504d80f654289`，从第9页node（P033，初始rank8）访问第7页node（P029，初始rank14）。

- P033是入口，讨论n_ph(t)、能量交换与峰值由3×10^-4降至1.5×10^-4。
- P029是目标，讨论phonon displacement q(t)的振荡、频率和衰减。
- 关系描述说明共同的慢振荡现象，同时明确两端涉及不同observable。
- endpoint拒绝；semantic接受，expected_gain=direct_evidence，并引用REL...:B:S000/B:S001。
- 这些B端锚点属于第9页入口，即已有P033，不属于准备去读的第7页目标。
- 随后route_joint_audit仍只引用P033，没有形成联合组，actual_gain为空。1.7J条件的信息仍缺失。

因此有描述改变了决策，但没有带来正确新证据。不能把“多访问一个node”称为救回。

修复方向：导航输入显式分开known_source与new_target；direct_evidence必须说明目标原文的新支持，不能仅引用入口作为访问收益。若收益属于联合约束，则需引用两端并解释新增目标贡献；bridge允许不直接回答，但必须给真实后续路线依据。保留两端身份映射，不能把A/B顺序与当前from/to方向混淆。

## 3. 另一导航题：缺另一个主题，现有边仍停留在旧主题

query比较NGC3256暖H2流出速度与SN H0pe的H0测量。

初始来源已经支持前者，缺SN H0pe；两条可用边都在NGC3256文章内，关于气体/方法。两组均拒绝，没有补充证据。

这不是必须放宽gate的例子。比较问题需要为各query需求建立检索入口；两个主题不必天然有文档语义关系。建议整query召回+按缺失子需求补充seed，再从各seed沿真实关系导航，并对新增检索预算作匹配对照。在线编码子query不要求重做语料embedding。不要按gold强建跨主题边。

## 4. 缺口状态也有语义错误

声子题R1为partial，但missing中出现“Source confirms drop from 3x10^-4 to 1.5x10^-4...”，这是已知正向信息而非缺失内容。

trace显示它来自将observations复制到missing的规范化。格式合法不能替代语义正确：observations可能是背景或支持说明，不一定是尚缺约束。联合核验后来给出的真正疑点是具体数值与omega0条件的明确归属。下一步应核查这项归属，不应把所有observation机械作为缺口驱动导航。

## 5. 实验仍未完成，且保留了旧删除审查错误

三个protocol_failure都是 `redundancy_audit: unexpected object fields`。原始调用只给了“Return the same marginal-decision JSON schema”，却没在该独立请求内给出完整schema；模型返回了自拟结构，验证器拒绝。

审计时的部署代码已改为对删除后集合执行redundancy_set_audit，而失败预测仍保留先前redundancy_audit调用。需按代码/输入身份处理恢复和结果版本，不能断言最新代码仍在执行同一个坏prompt，也不能把尚未刷新结果当成修复后成功。三个time_checkpoint与五个unprocessed也需分别记录。

代码中尚未执行query-edge向量粗排；目前主要是把描述交给LLM看邻边。这与完整离线edge embedding导航方案有区别。

## 下一步建议

1. 先修方向性增量归属与missing规范化，补“入口有答案、目标只有同主题背景”的负例。
2. 对这8题先做离线seed关联/候选边覆盖审计，定位node没有候选、路由排除、核验拒绝或未导入图；不继续用同一空邻域反复调gate。
3. 阅读顺序、正文-图表/标题等来源明确的结构路线单独接入、校验与消融；避免将结构联系冒充答案支持。
4. 对跨主题比较增加query-derived子需求入口，与同成本dense对照；图承担已有入口后的局部发现与消歧。
5. 完成剩余题并区分版本，保留全24题分母；在真实路径可用后再评估向量排序、联合支持和最终tokens。

本轮没有新的Recall/AP结论，没有最终回答LLM结果；不能以实际调用边或完成数增加，替代最终证据改善。
