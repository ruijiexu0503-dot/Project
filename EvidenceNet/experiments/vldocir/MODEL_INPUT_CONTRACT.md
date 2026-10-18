# 模型输入与开发记录分离

2026-10-16。用户要求baseline输入只包含模型需要的信息。
此前展示的完整node JSON是存储/追溯记录，并不是实际传给embedding的JSON。
原baseline已仅编码标题上下文与正文/视觉描述。本次把该边界显式化，不改变检索内容。

## 模型输入白名单

文档侧适配器仅提取：

```json
{"title_context":"原文标题和页面标题", "content":"原文或原文加冻结视觉描述"}
```

这是适配器导出格式，不将JSON字段名序列化进prompt。实际encoder输入为token IDs：
最多64标题tokens + 384正文tokens的窗口，stride320，原special-token模板不变。
batch padding时生成attention mask。查询侧仅保留固定检索instruction及question。

node_id、source IDs、bbox、status、policy、路径、question_id、题型、答案和gold标签
均不进入模型输入；需要的来源映射单独保存。坐标仍留在原始节点供来源审计，未删除。

## 已完成核查

导出路径：`EvidenceNet/output/vldocir_minimal_inputs_20261016/`。

各组`model_inputs.jsonl`为白名单内容，`encoder_inputs.jsonl`为实际未padding的token IDs；
`provenance.jsonl`和`window_provenance.jsonl`通过行号独立记录节点/页面/窗口映射。
`example_text_node.json`是对话中纯文字节点的实际最小输入。

使用冻结tokenizer，将现行白名单适配器与冻结检索代码独立生成的输入逐一比较：
六组共49,521个文档窗口和24个查询全部token ID一致。
518页、7,291节点及262个视觉组件的来源覆盖检查通过。

因此原baseline的检索排名、Recall/nDCG/AP保持适用；未重跑模型，未修改只读baseline。
这不是“去掉开发字段后得分提升”的新实验，因为这些字段此前也未被编码。

实现：`scripts/retrieve_vldocir.py`中的`document_model_input`/`query_model_input`；
导出器：`scripts/export_vldocir_model_inputs.py`。
`verification.json`记录覆盖与逐token等价结论，`manifest.json`记录导出代码与输出哈希。

```bash
EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/export_vldocir_model_inputs.py
```
