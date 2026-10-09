#!/usr/bin/env python3
"""Isolated ANN candidate audit; never creates verified semantic edges.

Real cached embeddings measure retrieval fidelity. Synthetic clustered vectors
measure scaling only. Exact baselines use bounded query batches, never N x N.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import resource
import sqlite3
import time

import faiss
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]


def read_rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_rows(path, rows):
    Path(path).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows))


def normalize(v):
    v = np.ascontiguousarray(v, dtype=np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    if not np.isfinite(v).all() or np.any(norms == 0):
        raise ValueError("Nonfinite or zero embedding")
    return v / norms


def index_for(v, approximate, ef=64):
    index = (faiss.IndexHNSWFlat(v.shape[1], 32, faiss.METRIC_INNER_PRODUCT)
             if approximate else faiss.IndexFlatIP(v.shape[1]))
    if approximate:
        index.hnsw.efConstruction = 160
        index.hnsw.efSearch = ef
    start = time.perf_counter()
    index.add(v)
    return index, time.perf_counter() - start


def search_filtered(index, queries, query_groups, target_groups, k):
    """Overfetch adaptively; never let same-article units consume all slots."""
    if index.ntotal == 0:
        return [[] for _ in queries]
    result = []
    for q, group in zip(queries, query_groups):
        fetch = min(index.ntotal, max(k * 2, 16))
        while True:
            scores, ids = index.search(q[None], fetch)
            hits = [(int(i), float(s)) for i, s in zip(ids[0], scores[0])
                    if i >= 0 and target_groups[i] != group]
            if len(hits) >= k or fetch == index.ntotal:
                result.append(hits[:k])
                break
            fetch = min(index.ntotal, fetch * 2)
    return result


def overlap(actual, expected):
    values = [len(set(a) & set(b)) / len(set(b)) for a, b in zip(actual, expected) if b]
    return float(np.mean(values)) if values else None


def timed_search(index, q, k, repeats=3):
    # Fixed batches make the exact baseline memory bounded at large N.
    def run():
        return np.concatenate([index.search(q[i:i + 32], k)[1]
                               for i in range(0, len(q), 32)])
    run()
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        ids = run()
        times.append(time.perf_counter() - start)
    return ids, float(np.median(times))


def aggregate(local, global_hits, lexical, owner, article_ids, budget, per_route):
    evidence = defaultdict(list)
    per_source = defaultdict(dict)
    for i, hits in enumerate(local):
        source = owner[i]
        for j, score in hits:
            target = owner[j]
            evidence[(source, target)].append((i, j, score))
            per_source[source][target] = max(score, per_source[source].get(target, -1.0))
    results = {}
    for a, source in enumerate(article_ids):
        routes = {
            "local": sorted(per_source[source], key=lambda t: (-per_source[source][t], t))[:per_route],
            "article": [article_ids[j] for j, _ in global_hits[a]][:per_route],
            "lexical": [t for t, _ in lexical[source]][:per_route],
        }
        fused = defaultdict(float)
        for targets in routes.values():
            for rank, target in enumerate(targets, 1):
                fused[target] += 1 / (60 + rank)
        chosen = sorted(fused, key=lambda t: (-fused[t], t))[:budget]
        results[source] = [{
            "source_article": source, "target_article": target,
            "rrf_score": fused[target],
            "routes": [name for name, values in routes.items() if target in values],
            "evidence": sorted(evidence[(source, target)], key=lambda x: -x[2])[:4],
            "edge_status": "UNVERIFIED_RETRIEVAL_CANDIDATE",
        } for target in chosen]
    return results


def lexical_candidates(units, owner, article_ids, cap):
    # Reuse corpus-derived term rules, with postings instead of pairwise joins.
    from audit_typed_anchor_relations import unit_candidates
    terms = defaultdict(set)
    for unit, article in zip(units, owner):
        terms[article].update(unit_candidates(unit["text"], 2, 7))
    postings = defaultdict(set)
    for article, words in terms.items():
        for word in words:
            postings[word].add(article)
    max_df = max(2, int(len(article_ids) * .15))
    postings = {w: p for w, p in postings.items() if 2 <= len(p) <= max_df}
    result = {}
    for article in article_ids:
        scores = Counter()
        for word in terms[article]:
            p = postings.get(word, ())
            for target in p:
                if target != article:
                    scores[target] += np.log((len(article_ids) + 1) / (len(p) + 1)) + 1
        result[article] = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:cap]
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=ROOT / "EdgeGeneration/output/typed_anchor_multimag_pilot_v1")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--sizes", type=int, nargs="*", default=[10000, 100000])
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--queries", type=int, default=128)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    faiss.omp_set_num_threads(args.threads)
    torch.set_num_threads(args.threads)
    files = [args.input / name for name in ("source_units.jsonl", "target_units.jsonl",
             "article_assignments.jsonl", "all_bge_m3_vectors_cpu.pt")]
    sources = read_rows(files[0])
    units = sources + read_rows(files[1])
    assignments = {r["node_id"]: r["article_id"] for r in read_rows(files[2])}
    if len({r["unit_id"] for r in units}) != len(units):
        raise ValueError("Duplicate unit IDs")
    # Explicit singleton fallback preserves unmapped evidence and reports it.
    owner = [assignments.get(r["unit_id"], r["doc_id"] if i >= len(sources)
             else "UNMAPPED::" + r["unit_id"]) for i, r in enumerate(units)]
    vectors = normalize(torch.load(files[3], map_location="cpu", weights_only=True).numpy())
    if len(vectors) != len(units):
        raise ValueError("Cached vector/unit count mismatch")
    article_ids = sorted(set(owner))
    members = {a: [i for i, x in enumerate(owner) if x == a] for a in article_ids}
    article_vectors = normalize(np.stack([vectors[members[a]].mean(0) for a in article_ids]))
    exact, _ = index_for(vectors, False)
    ann, build_seconds = index_for(vectors, True)
    ae, _ = index_for(article_vectors, False)
    aa, _ = index_for(article_vectors, True)
    faiss.write_index(ann, str(args.output / "evidence.hnsw"))
    faiss.write_index(aa, str(args.output / "articles.hnsw"))
    write_rows(args.output / "index_units.jsonl", [dict(r, article_id=a) for r, a in zip(units, owner)])
    write_rows(args.output / "index_articles.jsonl", [{"article_id": a, "unit_indexes": members[a]} for a in article_ids])
    np.save(args.output / "article_vectors.npy", article_vectors)
    start = time.perf_counter()
    local_e = search_filtered(exact, vectors, owner, owner, 10)
    exact_filtered_seconds = time.perf_counter() - start
    start = time.perf_counter()
    local_a = search_filtered(ann, vectors, owner, owner, 10)
    ann_filtered_seconds = time.perf_counter() - start
    global_e = search_filtered(ae, article_vectors, article_ids, article_ids, 20)
    global_a = search_filtered(aa, article_vectors, article_ids, article_ids, 20)
    lexical = lexical_candidates(units, owner, article_ids, 20)
    known = json.loads((ROOT / "EdgeGeneration/config/bge_open_set_neighbor_audit.json").read_text())["known_pair_audit"]
    by_id = {r["unit_id"]: i for i, r in enumerate(units)}
    known_rows, sweeps, candidates = [], [], []
    for budget in (5, 10, 20):
        e = aggregate(local_e, global_e, lexical, owner, article_ids, budget, 20)
        a = aggregate(local_a, global_a, lexical, owner, article_ids, budget, 20)
        for r in known:
            si, ti = by_id[r["source"]], by_id[r["target"]]
            sa, ta = owner[si], owner[ti]
            known_rows.append(dict(r, budget=budget, source_article=sa, target_article=ta,
                exact_candidate=ta in {x["target_article"] for x in e[sa]},
                ann_candidate=ta in {x["target_article"] for x in a[sa]},
                ann_evidence_top10=ti in {j for j, _ in local_a[si]},
                article_only_candidate=ta in {article_ids[j] for j, _ in global_a[article_ids.index(sa)][:budget]}))
        flat = [r for rows in a.values() for r in rows]
        unique = {tuple(sorted((r["source_article"], r["target_article"]))) for r in flat}
        sweeps.append({"budget_per_article": budget, "directed_candidates": len(flat),
            "unique_undirected_candidates": len(unique),
            "all_possible_undirected_pairs": len(article_ids) * (len(article_ids) - 1) // 2,
            "article_candidate_overlap_vs_exact": overlap(
                [[r["target_article"] for r in a[s]] for s in article_ids],
                [[r["target_article"] for r in e[s]] for s in article_ids])})
        for r in flat:
            r["budget"] = budget
            r["evidence"] = [{"source_unit": units[i]["unit_id"], "target_unit": units[j]["unit_id"],
                "cosine": score, "source_text": units[i]["text"][:800], "target_text": units[j]["text"][:800]}
                for i, j, score in r["evidence"]]
        candidates.extend(flat)

    # Route-union ablation avoids discarding single-route local relationships.
    # Fixed depths are reported together, not chosen using the provisional labels.
    union_sweep, union_candidates = [], []
    positive_articles = {(owner[by_id[r["source"]]], owner[by_id[r["target"]]])
                         for r in known if r["label"] == "likely_related"}
    for depth in (3, 5, 10, 20):
        union = aggregate(local_a, global_a, lexical, owner, article_ids, 3 * depth, depth)
        directed = {(s, r["target_article"]) for s, rows in union.items() for r in rows}
        undirected = {tuple(sorted(pair)) for pair in directed}
        union_sweep.append({"per_route_depth": depth, "max_candidates_per_article": 3 * depth,
            "directed_candidates": len(directed), "unique_undirected_candidates": len(undirected),
            "provisional_positive_article_pairs_retrieved": len(directed & positive_articles),
            "provisional_positive_article_pairs_total": len(positive_articles)})
        union_candidates.extend({"per_route_depth": depth, "source_article": s,
            "target_article": r["target_article"], "routes": r["routes"],
            "edge_status": r["edge_status"]} for s, rows in union.items() for r in rows)
    write_rows(args.output / "union_candidates.jsonl", union_candidates)
    # Recover reviewable evidence only inside the bounded union-3 article pairs.
    review_candidates = []
    for row in union_candidates:
        if row["per_route_depth"] != 3:
            continue
        si, ti = members[row["source_article"]], members[row["target_article"]]
        scores = vectors[si] @ vectors[ti].T
        top = np.argsort(-scores, axis=None)[:3]
        evidence = []
        for position in top:
            a, b = np.unravel_index(position, scores.shape)
            i, j = si[a], ti[b]
            evidence.append({"source_unit": units[i]["unit_id"], "target_unit": units[j]["unit_id"],
                "cosine": float(scores[a, b]), "source_text": units[i]["text"][:1600],
                "target_text": units[j]["text"][:1600]})
        review_candidates.append(dict(row, evidence=evidence))
    write_rows(args.output / "union3_review_candidates.jsonl", review_candidates)

    # Incremental insertion + persistence audit, using the last articles as arrivals.
    old_articles = set(article_ids[:int(len(article_ids) * .8)])
    order = [i for i, a in enumerate(owner) if a in old_articles] + [i for i, a in enumerate(owner) if a not in old_articles]
    nold = sum(a in old_articles for a in owner)
    inc, _ = index_for(vectors[order[:nold]], True)
    before = inc.ntotal
    start = time.perf_counter()
    inc.add(vectors[order[nold:]])
    insertion_seconds = time.perf_counter() - start
    inc_owner = [owner[i] for i in order]
    incremental_hits = search_filtered(inc, vectors, owner, inc_owner, 10)
    incremental_overlap = overlap([[order[j] for j, _ in row] for row in incremental_hits],
                                  [[j for j, _ in row] for row in local_e])
    faiss.write_index(inc, str(args.output / "incremental.hnsw"))
    reloaded = faiss.read_index(str(args.output / "incremental.hnsw"))
    restored = search_filtered(reloaded, vectors, owner, inc_owner, 10)
    if restored != incremental_hits:
        raise AssertionError("Index round-trip changed search results")
    write_rows(args.output / "incremental_index_units.jsonl", [{"unit_id": units[i]["unit_id"], "article_id": owner[i]} for i in order])

    # Cache retrieval candidates only; keys invalidate on data/policy changes.
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    policy = {"local_k": 10, "article_representation": "normalized mean of cached member vectors",
              "fusion": "RRF60", "per_route_article_limit": 20, "budgets": [5, 10, 20], "efSearch": 64,
              "route_union_ablation_depths": [3, 5, 10, 20],
              "same_article_excluded": True, "same_magazine_other_articles_allowed": True,
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    version = hashlib.sha256(json.dumps([hashes, policy], sort_keys=True).encode()).hexdigest()
    db = sqlite3.connect(args.output / "candidate_cache.sqlite")
    db.execute("CREATE TABLE IF NOT EXISTS candidates(version TEXT, source TEXT, target TEXT, budget INTEGER, payload TEXT, PRIMARY KEY(version,source,target,budget))")
    data = [(version, r["source_article"], r["target_article"], r["budget"], json.dumps(r)) for r in candidates]
    db.executemany("INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?)", data)
    db.commit()
    before_changes = db.total_changes
    db.executemany("INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,?)", data)
    db.commit()
    duplicate_inserts = db.total_changes - before_changes
    db.close()
    write_rows(args.output / "candidates.jsonl", candidates)
    write_rows(args.output / "known_pair_audit.jsonl", known_rows)

    real = {"units": len(units), "articles_or_papers": len(article_ids), "dimensions": vectors.shape[1],
            "unmapped_units": sum(a.startswith("UNMAPPED::") for a in owner),
            "local_top10_overlap_vs_exact": overlap([[j for j, _ in r] for r in local_a], [[j for j, _ in r] for r in local_e]),
            "hnsw_build_seconds": build_seconds, "candidate_sweep": sweeps, "route_union_sweep": union_sweep,
            "filtered_search_single_pass_seconds": {"exact": exact_filtered_seconds, "ann": ann_filtered_seconds},
            "hnsw_index_bytes": (args.output / "evidence.hnsw").stat().st_size,
            "incremental": {"old_units": before, "added_units": len(units) - before,
                "add_seconds": insertion_seconds, "top10_overlap_vs_exact": incremental_overlap,
                "index_roundtrip_identical": True, "duplicate_cache_inserts": duplicate_inserts},
            "known_label_warning": "7 provisional evidence-pair labels, not exhaustive gold; several collapse to the same article pair. Negative evidence pairs do not prove an entire article pair unrelated."}
    summary = {"production_modified": False, "real": real, "scaling": [], "policy": policy,
        "input_sha256": hashes, "cache_version": version,
        "environment": {"host": platform.node(), "slurm_job_id": os.getenv("SLURM_JOB_ID"),
                        "threads": args.threads, "faiss": faiss.__version__, "numpy": np.__version__},
        "limitations": ["CLAD/DLR are partial page pilots; article assignment and embeddings are reused unchanged.",
            "Article vectors are means, not newly encoded abstracts.", "No LLM semantic validation or production edges in this run.",
            "Synthetic scaling is an engineering test, not real-corpus semantic recall.",
            "Incremental audit tests append/reload/cache idempotency, not a production ingestion service or reverse-neighbor maintenance."]}
    write_json(args.output / "summary.json", summary)
    print(json.dumps({"real_complete": real}), flush=True)
    # Generate distinct clustered synthetic vectors, never label replicas as new papers.
    for size in args.sizes:
        rng = np.random.default_rng(20260916 + size)
        corpus = np.empty((size, vectors.shape[1]), dtype=np.float32)
        for start in range(0, size, 1024):
            count = min(1024, size - start)
            center = vectors[rng.integers(len(vectors), size=count)]
            noise = rng.standard_normal(center.shape, dtype=np.float32) * (.35 / np.sqrt(vectors.shape[1]))
            corpus[start:start + count] = normalize(center + noise)
        q = normalize(vectors[rng.integers(len(vectors), size=args.queries)] +
                      rng.standard_normal((args.queries, vectors.shape[1]), dtype=np.float32) * (.35 / np.sqrt(vectors.shape[1])))
        flat, flat_build = index_for(corpus, False)
        truth, flat_time = timed_search(flat, q, 10)
        hnsw, ann_build = index_for(corpus, True)
        for ef in (32, 64, 128):
            hnsw.hnsw.efSearch = ef
            hits, ann_time = timed_search(hnsw, q, 10)
            row = {"data_kind": "synthetic_clustered_vectors", "vectors": size, "queries": len(q),
                "efSearch": ef, "recall_at_10_vs_exact": overlap(hits.tolist(), truth.tolist()),
                "exact_batch_seconds": flat_time, "ann_batch_seconds": ann_time,
                "speedup": flat_time / ann_time, "ann_build_seconds": ann_build,
                "exact_build_seconds": flat_build, "vector_bytes": corpus.nbytes,
                "hnsw_serialized_bytes": int(faiss.serialize_index(hnsw).nbytes),
                "process_peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                "rss_scope": "cumulative process high-water mark including both indexes and input arrays"}
            summary["scaling"].append(row)
            print(json.dumps(row), flush=True)
        del flat, hnsw, corpus
        write_json(args.output / "summary.json", summary)
    rows = []
    for r in review_candidates:
        ev = "".join("<p>" + html.escape(e["source_text"]) + "</p><p>↔ " + html.escape(e["target_text"]) + "</p>" for e in r["evidence"][:2])
        rows.append(f'<details><summary>Union-3: {html.escape(r["source_article"])} → {html.escape(r["target_article"])} | {", ".join(r["routes"])}</summary>{ev}</details>')
    for r in candidates:
        if r["budget"] != 5:
            continue
        ev = "".join("<p>" + html.escape(e["source_text"]) + "</p><p>↔ " + html.escape(e["target_text"]) + "</p>" for e in r["evidence"][:2])
        rows.append(f'<details><summary>{html.escape(r["source_article"])} → {html.escape(r["target_article"])} | {", ".join(r["routes"])}</summary>{ev or "No local top-10 evidence; article/lexical candidate requires evidence retrieval."}</details>')
    (args.output / "report.html").write_text('<!doctype html><meta charset="utf-8"><title>ANN candidate audit</title><style>body{font:15px system-ui;max-width:1200px;margin:30px auto}pre{white-space:pre-wrap}details{padding:12px;border-bottom:1px solid #ddd}</style><h1>ANN candidate audit</h1><p>候选，不是已验证关系。合成规模测试不代表真实关系准确率。</p><pre>' + html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + '</pre><h2>Existing provisional labels</h2><pre>' + html.escape(json.dumps(known_rows, ensure_ascii=False, indent=2)) + '</pre><h2>Union-3 and RRF budget-5 candidates</h2>' + ''.join(rows))


if __name__ == "__main__":
    main()
