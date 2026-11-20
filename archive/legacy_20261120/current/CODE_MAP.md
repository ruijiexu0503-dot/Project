# 代码导航与提交范围

整理日期：2026-10-09。运行路径保持稳定；旧实验的本地归档与恢复记录保留。

| 目录 | 用途 | Git 中保留的内容 |
|---|---|---|
| `parsing/src/`、`parsing/src_splitpage/` | 解析、拆页、几何对齐 | 源码、提交器和测试 |
| `parsing/experiments/` | Dolphin 和视觉解析实验 | Driver、配置、说明；生成图片和中间文件忽略 |
| `EvidenceNet/evidence_graph/` | 节点和文章图的运行库 | 核心模块 |
| `EvidenceNet/pipeline_steps/` | 阶段入口 | 默认节点、可选 hybrid 节点、文章图入口 |
| `EvidenceNet/scripts/` | 节点生成、验证、可视化和检索实验 | 可执行代码、模板 |
| `EvidenceNet/config/`、`EvidenceNet/docs/` | 配置与结果记录 | 通用配置、实验限制和设计说明；实验 sources/reviews JSON 本地忽略 |
| `EvidenceNet/experiments/vldocir/` | VL-DocIR 接入 | README；下载记录和查询标签留在本机 |
| `EdgeGeneration/` | 跨文章和跨文档发现 | 源码、配置、测试；`CrossDocumentDiscovery` 是兼容链接 |
| `OfflineCitationGraph/` | 离线引用图 | 独立模块、试跑入口、配置、测试 |
| `current/` | 环境入口、工具脚本、导航与归档记录 | 环境脚本、恢复工具和文档；JSON 清单本地保留并忽略 |
| `current/slurm/` | 当前 Slurm 提交器 | 仅 README；17 个 sbatch 本地保留并忽略 |
| `current/json/` | 本地整理配置、归档和指标记录 | 仅 README；JSON/JSONL 忽略 |
| `experiments/` | 独立试验 | Driver 和说明，本地依赖/产物忽略 |
| `_archive/`、`migration/` | 本地历史实验和迁移备份 | 忽略；恢复工具和清单放在 `current/` |
| `data/`、`external/`、模型、虚拟环境、日志、输出 | 数据与运行环境 | 忽略 |

## 这次工作的入口

- Hybrid v2：`EvidenceNet/scripts/run_hybrid_node_v2.py`；VL-DocIR 使用通用阶段驱动
  `EvidenceNet/scripts/run_vldocir_nodes.py`，执行图片描述、候选准备、Qwen 决策、覆盖验证。
- 文章划分与跨页：`EvidenceNet/pipeline_steps/step2_c_document_article_graph.py`。
  该图与 hybrid EvidenceNode 的整合状态见对应实验记录，不据此宣称 node 图边已完成。
- Node 构成与链接查看：`EvidenceNet/scripts/build_evidence_node_graph_viewer.py` 和 HTML 模板。
- VL-DocIR：下载/选样/解析/适配/检索/评测脚本均在 `EvidenceNet/scripts/`；
  作业入口为 `current/slurm/vldocir/*.sbatch`，流程与指标见实验 README。
- 完整 pipeline 状态与设计决策：根目录 `PIPELINE_CURRENT.md`、`PIPELINE_STEPS.md`、
  `PIPELINE_DECISIONS.md`。实验成绩不等同于生产默认行为。

## 提交说明

此前归档形成的 260 个已跟踪文件删除记录均有本地归档副本，2026-10-09
逐文件校验与 HEAD 内容一致。本地映射见
`current/json/tracked_files_20261004.json`；它和完整本机规划 `current/json/archive-plan.json` 均已忽略。
删除记录代表移出当前工作树；原版本仍可从 Git 历史恢复。
忽略规则不会隐藏已跟踪文件的删除，不能靠添加 `.gitignore` 消除这些记录。

本轮补充忽略海报解析实验的生成文件，不移动当前执行脚本或运行中的输入/输出。
原有归档、数据、模型和环境保持在本机，Git 提交包含代码、配置、测试和文档；归档清单本地保留并忽略。

JSON/JSONL 按用途保留：通用配置、parser 来源清单和 ground truth
提交；EvidenceNet 的实验 sources/reviews JSON、本地归档清单、运行输出、缓存、归档执行状态、指标汇总和生成的
ground-truth `summary.json` 忽略。新增实验产物应写入已经忽略的 output/work/data
目录，避免用全局 `*.json` 规则隐藏配置和评测输入。

建议提交标题：`Organize pipeline experiments and add hybrid node retrieval evaluation`。
提交前检查记录见 `current/COMMIT_CHECKS.md`。

Slurm 提交器已从 96 个整理为 27 个保留入口，其余 69 个移到本机忽略的
`_archive/2026-10-09-launchers/`。清单和恢复方式见 `current/LAUNCHERS.md`。
不使用全局 `*.sbatch` 忽略规则；`current/slurm/` 的本机提交器忽略，其余模块入口保留。
其中原 `current/` 根目录的 17 个提交器已统一移动到 `current/slurm/`，
脚本内容保持一致；文档和 selection/launcher 清单同步使用新路径。
