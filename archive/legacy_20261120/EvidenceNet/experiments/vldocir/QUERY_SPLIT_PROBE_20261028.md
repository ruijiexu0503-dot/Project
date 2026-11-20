# Query split：SN H0pe单例机制验证

## 范围与隔离

用户希望先检查拆分query能否补回SN H0pe证据。只使用原题的两个子句，人工固定为：

1. What is the maximum intrinsic outflow velocity measured in the warm H₂ gas of NGC 3256?
2. What is the central value of the best H₀ measurement from the SN H0pe study?

不加入答案数值、gold页面、文档ID等信息。问题ID只用于定位原始query。
这是已看过的开发题，不是自动通用splitter或独立测试集。
现有node/edge不修改；本轮不启用edge扩展，以隔离query split，不将收益归给edge。
原来174/187中断的bounded实验和新的单句任务5216293均不修改或取消。

## 三组对照

- original：原query检索20页；原query BGE重排。
- split：原query与两条子query各自完整检索，在同一518页库上按轮询去重合并20页；原query BGE重排。
- split_rerank_rrf60：与split完全相同的20页和证据；额外用两条子query评分，三个BGE页面排名以固定等权RRF(k=60)融合。

每页固定使用原query选择的两个窗口，各组不改变窗口，防止把证据选择增益误归给拆分。
第三组是单独的重排与更多query评分预算变化，不能当作纯候选召回对照。
不根据结果调预算、融合权重或子query；保留所有分支排序与候选来源。

## 编码及复用

同一Qwen3-Embedding-0.6B、原10301个窗口token IDs、相同last-token pooling与归一化。
原query token IDs逐个与冻结缓存核对，原query也和子query一起重算，控制硬件数值差异。
原缓存只有query-window点积分数，没有窗口向量；本次补存查询无关的document_vectors.npy，
后续可按模型与语料哈希复用，不需要因为query拆分重新生成节点/边或重新编码文档。
每16窗口保留带hash的向量检查点，时间预算结束退出75；恢复不丢失完成进度。

## 评估与边界

只有report阶段读取gold。报告各gold页在三个检索分支中的排名、是否进入20页候选、
最终Top5、Recall@5/20和AP@5，明确区分召回与重排失败。
没有GPU结果前不声称找回SN H0pe。既有官方gold照常保留，相关性疑点另行审查。
只有1个query，不报告总体或六类宏平均提升。

## 验证与执行

6个测试通过：去重/均衡合并、预算、原始query token一致性、输入冻结、gold隔离及三组证据共享。
部署包与脚本单独SHA256校验；远端submit锁与intent记录防重复提交。
请求dev_accelerated单GPU、45分钟；编码预算30分钟、BGE预算8分钟。排队时间未知。

```bash
bash migration/horeka-query-split-20261028/submit.sh
```

该脚本在原Project终端优先复用现有Horeka认证。
只有submitted_job_id.txt及SUBMITTED记录才算实际提交成功。
输出目录为EvidenceNet/output/vldocir_query_split_probe_v1_20261028。
最初的vldocir_query_split_probe_20261028仅为开发中准备目录，无GPU结果，不应续跑。

提交状态（2026-10-28）：本地prepare/check通过；实际执行submit.sh --batch后，
三个部署校验和通过，但SSH返回Permission denied，未获得任务号。
因此尚未成功提交，需在持有现有认证的Project终端执行上面的提交命令。
