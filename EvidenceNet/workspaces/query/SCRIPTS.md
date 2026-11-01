# query 脚本索引

入口为相对符号链接；源码仍位于 `EvidenceNet/scripts/`。分类不是执行顺序，也不表示所有实验都已验证有效。

## 01_navigation

- [run_query_semantic_edge_v2.py](scripts/01_navigation/run_query_semantic_edge_v2.py)
- [query_semantic_edge_policy_v2.py](scripts/01_navigation/query_semantic_edge_policy_v2.py)
- [query_semantic_edge_core.py](scripts/01_navigation/query_semantic_edge_core.py)
- [run_top10_node_navigation.py](scripts/01_navigation/run_top10_node_navigation.py)
- [query_edge_gate.py](scripts/01_navigation/query_edge_gate.py)
- [run_query_edge_repair.py](scripts/01_navigation/run_query_edge_repair.py)
- [report_query_edge_gate.py](scripts/01_navigation/report_query_edge_gate.py)

## 02_selection

- [run_query_adaptive_evidence_v2.py](scripts/02_selection/run_query_adaptive_evidence_v2.py)
- [query_evidence_policy_v2.py](scripts/02_selection/query_evidence_policy_v2.py)
- [run_query_evidence_selection.py](scripts/02_selection/run_query_evidence_selection.py)
- [run_span_evidence_selection.py](scripts/02_selection/run_span_evidence_selection.py)
- [run_query_split_probe.py](scripts/02_selection/run_query_split_probe.py)
- [build_reader_anchor_ablation.py](scripts/02_selection/build_reader_anchor_ablation.py)
- [validate_reader_anchor_packets.py](scripts/02_selection/validate_reader_anchor_packets.py)

## 03_evaluation

- [run_hf_evidence_comparison.py](scripts/03_evaluation/run_hf_evidence_comparison.py)
- [run_vldocir_evidence_rerank.py](scripts/03_evaluation/run_vldocir_evidence_rerank.py)
- [run_vldocir_colnomic.py](scripts/03_evaluation/run_vldocir_colnomic.py)
- [retrieve_vldocir.py](scripts/03_evaluation/retrieve_vldocir.py)
- [evaluate_vldocir.py](scripts/03_evaluation/evaluate_vldocir.py)
- [evaluate_vldocir_ap.py](scripts/03_evaluation/evaluate_vldocir_ap.py)
- [audit_colnomic_edge_rescue.py](scripts/03_evaluation/audit_colnomic_edge_rescue.py)
- [audit_span_edge_results.py](scripts/03_evaluation/audit_span_edge_results.py)
- [compare_vldocir_cached_search.py](scripts/03_evaluation/compare_vldocir_cached_search.py)
- [run_cached_query_reranker.py](scripts/03_evaluation/run_cached_query_reranker.py)
- [probe_vldocir_query_graph.py](scripts/03_evaluation/probe_vldocir_query_graph.py)
- [trace_vldocir_edges.py](scripts/03_evaluation/trace_vldocir_edges.py)
- [verify_retrieval_baseline.py](scripts/03_evaluation/verify_retrieval_baseline.py)
- [build_retrieval_loss_report.py](scripts/03_evaluation/build_retrieval_loss_report.py)

## 04_history_dependencies

- [run_query_semantic_edge_v1.py](scripts/04_history_dependencies/run_query_semantic_edge_v1.py)
- [query_semantic_edge_policy.py](scripts/04_history_dependencies/query_semantic_edge_policy.py)
- [run_query_adaptive_evidence.py](scripts/04_history_dependencies/run_query_adaptive_evidence.py)
- [query_evidence_policy.py](scripts/04_history_dependencies/query_evidence_policy.py)
