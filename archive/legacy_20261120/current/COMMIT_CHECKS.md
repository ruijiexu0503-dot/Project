# 提交前检查

日期：2026-10-09。

| 检查 | 结果 |
|---|---|
| EvidenceNet 测试 | 143 passed |
| EdgeGeneration + OfflineCitationGraph 测试 | 37 passed；3 条已有 FAISS/SWIG 弃用警告 |
| Parsing 测试 | 41 passed |
| 新增/修改 Python 源码 AST 检查 | 186 文件通过 |
| 新增/修改 Shell、Slurm 的 `bash -n` | 91 文件通过 |
| 新增/修改 Markdown 本地链接 | 无失效链接 |
| `git diff --check` | 通过 |
| 此前归档对应的已跟踪删除 | 260 文件均有归档副本，与 HEAD 逐文件 SHA-256 相同 |
| 待提交文本中的常见 token、私钥模式扫描 | 无匹配；不输出凭据内容 |
| 海报解析生成文件 | 33 文件约 22 MB 被忽略；driver 保留 |

本轮未移动运行中的 pipeline 代码、输入或输出。数据、模型、日志和本地历史
归档保持原位置。代码导航见 [CODE_MAP.md](CODE_MAP.md)。

随后检查全部 11 份 README，修正其中 8 份的旧分区、归档入口、工作目录、
结构检测实际行为和实验版本说明；另更新 pipeline 状态图及 v2/v3 结果记录。
各模块 README 仍有独立用途，未删除。README 的 17 个 Bash 示例语法检查通过，
全部 Markdown 本地链接有效，EvidenceNet CLI/visualize 的 `--help` 检查通过。
此轮只改文档，不重新提交作业或重新运行模型。

JSON 清理：7 份生成的 JSON/JSONL 已从索引移除并加入忽略规则，磁盘原文件
全部保留。包括 6 份 `current/` 的执行状态/指标报告，以及旧评测的生成 summary。
该轮清理后保留 44 份 JSON/JSONL：配置、输入清单、审阅标签、ground truth、必要归档记录。
新增可移植归档映射覆盖 88 条路径映射 / 260 个历史已跟踪文件，单文件哈希核验通过；
移除了设备号、inode 和本机执行状态。所有保留 JSON/JSONL 语法检查通过。
既有 260 个归档删除之外，另有一项 summary 的停止跟踪；其本地内容保留。

Slurm 清理：96 个 sbatch 中保留 27 个可复用入口，69 个历史/被替代的提交器
移入本机忽略的 `_archive/2026-10-09-launchers/`，原内容及 SHA-256 保持不变。
当时新增清单后保留 JSON/JSONL 总数为 45。`restore_launchers.py` 的只读
预览确认 69 个文件可恢复；全部 96 个提交器通过 `bash -n`。
文档历史引用与 selection 配置已更新，无失效本地链接。VL-DocIR 的运行/依赖
任务保持原 ID 和路径，整理后队列核查正常。入口索引见 [LAUNCHERS.md](LAUNCHERS.md)。

随后将 `current/` 根目录的 17 个 sbatch 统一收进 `current/slurm/`。
源码内容及哈希未变，配置和文档路径已更新，根目录不再散放 sbatch。
Slurm 已保存既有作业的脚本副本；迁移前后保存脚本相同，无需重新提交任务。
17 个脚本语法、保留清单路径和本地 Markdown 链接检查通过。

最终 JSON 复查：另将 `current/` 下 5 份归档/整理清单从索引移除，
本地文件全部保留并忽略。当前保留 40 份 JSON/JSONL，均为配置、解析输入、
审阅标签或 ground truth。已有文件的删除记录仍在提交前显示为 D。
恢复工具需要本机清单与归档副本，详见 [归档说明](archives/README.md)。

随后将 11 份本地 JSON/JSONL 统一移动到 `current/json/`，内容哈希不变。
整理与恢复脚本、文档路径同步更新；模块内运行配置保持原位置。

随后将 17 个当前 sbatch 按五类用途分组，将 EvidenceNet 的 8 个实验 JSON
分入 `sources/`、`reviews/node_generation/` 和 `reviews/visual_roles/`。
运行和评测入口、文档及本地保留清单已同步更新。
分类后再次运行 EvidenceNet 测试：143 passed；25 个移动文件的 JSON/Slurm
语法与保留路径检查通过。队列仍为既有 VL-DocIR 任务，未重新提交。

最终按提交范围要求，将 `current/slurm/` 的 17 个本机 sbatch 和
EvidenceNet `sources/reviews` 的 8 个实验 JSON 从索引移除并忽略，
25 个磁盘文件全部保留。当前 Git 保留 32 份 JSON/JSONL。
这些实验在新 checkout 中需要另行提供本地配置、标签和集群提交器。

测试使用已有本地环境与 pytest 纯 Python 依赖：

```bash
PYTHONPATH="$PWD/migration/horeka2-2026-10-03/test-deps:$PWD/EvidenceNet" \
  EvidenceNet/.venv_qwen/bin/python -m pytest EvidenceNet/tests -q
PYTHONPATH="$PWD/OfflineCitationGraph:$PWD/EdgeGeneration/.ann_deps:$PWD/migration/horeka2-2026-10-03/test-deps:$PWD/EvidenceNet" \
  EvidenceNet/.venv_qwen/bin/python -m pytest EdgeGeneration/tests OfflineCitationGraph/tests -q
PYTHONPATH="$PWD/migration/horeka2-2026-10-03/test-deps" \
  parsing/.venv/bin/python -m pytest parsing/tests -q
```

首次合并测试因未设置 `OfflineCitationGraph` 的 Python 路径导致 collection
失败；补齐上述运行环境后全部通过，无需修改业务代码。

这次检查验证代码与测试可用性；排队/运行中的 VL-DocIR GPU 实验尚无完整成绩，
不将其算作测试成功或检索质量提升。暂存后可用以下命令审阅并提交：

```bash
git diff --cached --stat
git diff --cached --check
git commit -m "Organize pipeline experiments and add hybrid node retrieval evaluation"
```
