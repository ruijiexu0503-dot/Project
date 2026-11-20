"""CPU-only diagnostic audit and SVG visualisation for frozen E0 edge clusters.

This does not assign relation types.  It asks a narrower question: are edge
members close in E0 geometry also close in their source/target node semantics,
or are clusters primarily grouping document locality / modality / route effects?
"""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path("DynamicEdgeGraph/stage2_edge_construction/outputs/pilot_e0_stage1_v1")
VIEWS = Path("DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir-pilot-stage1-v1/retrieval_views.jsonl")


def l2(x):
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)


def pairs_for(indices, count, rng):
    if len(indices) < 2:
        return np.empty(0, dtype=int), np.empty(0, dtype=int)
    left = rng.choice(indices, size=count, replace=True)
    right = rng.choice(indices, size=count, replace=True)
    same = left == right
    while same.any():
        right[same] = rng.choice(indices, size=int(same.sum()), replace=True)
        same = left == right
    return left, right


def short(text, limit=180):
    text = " ".join(text.replace("\n", " ").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def svg_scatter(points, labels, centers, path):
    width, height, margin = 1280, 930, 55
    lo, hi = points.min(axis=0), points.max(axis=0)
    span = np.maximum(hi - lo, 1e-7)
    xy = (points - lo) / span
    xy[:, 0] = margin + xy[:, 0] * (width - 2 * margin)
    xy[:, 1] = height - margin - xy[:, 1] * (height - 2 * margin)
    cxy = (centers - lo) / span
    cxy[:, 0] = margin + cxy[:, 0] * (width - 2 * margin)
    cxy[:, 1] = height - margin - cxy[:, 1] * (height - 2 * margin)
    colors = [f"hsl({(i * 47) % 360},62%,42%)" for i in range(32)]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<text x="55" y="30" font-family="sans-serif" font-size="18">E0-MidDiff: randomized PCA projection (10,000 fixed directed edges)</text>',
           '<text x="55" y="52" font-family="sans-serif" font-size="12">Colours are K=32 cluster IDs; geometry is diagnostic, not relation labels.</text>']
    for (x, y), label in zip(xy, labels):
        out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.3" fill="{colors[int(label)]}" fill-opacity="0.42"/>')
    for i, (x, y) in enumerate(cxy):
        out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="white" stroke="{colors[i]}" stroke-width="2"/><text x="{x+6:.2f}" y="{y-6:.2f}" font-family="sans-serif" font-size="11">{i}</text>')
    out.append('</svg>')
    path.write_text("\n".join(out), encoding="utf-8")


def svg_heatmap(sim, path):
    cell, margin = 22, 70
    n, size = len(sim), margin + cell * len(sim) + 20
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<text x="8" y="18" font-family="sans-serif" font-size="13">Centroid cosine</text>']
    for i in range(n):
        out.append(f'<text x="{margin+i*cell+5}" y="{margin-7}" font-family="sans-serif" font-size="8">{i}</text>')
        out.append(f'<text x="{margin-14}" y="{margin+i*cell+14}" font-family="sans-serif" font-size="8">{i}</text>')
    for i in range(n):
        for j in range(n):
            v = float(sim[i, j]); shade = int(255 * (1 - (v + 1) / 2))
            out.append(f'<rect x="{margin+j*cell}" y="{margin+i*cell}" width="{cell}" height="{cell}" fill="rgb({shade},{shade},{255})"><title>{i},{j}: {v:.3f}</title></rect>')
    out.append('</svg>'); path.write_text("\n".join(out), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--cluster", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=1729)
    ap.add_argument("--pairs-per-cluster", type=int, default=1000)
    args = ap.parse_args()
    root = args.root; cluster = args.cluster or root / "clustering/middiff_k32_seed17"
    out = args.out or cluster / "semantic_audit"; out.mkdir(parents=True, exist_ok=True)
    labels = np.load(cluster / "labels.npy").astype(int)
    edge = l2(np.asarray(np.load(root / "edge_embeddings_middiff.npy"), dtype=np.float32))
    centers = l2(np.asarray(np.load(cluster / "centroids.npy"), dtype=np.float32))
    meta = [json.loads(x) for x in (root / "edge_metadata.jsonl").read_text().splitlines()]
    node = l2(np.asarray(np.load(json.loads((root / "input_manifest.json").read_text())["embedding"]["vector_path"]), dtype=np.float32))
    views = {r["node_id"]: r["retrieval_text"] for r in map(json.loads, VIEWS.open())}
    if not (len(labels) == len(edge) == len(meta)):
        raise ValueError("edge metadata/vector/label mismatch")
    rng = np.random.default_rng(args.seed)
    # Baseline uses the same number of independently sampled edge pairs as all
    # within-cluster measurements combined; it is not a relation-quality score.
    total_pairs = args.pairs_per_cluster * len(np.unique(labels))
    base_a, base_b = pairs_for(np.arange(len(edge)), total_pairs, rng)
    baseline = {
        "edge_cosine": float(np.mean(np.einsum("ij,ij->i", edge[base_a], edge[base_b]))),
        "source_cosine": float(np.mean(np.einsum("ij,ij->i", node[[meta[i]["source_embedding_row"] for i in base_a]], node[[meta[i]["source_embedding_row"] for i in base_b]]))),
        "target_cosine": float(np.mean(np.einsum("ij,ij->i", node[[meta[i]["target_embedding_row"] for i in base_a]], node[[meta[i]["target_embedding_row"] for i in base_b]]))),
    }
    rows = []
    for k in range(len(centers)):
        idx = np.flatnonzero(labels == k)
        a, b = pairs_for(idx, args.pairs_per_cluster, rng)
        src_a = [meta[i]["source_embedding_row"] for i in a]; src_b = [meta[i]["source_embedding_row"] for i in b]
        tgt_a = [meta[i]["target_embedding_row"] for i in a]; tgt_b = [meta[i]["target_embedding_row"] for i in b]
        centroid_similarity = edge[idx] @ centers[k]
        representatives = []
        for i in idx[np.argsort(-centroid_similarity)[:3]]:
            m = meta[i]
            representatives.append({"edge_id": m["edge_id"], "source": {"node_id": m["source_node_id"], "page": m["source_page"], "modality": m["source_modality"], "text": short(views.get(m["source_node_id"], "[missing view]"))},
                                    "target": {"node_id": m["target_node_id"], "page": m["target_page"], "modality": m["target_modality"], "text": short(views.get(m["target_node_id"], "[missing view]"))},
                                    "edge_to_centroid_cosine": float(edge[i] @ centers[k])})
        same_doc = np.mean([meta[i]["source_document_id"] == meta[i]["target_document_id"] for i in idx])
        rows.append({"cluster": k, "size": int(len(idx)), "mean_edge_to_centroid_cosine": float(centroid_similarity.mean()),
                     "within_edge_pair_cosine": float(np.mean(np.einsum("ij,ij->i", edge[a], edge[b]))),
                     "within_source_node_cosine": float(np.mean(np.einsum("ij,ij->i", node[src_a], node[src_b]))),
                     "within_target_node_cosine": float(np.mean(np.einsum("ij,ij->i", node[tgt_a], node[tgt_b]))),
                     "same_document_rate": float(same_doc), "representatives": representatives})
    # Randomized range finder + SVD: deterministic, dependency-free approximate PCA.
    omega = rng.normal(size=(edge.shape[1], 64)).astype(np.float32)
    q, _ = np.linalg.qr(edge @ omega, mode="reduced")
    _, _, vt = np.linalg.svd(q.T @ edge, full_matrices=False)
    axes = vt[:2].T
    svg_scatter(edge @ axes, labels, centers @ axes, out / "edge_clusters_randomized_pca.svg")
    svg_heatmap(centers @ centers.T, out / "centroid_cosine_heatmap.svg")
    payload = {"contract": {"edge_embedding": "frozen E0-MidDiff", "clusters": int(len(centers)), "edges": int(len(edge)), "query_or_gold_used": False,
                            "semantic_test": "same-cluster source/source and target/target Qwen node cosine versus random edge-pair baseline; diagnostic only"},
               "random_pair_baseline": baseline, "clusters": rows}
    (out / "cluster_semantic_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# E0 Cluster Semantic Audit", "", "This audit does **not** treat cluster IDs as relation types. It compares frozen node-vector semantic proximity within each edge cluster with a random directed-edge-pair baseline, then exposes text of the three centroid-nearest edges for manual inspection.", "", f"Random-pair baseline: edge={baseline['edge_cosine']:.3f}; source={baseline['source_cosine']:.3f}; target={baseline['target_cosine']:.3f}.", "", "|cluster|n|edge→center|within edge|source cosine|target cosine|same doc|", "|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"|{r['cluster']}|{r['size']}|{r['mean_edge_to_centroid_cosine']:.3f}|{r['within_edge_pair_cosine']:.3f}|{r['within_source_node_cosine']:.3f}|{r['within_target_node_cosine']:.3f}|{r['same_document_rate']:.1%}|")
    lines += ["", "## Centroid-nearest edge examples", ""]
    for r in rows:
        lines.append(f"### Cluster {r['cluster']}")
        for e in r['representatives']:
            lines.append(f"- `{e['edge_id']}` ({e['edge_to_centroid_cosine']:.3f}): **S** p{e['source']['page']} {e['source']['modality']} — {e['source']['text']} → **T** p{e['target']['page']} {e['target']['modality']} — {e['target']['text']}")
        lines.append("")
    (out / "CLUSTER_SEMANTIC_AUDIT.md").write_text("\n".join(lines), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
