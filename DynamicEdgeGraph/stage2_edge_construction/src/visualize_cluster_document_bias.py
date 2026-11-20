"""Read-only visualization of document concentration in saved E0 edge clusters.

The input labels are never recomputed.  A cluster's document concentration is
defined on the union of its source/target canonical node IDs, not on duplicated
directed-edge occurrences.  This deliberately complements (and does not replace)
the historical same-document/cross-document binary statistic.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

import numpy as np

try:  # supports both ``python -m ...`` and the repository's script-style calls
    from .common import read_jsonl, write_json
except ImportError:  # pragma: no cover
    from common import read_jsonl, write_json


METHODS = ("mid", "middiff")


def endpoint_rows(labels: np.ndarray, metadata: list[dict]) -> list[dict]:
    rows = []
    for cluster in range(int(labels.max()) + 1):
        indices = np.flatnonzero(labels == cluster)
        nodes: dict[str, str] = {}
        undirected, cross_doc, cross_mod = set(), 0, 0
        for i in indices:
            row = metadata[int(i)]
            source, target = str(row["source_node_id"]), str(row["target_node_id"])
            nodes[source] = str(row["source_document_id"])
            nodes[target] = str(row["target_document_id"])
            pair = tuple(sorted((source, target)))
            if pair not in undirected:
                undirected.add(pair)
                cross_doc += row["source_document_id"] != row["target_document_id"]
                cross_mod += row["source_modality"] != row["target_modality"]
        docs = collections.Counter(nodes.values())
        top_doc, top_nodes = docs.most_common(1)[0]
        counts = np.asarray(list(docs.values()), dtype=np.float64)
        probs = counts / counts.sum()
        rows.append({
            "cluster": cluster, "directed_edges": int(len(indices)), "unique_pairs": len(undirected),
            "unique_endpoint_nodes": len(nodes), "unique_documents": len(docs),
            "top_document_id": top_doc, "top_document_endpoint_nodes": int(top_nodes),
            "top_document_endpoint_share": float(top_nodes / len(nodes)),
            "endpoint_document_entropy_bits": float(-(probs * np.log2(probs)).sum()),
            "cross_document_pair_count": cross_doc,
            "cross_document_pair_rate": float(cross_doc / len(undirected)) if undirected else 0.0,
            "cross_modal_pair_count": cross_mod,
            "cross_modal_pair_rate": float(cross_mod / len(undirected)) if undirected else 0.0,
        })
    return rows


def pca2(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    centered = values - values.mean(axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    return (centered @ vt[:2].T).astype(np.float32)


def plot_summary(method_rows: dict[str, list[dict]], out: Path) -> None:
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(15, 10), sharex=True)
    for ax, method in zip(axes, METHODS):
        rows = sorted(method_rows[method], key=lambda x: x["top_document_endpoint_share"])
        shares = [x["top_document_endpoint_share"] * 100 for x in rows]
        colors = ["#b2182b" if x >= 80 else "#ef8a62" if x >= 50 else "#67a9cf" for x in shares]
        ax.barh([str(x["cluster"]) for x in rows], shares, color=colors)
        ax.axvline(80, color="#b2182b", linestyle="--", linewidth=1)
        ax.axvline(50, color="#666666", linestyle=":", linewidth=1)
        ax.set_title(f"{method}: cluster endpoint document concentration")
        ax.set_xlabel("largest document's share of unique endpoints (%)")
        ax.set_ylabel("cluster ID (sorted)")
        ax.set_xlim(0, 100)
    fig.suptitle("Saved E0 clusters: actual document-ID concentration, not just same-document edge rate")
    fig.tight_layout(); fig.savefig(out / "endpoint_document_concentration.png", dpi=180); plt.close(fig)


def plot_structure(method_rows: dict[str, list[dict]], out: Path) -> None:
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    for ax, method in zip(axes, METHODS):
        rows = method_rows[method]
        x = [r["directed_edges"] for r in rows]
        y = [r["top_document_endpoint_share"] * 100 for r in rows]
        c = [r["cross_document_pair_rate"] * 100 for r in rows]
        dots = ax.scatter(x, y, c=c, cmap="viridis", s=65, edgecolors="black", linewidths=.35)
        for r, a, b in zip(rows, x, y): ax.annotate(str(r["cluster"]), (a, b), xytext=(3, 3), textcoords="offset points", fontsize=8)
        ax.axhline(80, color="#b2182b", linestyle="--", linewidth=1)
        ax.set_title(method); ax.set_xlabel("directed edges in cluster")
        ax.set_ylabel("largest-document endpoint share (%)")
        fig.colorbar(dots, ax=ax, label="cross-document unique-pair rate (%)")
    fig.suptitle("Large, document-concentrated clusters are not necessarily cross-document sparse")
    fig.tight_layout(); fig.savefig(out / "cluster_size_document_bias_scatter.png", dpi=180); plt.close(fig)


def plot_pca(root: Path, method: str, labels: np.ndarray, out: Path) -> None:
    import matplotlib.pyplot as plt
    vectors = np.asarray(np.load(root / f"edge_embeddings_{method}.npy", mmap_mode="r"), dtype=np.float32)
    xy = pca2(vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12))
    fig, ax = plt.subplots(figsize=(8, 6.5))
    scatter = ax.scatter(xy[:, 0], xy[:, 1], c=labels, s=4, alpha=.55, cmap="tab20", linewidths=0)
    ax.set_title(f"{method}: centered PCA of saved E0 vectors")
    ax.set_xlabel("PC1"); ax.set_ylabel("PC2")
    fig.colorbar(scatter, ax=ax, label="saved K=32 cluster ID")
    ax.text(.01, .01, "Projection is descriptive; separation does not establish relation types.", transform=ax.transAxes, fontsize=8, va="bottom")
    fig.tight_layout(); fig.savefig(out / f"{method}_centered_pca.png", dpi=180); plt.close(fig)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    metadata = list(read_jsonl(args.root / "edge_metadata.jsonl"))
    all_rows, summary = {}, {}
    for method in METHODS:
        labels = np.load(args.root / "clustering" / f"{method}_k32_seed17" / "labels.npy").astype(np.int32)
        if len(labels) != len(metadata): raise ValueError(f"{method}: labels/metadata length mismatch")
        rows = endpoint_rows(labels, metadata); all_rows[method] = rows
        write_csv(args.out / f"{method}_cluster_document_composition.csv", rows)
        shares = np.asarray([r["top_document_endpoint_share"] for r in rows])
        summary[method] = {
            "clusters": len(rows), "directed_edges": len(labels),
            "clusters_top_document_share_ge_80pct": int((shares >= .8).sum()),
            "clusters_top_document_share_ge_90pct": int((shares >= .9).sum()),
            "median_top_document_endpoint_share": float(np.median(shares)),
            "weighted_top_document_endpoint_share": float(sum(r["top_document_endpoint_nodes"] for r in rows) / sum(r["unique_endpoint_nodes"] for r in rows)),
        }
        plot_pca(args.root, method, labels, args.out)
    plot_summary(all_rows, args.out); plot_structure(all_rows, args.out)
    write_json(args.out / "summary.json", summary)
    report = ["# Saved E0 clustering: document-bias visualization", "", "These plots read existing labels only; they do not fit a new clustering or treat IDs as relation types.", "", "| method | clusters ≥80% one document | clusters ≥90% | median largest-document endpoint share | weighted share |", "|---|---:|---:|---:|---:|"]
    for method in METHODS:
        x = summary[method]
        report.append(f"| {method} | {x['clusters_top_document_share_ge_80pct']}/{x['clusters']} | {x['clusters_top_document_share_ge_90pct']}/{x['clusters']} | {x['median_top_document_endpoint_share']:.2%} | {x['weighted_top_document_endpoint_share']:.2%} |")
    report += ["", "- `endpoint_document_concentration.png` is the primary bias chart: each bar uses unique endpoints merged within a cluster.", "- `cluster_size_document_bias_scatter.png` shows that pair-level cross-document rate and endpoint document concentration are different statistics.", "- Centered PCA figures are only a view of the saved E0 geometry, not evidence of relation purity.", ""]
    (args.out / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
