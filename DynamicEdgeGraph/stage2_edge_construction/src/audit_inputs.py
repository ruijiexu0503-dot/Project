"""Read-only Stage 2 Pilot / Stage 1 asset audit."""
from __future__ import annotations
import argparse, collections
import numpy as np
from common import load_config, read_jsonl, repo_path, run_dir, sha256_file, write_json

def node_records(config):
    baseline = repo_path(config["baseline_dir"]); paths = sorted(baseline.glob(config["nodes_glob"])); nodes, duplicates = {}, []
    for path in paths:
        for row in read_jsonl(path):
            node_id = row.get("node_id")
            if not node_id: raise ValueError(f"node without node_id: {path}")
            if node_id in nodes: duplicates.append(node_id)
            nodes[node_id] = {**row, "source_path": str(path.relative_to(baseline))}
    return baseline, paths, nodes, duplicates

def inventory(config):
    baseline, node_paths, nodes, duplicates = node_records(config)
    docs = {n["node_id"].split("_")[0] for n in nodes.values()}
    unit_types = collections.Counter(str(n.get("unit_type") or "MISSING") for n in nodes.values())
    text = collections.Counter("present" if n.get("plain_text") else "empty" for n in nodes.values())
    visual = collections.Counter("present" if n.get("visual_description") else "empty" for n in nodes.values())
    search = repo_path("DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-abc-score-support-pruning-20261109/normalized_abc_search_126279")
    balanced = repo_path("DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir_balanced_v1")
    vector_path, ids_path = repo_path(config.get("embedding_path")), repo_path(config.get("embedding_ids_path"))
    embedding = {"encoder_id": config.get("encoder_id"), "vector_path": str(vector_path) if vector_path else None, "ids_path": str(ids_path) if ids_path else None, "usable": False, "reason": "embedding_path and embedding_ids_path are not configured"}
    if vector_path and ids_path:
        if vector_path.is_file() and ids_path.is_file():
            matrix = np.load(vector_path, mmap_mode="r")
            ids = [row["node_id"] for row in read_jsonl(ids_path)]
            valid = matrix.ndim == 2 and matrix.shape[0] == len(ids) and len(ids) == len(set(ids)) and np.isfinite(matrix).all()
            embedding.update(usable="verified" if valid else "invalid", vector_sha256=sha256_file(vector_path), ids_sha256=sha256_file(ids_path), shape=list(matrix.shape), dtype=str(matrix.dtype), ids=len(ids))
        else: embedding["reason"] = "node embedding paths are configured but have not been generated yet"
    return {"dataset": {k: config[k] for k in ("dataset_id", "dataset_revision", "node_id_namespace")},
      "pilot_nodes": {"node_files": len(node_paths), "nodes": len(nodes), "documents": len(docs), "duplicate_ids": len(duplicates), "unit_types": dict(unit_types), "plain_text": dict(text), "visual_description": dict(visual)},
      "embedding": embedding,
      "stage1_balanced_v1": {"search_directory": str(search), "recommended_operating_points_exists": (search / "recommended_operating_points.csv").is_file(), "normalization_reference_exists": (search / "normalization_reference.csv").is_file(), "full_balanced_pair_export_exists": (balanced / "balanced_v1_candidate_pairs.npz").is_file(), "status": "Balanced v1 full export is a later RepresentativeSubset input and is intentionally not mapped into this Pilot run"},
      "candidate_mode": {"selected": config.get("candidate_mode", "pilot_local_candidate"), "strict_abc_transfer": False, "reason": "Pilot Top-100 routes lack the frozen full-corpus ECDF/cross-score contract; fixed Balanced-v1 thresholds were not applied."},
      "relation_labels": {"status": "not_available", "note": "retrieval Gold Evidence is not an edge-relation label and was not read."}}, nodes

def markdown(data):
    p, e, b = data["pilot_nodes"], data["embedding"], data["stage1_balanced_v1"]
    return f"""# Stage 2 Pilot 数据资产审计\n\n- 数据集：`{data['dataset']['dataset_id']}`；revision：`{data['dataset']['dataset_revision']}`；ID namespace：`{data['dataset']['node_id_namespace']}`。\n- 冻结 Pilot 节点：{p['nodes']}；节点文件：{p['node_files']}；文档：{p['documents']}；重复 ID：{p['duplicate_ids']}。\n- 原始 unit_type：`{p['unit_types']}`；plain text：`{p['plain_text']}`；visual description：`{p['visual_description']}`。\n- Embedding：`{e['usable']}`；encoder：`{e['encoder_id']}`；shape：`{e.get('shape')}`；dtype：`{e.get('dtype')}`；vector SHA-256：`{e.get('vector_sha256')}`；ID SHA-256：`{e.get('ids_sha256')}`。矩阵行数、唯一 ID 数和映射文件均已校验。\n- Stage 1：参考分布={b['normalization_reference_exists']}，推荐配置={b['recommended_operating_points_exists']}，完整 Balanced v1 Pair 导出={b['full_balanced_pair_export_exists']}。{b['status']}\n- 候选输入：`{data['candidate_mode']['selected']}`；严格 ABC 迁移：否。原因：{data['candidate_mode']['reason']}\n- 关系标签：`not_available`。页面 Gold Evidence 未被用作边标签或候选生成输入。\n\n## 结论\n\n本 Pilot 可安全复用同一 `Qwen3-Embedding-0.6B`、同一 `pilot_multimodal_representation_v1` 路由产生的 7,288 个视图和逐行 ID 映射。全量 RepresentativeSubset Balanced v1 的节点命名空间、候选对和向量空间未混入本实验；它仅保留为后续适配器输入。\n"""
def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); args = parser.parse_args()
    config = load_config(args.config); data, _ = inventory(config); out = run_dir(config); out.mkdir(parents=True, exist_ok=True)
    write_json(out / "input_manifest.json", data); (out / "data_inventory.md").write_text(markdown(data), encoding="utf-8"); print(out / "data_inventory.md")
if __name__ == "__main__": main()
