# Stage 2: Directed Edge Embedding (E0)

本目录只构造与 Query 无关的有向 Edge 表示。它不修改冻结的 VL-DocIR no-edge baseline、不重跑 Stage 1，也不把检索 Gold Evidence 当作边标签。

先运行 `node_representations.py` 与 `encode_node_embeddings.py --dry-run`：前者将 TEXT、TABLE、CAPTION、VISUAL、COMPOSITE 节点路由为带模态标签的内容和冻结页面上下文，后者验证窗口预算。仅在同一个冻结 encoder 对这些已验证 ID 完成编码后，E0 才读取 `node_embeddings.npy`。当前工作区中的 Stage 1 Pilot 候选属于另一套 2,223-view RepresentativeSubset 命名空间，不能映射到冻结 Pilot 的 7,291 nodes；因此不能迁移 ABC。

```bash
python DynamicEdgeGraph/stage2_edge_construction/src/audit_inputs.py --config DynamicEdgeGraph/stage2_edge_construction/configs/pilot_e0.json
python DynamicEdgeGraph/stage2_edge_construction/src/node_representations.py --config DynamicEdgeGraph/stage2_edge_construction/configs/pilot_node_embeddings.json
python DynamicEdgeGraph/stage2_edge_construction/src/encode_node_embeddings.py --config DynamicEdgeGraph/stage2_edge_construction/configs/pilot_node_embeddings.json --dry-run
python DynamicEdgeGraph/stage2_edge_construction/src/prepare_pilot_pairs.py --config DynamicEdgeGraph/stage2_edge_construction/configs/pilot_e0.json
python DynamicEdgeGraph/stage2_edge_construction/src/build_edges.py --config DynamicEdgeGraph/stage2_edge_construction/configs/pilot_e0.json
python DynamicEdgeGraph/stage2_edge_construction/src/evaluate_edges.py --run-dir DynamicEdgeGraph/stage2_edge_construction/outputs/pilot_e0
```

默认候选是确定性的同文档/页窗口候选，标记为 `pilot_local_candidate`，仅用于 E0 表示比较，并不声称是 Balanced v1；不读取 Query 或 Gold Evidence。每个无向 pair 会被 materialize 为正反两个 edge。

全量扩展只能读取已封装的 `vldocir_balanced_v1`；运行 `audit_balanced_v1.py` 仅验证其固定 ABC 选择与 Stage 2 可嵌入性，绝不重新搜索阈值。IMAGE 节点若没有版本化视觉描述，必须隔离或补全描述，不能用 OCR/HTML 文本伪装为视觉表示。
