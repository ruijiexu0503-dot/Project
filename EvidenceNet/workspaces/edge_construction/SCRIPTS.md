# edge_construction 脚本索引

入口为相对符号链接；源码仍位于 `EvidenceNet/scripts/`。分类不是执行顺序，也不表示所有实验都已验证有效。

## 01_pipeline

- [run_evidence_edge_pipeline.py](scripts/01_pipeline/run_evidence_edge_pipeline.py)
- [run_vldocir_edge_pipeline.py](scripts/01_pipeline/run_vldocir_edge_pipeline.py)
- [prepare_vldocir_edge_adapter.py](scripts/01_pipeline/prepare_vldocir_edge_adapter.py)
- [run_vldocir_pipeline_comparison.py](scripts/01_pipeline/run_vldocir_pipeline_comparison.py)
- [vldocir_candidate_comparison.py](scripts/01_pipeline/vldocir_candidate_comparison.py)

## 02_candidates

- [repair_edge_candidate_allocation.py](scripts/02_candidates/repair_edge_candidate_allocation.py)
- [repair_remaining_edge_candidates.py](scripts/02_candidates/repair_remaining_edge_candidates.py)
- [run_hierarchical_edge_retrieval.py](scripts/02_candidates/run_hierarchical_edge_retrieval.py)
- [run_line_aware_edge_retrieval.py](scripts/02_candidates/run_line_aware_edge_retrieval.py)
- [edge_text_views.py](scripts/02_candidates/edge_text_views.py)
- [edge_granularity_views.py](scripts/02_candidates/edge_granularity_views.py)
- [edge_source_roles.py](scripts/02_candidates/edge_source_roles.py)
- [source_grounding.py](scripts/02_candidates/source_grounding.py)
- [compare_edge_embedding_models.py](scripts/02_candidates/compare_edge_embedding_models.py)

## 03_verification

- [run_layered_edge_verifier.py](scripts/03_verification/run_layered_edge_verifier.py)
- [run_fact_grounded_edges.py](scripts/03_verification/run_fact_grounded_edges.py)
- [run_named_identity_gate_verifier.py](scripts/03_verification/run_named_identity_gate_verifier.py)
- [postprocess_named_identity_gate.py](scripts/03_verification/postprocess_named_identity_gate.py)
- [run_edge_selector_reranker.py](scripts/03_verification/run_edge_selector_reranker.py)
- [run_edge_selector_reranker_symmetric.py](scripts/03_verification/run_edge_selector_reranker_symmetric.py)
- [run_routed_edge_context.py](scripts/03_verification/run_routed_edge_context.py)
- [run_node_context_edges.py](scripts/03_verification/run_node_context_edges.py)
- [run_edge_context_ablation.py](scripts/03_verification/run_edge_context_ablation.py)

## 04_descriptions_embeddings

- [bounded_edge_descriptions.py](scripts/04_descriptions_embeddings/bounded_edge_descriptions.py)
- [sentence_edge_descriptions.py](scripts/04_descriptions_embeddings/sentence_edge_descriptions.py)
- [run_vldocir_edge_embedding.py](scripts/04_descriptions_embeddings/run_vldocir_edge_embedding.py)
- [edge_embedding_records.py](scripts/04_descriptions_embeddings/edge_embedding_records.py)

## 05_structure_node_context

- [vldocir_reading_backbone.py](scripts/05_structure_node_context/vldocir_reading_backbone.py)
- [repair_vldocir_single_work_reading.py](scripts/05_structure_node_context/repair_vldocir_single_work_reading.py)
- [dolphin_softwrap.py](scripts/05_structure_node_context/dolphin_softwrap.py)
- [dolphin_text.py](scripts/05_structure_node_context/dolphin_text.py)
- [repair_line_view_eligibility.py](scripts/05_structure_node_context/repair_line_view_eligibility.py)
- [node_context_coreference.py](scripts/05_structure_node_context/node_context_coreference.py)
- [node_context_policy.py](scripts/05_structure_node_context/node_context_policy.py)
- [verify_node_context.py](scripts/05_structure_node_context/verify_node_context.py)
- [verify_node_context_v3.py](scripts/05_structure_node_context/verify_node_context_v3.py)
- [prepare_vldocir_nodes.py](scripts/05_structure_node_context/prepare_vldocir_nodes.py)
- [run_vldocir_nodes.py](scripts/05_structure_node_context/run_vldocir_nodes.py)
- [parse_vldocir_pages.py](scripts/05_structure_node_context/parse_vldocir_pages.py)

## 06_formula

- [formula_context_packets.py](scripts/06_formula/formula_context_packets.py)
- [formula_retrieval_views.py](scripts/06_formula/formula_retrieval_views.py)
- [formula_structure_index.py](scripts/06_formula/formula_structure_index.py)
- [formula_semantic_specs_20261027.py](scripts/06_formula/formula_semantic_specs_20261027.py)
- [run_formula_context_trial.py](scripts/06_formula/run_formula_context_trial.py)
- [run_formula_semantics_trial.py](scripts/06_formula/run_formula_semantics_trial.py)
- [run_formula_retrieval_comparison.py](scripts/06_formula/run_formula_retrieval_comparison.py)
- [build_formula_context_review.py](scripts/06_formula/build_formula_context_review.py)

## 07_diagnostics_history

- [audit_edge_context_failures.py](scripts/07_diagnostics_history/audit_edge_context_failures.py)
- [audit_edge_errors_by_modality.py](scripts/07_diagnostics_history/audit_edge_errors_by_modality.py)
- [audit_missed_edge_stages.py](scripts/07_diagnostics_history/audit_missed_edge_stages.py)
- [build_weekly_edge_review.py](scripts/07_diagnostics_history/build_weekly_edge_review.py)
- [build_evidence_edge_review_suite.py](scripts/07_diagnostics_history/build_evidence_edge_review_suite.py)
- [build_edge_repair_review.py](scripts/07_diagnostics_history/build_edge_repair_review.py)
- [build_remaining_six_positive_viewer.py](scripts/07_diagnostics_history/build_remaining_six_positive_viewer.py)
- [run_real_text_edge_suite.py](scripts/07_diagnostics_history/run_real_text_edge_suite.py)
- [run_synthetic_edge_suite.py](scripts/07_diagnostics_history/run_synthetic_edge_suite.py)
- [run_text_multimodal_diagnostic_v2.py](scripts/07_diagnostics_history/run_text_multimodal_diagnostic_v2.py)
- [review_text_multimodal_v2_results.py](scripts/07_diagnostics_history/review_text_multimodal_v2_results.py)
- [build_fresh_edge_suite.py](scripts/07_diagnostics_history/build_fresh_edge_suite.py)
- [fresh_edge_specs_20261021.py](scripts/07_diagnostics_history/fresh_edge_specs_20261021.py)
- [synthetic_edge_specs_20261021.py](scripts/07_diagnostics_history/synthetic_edge_specs_20261021.py)
- [run_split_taxonomy_suite.py](scripts/07_diagnostics_history/run_split_taxonomy_suite.py)
- [build_split_taxonomy_benchmark.py](scripts/07_diagnostics_history/build_split_taxonomy_benchmark.py)
- [run_semantic_relation_trial.py](scripts/07_diagnostics_history/run_semantic_relation_trial.py)
- [run_all_node_multimodal_relatedness.py](scripts/07_diagnostics_history/run_all_node_multimodal_relatedness.py)
- [run_relatedness_pilot.py](scripts/07_diagnostics_history/run_relatedness_pilot.py)
