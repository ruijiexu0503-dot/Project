"""One-hop Pilot graph retrieval using frozen seeds and full static candidates.

The graph is query-independent.  Queries are used only online to select seed
nodes and score already-existing directed candidate traversals.  Evaluation is
performed after rankings are written.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import time

import numpy as np

from common import load_config, load_embeddings, read_jsonl, repo_path, run_dir, sha256_file, stable_edge_id, stable_pair_id, write_json, write_jsonl
from edge_representation_scoring import pair_aware_score, prototype_context_score

BASELINE = "EvidenceNet/output/baselines/vldocir_no_edge_v1_20261011"
MODEL = "EvidenceNet/models/Qwen3-Embedding-0.6B"


def page(row): return str(row["document_id"]), str(row["page_number"])
def norm(v):
    n = np.linalg.norm(v)
    return v / n if n else np.zeros_like(v)
def q_input(question): return "Instruct: Retrieve document pages containing evidence to answer the question.\nQuery: " + question


def query_vectors(queries, output, allow_cpu):
    path = output / "query_vectors_qwen3_0_6b.npy"
    if path.is_file():
        values = np.load(path)
        if values.shape == (len(queries), 1024) and np.isfinite(values).all(): return values
        raise ValueError("stale/incompatible cached query vectors")
    import torch
    if not torch.cuda.is_available() and not allow_cpu:
        raise RuntimeError("no CUDA allocation: rerun explicitly with --allow-cpu for this 24-query bounded encoding")
    from transformers import AutoModel, AutoTokenizer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(repo_path(MODEL), local_files_only=True, padding_side="left")
    model = AutoModel.from_pretrained(repo_path(MODEL), local_files_only=True, torch_dtype=torch.bfloat16 if device == "cuda" else torch.float32).to(device).eval()
    sequences = [tokenizer.encode(q_input(row["question"]), add_special_tokens=True) for row in queries]
    if any(len(seq) > 512 for seq in sequences): raise ValueError("query exceeds 512-token Qwen encoder budget")
    result = []
    with torch.inference_mode():
        for start in range(0, len(sequences), 8):
            batch = tokenizer.pad({"input_ids": sequences[start:start + 8]}, padding=True, return_tensors="pt").to(device)
            result.append(torch.nn.functional.normalize(model(**batch).last_hidden_state[:, -1].float(), p=2, dim=1).cpu().numpy())
    values = np.concatenate(result).astype(np.float32)
    np.save(path, values)
    write_json(output / "query_embedding_manifest.json", {"encoder_id": "Qwen3-Embedding-0.6B", "queries": len(queries), "shape": list(values.shape), "device": device, "input": "retrieve_vldocir.query_model_input compatible instruction", "sha256": sha256_file(path)})
    return values


def metrics(ranked, gold, k):
    top = ranked[:k]; hits = len(set(top) & gold)
    dcg = sum(1 / math.log2(i + 2) for i, p in enumerate(top) if p in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
    ndcg = dcg / ideal
    return {f"Recall@{k}": hits / len(gold), f"nDCG@{k}": ndcg, f"RecallAll@{k}": float(hits == len(gold)), f"nDCGAll@{k}": float(hits == len(gold)) * ndcg}


def evaluate(queries, gold, rankings, initial):
    per, by_type = {}, collections.defaultdict(list)
    for row in queries:
        qid, rank = str(row["question_id"]), rankings[str(row["question_id"])]
        values = {}
        for k in (3, 5, 10):
            values.update(metrics(rank, gold[qid], k))
            values[f"NewGoldPagesRecovered@{k}"] = len((set(rank[:k]) - set(initial[qid][:k])) & gold[qid])
        per[qid] = values; by_type[row["question_type"]].append(values)
    def average(items): return {key: sum(x[key] for x in items) / len(items) for key in items[0]}
    grouped = {kind: average(items) for kind, items in by_type.items()}
    return {"queries": len(queries), "per_query": per, "by_question_type": grouped, "macro_six_types": average(list(grouped.values())), "page_aggregation": "max directed-edge score per non-seed target page; final=frozen_base_minmax+0.25*graph_score", "tie_break": "page ID"}


def pair_score(query, source, target, arm, edge_vector=None, prototype=None, prototype_weight=0.1):
    target_score = (float(query @ target) + 1.0) / 2.0
    if arm == "target_only": return target_score, {"target_cosine": float(query @ target)}
    if prototype is not None: return prototype_context_score(query, source, target, prototype, prototype_weight)
    return pair_aware_score(query, source, target, edge_vector)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--seed-pages", type=int, default=10)
    parser.add_argument("--graph-weight", type=float, default=0.25)
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--edge-representation", choices=("original_midDiff", "cluster_prototype_context", "hard_prototype_updated", "soft_prototype_updated", "random_prototype_updated"), default="original_midDiff")
    parser.add_argument("--prototype-alpha", type=float, choices=(0.1, 0.3), default=0.1)
    parser.add_argument("--prototype-context-weight", type=float, default=0.10)
    parser.add_argument("--protected-baseline-topk", type=int, default=0, help="Freeze the original top-k pages before graph reranking; diagnostic safety control.")
    parser.add_argument("--output-subdir", default="query_conditioned_retrieval")
    args = parser.parse_args()
    if not 0 <= args.graph_weight <= 1 or not 0 <= args.prototype_context_weight <= 1: raise ValueError("weights must be in [0,1]")
    config, out = load_config(args.config), run_dir(load_config(args.config))
    if args.protected_baseline_topk < 0: raise ValueError("protected-baseline-topk must be nonnegative")
    result_dir = out / args.output_subdir; result_dir.mkdir(parents=True, exist_ok=True)
    base = repo_path(BASELINE)
    queries = list(read_jsonl(base / "pilot/queries.jsonl")); qids = [str(q["question_id"]) for q in queries]
    gold = collections.defaultdict(set)
    for row in read_jsonl(base / "pilot/gold_evidence.jsonl"): gold[str(row["question_id"])].add(page(row))
    frozen = collections.defaultdict(dict)
    for row in read_jsonl(base / "retrieval/hybrid_visual_scores.jsonl"):
        frozen[str(row["question_id"])][page(row)] = float(row["score"])
    node_pages, page_nodes = {}, collections.defaultdict(list)
    for row in read_jsonl(base / "retrieval/node_pages.jsonl"):
        if len(row["source_pages"]) != 1: raise ValueError("Pilot graph retrieval requires unambiguous one-page nodes")
        node_pages[row["node_id"]] = page(row["source_pages"][0]); page_nodes[node_pages[row["node_id"]]].append(row["node_id"])
    vectors, ids = load_embeddings(config); vectors = np.asarray(vectors, dtype=np.float32); vectors = np.asarray([norm(v) for v in vectors])
    index = {node: i for i, node in enumerate(ids)}
    if set(ids) != set(index) or not set(ids) <= set(node_pages): raise ValueError("embedding IDs do not exactly map to frozen Pilot pages")
    query = query_vectors(queries, result_dir, args.allow_cpu)
    update_vectors, centers = {}, None
    if args.edge_representation == "cluster_prototype_context":
        centers = np.asarray(np.load(out / "clustering/middiff_k32_seed17/centroids.npy"), dtype=np.float32)
        centers = np.asarray([norm(v) for v in centers])
    elif args.edge_representation != "original_midDiff":
        method = args.edge_representation.removesuffix("_prototype_updated")
        update_root = out / "prototype_updates" / "middiff_k32_seed17_t0.1"
        update_matrix = np.load(update_root / f"{method}_alpha{args.prototype_alpha:g}.npy", mmap_mode="r")
        sample_meta = list(read_jsonl(out / "edge_metadata.jsonl"))
        if len(update_matrix) != len(sample_meta): raise ValueError("prototype update / edge metadata mismatch")
        update_vectors = {row["edge_id"]: np.asarray(update_matrix[i], dtype=np.float32) for i, row in enumerate(sample_meta)}
    initial, seed_nodes = {}, {}
    for qi, qid in enumerate(qids):
        ranked = sorted(frozen[qid], key=lambda p: (-frozen[qid][p], p))
        initial[qid] = ranked
        seeds = []
        for pid in ranked[:args.seed_pages]:
            candidates = [node for node in page_nodes[pid] if node in index]
            if not candidates: continue
            seeds.append(max(candidates, key=lambda node: (float(query[qi] @ vectors[index[node]]), node)))
        seed_nodes[qid] = seeds
    all_seeds = set().union(*map(set, seed_nodes.values()))
    adjacency = collections.defaultdict(list); pairs_scanned = 0
    for row in read_jsonl(repo_path(config["candidate_union_path"])):
        left, right = row["source_id"], row["target_id"]; pairs_scanned += 1
        if left in all_seeds and right in index: adjacency[left].append(right)
        if right in all_seeds and left in index: adjacency[right].append(left)
    outputs, costs, source_replacement = {}, {}, []
    for arm in ("target_only", "pair_aware"):
        started = time.perf_counter(); rankings, trace, ranking_rows = {}, [], []
        edge_count = target_count = 0; cluster_usage = collections.Counter()
        for qi, qid in enumerate(qids):
            seed_pages = {node_pages[n] for n in seed_nodes[qid]}; candidate_pages = {}
            alternatives = seed_nodes[qid]
            for source_id in seed_nodes[qid]:
                source = vectors[index[source_id]]
                for target_id in adjacency[source_id]:
                    target_page = node_pages[target_id]
                    if target_page in seed_pages: continue  # preserve original retrieval; do not count repeats as expansion
                    edge_vector = prototype = None
                    if arm == "pair_aware" and centers is not None:
                        raw_edge = np.concatenate(((source + vectors[index[target_id]]) / 2.0, vectors[index[target_id]] - source))
                        cluster_id = int(np.argmax(norm(raw_edge) @ centers.T)); prototype = centers[cluster_id]; cluster_usage[cluster_id] += 1
                    if arm == "pair_aware" and update_vectors:
                        pair_id = stable_pair_id(source_id, target_id, config["node_id_namespace"])
                        edge_id = stable_edge_id(pair_id, source_id, target_id)
                        edge_vector = update_vectors.get(edge_id)
                        if edge_vector is None:
                            raise ValueError("prototype update has incomplete full-candidate coverage; refusing mixed updated/original pair scoring")
                    score, features = pair_score(query[qi], source, vectors[index[target_id]], arm, edge_vector, prototype, args.prototype_context_weight)
                    if prototype is not None: features["prototype_cluster"] = cluster_id
                    edge_count += 1
                    if target_page not in candidate_pages or score > candidate_pages[target_page][0]: candidate_pages[target_page] = (score, source_id, target_id, features)
                    if arm == "pair_aware" and len(alternatives) > 1:
                        replacement_id = next(x for x in alternatives if x != source_id)
                        replacement_edge = replacement_prototype = None
                        if update_vectors:
                            replacement_pair = stable_pair_id(replacement_id, target_id, config["node_id_namespace"])
                            replacement_edge = update_vectors.get(stable_edge_id(replacement_pair, replacement_id, target_id))
                            if replacement_edge is None:
                                raise ValueError("prototype update lacks replacement-edge coverage; source replacement test cannot mix representations")
                        if centers is not None:
                            replacement_raw = np.concatenate(((vectors[index[replacement_id]] + vectors[index[target_id]]) / 2.0, vectors[index[target_id]] - vectors[index[replacement_id]]))
                            replacement_prototype = centers[int(np.argmax(norm(replacement_raw) @ centers.T))]
                        replaced, _ = pair_score(query[qi], vectors[index[replacement_id]], vectors[index[target_id]], arm, replacement_edge, replacement_prototype, args.prototype_context_weight)
                        source_replacement.append(abs(score - replaced))
            target_count += len(candidate_pages)
            raw = frozen[qid]; low, high = min(raw.values()), max(raw.values()); span = high - low or 1.0
            final = {pid: (value - low) / span for pid, value in raw.items()}
            for pid, (score, _, _, _) in candidate_pages.items(): final[pid] += args.graph_weight * score
            graph_ranked = sorted(final, key=lambda pid: (-final[pid], pid))
            protected = initial[qid][:args.protected_baseline_topk]
            rankings[qid] = protected + [pid for pid in graph_ranked if pid not in set(protected)]
            ranking_rows.extend({"question_id": qid, "arm": arm, "rank": rank, "document_id": pid[0], "page_number": pid[1], "final_score": float(final[pid]), "frozen_score": float((raw[pid] - low) / span), "graph_score": float(candidate_pages[pid][0]) if pid in candidate_pages else None} for rank, pid in enumerate(rankings[qid], 1))
            trace.extend({"question_id": qid, "arm": arm, "source_node_id": src, "target_node_id": tgt, "target_page": list(pid), "edge_score": score, "features": feat} for pid, (score, src, tgt, feat) in candidate_pages.items())
        outputs[arm] = evaluate(queries, gold, rankings, initial)
        outputs[arm]["cost"] = {"candidate_pairs_scanned_once": pairs_scanned, "actual_directed_edges_scored": edge_count, "unique_non_seed_target_pages_scored": target_count, "elapsed_seconds": time.perf_counter() - started, "seed_pages_per_query": args.seed_pages, "seed_nodes_total": sum(map(len, seed_nodes.values())), "hop_limit": 1, "prototype_cluster_usage": dict(cluster_usage) if arm == "pair_aware" and centers is not None else None}
        write_jsonl(result_dir / f"{arm}_edge_trace.jsonl", trace)
        write_jsonl(result_dir / f"{arm}_page_rankings.jsonl", ranking_rows)
        write_json(result_dir / f"{arm}_metrics.json", outputs[arm])
    outputs["pair_aware"]["source_replacement_test"] = {"edges_tested": len(source_replacement), "mean_absolute_score_change": float(np.mean(source_replacement)) if source_replacement else None, "fraction_changed": float(np.mean(np.asarray(source_replacement) > 1e-7)) if source_replacement else None, "interpretation": "Nonzero changes show the scorer is source-conditioned; this is not a relation-quality metric."}
    write_json(result_dir / "pair_aware_metrics.json", outputs["pair_aware"])
    write_json(result_dir / "retrieval_manifest.json", {"candidate_graph": config["candidate_union_path"], "candidate_pairs": pairs_scanned, "node_vector_encoder": config["encoder_id"], "query_encoder": "Qwen3-Embedding-0.6B", "query_space_compatible": True, "edge_representation": args.edge_representation, "prototype_context_weight": args.prototype_context_weight if centers is not None else None, "arms": ["target_only", "pair_aware"], "score_formulas": {"target_only": "(cos(q,h_t)+1)/2", "pair_aware": "0.50*target + 0.35*(cos(norm(q-h_s), directed_channel)+1)/2 + 0.15*(cos(q, shared_channel)+1)/2; D mixes 0.90*C + 0.10*prototype_context"}, "graph_weight": args.graph_weight, "protected_baseline_topk": args.protected_baseline_topk, "query_or_gold_used_for_static_graph": False, "gold_used_only_in": "post-hoc evaluation"})
    print(result_dir)


if __name__ == "__main__": main()
