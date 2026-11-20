"""CPU-only residual prototype updates for the fixed E0-MidDiff clustering sample.

Updated vectors are *not* invertible MidDiff vectors.  Their first/second
halves are retained as shared-like/directed-like channels for downstream
scoring, each normalized independently at scoring time.
"""
from __future__ import annotations

import argparse
import collections
import json

import numpy as np

from common import load_config, read_jsonl, run_dir, write_json, write_jsonl


def rows_l2(x):
    n = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.maximum(n, np.finfo(np.float32).eps)


def cosine(a, b): return np.sum(rows_l2(a) * rows_l2(b), axis=1)


def update(edges, contexts, alpha):
    return rows_l2((1.0 - alpha) * edges + alpha * contexts)


def hard_context(labels, centers): return centers[labels]


def soft_context(edges, centers, temperature):
    logits = (edges @ centers.T) / temperature
    logits -= logits.max(axis=1, keepdims=True)
    weights = np.exp(logits); weights /= weights.sum(axis=1, keepdims=True)
    return rows_l2(weights @ centers), weights


def random_context(edges, hard_labels, seed):
    rng = np.random.default_rng(seed)
    labels = rng.permutation(hard_labels)
    centers = np.zeros((int(labels.max()) + 1, edges.shape[1]), dtype=np.float32)
    for k in range(len(centers)):
        centers[k] = edges[labels == k].mean(axis=0)
    return centers[labels], labels, rows_l2(centers)


def direction_metrics(edges, metadata):
    half = edges.shape[1] // 2
    by_pair = collections.defaultdict(list)
    for i, row in enumerate(metadata): by_pair[row["pair_id"]].append(i)
    midpoint, difference, full = [], [], []
    for values in by_pair.values():
        if len(values) != 2: continue
        left, right = values
        midpoint.append(float(cosine(edges[left:left + 1, :half], edges[right:right + 1, :half])[0]))
        difference.append(float(cosine(edges[left:left + 1, half:], -edges[right:right + 1, half:])[0]))
        full.append(float(cosine(edges[left:left + 1], edges[right:right + 1])[0]))
    return {"paired_directions": len(midpoint), "midpoint_reverse_cosine_mean": float(np.mean(midpoint)), "difference_antireverse_cosine_mean": float(np.mean(difference)), "forward_reverse_full_cosine_mean": float(np.mean(full)), "fraction_forward_reverse_distinguishable_cos_lt_0_99": float(np.mean(np.asarray(full) < 0.99))}


def document_similarity(edges, metadata, seed):
    rng = np.random.default_rng(seed); docs = collections.defaultdict(list)
    for i, row in enumerate(metadata): docs[row["source_document_id"]].append(i)
    same = []
    for indices in docs.values():
        if len(indices) > 1:
            for _ in range(min(80, len(indices))):
                a, b = rng.choice(indices, 2, replace=False); same.append((a, b))
    all_ids = np.arange(len(edges)); cross = []
    while len(cross) < len(same):
        a, b = rng.choice(all_ids, 2, replace=False)
        if metadata[a]["source_document_id"] != metadata[b]["source_document_id"]: cross.append((a, b))
    def average(pairs): return float(np.mean([edges[a] @ edges[b] for a, b in pairs])) if pairs else None
    return {"same_document_pairs": len(same), "cross_document_pairs": len(cross), "same_document_cosine_mean": average(same), "cross_document_cosine_mean": average(cross)}


def geometry(name, original, updated, metadata, labels, centers, seed, extra=None):
    half = original.shape[1] // 2
    nearest = np.argmax(updated @ centers.T, axis=1)
    payload = {"name": name, "vectors": len(updated), "dimensions": int(updated.shape[1]), "mean_original_updated_cosine": float(np.mean(np.sum(original * updated, axis=1))), "minimum_original_updated_cosine": float(np.min(np.sum(original * updated, axis=1))), "mean_midpoint_channel_cosine_to_original": float(np.mean(cosine(original[:, :half], updated[:, :half]))), "mean_difference_channel_cosine_to_original": float(np.mean(cosine(original[:, half:], updated[:, half:]))), "difference_to_midpoint_norm_ratio_mean": float(np.mean(np.linalg.norm(updated[:, half:], axis=1) / np.maximum(np.linalg.norm(updated[:, :half], axis=1), 1e-12))), "nearest_hard_prototype_agreement": float(np.mean(nearest == labels)), "near_prototype_collapse_cos_ge_0_99": float(np.mean(np.max(updated @ centers.T, axis=1) >= 0.99)), "direction": direction_metrics(updated, metadata), "document_similarity": document_similarity(updated, metadata, seed)}
    if extra: payload.update(extra)
    return payload


def markdown(metrics):
    lines = ["# Prototype-based Edge Updating（10,000 条 E0-MidDiff 有向边）", "", "更新输入为整条 L2-normalized E0-MidDiff。输出不再可逆还原端点；前/后 1024 维只能作为 prototype-conditioned shared-like / directed-like channel，在检索时分别归一化。", "", "| variant | 原始余弦 | midpoint 通道保留 | difference 通道保留 | 反向 difference 保留 | 正反边整体余弦 | 同文档 cosine | 跨文档 cosine |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for key, value in metrics.items():
        if key.endswith("alpha0"): continue
        direction, docs = value["direction"], value["document_similarity"]
        lines.append(f"| {key} | {value['mean_original_updated_cosine']:.4f} | {value['mean_midpoint_channel_cosine_to_original']:.4f} | {value['mean_difference_channel_cosine_to_original']:.4f} | {direction['difference_antireverse_cosine_mean']:.4f} | {direction['forward_reverse_full_cosine_mean']:.4f} | {docs['same_document_cosine_mean']:.4f} | {docs['cross_document_cosine_mean']:.4f} |")
    soft = metrics.get("soft_alpha0.1")
    if soft:
        lines += ["", f"Soft assignment：T={soft['temperature']}；平均熵={soft['assignment_entropy_nats_mean']:.4f} nats；有效 prototype 数={soft['prototype_effective_count']:.2f}。权重是无监督相似度权重，不是关系概率。"]
    lines += ["", "高 α 会使正反方向边的整体余弦上升，因此即使 difference 的反向性质仍较高，也可能发生方向区分压缩。随机分组是负对照；不得把其变化解释为共享关系信息。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--clusters", type=int, default=32)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--temperature", type=float, default=0.10)
    parser.add_argument("--alphas", type=float, nargs="+", default=(0.0, 0.1, 0.3))
    args = parser.parse_args()
    if args.temperature <= 0 or any(a < 0 or a > 1 for a in args.alphas): raise ValueError("temperature > 0 and alpha in [0,1] required")
    out = run_dir(load_config(args.config)); cluster = out / "clustering" / f"middiff_k{args.clusters}_seed{args.seed}"
    original = rows_l2(np.asarray(np.load(out / "edge_embeddings_middiff.npy"), dtype=np.float32))
    labels = np.load(cluster / "labels.npy").astype(np.int32); centers = rows_l2(np.asarray(np.load(cluster / "centroids.npy"), dtype=np.float32))
    metadata = list(read_jsonl(out / "edge_metadata.jsonl"))
    if len(original) != len(labels) or len(original) != len(metadata): raise ValueError("edge/label/metadata count mismatch")
    target = out / "prototype_updates" / f"middiff_k{args.clusters}_seed{args.seed}_t{args.temperature:g}"; target.mkdir(parents=True, exist_ok=True)
    random_ctx, random_labels, random_centers = random_context(original, labels, args.seed)
    soft_ctx, weights = soft_context(original, centers, args.temperature)
    assignments = {"hard": hard_context(labels, centers), "soft": soft_ctx, "random": random_ctx}
    all_metrics = {}
    for method, context in assignments.items():
        for alpha in args.alphas:
            tag = f"{method}_alpha{alpha:g}"
            updated = original if alpha == 0 else update(original, context, alpha)
            if alpha != 0: np.save(target / f"{tag}.npy", updated.astype(np.float32))
            extra = {"alpha": alpha, "assignment": method, "context_semantics": "normalized prototype context; residual mixing after original whole-edge L2 normalization"}
            if method == "soft":
                entropy = -np.sum(weights * np.log(np.maximum(weights, 1e-12)), axis=1)
                extra.update({"temperature": args.temperature, "assignment_entropy_nats_mean": float(np.mean(entropy)), "assignment_entropy_nats_min": float(np.min(entropy)), "prototype_mean_weights": weights.mean(axis=0).tolist(), "prototype_effective_count": float(np.exp(np.mean(entropy)))})
            all_metrics[tag] = geometry(tag, original, updated, metadata, labels, centers, args.seed, extra)
            if alpha != 0:
                change = 1.0 - np.sum(original * updated, axis=1)
                worst = np.argsort(-change)[:20]
                write_jsonl(target / f"{tag}_failure_cases.jsonl", ({"edge_id": metadata[i]["edge_id"], "pair_id": metadata[i]["pair_id"], "source_node_id": metadata[i]["source_node_id"], "target_node_id": metadata[i]["target_node_id"], "source_document_id": metadata[i]["source_document_id"], "target_document_id": metadata[i]["target_document_id"], "hard_cluster": int(labels[i]), "original_updated_cosine": float(original[i] @ updated[i]), "nearest_prototype_similarity": float(np.max(updated[i] @ centers.T))} for i in worst))
    write_json(target / "prototype_update_metrics.json", {"input": {"edge_embedding": "E0-MidDiff, 10,000 directed sample edges", "input_whole_edge_l2_normalized": True, "cluster_centers": str(cluster / "centroids.npy"), "clusters": args.clusters}, "semantic_contract": "updated vectors are not invertible MidDiff; split halves are prototype-conditioned shared-like and directed-like channels, each requires L2 normalization before query scoring", "hard_labels": labels.tolist(), "random_assignment_seed": args.seed, "metrics": all_metrics})
    write_json(target / "prototype_assignment_summary.json", {"hard_cluster_counts": np.bincount(labels, minlength=args.clusters).tolist(), "random_cluster_counts": np.bincount(random_labels, minlength=args.clusters).tolist(), "soft_temperature": args.temperature, "soft_mean_weights": weights.mean(axis=0).tolist()})
    (target / "PROTOTYPE_UPDATE_REPORT.md").write_text(markdown(all_metrics), encoding="utf-8")
    print(target)


if __name__ == "__main__": main()
