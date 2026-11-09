"""Bounded dense ANN, BM25 and structural candidate routes."""
from __future__ import annotations
import argparse, json, math, time, platform, resource, sys
from collections import Counter, defaultdict
from pathlib import Path
_LOCAL_ANN_DEPS = Path(__file__).resolve().parents[1] / ".ann_deps"
if _LOCAL_ANN_DEPS.exists():
    # FAISS 1.8 is built against NumPy 1.x; load its isolated ABI first.
    sys.path.insert(0, str(_LOCAL_ANN_DEPS))
import numpy as np
from .common import load_config, node_record, read_jsonl, repo_path, run_dir, tokens, write_jsonl


def dense(nodes, vectors, top_k, chunk_size, route, model, run_id, config, index_path):
    """HNSW ANN retrieval; never computes or materializes an N x N score matrix."""
    dependency = config.get("ann_dependency_path")
    if dependency:
        sys.path.insert(0, str(repo_path(str(dependency))))
    try:
        import faiss
    except ImportError as exc:
        raise RuntimeError("FAISS is required for dense ANN; install it under the Stage-1-local .ann_deps directory") from exc
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or len(matrix) != len(nodes):
        raise ValueError(f"{route}: vector/view count mismatch: {matrix.shape} vs {len(nodes)}")
    norms = np.linalg.norm(matrix, axis=1)
    if not np.isfinite(matrix).all() or np.any(norms == 0):
        raise ValueError(f"{route}: non-finite or zero frozen embedding")
    matrix = np.ascontiguousarray(matrix / norms[:, None], dtype=np.float32)
    m = int(config.get("ann_hnsw_m", 32))
    index = faiss.IndexHNSWFlat(matrix.shape[1], m, faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = int(config.get("ann_ef_construction", 160))
    index.hnsw.efSearch = int(config.get("ann_ef_search", 256))
    started = time.perf_counter(); index.add(matrix); build_seconds = time.perf_counter() - started
    index_path.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_path))
    fetch = min(len(nodes), max(top_k * int(config.get("ann_overfetch", 6)), top_k + 16))
    started = time.perf_counter(); score_matrix, id_matrix = index.search(matrix, fetch); search_seconds = time.perf_counter() - started
    rows = []
    for source, (scores, ids) in enumerate(zip(score_matrix, id_matrix)):
        seen, rank = {nodes[source]["node_id"]}, 0
        for target, score in zip(ids, scores):
            if target < 0 or not math.isfinite(float(score)) or nodes[int(target)]["node_id"] in seen:
                continue
            seen.add(nodes[int(target)]["node_id"]); rank += 1
            rows.append({"source_id": nodes[source]["node_id"], "target_id": nodes[int(target)]["node_id"],
                         "route": route, "direction": "forward", "rank": rank, "raw_score": float(score),
                         "model": model, "run_id": run_id, "retrieval_engine": "faiss.IndexHNSWFlat",
                         "candidate_bounded": True})
            if rank == top_k: break
    return rows, {"device": "cpu (HNSW ANN)", "engine": "faiss.IndexHNSWFlat", "approximate": True,
                  "m": m, "ef_construction": index.hnsw.efConstruction, "ef_search": index.hnsw.efSearch,
                  "overfetch": fetch, "index_build_seconds": build_seconds, "search_seconds": search_seconds,
                  "index_path": str(index_path)}


def bm25(nodes, top_k, route, run_id):
    postings = defaultdict(dict)
    lengths = []
    for i, node in enumerate(nodes):
        terms = Counter(tokens(node["text"])); lengths.append(sum(terms.values()))
        for term, count in terms.items(): postings[term][i] = count
    avg = sum(lengths) / max(len(lengths), 1); total = len(nodes); rows = []
    for source, node in enumerate(nodes):
        scores = defaultdict(float)
        for term in set(tokens(node["text"])):
            for target, tf in postings[term].items():
                if target == source or nodes[target]["node_id"] == node["node_id"]: continue
                df = len(postings[term]); idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
                denom = tf + 1.5 * (1 - 0.75 + 0.75 * lengths[target] / max(avg, 1))
                scores[target] += idf * tf * 2.5 / denom
        ranked = sorted(scores, key=lambda i: (-scores[i], nodes[i]["node_id"]))[:top_k]
        rows.extend({"source_id": node["node_id"], "target_id": nodes[i]["node_id"], "route": route,
                     "direction": "forward", "rank": rank, "raw_score": float(scores[i]),
                     "model": "BM25:local-inverted-index", "run_id": run_id} for rank, i in enumerate(ranked, 1))
    return rows


def structural(nodes, window, route, run_id):
    groups = defaultdict(list)
    for i, node in enumerate(nodes): groups[(node["document_id"], str(node["page_number"]))].append(i)
    rows = []
    for source, node in enumerate(nodes):
        candidates = []
        for (doc, page), indices in groups.items():
            if doc != node["document_id"]: continue
            try: distance = abs(int(page) - int(node["page_number"]))
            except (TypeError, ValueError): distance = 0 if page == str(node["page_number"]) else window + 1
            if distance <= window:
                candidates.extend((distance, i) for i in indices
                                  if i != source and nodes[i]["node_id"] != node["node_id"])
        candidates = sorted(candidates, key=lambda x: (x[0], nodes[x[1]]["node_id"]))
        rows.extend({"source_id": node["node_id"], "target_id": nodes[i]["node_id"], "route": route,
                     "direction": "forward", "rank": rank, "raw_score": float(1 / (1 + distance)),
                     "model": "structural:document-page-window", "run_id": run_id}
                    for rank, (distance, i) in enumerate(candidates, 1))
    return rows


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--config", required=True); args = parser.parse_args()
    config = load_config(args.config); out = run_dir(config); out.mkdir(parents=True, exist_ok=True)
    nodes = [node_record(r, i) for i, r in enumerate(read_jsonl(repo_path(config["node_path"])))]
    if config.get("max_nodes"): nodes = nodes[:int(config["max_nodes"])]
    routes = {}
    route_stats = {}
    for route in config["routes"]:
        if route in config.get("vector_routes", {}):
            spec = config["vector_routes"][route]
            started = time.perf_counter()
            vectors = np.load(repo_path(spec["path"]), mmap_mode="r", allow_pickle=False)[:len(nodes)]
            if len(vectors) != len(nodes): raise ValueError(f"{route} vectors do not cover selected views")
            routes[route], ann_stats = dense(nodes, vectors, int(config["top_k"]), int(config.get("chunk_size", 512)),
                                              route, spec["model"], config["run_id"], config,
                                              out / "ann_indexes" / f"{route}.hnsw")
            route_stats[route] = {"elapsed_seconds": time.perf_counter() - started,
                                  "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                                  "vector_shape": list(vectors.shape), "model": spec["model"],
                                  **ann_stats}
    if "bm25" in config["routes"]:
        started = time.perf_counter()
        routes["bm25"] = bm25(nodes, int(config["top_k"]), "bm25", config["run_id"])
        route_stats["bm25"] = {"elapsed_seconds": time.perf_counter() - started, "model": "BM25:local-inverted-index"}
    if "structural" in config["routes"]:
        started = time.perf_counter()
        routes["structural"] = structural(nodes, int(config["structural_window"]), "structural", config["run_id"])
        route_stats["structural"] = {"elapsed_seconds": time.perf_counter() - started, "model": "structural:document-page-window"}
    for route, rows in routes.items(): write_jsonl(out / "route_candidates" / f"{route}.jsonl", rows)
    union = {}
    for route, rows in routes.items():
        for row in rows:
            pair = tuple(sorted((row["source_id"], row["target_id"])))
            if pair[0] == pair[1]: continue
            entry = union.setdefault(pair, {"source_id": pair[0], "target_id": pair[1], "routes": {}})
            entry["routes"].setdefault(route, []).append({"direction": row["direction"], "rank": row["rank"], "raw_score": row["raw_score"]})
    write_jsonl(out / "candidate_union.jsonl", (union[pair] for pair in sorted(union)))
    (out / "route_resources.json").write_text(json.dumps({"hardware": platform.platform(),
        "routes": route_stats, "candidate_counts": {k: len(v) for k, v in routes.items()},
        "union_pairs": len(union), "all_pairs_scored": False,
        "note": "Dense routes use HNSW ANN. Exact scores are retained only for ANN-returned candidates."}, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"output": str(out), "nodes": len(nodes), "routes": {k: len(v) for k, v in routes.items()}, "union": len(union)}))


if __name__ == "__main__": main()
