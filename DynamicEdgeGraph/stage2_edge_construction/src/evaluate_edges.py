"""Algebraic E0 checks; relation quality remains unavailable without reviewed pairs."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
from representations import invert_middiff
from common import read_jsonl, write_json
def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--run-dir", required=True); args = parser.parse_args(); out = Path(args.run_dir)
    metadata = list(read_jsonl(out / "edge_metadata.jsonl")); n = len(metadata) // 2
    if len(metadata) % 2: raise ValueError("expected paired directed metadata")
    metrics = {"directed_edges": len(metadata), "relation_semantics": "not_available: no reviewed node-pair relation labels", "direction_semantics": "not_available: endpoint swap alone is not a semantic direction test"}
    if (out / "edge_embeddings_mid.npy").is_file():
        mid = np.load(out / "edge_embeddings_mid.npy"); metrics["midpoint_swap_max_abs"] = float(np.max(np.abs(mid[:n] - mid[n:])))
    if (out / "edge_embeddings_diff.npy").is_file():
        diff = np.load(out / "edge_embeddings_diff.npy"); metrics["difference_reverse_max_abs"] = float(np.max(np.abs(diff[:n] + diff[n:]))); metrics["zero_difference_rows"] = int((np.linalg.norm(diff, axis=1) == 0).sum())
    if (out / "edge_embeddings_middiff.npy").is_file():
        edge = np.load(out / "edge_embeddings_middiff.npy"); source, target = invert_middiff(edge); metrics["middiff_reconstruction_finite"] = bool(np.isfinite(source).all() and np.isfinite(target).all())
    write_json(out / "metrics.json", metrics); (out / "report.md").write_text("# E0 评估\n\n工程恒等式已检查；没有人工审核 Node–Node 关系标签，关系语义、方向语义、analogy retrieval 与 hard-negative 指标均为 `not_available`。端点交换后的向量变化不构成方向关系正确性的证据。\n", encoding="utf-8"); print(json.dumps(metrics, indent=2))
if __name__ == "__main__": main()
