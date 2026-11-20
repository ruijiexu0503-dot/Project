# 同语料ColNomic原图检索对照

2026-10-16。用户同意在冻结24查询、518页pilot上补测作者评测的原图检索器。
本实验使用ColNomic-7B的基础页面检索，不加Ctx、重排、ensemble或edge。
原无edge baseline不修改；这不是全库论文成绩复现。

## 完成结果

**82567 COMPLETED，退出0，用时2分55秒，NVIDIA H100。** 全518页及12432个query-page
得分完整；适配器394个张量值与官方权重核对通过，全部参数位于cuda:0，未CPU offload。

| 方法 | Recall@5 | nDCG@5 | RecallAll@5 | mAP@5 | 完整mAP |
| --- | ---: | ---: | ---: | ---: | ---: |
| ColNomic-7B 原图 | 79.17% | 71.28% | 66.67% | 65.83% | 70.27% |
| 冻结hybrid_visual | 83.33% | 71.76% | 66.67% | 62.78% | 65.75% |

ColNomic的mAP@5高3.06个百分点、完整mAP高4.52个百分点；冻结节点检索的
Recall@5高4.17个百分点、nDCG@5高0.48个百分点。没有一个方案所有指标均胜出。
24题逐项AP@5对照：ColNomic 7胜8负9平；完整AP 7胜9负8平。平均值改善不表示多数
题均改善。单问题大变化会影响小样本均值，不宣称显著性或全库优势。

原始scores、指标、完整六组对照和逐问题变化保存在输出目录；结果SHA256清单为
result_manifest.json。既有冻结baseline及其输入未改。没有训练新模型。

已提交GPU任务 **82561**，随后确认RUNNING于hkn0901。准备阶段24查询/518页检查通过，
权重和输入manifest已冻结。未完成前不报告检索成绩。

82561在49秒后失败：基座/适配器加载校验通过，但Transformers的loading_info中set
不能JSON序列化，尚未编码查询或页面。失败目录及原始代码已归档，代码哈希与旧manifest一致。
修复诊断记录格式并新增回归测试后，共10项相关测试通过，重新冻结输入并提交 **82567**。

## 固定模型与独立运行依赖

- 官方适配器`nomic-ai/colnomic-embed-multimodal-7b`，revision `09dbc9502b66605d5be56d2226019b49c9fd3293`。
- 指定基座`nomic-ai/colqwen2.5-7B-base`，revision `15e77de3944c94363b38ff3b53844f066e6fcd19`。
  未用已有普通Qwen2.5-VL替代；检索投影层与指定基座必须匹配。
- 官方ColPali engine commit `97487f8871ff4d5d2284411fe61bdcd2cfe99894`，独立目录`external/colpali-engine`。
- PEFT 0.19.0安装于`external/colnomic_runtime`，通过PYTHONPATH使用，未升级既有环境。

预检：394个LoRA张量名与尺寸均匹配；指定基座无缺少的模型层，唯一额外项为不使用的
生成头`lm_head.weight`。真实加载时再次核对基座loading_info及全部适配器张量值。

## 输入与评分

官方processor分别处理原始页面像素和问题字符串，不读node JSON、OCR、标题、答案或gold。
沿发布的training_config.yml显式设置1280视觉tokens；此设置避免新版processor对旧size字段
解释不同。实测2000×4000页面产生1261个输入tokens（含图像外提示）。
这不是已经核对了作者所有图像预处理超参数，不据此宣称严格复现作者全库设置。

GPU bfloat16、SDPA，单页batch，查询4条一批；官方多向量MaxSim评分。
完整24×518=12432条页面得分后才计算Recall/nDCG/RecallAll/nDCGAll及AP。
AP@k分母为全部相关页，另报告完整排名mAP。与冻结六组在完全相同查询/页面/gold上比较。

模型与输入形式都不同，因此不是只改变node generation的消融。pilot标签仅评分，
不能把其成绩直接与作者全库表格比较。

## 执行与恢复

输出`EvidenceNet/output/vldocir_colnomic_7b_20261016/`。
准备阶段SHA256固定代码、processor/模型与图像。
一次GPU作业内先编码四种来源各一页作冒烟检查，再继续全518页。
逐页CPU embedding检查点可恢复；到时间预算时明确记录partial，不生成完整成绩。
只有完整评分覆盖检查通过，才产生metrics.json、comparison.json和REPORT.md。

```bash
PYTHONPATH=external/colnomic_runtime:external/colpali-engine EvidenceNet/.venv_qwen/bin/python EvidenceNet/scripts/run_vldocir_colnomic.py prepare
sbatch current/slurm/vldocir/run_colnomic_pilot_gpu.sbatch
```

一次申请1张H100/H200 GPU、最多1小时，8 CPU、96GB内存。提交状态另记录jobs.json。
10项指标与来源检查测试通过，原图processor、真实GPU模型前向和完整评分均通过。

官方参考：
- https://huggingface.co/nomic-ai/colnomic-embed-multimodal-7b
- https://github.com/illuin-tech/colpali
- https://huggingface.co/datasets/anonymous-8421/VL-DocIR
