# Edge embedding 与 VL-DocIR 检索实验：实现交接

日期：2026-10-25。本文交接设计、已有材料和验收要求；新实验尚未实现、运行或提交。

读者：接手代码实现的模型或开发者。全文路径除特别注明外，均相对于项目根目录：

```text
/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project
```

## 1. 用户明确要做什么

用户已澄清：**对 edge 本身进行 embedding，使关系表达不必受固定关系种类限制；不同 query 根据需要检索不同 edge。** 不是仅重新做 node-to-node 相似度，也不是只增加几个关系标签。

需要比较新方案和现有 edge pipeline 对最终页面检索的作用，使用之前接入的 [VL-DocIR](https://huggingface.co/datasets/anonymous-8421/VL-DocIR)。主要看 Recall、AP 等最终指标，并保留完整搜索路径。

用户的持续约束：node、edge 及其表示提前离线建立；不能等 query 到来后再重做文档或 edge embedding。query 自身正常编码是允许的。本文主方案不依赖在线 LLM 给每条 edge 重新判关系。

完整产品流程仍然包含：原始文件/页面 → Dolphin 解析 → node generation → edge generation → edge embedding → query 检索 → 页面排序。第一阶段复用冻结 node 是为了隔离 edge 的作用，不代表删除 node generation；新增语料仍需走解析和建 node 流程。

## 2. 核心表示和使用方式

```text
离线：
原始 node A/B → 可定位的两端证据 + 必要上下文
             → 不依赖 query 的自然语言关系描述
             → edge 文本表示 → edge 向量与索引

在线：
query → 原有 node 检索 ───────────────┐
      → 匹配模型的 query 向量 → edge 检索 → 端点页面候选
                                    ↓
                         合并、去重、固定候选预算
                                    ↓
                         同一个页面 reranker → 排名
```

- 边的证据和描述提前固定，检索价值随 query 变化。
- `relation_description` 使用自然语言，不要求属于 SUPPORT/CONTRAST 等枚举。来源类型、处理状态和权限字段仍可用枚举；它们不是语义关系类别。
- 描述不是独立事实证据。高 embedding 相似度也不证明关系正确；最终回答必须能回到原文、原表或原图。
- 一条 edge 命中只能引入候选，不能给两个端点无条件增加最终分数。
- 当前图允许无向导航。端点有语义方向时在描述中明确主体，不把向量顺序自动解释为支持方向。
- 不对所有 node 两两生成描述或编码。扩大图时先做离线候选发现，再编码稀疏候选连接。

## 3. 已核实的历史状态

### 3.1 现有方法已经做了什么

现有流程为：Qwen3-Embedding-8B 的 node/view 编码 → dense/BM25/identifier 等候选召回 → 文章路由和预算筛选 → 原始多模态 LLM 核验 → 宽泛的无向 RELATED 提议。

因此，新增工作是 **edge 的联合表示和按 query 检索 edge**，不能把已有 node/view 向量改名为 edge 向量就算完成。

冻结 pilot 有 24 个 query、518 页、7,291 个 node。1,088 个候选 pair 完成核验后导出 213 条 RELATED；它们是模型提议，不是人工金标。来源分流为 187 条 semantic proposal、17 条 reference_review、9 条 administrative_review。来源分流通过不代表语义正确。

旧建边配置关闭了额外公式上下文等实验功能；不能把该旧图称为已经验证的“所有上下文功能都启用”的版本。

### 3.2 Job 5209174 的真实结果

这是 query gate 单独实验，已完成，退出码 0，用时 00:21:29。35 条路径全部处理；16 条通过输出协议校验，19 条失败。有效输出包括 9 UNSUPPORTED、3 PARTIAL、2 DIRECT、2 BRIDGE。

19 条失败的首个错误：16 条引用不匹配、2 条 BRIDGE 错填 answered_aspect、1 条 JSON 非法转义。19 次第二次尝试均与第一次输出逐字相同。总计 54 次模型调用。

7 条有效放行路径全部指向原 dense Top10；最终 24 个 query 的候选集都等于 dense Top20。按现有相同页面评分和 tie-break，gate 与无边 reranker 的排序会相同。这是等价性检查，**不是新测得的 Recall/AP**：955 条 BGE 评分仍未运行。

重要错例与工程问题：

| 预测行号 | 观察 | 实现启示 |
| --- | --- | --- |
| 1 | 原回答已判投票推荐语不能解释撤回授权；弯引号改直引号导致 INVALID | 引文用 span ID/offset 回填，不要求模型重抄 |
| 7 | 全赛事售票数被当作开幕式观众人数 | 保留事件范围及统计口径 |
| 19 | 仅凭 caption 推断 Ce 4f 局域性，未传原图 | 缺视觉证据要记录，不能补想象 |
| 26 | 原文未提 DMN，模型补入网络归属并加强因果 | 描述不能超出原始证据 |
| 32 | 重复“2004 年三座大满贯”被当作寻找 2005 答案的桥接 | 重复背景不自动产生新导航依据 |
| 34 | 表中只有 R128/R64/R32 胜场，缺 target 年份上下文 | 表头、年份、轮次和冠军不可混淆 |
| 35 | “医务人员”与“专门从事机器人手术的医务人员”被混同 | 保留限定词；拒绝理由也需核对 |

有些 quote 失败只是排版，有些则是从 seed_hit 补入 anchor 未包含的内容。不能统一用模糊匹配放过。旧 anchor 还出现重叠片段、半个单词和句子截断；应从原始 member 与 offsets 重建，不能简单拼接旧 quote。

详细诊断：[可视化](../../output/query_edge_gate_review_20261025/diagnostics.html)、[运行核查](../../output/query_edge_gate_review_20261025/execution_audit.json)、[逐 query 候选](../../output/query_edge_gate_review_20261025/candidate_effects.jsonl)。以上人工式复核不是独立金标。

### 3.3 pilot 的覆盖上限

当前 dense Top20 已覆盖 40 个 query–gold-page 组合中的 39 个。唯一漏页是文档 `e3d24500-9a0a-41d7-8886-bca6db430252` 第 13 页，dense rank 40。该页有 5 个 node、12 个检索视图，但没有进入最终候选 pair 或当前图端点。

所以只给旧图加 edge embedding 无法到达这个漏页。该问题本身是跨主题比较，两份 gold 材料也不必天然存在语义 RELATED；不能按 gold 强建边。旧 24 题已反复检查，只用作开发回归。

## 4. 可复用的数据与代码

### 4.1 数据入口

| 根目录下的路径 | 内容与用途 |
| --- | --- |
| `EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011/` | 冻结 no-edge baseline；pilot 查询、页面、gold、prepared 表示、各检索组分数。保持原样 |
| `migration/vldocir-edge-20261022/results/` | 下列 nodes、views、向量、候选、旧图和搜索缓存的根目录 |
| `migration/vldocir-edge-20261022/results/nodes.jsonl` | 7,291 node；成员原文、node ID、来源页面与图像定位 |
| `migration/vldocir-edge-20261022/results/views.jsonl` | node/view 对应、member ID、offset、quote、retrieval_text、来源性质 |
| `migration/vldocir-edge-20261022/results/view_vectors.npy` | 8B 的 **view** 向量，不是 edge 向量；配套 embedding_manifest.json |
| `migration/vldocir-edge-20261022/results/node_candidates.jsonl` | 1,088 个已选择候选，含 best_views、候选分数与路由 |
| `migration/vldocir-edge-20261022/results/article_candidates.jsonl` | 文章路由及 selected_for_node_search，帮助追踪召回遗漏 |
| `migration/vldocir-edge-20261022/results/graph/related.jsonl` | 213 条旧 edge，含模型描述、原始 anchors 与 offsets |
| `migration/vldocir-edge-20261022/results/graph/rejected.jsonl` | 已拒绝候选；不能悄悄改成已验证语义边 |
| `migration/vldocir-edge-20261022/results/graph/review.jsonl` | 待复核/无效输出候选；与已通过边分开记录 |
| `migration/vldocir-edge-20261022/results/search/` | 旧 no-edge/edge 分数、query_window_scores.npy、encoding.json 和搜索路径 |
| `migration/vldocir_trace_inputs_20261023/` | 冻结 queries、units、windows、window_tokens、gold |
| `EvidenceNet/output/query_edge_repair_v2_20261023/` | 本地冻结 gate 输入、query_contexts、role_audit；此处旧 status 不是远端最终结果 |
| `EvidenceNet/output/vldocir_eval_bundle_20261016/` | 统一查询、页面、qrels 和来源映射；不是训练标签生成器 |
| `EvidenceNet/output/vldocir_colnomic_7b_20261016/` | 相同 24-query/518-page 的 ColNomic scores 和配置，可作外部模型对照 |
| `EvidenceNet/output/vldocir_matched_comparison_20261023/` | 已有同 query、同语料比较 |

**5209174 的真实预测和最终 status 在以下已取回目录，不要再为读取它们要求 SSH 登录：**

```text
migration/horeka-query-edge-repair-20261023/
  results_5209174_20261025T013046Z_ElcFUQSl/
    EvidenceNet/output/query_edge_repair_v2_20261023/
      gate_inputs.jsonl
      gate_predictions.jsonl
      gate_execution.json
      status.json
      manifest.json
      query_contexts.jsonl
      ...
    logs/query-edge-repair-5209174.out
    logs/query-edge-repair-5209174.err
```

node 的原字段为 `id/document/page/members/node_type`；view 用 `node_id/member_id/char_start/char_end/quote/retrieval_text`；旧 edge 用 `task_id/source/target/model_result.anchors`。适配层要显式转换，不要猜字段名称。

### 4.2 代码入口

| 文件（均在 `EvidenceNet/scripts/`） | 可复用部分 |
| --- | --- |
| `run_evidence_edge_pipeline.py` | 现有离线候选、核验、导出；重点看 select/retrieve/prepare_verifier |
| `run_vldocir_edge_pipeline.py`、`prepare_vldocir_edge_adapter.py` | VL-DocIR node/图像来源适配 |
| `run_hierarchical_edge_retrieval.py`、`repair_edge_candidate_allocation.py` | 多路召回、文章路由、escape 与引用候选预算 |
| `compare_edge_embedding_models.py` | embed、pooling、tokenizer；函数本身不会自动添加 query instruction |
| `edge_source_roles.py` | 来源分流，不能当语义正确性判定 |
| `run_query_edge_repair.py` | 冻结 query context、select_candidates、页面评分、结果对照；旧候选排序按 dense rank，新方案需单独实现 edge-score 排序 |
| `query_edge_gate.py` | 旧 gate 协议与来源校验，仅作历史比较或参考 |
| `run_cached_query_reranker.py` | BGE 输入 hash、断点续跑、统一 query–passage 评分 |
| `evaluate_vldocir.py`、`evaluate_vldocir_ap.py` | 页面级 Recall/nDCG/完整证据指标、AP 定义 |
| `trace_vldocir_edges.py` | 旧检索路径 schema；旧 edge bonus 逻辑不要直接带进新主实验 |
| `run_vldocir_colnomic.py`、`compare_vldocir_cached_search.py` | 同语料外部模型对照 |
| `parse_vldocir_pages.py`、`run_vldocir_nodes.py` | 新增语料时复用解析与 node generation |

本地可用 Python：`EvidenceNet/.venv_qwen/bin/python`。系统 `python3` 可读写 JSON，但当前没有 NumPy。先检查环境再运行，不为阅读缓存加载 GPU 模型。

## 5. 实验分组：先固定图，再扩大覆盖

下面的数值和命名是本交接提出的默认实现协议，不是已经运行的新实验。实现者可以提出修改，但必须记录为新配置并在看新评测结果前冻结。

### 5.1 第一阶段：固定 node 和图

默认主图 `G0`：按已冻结 role_audit，从旧 213 条图中取 187 条 semantic proposal。reference/admin 数据保留在独立来源通道。C、D 及 endpoint 对照必须用完全相同的 G0。使用全部 213 条边可作为另一个明确命名的来源策略消融，不能悄悄混入某一组。

| Arm | 图/检索方式 | 定位 |
| --- | --- | --- |
| A_node | 原有 node 检索取 dense Top20，同一最终 reranker | 主无边对照 |
| B_current | 复现当前 gate 路径与候选规则，复用真实 35 条 gate 输出 | 当前系统参考；保留原始 INVALID，不偷偷修复再复用原结果 |
| C_pair | G0 的两端证据与上下文联合 embedding，全局检索 edge index | 两端联合内容对照 |
| D_relation | 与 C 相同两端文本，额外加入开放式关系描述，编码并检索 | 用户提出的主方案 |
| E_endpoint | 与 C/D 相同 G0、全局入口和页面映射，但按 query 与独立端点表示的匹配排序 edge | 区分联合表示与仅换检索入口的必要控制 |

E 的默认分数：`max(cos(q, A_text), cos(q, B_text))`，两端文本分别用与 C/D 相同的 8B 编码器编码。不能直接拿不匹配片段的旧 view 分数冒充该控制；只有文本、模型及预处理 hash 完全一致才复用。

- **D vs C**：在同端点信息、同图、同入口、同预算下测关系描述的增量。
- **C vs E**：测联合表示相对独立端点匹配的增量。
- **D vs A/B**：测整套系统变化；B 是 seed 后局部 gate，C/D 是全局 edge 检索，不能把差异全部归因于 embedding。
- 旧 edge-bonus 排名可以单列历史参考，不作为新组共享的排序规则。
- 所有组都输出带相同 reranker 的版本；若加不使用 reranker 的快速版本，应全组一起报告，不能跨版本宣称增益。

### 5.2 第二阶段：更宽候选图和新数据

第一阶段只能检验旧图上的表示/检索变化。扩大候选覆盖另开实验，不能与 D 的表示变化混在一起。

从冻结 views/vectors 重建并保存完整初始候选池，包含近邻、词法、明确引用等来源。适当增加每 node 覆盖与跨文章 escape，记录文章路由前后候选。候选是导航提议，不自动升级为已验证的语义关系。不要只沿用旧文章路由丢掉的候选而声称已扩大覆盖。

新图再次比较 C/D/E，并固定相同在线页面预算；图规模、节点覆盖率、建图时间、编码成本分别报告。同文档阅读导航和引用连接应有明确来源标记，不伪装成 RELATED 证据。

## 6. Edge 数据契约

新增 sidecar，引用原 node/edge ID，不覆盖原 node、旧图或历史预测。建议一条记录包含：

```json
{
  "edge_id": "existing_task_id_or_stable_pair_id",
  "source_node_id": "node_A",
  "target_node_id": "node_B",
  "graph_version": "frozen_G0",
  "source_route": "semantic",
  "endpoints": {
    "A": {"node_id": "node_A", "spans": [], "contexts": [], "pages": []},
    "B": {"node_id": "node_B", "spans": [], "contexts": [], "pages": []}
  },
  "relation_description": {
    "text": "自由文本描述，不设关系类别枚举",
    "cited_span_ids": [],
    "status": "pending",
    "provenance": "query_independent_generation"
  },
  "representation_mode": "text_with_original_caption",
  "input_sha256": "computed_not_placeholder"
}
```

上例只是 schema 示意，不能作为真实实验记录。每个 span 至少保存 `span_id/node_id/member_id/char_start/char_end/text/member_sha256/source_kind`。offset 采用 Python 原始字符串的 Unicode 字符索引、左闭右开；必须满足 `original_member[start:end] == text`。如检索文本另做空白归一化，保留其到原文的映射。

实施规则：

1. 从原始 member 重建连续原文。仅合并同一 member 内重叠或相接的区间，不跨 node/member 缝合句子；跨段保持显式分段和独立 span ID。
2. 恢复完整句子或表格上下文属于新增上下文，记录扩展区间与策略，不冒称旧 anchor 原样。C/D/E 共享同一份恢复后的端点文本。
3. 必要上下文可包含原始标题、相邻句、公式定义、caption、表头、单位与年份。选择规则只依赖文档和 edge，不依赖评测 query 或 gold。
4. 生成模型选择 span ID，由程序回填引用。保留原始回答、引用 ID、校验错误；校验只能证明来源可追溯，不能证明语义成立。
5. 描述要保留主体、时间、条件、否定、统计口径和不确定性。关系弱或证据不足时可以如实描述，不强迫生成“支持”关系。
6. 不直接把旧 `model_result.reason/limitation` 当作可信原文。若复用，标为单独的 legacy-description 消融；主 D 使用重新生成的、仅看原始证据的描述。
7. 描述生成不得读取 queries、answers、gold、旧 query-gate 判断或其解释。描述中不得针对已知 query 补出所谓“缺失答案”。
8. D 描述失败时默认退回 C 的相同文本，记录 fallback；不单独删除该 edge，否则 C/D 不再同图。报告失败率与 fallback 数量。
9. 可重试一次，但第二次必须包含具体错误反馈或使用受约束输出；同一确定性请求原样重试没有修复作用。
10. 纯文本 encoder 不能直接读取图片。原图、caption、生成视觉描述分别保存来源；使用生成描述时 C/D/E 必须一致并注明。直接多模态 edge encoder 是后续独立实验。

## 7. 编码、缓存和端点顺序

- 默认沿用本地 `EvidenceNet/models/Qwen3-Embedding-8B`；运行前检查实际模型文件，配置路径可覆盖，不把历史远端路径硬编码到公共逻辑中。
- 新 query 与 edge 必须使用同一模型/兼容任务配置。旧 node 查询缓存来自 Qwen3-Embedding-0.6B，只能用于原有 node 召回通道，不能与 8B edge 向量点积。
- 固定并记录 tokenizer、模型权重/版本、query instruction、pooling、归一化、dtype、最大长度和代码 hash。旧 8B view 编码使用 last_token、L2、max_length=512；它没有自动 query instruction，新增 query 编码须显式决定并冻结。
- 主 C 文本为两端证据加上下文；D 仅额外加入关系描述，**不改变两端片段**。
- 默认新编码上限 512 tokens，提前为描述预留固定预算（建议 64 tokens），其余扣除标记后公平分配给两端与上下文。使用实际 tokenizer 检查；不能给 D 加描述后直接全局截断，使 B 端丢失。
- 过长原文按可追溯片段/完整表行选择，记录省略与覆盖情况。遇到无法保留关键公式、表头或条件的项，标记 insufficient；如改用更长长度，要对 C/D/E 一起改变并另记协议。
- 为降低 A/B 顺序偏差，建议 C/D 均编码 AB 和 BA 两个视图，edge 得分取两者余弦最大值；视图数固定，不靠给某些边更多视图获得不公平 max 优势。另报额外编码成本。
- E 使用相同两端内容各自编码；query 编码在 C/D/E 之间复用。
- `.npy` 必须有行号到 edge/view ID 的映射和 manifest。新索引行顺序变化、描述变化、模型变化或 prompt 变化时拒绝旧缓存。校验维度、有限数值、L2 范数与完整记录数。

## 8. 在线检索与页面预算

推荐 v1 默认：全局 edge 检索；原 dense core 10 页；最终 reranker 候选 20 页；每页 2 个冻结 query 命中窗口；最多扫描 `min(100, |G0|)` 条排好序的 edge。数值在 protocol 中配置，不能看测试结果后临时调参。

```python
direct = frozen_node_page_ranking(query)   # 旧 0.6B 通道，可复用缓存
selected = ordered_unique(direct[:10])

# C/D/E 使用各自分数，但相同 edge 集、去重和页面映射规则
for edge in sort_by_score_then_edge_id(edge_scores)[:max_edges_scanned]:
    # 两端都可作候选。固定用 direct rank、page ID 处理端点顺序。
    for page in endpoint_pages_sorted_by_direct_rank(edge):
        if page not in selected and len(selected) < 20:
            selected.append(page)
    if len(selected) == 20:
        break

fill_from_direct_ranking(selected, limit=20)
ranked = rerank_with_shared_page_scores(selected)
```

- 从同页 edge 或重复目标中不能得到新候选时，继续扫描后续 edge；不能把重复项当作已经用完的有效页配额。
- 小图可计算全部 edge 分数，再按共同的扫描上限取候选；大图可直接检索 top100。不足时按预冻结上限处理，不能临时无限扩大扫描以凑新增页；报告扫描数与截断原因。
- 每条边的两端页面必须来自 node 的正式 provenance；不能由生成描述猜 page ID。
- 对页面去重后统一 rerank；不叠加 edge 数量、节点度数或 cosine 奖励。
- A/B/C/D/E 的页面文本获取函数必须相同。按该 query 的原始 node/window 分数取固定两窗，每页得分为两个 BGE 分数的最大值；统一相同 tie-break。
- 保存所有组候选页的并集，先构造唯一 query–window 评分任务，再缓存一次供各组复用。新 edge 带来的页面可能不在旧 955 个任务里，不能只加载旧任务后默默漏掉它们。
- BGE 文本截断及 query 长度检查复用现有 runner；长 query 不可静默截断。缺模型权重/缺评分时报告 incomplete，不填零冒充完整实验。
- **记录 edge 关键证据是否实际出现在这两窗中。** 如想加入 edge anchor 扩充重排证据，应另立 evidence-expansion 消融，并给所有对照相同的冻结页面证据集合。
- 可另做 seeded/local 选边版本，但须在 arm 名、入口、路径和预算中明确；不要与 global 版本混为同一种检索。

## 9. 开放描述的生成要求

最小 prompt 应要求模型：描述两端明确可见的联系及重要差异；指定支撑的 span IDs；保留限定条件；缺依据就说明不足；不得把同一主题当作独立佐证；不得推测未展示图像或被引用论文的结果。

不需要额外的语义类别字段。可以输出 `description/cited_span_ids/limitations/status` 等处理字段。对无向边，文字仍要明确 A/B 各自说了什么，不能混淆所属论文、作者、研究人群或时间。

关系描述模型可以复用现有 Qwen3.5-35B-A3B，但它与 8B embedding 模型是不同阶段。需记录离线生成成本。第一阶段不训练或微调 encoder；如果以后训练，需要新的训练/验证/测试划分，不能拿这批评测 query 作监督后报告同集成绩。

## 10. 评测约定

官方数据定义与指标参考：[VL-DocIR 数据卡](https://huggingface.co/datasets/anonymous-8421/VL-DocIR)。先固定已有 pilot revision `40a1818110c20e9279bbb4a3b6283ceac2d631ba`；新实验要记录实际采用的数据 revision，不能将 main 最新数据与旧缓存混合。

必须保持相同 query 文本、corpus page IDs/图像 hashes、gold、node generation 输出、来源分流策略、页面预算和重排器。答案、gold、人工复核意见不进入编码、描述生成或候选筛选。

主报告：Recall@5、nDCG@5、RecallAll@5、mAP@5；同时输出 @3/@10、nDCGAll、逐 query 指标和六种 question type 的宏平均。mAP 是本项目补充指标，定义沿用现有脚本：

```text
AP@k = sum(P@r * relevant(r), r=1..k) / R
R = 该 query 全部不同 gold 页面数
```

不要悄悄换成除以 min(R,k)。页面 ID 使用 `(document_id, str(page_number))`；冻结评测的平分规则是按这个 tuple 排序，不能未经说明切换为整数页码排序。

同时报告：

- 每 query AP@5/RecallAll@5 的 wins、losses、ties；分跨文档/同文档、多页/单页、可用模态观察。
- 新增相关页、新增非相关页、被挤出的原候选页、最终 Top5 变化；这些标签仅在排名冻结后作事后分析。
- 候选集完全相同的 query 数；相同候选与相同页面评分必须产生相同排名。
- 关系描述失败率、fallback、丢失端点/图片/表头、输入截断及引用可追溯性。
- 离线描述/编码成本、索引规模、在线 query 编码和检索耗时、reranker 次数；平均指标外保留 latency 分布。
- 多次查看旧 pilot 后，不用小幅均值变化宣称泛化提升。正式 holdout 做配对、按题型分层的不确定性估计。

页面 gold 只标页面相关，不能把页面内所有 node 或所有 incident edge 标成正例；模型解释也不是 edge 金标。最终检索收益是主判据，路径诊断用于解释原因。

## 11. 新 holdout 与外部模型比较

先完成旧 24 题的回归和缓存等价性检查，再固定没查看过的新 query、完整相关文档页及足够干扰文档。建议按 4 个来源 × 6 类问题分层；具体规模由实现预算确定并写入 manifest。

新 query 至少与旧 24 题去重；优先文档也与开发集隔离，若不能隔离则明确是 query-only holdout。不能先跑方法，再挑 baseline 表现差或新方法表现好的题当测试集。图和描述可以看到无标签文档，但不能看到测试 query/答案/gold。

仅挑 gold 文档构成的小库会偏容易，必须记录语料选择过程与干扰文档。选择语料时使用 gold 以确保相关页存在，与把 gold 送入模型是两回事，报告须透明。

旧同语料 ColNomic scores 可直接复用作历史 pilot 对照。新 holdout 必须用相同 query/语料重新跑外部模型；不能拿本地 24题/518页的分数直接对比作者全库表格，也不能把本地基础 ColNomic 说成作者的 Ctx/Ensemble/Rerank 版本。

## 12. 输出与搜索路径

建议新根目录：`EvidenceNet/output/vldocir_edge_embedding_v1_<date>/`；路径尚未创建。至少保存：

```text
protocol.json                     # 阶段、arms、图集合、入口、预算、模型设置
manifest.json                     # 输入/代码/模型/模板 hashes
edge_records.jsonl                # 两端可追溯证据、上下文、描述与生成状态
description_predictions.jsonl     # 原始输出、校验错误、重试、版本
edge_inputs_pair.jsonl            # C 实际编码文本，AB/BA 映射
edge_inputs_relation.jsonl        # D 实际编码文本，失败fallback记录
endpoint_inputs.jsonl             # E 的匹配端点文本
edge_vectors_pair.npy
edge_vectors_relation.npy
endpoint_vectors.npy
query_vectors.npy                 # 仅对应同模型的新edge查询通道
embedding_manifest.json
query_candidates.jsonl
reranker_inputs.jsonl
reranker_scores.jsonl
runs/<arm>.jsonl                  # question_id/document_id/page_number/score
search_paths.jsonl
results.json
REPORT.md
index.html
```

每条搜索路径至少记录：query ID/text、arm、global/seeded 入口、seed（无则 null）、edge ID、两端 node/page IDs、原文 span IDs、edge 分数、两端独立匹配分数（如已计算）、原 dense 页排名、是否新增页、去重/预算丢弃原因、描述版本、reranker 实际输入及得分、最终排名。全局 edge 检索不要伪造一个并未经过的 seed。

full ranking 如通过“已重排候选在前、其余沿原 dense 顺序追加”得到，必须明确记录；不要把未重排页面称为已评分。完整 AP 仅在明确完整排序协议后报告。

## 13. 实现顺序与验收

建议新建独立模块，例如 `edge_embedding_records.py`、`run_vldocir_edge_embedding.py`、`report_vldocir_edge_embedding.py`；这些是建议名称，目前尚不存在。CLI 分阶段：prepare、describe、embed、retrieve、rerank、report。每阶段可恢复，GPU阶段和CPU阶段分离。

按以下顺序完成：

1. 读取旧结果、核验 hashes，冻结 G0 与 A/B/C/D/E 协议，建立新的输出目录。
2. CPU 构造并验证两端 spans、连续原文、上下文、页面映射和 C/E 输入，做 token 预算预检。
3. 离线生成开放描述，记录引用和失败；构造 D，确认 C/D 两端文本完全相同。
4. 编码 query、C、D、E，验证缓存身份和维度，保留原始编码文本。
5. CPU 计算候选与完整路径，先统计候选是否变化；若没有变化，明确报告，不用额外重排包装成 edge 增益。
6. 对所有 arm 的唯一 query–passage 并集计算共享重排分数，完成度不足时保留检查点。
7. 排名冻结后加载 gold，生成统一指标、逐 query 对照、失败例和可视化。
8. 第一阶段完成后，再单独扩大图和准备 holdout。

需要有意义的验证：

- span offsets、原文 hash、重叠合并、跨 member 边界与表格引用正确；公式、弯引号、断行可追溯。
- C/D 使用相同 G0、相同端点原文；D失败不偷偷减少图。
- 编码模型或文本改变时不能读旧向量；0.6B/8B 混空间被拒绝。
- 同页/重复 endpoint 不占新页额度，最终页去重、预算一致、无非法 page ID。
- query/gold 不进入离线描述和图生成；gold 只在评测阶段读取。
- 同候选集、同页面分数下排序完全一致；空edge/fallback回到定义好的无边候选。
- 部分任务、无效输出、reranker 缺失不伪装成功；每个 query 都在报告中，失败 query 不被删掉。
- 数值小样本检查 Recall/AP/RecallAll 与现有评测器一致。

## 14. 执行环境与提交边界

本次交接只要求写方案；没有因本文而提交新任务。实现者先完成代码、CPU预检和可复核配置，实际 GPU 执行根据用户后续指令和当时资源安排。

Horeka 用户名是 **`dv3352`**；原项目服务器账户是 **`ka_dv3352`**。远端项目基路径为 `/hkfs/home/project/hk-project-p0025545/dv3352/Project`，本地是 `/hfs2/data/project/hk-project-p0025545/ka_dv3352/Project`，不能混用。

先前 gate 用 dev_accelerated、4 GPU、1小时，但这不是新 embedding/reranker 的资源保证。不得把旧 job ID 当新提交；不得自动排重复任务。新实验单独目录，保留已冻结图、baseline 与已下载结果。

本地现有模型目录包括 `EvidenceNet/models/Qwen3-Embedding-8B`、`EvidenceNet/models/bge-reranker-v2-m3`；远端位置和完整权重需实际核实。先前 Horeka 未完成 BGE 权重传输，不能假定现在已准备好。SSH socket 只属于所在主机，存在也不证明可用；认证信息只在用户终端输入，不写进代码、文档或日志。

## 15. 可直接交给实现模型的任务

> 请先阅读本文件与列出的现有代码，实现“离线开放式 edge 描述与 embedding、query 驱动 edge 检索、VL-DocIR 同语料对照”。先复用冻结 node 和 G0，完成 A/B/C/D/E 的可复现实验框架、缓存验证、搜索路径记录和 CPU 检查。用户明确要编码的是 edge，不是仅重算 node 相似度。将历史事实、建议默认协议、尚未执行的新实验分开记录。不要覆盖旧结果，不要把协议有效率当准确率，不要把本地 pilot 分数冒充官方全库成绩。完成后列出实际改动、验证结果、还需要的模型/计算资源和可执行命令；未运行的阶段明确标记。
