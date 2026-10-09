# EvidenceNet 配置

根目录保留 pipeline 的 YAML 配置和文档列表。实验 JSON 按用途组织：

| 目录 | 内容 |
|---|---|
| `sources/` | relation-first 语料来源和多样本输入清单 |
| `reviews/node_generation/` | Hybrid 节点和模型比较的冻结审阅标签 |
| `reviews/visual_roles/` | 人工审阅流程中确认的视觉角色标签 |

这些 JSON 是本机实验的运行和回归评测输入，Git 忽略，磁盘文件保留。
新 checkout 运行这些实验前，需要另行提供对应配置与标签。
节点审阅标签来自助手对
源文档的审阅，不代表独立人工 ground truth。
脚本和 Slurm 入口已使用对应子目录路径。
