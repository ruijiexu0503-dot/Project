# 标注归档约定

当前还没有冻结的 72 对核验结果。本目录用于后续归档，不表示真值已经完成。

每版单独建目录，包含标签 JSONL、规范、逐例理由和输入 SHA256。至少记录 blind_pair_id、review_label（accepted/rejected/unknown）、description_verdict、原文证据、数据质量、label_source、human_review_status。AI 审核明确标 silver，正式人工真值单独保存。

禁止覆盖原始盲审样本、把旧模型提案当金标、把 unknown 当负例。标签冻结之前不读取 proposer key。记录图关系是否成立与其对具体 query 是否有用的区别。
