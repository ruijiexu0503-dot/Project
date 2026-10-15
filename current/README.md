# 当前保留的结果与运行路线

更新日期：**2026-10-15**。[Edge 开发前检查点](PRE_EDGE_CHECKPOINT.md)记录本次提交范围，以及文章分割尚未自动接入 hybrid-v2 主链的实际情况。
代码目录见 [CODE_MAP.md](CODE_MAP.md)，
提交前验证见 [COMMIT_CHECKS.md](COMMIT_CHECKS.md)。
Slurm 脚本已收拢为 27 个保留入口，旧提交器的查找与恢复见 [LAUNCHERS.md](LAUNCHERS.md)。

## 当前实验入口

| 工作 | 入口与说明 | 状态 |
|---|---|---|
| VL-DocIR 检索对照 | [接入说明与任务链](../EvidenceNet/experiments/vldocir/README.md)、[冻结 baseline](../EvidenceNet/experiments/vldocir/BASELINE.md) | 24 查询、518 页、7,291 个节点的六组无 edge 检索评测已完成并冻结；不是全库结果。 |
| Hybrid v2 节点 | [验证记录](../EvidenceNet/docs/hybrid_evidence_node_v2_2026-10-08.md)、[通用 VL-DocIR 驱动](../EvidenceNet/scripts/run_vldocir_nodes.py) | 49/49 页结构有效，15 个已知错误合并均阻止，3 个表格恢复；仍是 shadow 分支 |
| 文章划分、阅读顺序和跨页 | [文章图契约](../EvidenceNet/experiments/document_article_graph/README.md)、[实际接入检查](PRE_EDGE_CHECKPOINT.md) | 独立 component shadow 图和来源匹配适配已有实现；通用 Dolphin/hybrid-v2 驱动未自动调用文章分割。 |
| Node 构成与链接查看 | [可视化构建器](../EvidenceNet/scripts/build_evidence_node_graph_viewer.py) | 来源成员、原图、描述、结构标题及文章分组；推定链接与实际边须区分 |
| 稳定包入口 | [EvidenceNet CLI](../EvidenceNet/README.md) | 确定性节点与结构校验；与新 hybrid 实验入口分开 |

Hybrid v2 的两组回归都保留了 3 个表格且未保留 15 个已知错误合并；
embedding＋几何＋Qwen 保留 2/2 个指定续句，几何＋Qwen 为 0/2。
两组都漏掉一个正确的跨图续句，并保留一个幻灯片标题误入 evidence 的问题。
这些是开发回归，不是独立准确率。Boundary v3 未通过生成/来源校验，未用作本轮检索入口。

## 历史结果与保留依据

整理日期：**2026-10-04**。日常从这里进入；数据、模型和原始实验记录保留在本机。
指标从已有结果读取，没有重跑模型。主要结果保留在下方实验文档；
本机生成的 `current/json/metrics.json` 指标/哈希汇总已忽略，不进入提交。
整理后153项测试、49页输入预检及归档完整性检查通过，详见 [验证记录](VALIDATION.md)。

**全量测试准备**：[25份文档、1048页/张的清单与启动记录](ALL_DATA_RUN.md)。
10月5日的49页回归46209与候选阶段46210已完成：[结果](../EvidenceNet/docs/latest_regression_results_2026-10-05.md)。
32页完整、9页partial、8页flow失败；41页结构有效，同时有3个旧完整页回退。1048页全页推理尚未提交。

**10月5日修复与语义审计**：[详细记录](../EvidenceNet/docs/assignment_patch_and_semantics_2026-10-05.md)。
新增可选 bounded-v2 / span-id-v2；40项测试、49页本地检查通过。旧41页flow不变，2个失败可离线修复，
后续GPU补丁任务48023实际修复5/8失败页。42条边完成文本审查，23条核对原图，发现7条应拒绝的关联及证据选择问题；
这是定向助手审查，不是独立准确率。任务48027完成9页，CLAD 1页flow失败，不能将缺失边当成语义改进。

**10月6日 prompt 对照未通过晋升**：[结果与归档记录](../EvidenceNet/docs/prompt_comparison_and_archive_2026-10-06.md)。
52533两组各12个视觉案例，固定输入与校验规则，仅改变prompt。明确错误边3→3、有依据的关联13→9、
正例视觉保留7/7→6/7，因此保留原默认prompt，**未提交扩大测试**。42项相关测试通过。
12个旧实验目录和4份日志已归档，1,441个文件逐一核验，原路径兼容链接保留；
本地清单：`json/experiment-archive-20261006.json`，已忽略，磁盘文件保留。

**10月7日节点生成混合试验**：[四页对照](../EvidenceNet/docs/hybrid_node_generation_pilot_2026-10-07.md)。
在 parser/embedding/几何骨架上，仅让35B判断相邻文本续句和短副标题；三页开发样本加一页预留样本中，
结构文字误入证据节点1→0、漏合并续句3→1，图片说明仍为4/4，未增加审阅到的错误合并。
已提供[可选入口](../EvidenceNet/pipeline_steps/step2_b_hybrid_member_nodes.py)，默认 Step-2A 未切换；
表格节点和困难多图页还需独立审核。

## 早期路线与对照记录（10月4日至7日）

| 阶段 | 保留结果 / 入口 | 选择依据与限制 |
| --- | --- | --- |
| 稳定 OCR → 布局 → 对齐 → 节点 | [DeepSeek pipeline](../parsing/pipeline_steps/step1_run_parsing_pipeline.sbatch)、[节点入口](../EvidenceNet/pipeline_steps/step2_a_evidencenet_build_nodes.py) | 既有稳定路线，保留原始几何与来源；不等同于已解决文章重建和语义关系。 |
| Hybrid v1 历史对照 | [49页压力测试](../EvidenceNet/docs/hybrid_node_49page_stress_2026-10-07.md)、[七类材料对照](../EvidenceNet/docs/hybrid_node_mixed_material_pilot_2026-10-07.md)、[v1 阶段入口](../EvidenceNet/pipeline_steps/step2_b_hybrid_member_nodes.py) | v1 有至少15/71错误合并并漏3个表格；当前检索使用上方的 v2 通用驱动，v1 入口没有升级为 v2。 |
| Parser 对照 | [10页比较](../parsing/audits/dolphin_vs_deepseek_magazines_v1/comparison_summary.json) | DeepSeek 文本召回 91.56%，Dolphin 85.87%；Dolphin bbox 覆盖 100%，DeepSeek 90.84%。这是 PDF 文本覆盖代理指标，不能据此宣布 parser 全面胜出。两条路线保留。 |
| HoReKa2 原生视觉成员 → 节点 | [35B结果](../EvidenceNet/output/member_asset_evidence_pipeline_horeka2/Qwen3.5-35B-A3B/summary.json)、[35B入口](../_archive/2026-10-09-launchers/EvidenceNet/slurm/run_member_asset_nodes_hk2_qwen35_h200.sbatch) | 35B 四页结构验证 **4/4**；122B **2/4**，含一页生成失败。继续优先用35B；122B结果留作对照，不用模型大小代表质量。 |
| 阅读流 → 有界图文组合 | [bounded v4](../EvidenceNet/output/bounded_composite_v4_geometry/summary.json)、[实现](../EvidenceNet/scripts/run_bounded_composite_pilot.py) | 五页结构验证 **5/5**，仍有34个 needs_review 节点；语义审核 pending。保留为小样本候选及后续实验输入。 |
| 多模态信息单元 | [labelled v2 CPU](../EvidenceNet/output/multimodal_information_unit_pilot_v2_labelled_cpu/summary.json)、[实现](../EvidenceNet/scripts/run_multimodal_information_unit_pilot.py) | 两页覆盖验证 **2/2**，合计59个组件、5个组合；一条模型提议被拒绝。只是两页候选结果，不当作全语料结论。 |
| 49页关系优先重建 | [v7目录](../EvidenceNet/output/relation_first_corpus_shadow_v7_cpu/)、[当前实现](../EvidenceNet/scripts/run_relation_first_corpus_shadow.py) | 当前开发路线：29完整、5部分、15阅读流失败。保留整个结果和失败样本，不能只展示成功页。 |
| 同语料完成率对照 | [v5目录](../EvidenceNet/output/relation_first_corpus_shadow_v5_cpu/) | 31完整、3部分、15失败，比v7完整完成页数多；但提示和关系验收策略不同，不能直接推出语义质量更好。 |
| 当前节点 → 边候选衔接 | [v7 adapter快照](../EdgeGeneration/output/relation_first_v7_edge_input_snapshot_20261001_review/)、[入口](../EdgeGeneration/scripts/prepare_relation_first_inputs.py) | 导入34页，431单元、37局部图文关系、2403候选；15页明确跳过。候选还不是已验证语义边。 |
| 向量模型比较 | [94单元结果](../EdgeGeneration/output/full_database_embedding_benchmark_v1/comparison/summary.json) | Qwen3-Embedding-0.6B 的整体 Top-1 **64.89%**、R@5 **89.36%**、MRR **0.7467** 领先该实验。指标是单元恢复/凝聚性代理，不是关系精度；保留所有同场模型对照。 |
| ANN 工程基准 | [ANN v3](../EdgeGeneration/output/ann_candidate_real_v3/summary.json)、[实现](../EdgeGeneration/scripts/run_ann_candidate_pilot.py) | 447单元、65文章/论文，HNSW top-10 与精确检索重合率1.0；证明该快照检索一致性，不证明语义正确。 |
| 文内语义类型 + REFERENCES | [split-taxonomy结果](../EvidenceNet/output/split_taxonomy_relation_typing/) | 27个可评语义对：35B语义类型+方向66.67%，3.6版本62.96%；REFERENCES F1分别33.33% / 46.15%。各维度胜负不同，保留两者与原始GT，不选一个全局赢家。 |
| 精确引用图 | [三论文对照](../OfflineCitationGraph/output/gw150914_three_paper_pilot/comparison_summary.json)、[包入口](../OfflineCitationGraph/README.md) | 增强精确书目信息匹配从1条跨文档引用增加至3条；保留同场基线，仍是三论文 pilot。 |

**保留的研究主线**：Dolphin/原生视觉输入 → 来源可追溯组件 → 阅读流 → 有界图文关系 → EvidenceNodes → 分作用域候选 → 待做的语义核验。
**稳定对照**：DeepSeekOCR2 + PP-DocLayout → 几何校验对齐 → 确定性节点。
两条路线不拼成一个已经验证完毕的系统。完整流程契约仍见 [PIPELINE_STEPS](../PIPELINE_STEPS.md)。

**新 shadow 实验（未选入基线）**：[v7 flow/anchor 失败回放与短 GPU 重复归属实验](../EvidenceNet/docs/flow_anchor_recovery_2026-10-04.md)。
它只验证来源 ID 记账和局部模型选择；未解决的组件仍被隔离，语义验收待做。

**已接入的可选改动（D-032）**：[受限修复与窗口检索](../EvidenceNet/docs/bounded_recovery_integration_2026-10-04.md)。
集成版不采用上述探索回放的缺失片段隔离策略：缺失 ID 仍报错，重复归属只允许一次受限模型选择；
恢复页保留 `partial` 和审核标记。冻结回复回归：34个原有效 flow 不变，5页修复重复归属、3页走视觉分支，7页仍失败；
局部关系37→39。以上是结构验证，尚无独立语义准确率。
实际dev GPU检查也已完成：三页均结构有效、均为partial；窗口检索296单元生成317窗口、2885候选对，
其中136对命中非首窗口。三路候选各600对，等待独立语义审核，详细结果见上述集成记录。

**进一步改动（D-033）**：[原文片段选择、视觉角色与盲审](../EvidenceNet/docs/span_grounding_and_blind_review_2026-10-04.md)。
新增 `span-id-v1` 引文选择和带来源校验的视觉角色审核表；两项均为可选实验参数。
三路候选已生成[248对盲审页面](../EdgeGeneration/output/blind_candidate_review_20261004/reviewer/index.html)，
保留原页、方向和证据审核，当前无标签；GPU检查作业45701已提交。

## 避免把失败当成改进

[staged/joint CPU 对照](../EvidenceNet/output/qwen_stages_comparison_v1_cpu/REVIEW.md) 的两种方法都未通过严格验证。
联合推理在一页上更快，不足以替换当前路线；较少的短节点也可能来自遗漏源片段。
该失败对照保留，防止再次仅按速度、输出数量或版本号选择方案。

## HoReKa2 的明确入口

以下命令从仓库根目录执行。新的运行使用独立输出目录，避免覆写已选结果。

```bash
cd ~/Project
source current/env.sh

# 49页输入预检：不调用模型。
bash current/check_relation_first.sh

# 真正提交CPU实验时才执行；本次整理未提交推理。
sbatch current/slurm/edge_generation/run_relation_first_v7_cpu.sbatch

# 当前较可靠的HoReKa2 35B节点试验；正式运行时才执行。
sbatch current/slurm/evidence_nodes/run_member_asset_35b_h200.sbatch

# 多模态2页试验；正式运行时才执行。
sbatch current/slurm/evidence_nodes/run_multimodal_labelled_cpu.sbatch

# D-032短GPU实验：三页集成检查 / 296单元窗口检索，均写入独立目录。
sbatch current/slurm/evidence_nodes/run_bounded_recovery_dev.sbatch
sbatch current/slurm/edge_generation/run_window_candidates_dev.sbatch

# D-033：GW/Hallmarks的原文片段选择与已审核logo处理。
sbatch current/slurm/evidence_nodes/run_span_grounding_dev.sbatch
```

稳定解析基线需要GPU；从 `parsing/` 提交时，`PROJECT_ROOT` 必须是 **parsing目录**，
不能直接沿用研究入口的仓库根目录：

```bash
cd ~/Project/parsing
export PROJECT_ROOT="$PWD"
export HF_HOME=/hfs2/data/project/hk-project-p0025545/ka_dv3352/.cache/huggingface
export LAYOUT_MODEL_DIR="$PWD/../external/models/PP-DocLayout-L"
sbatch --partition=gpu-h200 --account=hk-project-p0025545 \
  pipeline_steps/step1_run_parsing_pipeline.sbatch
```

上面解析命令保留基线原有输出/恢复行为；不要用 `OVERWRITE` 重新生成冻结的比较输入。
已有解析结果建节点的入口为 `EvidenceNet/pipeline_steps/step2_a_evidencenet_build_nodes.py`，
其配置路径按 `EvidenceNet/` 工作目录解释。默认配置还包含既有规范化和后续选项，
不能把完整配置当作只执行某个新 shadow 方法。

历史结果中的 `/hkfs/...` 来源字段作为实验记录保留。它们不是新的HoReKa2运行入口；
跨机复用旧快照里的图片路径仍需做路径映射，不能仅以文件存在就判定已独立迁移。

## 文件放在哪里

本轮Git噪声清理与7份旧脚本的可恢复归档见 [GIT_CLEANUP.md](GIT_CLEANUP.md)。
解析工作目录、生成审计报告和本地第三方依赖仍在原位置，只增加忽略规则；当前入口继续保留。

- `current/`：精选结果索引、指标、明确运行入口、归档映射。
- 原包的 `output/`：精选结果和实际仍被引用的输入依赖，保持稳定路径。
- `_archive/2026-10-04/`：未选中的旧实验、脚本、提交器及输出，按原目录结构收拢。
- `_archive/2026-10-04-superseded-scripts/`：已被D-032集成实现替代的探索脚本与历史检索提交器。
- `migration/`：迁移备份和私人Codex历史备份，单独忽略，不进入Git。
- `data/`、`external/`、虚拟环境、GT和核心运行库继续保留；本次不清理下载模型或原始数据。

已跟踪文件的归档路径见本地 `json/tracked_files_20261004.json`，该清单已忽略。
完整规划 `json/archive-plan.json` 和执行日志 `json/archive-journal.jsonl` 本地保留并忽略。
`retained_outputs` 标明哪些是精选结果，哪些只是运行/来源依赖；依赖存在不代表方法被选为最好。
文件通过同一文件系统内重命名归档，没有删除。恢复命令见 [restore_archive.py](restore_archive.py)。
对Git已跟踪的旧文件，归档会表现为原路径删除；归档副本被忽略，但Git原历史和本地原内容均保留。
本次没有创建提交。
