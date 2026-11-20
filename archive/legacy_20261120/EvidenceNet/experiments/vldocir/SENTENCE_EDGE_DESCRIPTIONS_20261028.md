# 单句关系描述对照：sentence-v1

## 动机与已知旧结果

旧 bounded-v2 任务 5215455 已于 2026-10-28 14:05:36（Europe/Berlin）失败：
描述阶段时间预算结束，174/187 已处理，随后 embed 报 descriptions incomplete。
13:49 的已保存快照为153/187，29条通过格式/引用/长度检查，124条失败；
其中121条最终因三行格式失败、3条因token预算失败。这不是语义准确率。
旧产物及部署保持原样，未将旧失败输出伪装为新模型输出。

## 新版本

- 新策略 sentence-v1，独立目录 vldocir_edge_sentence_v1_20261028。
- prompt 只要求一句具体关系描述，不重复A/B原文概要；建议description至多40英文词、limitations至多30词。
- 为兼容现有产物，关系句仍使用 description 字段，而非重命名成 connection。
- limitations 单独且必须非空；保留出处ID、源间差异、否定、单位和身份不确定性。
- 句数和词数是生成约束，不使用句号切分硬拒绝（避免小数点、缩写误伤）。
- 程序只规范空白，不改写语义。总输入使用真实embedding tokenizer校验，两种端点顺序均不得超过512 token；不截掉限制条件。
- 引用须来自两端；INSUFFICIENT须空描述、空引用、非空原因；invalid/INSUFFICIENT的D输入严格回退C，不编码“无关系”解释。
- 重试提供上次原始输出；连续相同失败不浪费第三次调用。此改动也是实验差异，不能声称是纯句数消融。
- 逐条更新进度；描述不完整则作业以75退出并保留checkpoint，不启动embedding。不会自动提交无限续跑。
- 断点续跑只跳过已记录项，包括失败项；要改变prompt/重试失败项必须采用独立、可追溯的新实验。

## 控制变量及评估

沿用同一187条G0边、24 queries、518页、小规模已看过开发集；不是官方全集、不是新的node生成实验。
保持8B encoder、192 tokens/端点、512总输入、相同10页dense core、20页候选和100条边扫描预算、相同BGE重排。
保留A_node/B_current/C_pair/D_relation/E_endpoint及原始官方gold。
比较描述通过率、fallback比例、重试成本、语义误连案例，再比较Recall@5、nDCG@5、mAP@5及逐query变化。
优先比较本轮D与本轮C，避免把共同候选策略收益归给关系句；历史自由描述结果仅为辅助对照。
独立人工检查语义及单句遵循情况：程序valid不等于正确、简短不等于有用。

## 验证与运行

本地39个相关测试通过：新策略、源引用、限制、空白规范、长度拒绝、两种顺序、精确fallback，以及187条边/24 queries与对照逐字节一致。
部署目录：migration/horeka-edge-sentence-20261028。
Horeka目标：/hkfs/home/project/hk-project-p0025545/dv3352/Project/remote_runs/edge-sentence-20261028。
一个accelerated任务，4 GPU，3小时；145分钟描述预算，保留后续embedding/重排时间。
提交通过校验和及远端锁/意图记录避免重复。仅有SUBMITTED任务号才表示提交成功。

在已认证的原项目Project终端运行：

```bash
bash migration/horeka-edge-sentence-20261028/submit.sh
```

目前代码/测试/部署包已准备好；本文件不代表已提交或有新的GPU结果。

2026-10-28 本会话实际执行 submit.sh --batch：三个部署校验和均通过，
SSH 返回 Permission denied (publickey,keyboard-interactive)，未取得任务号。
本地无submitted_job_id.txt，当前可见远端无edge-sentence-20261028目录。
因此新实验尚未成功提交；需在持有有效SSH连接的原项目终端执行上面的短命令。
本地完整187边prepare与check均通过，旧数据未改写。
