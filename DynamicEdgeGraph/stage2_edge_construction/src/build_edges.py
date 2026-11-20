"""Materialize both directions of strict-mapped E0 edge embeddings."""
from __future__ import annotations
import argparse, time
import numpy as np
from common import load_config, load_embeddings, read_jsonl, repo_path, run_dir, sha256_file, stable_edge_id, write_json, write_jsonl
from representations import edge_representation, l2_normalize

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); args = parser.parse_args(); config = load_config(args.config)
    out = run_dir(config); pairs_path = out / "pairs.jsonl"
    if not pairs_path.is_file(): raise FileNotFoundError(f"run prepare_pilot_pairs.py first: {pairs_path}")
    vectors, ids = load_embeddings(config); index = {node_id: i for i, node_id in enumerate(ids)}
    pairs = list(read_jsonl(pairs_path)); missing = sorted({node for pair in pairs for node in (pair["source_node_id"], pair["target_node_id"]) if node not in index})
    if missing: raise ValueError(f"pair nodes missing from embedding IDs ({len(missing)}): {missing[:3]}")
    source_rows = np.asarray([index[p["source_node_id"]] for p in pairs] + [index[p["target_node_id"]] for p in pairs]); target_rows = np.asarray([index[p["target_node_id"]] for p in pairs] + [index[p["source_node_id"]] for p in pairs])
    source, target = np.asarray(vectors[source_rows], dtype=np.float32), np.asarray(vectors[target_rows], dtype=np.float32)
    if config.get("input_l2_normalize"): source, _ = l2_normalize(source); target, _ = l2_normalize(target)
    metadata = []
    directed_pairs = pairs + [{**p, "source_node_id": p["target_node_id"], "target_node_id": p["source_node_id"], "source_document_id": p["target_document_id"], "target_document_id": p["source_document_id"], "source_page": p["target_page"], "target_page": p["source_page"], "source_modality": p["target_modality"], "target_modality": p["source_modality"]} for p in pairs]
    started = time.perf_counter(); results = {}
    for method in config.get("methods", []):
        edge = edge_representation(source, target, method).astype(config.get("dtype", "float32"), copy=False)
        zero_output = 0
        if config.get("output_l2_normalize"):
            edge, zero = l2_normalize(edge); zero_output = int(zero.sum())
        if not np.isfinite(edge).all(): raise ValueError(f"{method} created NaN/Inf")
        path = out / f"edge_embeddings_{method}.npy"; np.save(path, edge)
        results[method] = {"path": path.name, "shape": list(edge.shape), "dtype": str(edge.dtype), "bytes": path.stat().st_size, "zero_output_rows": zero_output}
    for row, srow, trow in zip(directed_pairs, source_rows, target_rows, strict=True):
        metadata.append({**row, "edge_id": stable_edge_id(row["pair_id"], row["source_node_id"], row["target_node_id"]), "embedding_row": len(metadata), "source_embedding_row": int(srow), "target_embedding_row": int(trow), "encoder_id": config.get("encoder_id"), "input_vector_version": config.get("input_vector_version"), "normalization": {"input_l2": bool(config.get("input_l2_normalize")), "output_l2": bool(config.get("output_l2_normalize"))}, "dtype": config.get("dtype")})
    write_jsonl(out / "edge_metadata.jsonl", metadata)
    write_json(out / "build_metrics.json", {"unordered_pairs": len(pairs), "directed_edges": len(metadata), "embedding_dimension": int(vectors.shape[1]), "methods": results, "seconds": time.perf_counter() - started, "embedding_sha256": sha256_file(repo_path(config["embedding_path"])), "embedding_ids_sha256": sha256_file(repo_path(config["embedding_ids_path"]))})
    print(out)
if __name__ == "__main__": main()
