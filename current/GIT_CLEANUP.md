# Git噪声与旧脚本整理

日期：2026-10-04。仅整理工作区，不提交、不暂存、不修改Git索引。

## 为什么原来有8k多项

清理前 `git status --porcelain=v1 --untracked-files=all` 共8100项：
7827个未跟踪文件、260个既有删除记录、13个已修改文件。
主要来源是生成的解析图片/报告、Dolphin工作目录和本地下载的Python依赖。

## 本轮处理

- `.gitignore` 增加 `parsing/audits/` 下的生成子目录；根目录的3个审计Python脚本仍可跟踪。
- 忽略 `parsing/experiments/dolphin_v2_pilot/{work,input,vendor}/`；保留driver、配置、说明和测试。
- 忽略本地安装的 `EvidenceNet/vendor/{adapters_runtime,specter_runtime}/` 和 `EdgeGeneration/.ann_deps/`。
- 这些生成文件/依赖仍在原位置，现有输入路径可继续使用。
- 将7份已被替代的探索脚本/提交器移入 `_archive/2026-10-04-superseded-scripts/`，保持原相对目录。
  包括重复归属探索、旧记账回放，以及两个历史截断检索提交器。
  当前flow修复、span grounding、dense/window检索和盲审入口继续保留，并补入 `json/selection.json`。

本轮归档只移动原本未跟踪的文件，没有新增已跟踪文件删除。原有260个删除记录来自此前归档，
`.gitignore`不能隐藏已跟踪文件的变化；这些记录保留供后续正常审阅和提交，没有使用
`assume-unchanged`、`skip-worktree`、`git rm --cached`或reset来掩盖。

## 归档和恢复

本地 `json/superseded-scripts-20261004.json` 记录原路径、归档位置、原因与SHA-256；该清单已忽略。
归档目录另有manifest、移动日志和整理前Git状态快照。7个文件移动后哈希均保持一致。

```bash
# 只预览并校验，不改文件。
python3 current/restore_superseded_scripts.py

# 恢复全部7个文件；遇到原位置已有文件或归档哈希不符时拒绝覆盖。
python3 current/restore_superseded_scripts.py --apply

# 或只恢复指定文件。
python3 current/restore_superseded_scripts.py \
  --path EvidenceNet/scripts/experiment_flow_anchor_recovery.py --apply
```

旧的 `_archive/2026-10-04/` 与 `restore_archive.py` 保持原样，不与本轮恢复混用。

## 验证

- 清理时队列中没有用户的运行/等待作业；所移7个文件无当前保留代码的运行引用。
- 7个归档文件全部通过哈希校验，恢复预览通过。
- `bash current/check_relation_first.sh`：49/49页输入/结构预检通过，0失败，无模型推理。
- Git状态计数和忽略规则检查见下方最终记录；核心代码保持可见。

最终状态：**8100 → 506项**，其中233项未跟踪、13项修改、260项既有删除。
核对125条保留入口/源码路径，均未被ignore；8类应忽略路径匹配正确。
原有已跟踪变更状态集合保持一致，完整检查记录存于本轮归档目录。
