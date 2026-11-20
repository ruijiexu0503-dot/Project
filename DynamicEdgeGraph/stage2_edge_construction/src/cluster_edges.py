"""Dependency-free exploratory clustering for query-independent E0 edge vectors.

Clusters are diagnostic only.  They are never emitted as relation labels.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import numpy as np

from common import load_config, read_jsonl, run_dir, write_json


def l2_rows(values: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, np.finfo(values.dtype).eps)


def kmeans(values: np.ndarray, clusters: int, seed: int, iterations: int) -> tuple[np.ndarray, np.ndarray, int]:
    if not 2 <= clusters <= len(values):
        raise ValueError("clusters must be in [2, number of vectors]")
    rng = np.random.default_rng(seed)
    # Seeded random distinct initialization is intentionally simple and stable.
    centroids = values[rng.choice(len(values), size=clusters, replace=False)].copy()
    labels = np.full(len(values), -1, dtype=np.int32)
    for step in range(iterations):
        scores = values @ centroids.T  # normalized vectors: cosine similarity
        next_labels = np.argmax(scores, axis=1).astype(np.int32)
        if np.array_equal(labels, next_labels):
            return labels, centroids, step
        labels = next_labels
        for cluster in range(clusters):
            members = values[labels == cluster]
            if len(members):
                centroids[cluster] = members.mean(axis=0)
            else:
                centroids[cluster] = values[rng.integers(len(values))]
        centroids = l2_rows(centroids)
    return labels, centroids, iterations


def entropy(counter: collections.Counter) -> float:
    total = sum(counter.values())
    if not total:
        return 0.0
    return float(-sum((n / total) * np.log2(n / total) for n in counter.values()))


def composition(labels: np.ndarray, metadata: list[dict]) -> list[dict]:
    result = []
    for cluster in range(int(labels.max()) + 1):
        rows = [metadata[i] for i in np.flatnonzero(labels == cluster)]
        docs = collections.Counter("same_document" if r["source_document_id"] == r["target_document_id"] else "cross_document" for r in rows)
        modalities = collections.Counter("same_modality" if r["source_modality"] == r["target_modality"] else "cross_modality" for r in rows)
        support = collections.Counter(str(r.get("route_support", "not_available")) for r in rows)
        result.append({"cluster": cluster, "size": len(rows), "document_composition": dict(docs), "modality_composition": dict(modalities), "route_support": dict(support), "document_entropy_bits": entropy(docs), "modality_entropy_bits": entropy(modalities)})
    return result


def report(payload: dict) -> str:
    lines = ["# E0 Edge Clustering（探索性诊断）", "", f"- 方法：`{payload['method']}`；向量：{payload['vectors']}；维度：{payload['dimensions']}；clusters：{payload['clusters']}；seed：{payload['seed']}。", "- 输入先按行 L2 归一化，K-means 使用余弦等价的点积更新；不使用 Query、Gold 或关系标签。", "- Cluster ID 不是关系类型。它只帮助检查 E0 几何是否主要由文档、模态或检索路线支持度驱动。", "", "## Cluster 概览", "", "| cluster | size | 同文档 | 跨模态 | 文档熵(bit) | 模态熵(bit) |", "|---:|---:|---:|---:|---:|---:|"]
    for row in payload["composition"]:
        n = max(row["size"], 1)
        lines.append(f"| {row['cluster']} | {n} | {row['document_composition'].get('same_document', 0)/n:.2%} | {row['modality_composition'].get('cross_modality', 0)/n:.2%} | {row['document_entropy_bits']:.3f} | {row['modality_entropy_bits']:.3f} |")
    if "reverse_same_cluster_rate" in payload:
        lines += ["", f"- 对每个无向 Pair 的双向 E0 边，正反方向落入同一 cluster 的比例：**{payload['reverse_same_cluster_rate']:.2%}**。此数值描述该聚类配置对端点交换的敏感度，不能解释为方向关系正确率。"]
    lines += ["", "## 边界", "", "没有人工 Node–Node 关系标签，不能计算 relation purity、direction accuracy、analogy retrieval 或 topic-leakage 通过率。待 Review Sheet 标注后再将这些指标接入；在此之前不得依据本报告选择“最佳关系簇”。", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--method", choices=("mid", "middiff", "diff", "concat"), default="middiff")
    parser.add_argument("--clusters", type=int, default=32)
    parser.add_argument("--max-iter", type=int, default=100)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    config, out = load_config(args.config), None
    out = run_dir(config)
    vectors = np.load(out / f"edge_embeddings_{args.method}.npy", mmap_mode="r")
    metadata = list(read_jsonl(out / "edge_metadata.jsonl"))
    if len(vectors) != len(metadata):
        raise ValueError(f"edge vector/metadata mismatch: {len(vectors)} != {len(metadata)}")
    seed = int(config["seed"] if args.seed is None else args.seed)
    normalized = l2_rows(np.asarray(vectors, dtype=np.float32))
    labels, centroids, steps = kmeans(normalized, args.clusters, seed, args.max_iter)
    target = out / "clustering" / f"{args.method}_k{args.clusters}_seed{seed}"
    target.mkdir(parents=True, exist_ok=True)
    np.save(target / "labels.npy", labels)
    np.save(target / "centroids.npy", centroids)
    pair_labels = collections.defaultdict(list)
    for label, row in zip(labels.tolist(), metadata):
        pair_labels[row["pair_id"]].append(label)
    reverse_rate = sum(values[0] == values[1] for values in pair_labels.values() if len(values) == 2) / len(pair_labels)
    payload = {"method": args.method, "vectors": len(vectors), "dimensions": int(vectors.shape[1]), "clusters": args.clusters, "seed": seed, "iterations": steps, "input_l2_normalized": True, "query_used": False, "gold_labels_used": False, "relation_labels_used": False, "reverse_same_cluster_rate": reverse_rate, "composition": composition(labels, metadata)}
    write_json(target / "clustering_metrics.json", payload)
    (target / "report.md").write_text(report(payload), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
