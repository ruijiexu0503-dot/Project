# 与作者公开数据及模型接口的对齐

2026-10-16。核查本地固定revision数据卡、四类JSONL，及公开一手资料：

- VL-DocIR数据卡：https://huggingface.co/datasets/anonymous-8421/VL-DocIR
- 公开论文实验设置：https://arxiv.org/html/2610.17057#S4.SS1
- ColNomic模型卡：https://huggingface.co/nomic-ai/colnomic-embed-multimodal-7b
- 模型卡列出的训练集之一：https://huggingface.co/datasets/nomic-ai/colpali_train_set_split_by_source

## 事实边界

VL-DocIR公开定义是(q, gold证据页集合, 页面图像语料库)的检索评测。
公开实验列举现有视觉、OCR/文本及混合检索器，评测时给查询并输出页面排名。
没有找到“将本项目的完整node JSON作为训练输入”的依据；HF split名train不构成
作者在这个benchmark上训练过检索器的证据。不可把生成问题的VLM、过滤器训练、
底层检索器的预训练/微调和本次检索评测混为一谈。

ColNomic 7B模型卡列出的训练数据是llamaindex/vdr-multilingual-train和
nomic-ai/colpali_train_set_split_by_source。后者公开样例含image、query及answer、source、
filename等附加字段；字段存在不等于全部传入模型。模型卡示例使用process_images和
process_queries分别编码图像与问题。不能通过给文本JSON改字段名复现视觉多向量模型。

数据卡允许visual、OCR、text-only或hybrid内部表示，评测输出必须统一为页面ID。
论文的Ctx为页面/文档多向量分数的组合，不是我们在每个文本窗口添加64tokens标题。

## 已完成的本地适配

导出目录：`EvidenceNet/output/vldocir_eval_bundle_20261016/`。
此为我们的统一适配格式，未声称是作者未核查的官方训练loader格式。

- `queries.jsonl`：仅_id与text；编码器只读取text，原检索器所需instruction由适配器加。
- `corpus_pages.jsonl`：页面_id与image路径，视觉编码器读取图像像素；ID/路径不是prompt内容。
- 六臂`corpus_units.jsonl`：检索单元_id、text、title；编码器只读文本字段，title可单独作为对照因素。
- `unit_pages.jsonl`：节点/结构检索单元到官方页面的映射，完全在模型外。
- `qrels.tsv`：query-id、corpus-id、score，24查询与518页面中40条相关性关系，仅评分使用。
- `runs/*.jsonl`：六组现有页面得分的统一格式。
- `page_provenance.jsonl`、`query_provenance.jsonl`：来源、题型等，不进模型。

独立读取导出的run重新评测，六组每组12432条query-page评分，逐问题指标全部与冻结
baseline一致，验证页面映射、查询映射、标签分离没有改变原测量。
没有进行训练或新的模型推理，也未修改冻结baseline。

不能由页面gold直接把一页中每个node都标成正例；该bundle不生成伪造的node训练标签。
如后续训练，需要独立训练/验证/测试划分与可靠node标签；本次不启动微调。

## 后续比较应对齐的因素

相同查询、完整候选库、gold和page-level指标；分别标记OCR/text与原图输入。
在相同pilot上跑作者模型才能与我们对照；不能把本地24查询/518页成绩与作者全库表格
直接比较。若移除标题、切换模型、替换视觉描述或使用原图，都属于新实验而非JSON清理。

运行：`python EvidenceNet/scripts/export_vldocir_eval_bundle.py`。
