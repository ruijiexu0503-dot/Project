# 原文片段选择、视觉角色与三路盲审

状态：D-033 opt-in shadow；未替换现有基线，未修改源文字、几何或生产图。

## 已实现

### 原文片段选择

`run_relation_first_corpus_shadow.py --anchor-protocol span-id-v1` 先把候选原文按句子边界切分，
超长句按空白位置截成不超过600字符的证据块。每块保留 unit text 的精确字符位置和内容哈希；
这不改变节点边界，也不创建片段 bbox。

模型返回 `anchor_span_id` 和 `supporting_span_ids`。程序从候选自身的片段表提取原文，
拒绝其他节点的ID、未知ID及混入的自由引文/字符位置。重复字符串可按不同位置明确选择。
主片段无效时整条关系拒绝；开启 bounded-v1 后，错误的附加ID单独记录。
caption 的位置、归属和正文限制继续生效；片段ID有效不代表关系语义正确。

### 视觉角色

`--visual-role-map EvidenceNet/config/reviews/visual_roles/reviewed_visual_roles_20261004.json` 接入明确审核过的角色。
当前只录入原页上已目视检查的两个 Europe PMC logo，审核来源记为 `assistant_visual_review`，
不是独立人工GT。角色枚举：CONTENT_FIGURE / LOGO / DECORATION / UNKNOWN。

审核记录绑定完整原页哈希、裁剪图哈希和原始 geometry_members；任一不一致会拒绝使用旧判断。
已审核 logo/装饰仍保留节点及几何，但跳过正文语义候选。角色及排除原因传入 edge adapter，
即使存在 linked-text proxy 也不能重新启用该视觉候选。未列入审核表的组件保持 UNKNOWN，
不因尺寸、重复位置或模型猜测而被排除。这是审核表接口，尚无全语料自动视觉分类器。

### 可用的盲审包

[打开审核页面](../../EdgeGeneration/output/blind_candidate_review_20261004/reviewer/index.html)。
本地浏览器打开，可查看全文、视觉资产与原页，填写判断、类型、方向和双端证据，导出JSONL。
已保存的JSONL可以重新导入；支持浏览器本地存储时会自动保存。

输入是作业45659的 lexical/dense/hybrid各600对，3个scope各200对。
每条路线每个scope独立抽30对，共270次抽取，去重后248对：
文内局部条目83、跨文档86、同文档文章归属未确定79。
左右端点和展示顺序随机化；审核页面不包含路线、分数、排名和抽样概率。
49个去重图片文件已复制，涉及的来源图片缺失数为0。

只将 `reviewer/` 交给审核者；`evaluation_only/` 含路线映射、抽样概率和输入哈希，
在标签冻结后用于评估。对跨路线共享的候选使用联合入样概率：
`pi = 1 - product(1 - n_arm_scope / N_arm_scope)`。
统计使用逆概率权重的自归一化比例，避免共享候选更容易入样造成直接计数偏差。

审核沿用 SUPPORTS、EXPLAINS_OR_ELABORATES、MODIFIES、CONTRASTS_WITH，
REFERENCES 独立标记；共享主题不算明确关系。YES须有已确定的类型/方向和双端证据；
NO和UNCERTAIN单独记录。未完成全部标签时只返回进度，不输出路线排名。
结果只估计固定候选预算下的确认关系比例/数量，不声称召回率或模型类型、方向准确率。
审核方式必须记录，模型自评不能冒充独立人工GT。

```bash
# 重建请使用新的output目录。
EvidenceNet/.venv_qwen/bin/python EdgeGeneration/scripts/prepare_blind_candidate_review.py \
  --candidates EdgeGeneration/output/window_candidates_dev_45659 \
  --snapshot EdgeGeneration/output/relation_first_v7_edge_input_snapshot_20261001_review \
  --output /tmp/new_blind_review --per-scope 30 --seed 20261004

# 完成后，将--labels指向浏览器导出的labels.jsonl；使用新的结果文件名。
EvidenceNet/.venv_qwen/bin/python EdgeGeneration/scripts/score_blind_candidate_review.py \
  --package EdgeGeneration/output/blind_candidate_review_20261004 \
  --labels /tmp/labels.jsonl --output /tmp/review_scores.json
```

## 验证与实际推理

37项相关测试通过：7项source grounding、8项bounded recovery、14项既有relation-first、
4项edge adapter、4项盲审/统计测试。包括重复引文定位、Unicode覆盖、无效ID拒绝、旧caption约束、
完整runner写出与resume、角色来源变更拒绝、proxy不能恢复logo检索，以及盲审去重、抽样概率和未完成标签拦截。
审核页面的JavaScript语法检查通过。

两页无模型完整检查通过：GW候选共生成24个原文片段；Hallmarks的两个logo保持可寻址，
跳过语义候选，adapter保留角色/排除原因。输出：
`EvidenceNet/output/span_grounding_local_check_20261004/shard_0/`。

短GPU作业45701已在 `dev-gpu-h100` 完成，2 GPU，耗时3分54秒，退出码0。
入口 `current/slurm/evidence_nodes/run_span_grounding_dev.sbatch`，输出将为
`EvidenceNet/output/span_grounding_smoke_45701/shard_0/`。
实际结果：GW p2保留1条局部关系，review为matched、页面为complete，没有被拒绝的附加引文；
Hallmarks p18完成2个重复归属的受限修复，2个logo记为reviewed_noncontent_visual，页面仍partial。
两页均结构有效。这是两页集成检查，不能据此报告全语料引文准确率或独立语义改进。
盲审标签目前0/248。

## 后续边界

本轮未新增零文本页OCR，NASA页仍需单独文字恢复；未重切现有节点。
新的候选证据块可能过粗，需在真实输出中检查是否选中了正确陈述及足够上下文。
先记录片段ID有效率、源引用覆盖和关系拒绝原因，再结合独立审核判断是否扩大使用。
