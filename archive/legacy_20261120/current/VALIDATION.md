# 整理后的验证记录

日期：2026-10-04。验证针对当前 HoReKa2 工作区；没有重新运行模型或提交正式 Slurm 作业。

| 检查 | 结果 |
| --- | --- |
| EvidenceNet pytest | 93 passed |
| EdgeGeneration pytest | 19 passed；3条既有 FAISS/SWIG 弃用警告 |
| parsing pytest | 41 passed |
| relation-first 本地输入预检 | 49/49，0失败 |
| `current/*.sh`、`current/*.sbatch` 的 `bash -n` | 通过 |
| 三个新 Slurm 提交器的 `sbatch --test-only` | CPU relation-first、H200 35B、CPU multimodal 均通过 |
| 精选指标来源 | 16个文件 SHA-256 与整理前一致 |
| 归档完整性 | 398项 inode/device 一致，单文件条目另核对 SHA-256 |
| README 本地链接 | 无失效链接 |
| 恢复脚本预检 | 398项可恢复，无路径冲突 |
| Git ignore | `_archive/` 和 `migration/` 生效 |

测试使用各模块现有环境：EvidenceNet 与 EdgeGeneration 使用
`EvidenceNet/.venv_qwen/bin/python`，parsing 使用 `parsing/.venv/bin/python`。
EdgeGeneration 额外将 `EdgeGeneration/.ann_deps` 加入 `PYTHONPATH`。
由于这些环境未装 pytest，复用了 `.venv-magazine-exp1` 中 pytest 的纯 Python 包，
通过 `migration/horeka2-2026-10-03/test-deps/` 的链接提供；未混入 Python 3.9 的二进制依赖。

复现测试（从仓库根目录执行）：

```bash
source current/env.sh
export PYTHONPATH="$PROJECT_ROOT/migration/horeka2-2026-10-03/test-deps:$PYTHONPATH"
EvidenceNet/.venv_qwen/bin/python -m pytest EvidenceNet/tests -q
PYTHONPATH="$PROJECT_ROOT/EdgeGeneration/.ann_deps:$PYTHONPATH" \
  EvidenceNet/.venv_qwen/bin/python -m pytest EdgeGeneration/tests -q
parsing/.venv/bin/python -m pytest parsing/tests -q
```

首次完整测试发现旧 `test_llm_client.py` 的替身没有初始化现有的
`enable_thinking` 字段，其 tokenizer 替身也不接受该参数。已将替身与现有接口对齐，
保留原来的设备转移断言并检查关闭 thinking 的传参；未修改推理实现。

测试日志在本目录的 `*-pytest.log`；输入预检明细在
`migration/horeka2-2026-10-03/post-cleanup-preflight/`。
文件校验汇总保存在本机 `current/json/integrity-verification.json`（生成产物，Git 忽略）。

这些检查确认保留代码、输入和提交入口的可用性，不证明 GPU 推理成功或语义质量提升。
既有实验的失败、待审核节点及样本规模限制见 [README](README.md)。
