# 2026-10-30：证据选择引用协议修复

## 问题与边界

旧 dev 5217820 / 5217821 分别处理 20/24、9/24，只有 6、1 题通过完整格式校验。主要失败是模型复制原文时改动空白、重组表格或拼接不连续文本。通过校验不等于检索准确；旧结果保持原样，不将失败记录自动标记为成功。

本轮只修复输入输出协议和断点恢复，不改变候选、图、评分范围、edge prompt、原文整块预算选择。没有运行回答 LLM，没有新 GPU 结果，不能声称检索改善。

## 实现

入口：`EvidenceNet/scripts/run_span_evidence_selection.py`。

- 新协议 `source-span-v1`：模型输出 `covers: [{requirement, span_ids}]`，不再抄写 quote。
- span 包含 packet ID、原文字符起止偏移、文本及 SHA256。跨 packet、未知 ID、重复 ID、原文篡改均拒绝。
- 只在空行处分段；普通 OCR 换行不切分。包含 HTML table 的 packet 保留整体，避免拆散表头与单元格。偏移为 Python 字符偏移，不是字节偏移。
- span 是来源定位，不是语义正确性证明。模型仍需核对年份、主语、否定、单位。最终 reader 仍接收整 packet；尚未实现 span 级压缩，不能声称 token 已减少。
- assessment 校验通过即原子保存；edge 阶段失败或进程中断后复用 assessment。旧尝试记录累积保存，不覆盖错误历史。
- 每次生成前检查时间预算；单次正在进行的生成不会被此软预算打断。
- 续跑优先未处理题，避免前部失败题一直耗尽额度；所有题完成则不加载模型。
- 运行前校验任务、代码及 tokenizer；旧冻结部署与新输出分离。

## 真实输入验证

新输入：

- `EvidenceNet/output/top10_span_navigation_20261030`：24 题、268 spans，最长输入 18,189 tokens。
- `EvidenceNet/output/query_span_selection_20261030`：24 题、927 spans，最长输入 9,528 tokens。

两组均逐题核对 packets、edges、edge prompt 与旧任务完全一致；span 拼接还原原文且偏移/哈希验证通过。Top10 navigation 文件原样复制。未引入 gold 到提示词。

16 项测试通过：span 协议 5 项，已有 evidence selection、Top10 navigation、reader anchor 11 项。覆盖错来源、重复 ID、篡改、表格/OCR 换行、edge 阶段失败续跑、GPU 异常保留 assessment、过期 checkpoint、时间预算及旧预算/路径逻辑。

## 运行

需要原有四 GPU Qwen 环境。新任务尚未提交。

```bash
python EvidenceNet/scripts/run_span_evidence_selection.py infer --out EvidenceNet/output/top10_span_navigation_20261030 --minutes 25
python EvidenceNet/scripts/run_span_evidence_selection.py report --out EvidenceNet/output/top10_span_navigation_20261030
```

固定候选组将 out 替换为 `EvidenceNet/output/query_span_selection_20261030`。远端需部署当前代码和新 prepared inputs，不能直接套用旧冻结 manifest 或旧 dev 重提脚本。

先验证少量真实生成是否遵守新协议，再跑全 24 题。对比必须保留全量分母、未处理/失败状态；新增邻居是否进入最终输入、是否找回 gold、实际输入 token 成本分别报告。来源校验仍无法判断模型的支持关系是否正确，需要独立语义审查。
