"""P0/P1: replay legacy QKV, then test one fixed extra-page utility slot.

This is deliberately an *incremental-page* diagnostic.  It does not rerank the
frozen Top-10 and it never uses Gold until page sets and decisions are written.
"""
from __future__ import annotations

import argparse, collections, hashlib, json, math, subprocess, time
from pathlib import Path

import numpy as np

from common import load_config, load_embeddings, read_jsonl, repo_path, run_dir, sha256_file, write_json, write_jsonl
from edge_representation_scoring import pair_aware_score, unit
from run_query_conditioned_edge_retrieval import BASELINE, evaluate, norm, page


def stable_rank(scores):
    return sorted(scores, key=lambda p: (-scores[p], p))


def at_k(ranking, gold, k=11):
    top = ranking[:k]; hits = len(set(top) & gold)
    dcg = sum(1 / math.log2(i + 2) for i, pid in enumerate(top) if pid in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(gold))))
    return {"page_recall_at_11": hits / len(gold), "gold_complete_at_11": float(hits == len(gold)), "ndcg_at_11": dcg / ideal if ideal else 0.0, "gold_hits_at_11": hits}


def macro(rows, key): return float(np.mean([r[key] for r in rows]))


def qkv_scores(query, source, target):
    """Fixed zero-training Q/K/V definitions from the previous probe."""
    root = np.sqrt
    residual = unit(query - source)
    midpoint = unit((source + target) / 2)
    difference = unit(target - source)
    qk_q = np.concatenate((root(.50) * query, root(.35) * residual, root(.15) * query))
    key = np.concatenate((root(.50) * target, root(.35) * difference, root(.15) * midpoint))
    qv_q = np.concatenate((root(.50) * query, root(.15) * residual, root(.35) * query))
    value = np.concatenate((target, midpoint, difference))
    return float(qk_q @ key), float(qv_q @ value)


def replay_legacy_value_aware(base, old_root, queries, gold, frozen):
    """Reconstruct old rankings from logits; deliberately ignore broken logged weights."""
    trace_path = old_root / "none/edge_attention_trace.jsonl"
    saved_path = old_root / "none/metrics.json"
    if not trace_path.is_file() or not saved_path.is_file():
        return {"status": "NOT_RUN", "reason": "legacy value-aware trace/metrics missing"}
    grouped = collections.defaultdict(list)
    for row in read_jsonl(trace_path):
        grouped[str(row["question_id"])].append(row)
    rankings = {}
    finite = True
    for q in queries:
        qid = str(q["question_id"]); mass = collections.defaultdict(float)
        for r in grouped[qid]:
            z, u = float(r["qk_logit"]), float(r["value_logit"])
            finite &= math.isfinite(z) and math.isfinite(u)
            mass[tuple(r["target_page"])] += math.exp(z) * (.5 + .5 * u)
        raw = frozen[qid]; lo, hi = min(raw.values()), max(raw.values()); span = hi - lo or 1.
        final = {pid: (score - lo) / span for pid, score in raw.items()}
        if mass:
            denom = max(mass.values())
            for pid, value in mass.items(): final[pid] += .25 * value / denom
        rankings[qid] = stable_rank(final)
    initial = {qid: stable_rank(scores) for qid, scores in frozen.items()}
    rebuilt = evaluate(queries, gold, rankings, initial)["macro_six_types"]
    saved = json.loads(saved_path.read_text())["macro_six_types"]
    keys = sorted(set(rebuilt) & set(saved)); max_error = max(abs(float(rebuilt[k]) - float(saved[k])) for k in keys)
    base_zero = all(stable_rank(scores) == initial[qid] for qid, scores in frozen.items())
    return {"status": "PASS" if finite and max_error <= 1e-12 and base_zero else "FAIL", "trace": str(trace_path), "finite_logits": finite, "reconstructed_from_logits_not_logged_attention": True, "metric_max_abs_error": max_error, "tolerance": 1e-12, "graph_weight_zero_recovers_frozen_baseline": base_zero, "rebuilt_macro": rebuilt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--output-dir", required=True, help="new directory; refusal to overwrite is intentional")
    ap.add_argument("--seed-pages", type=int, default=10)
    ap.add_argument("--prototype-context-weight", type=float, default=.10, help="recorded only; P1 core arms do not use prototype")
    ap.add_argument("--allow-cpu", action="store_true")
    args = ap.parse_args()
    if args.seed_pages != 10: raise ValueError("P1 protocol freezes 10 dense seed pages")
    output = Path(args.output_dir)
    if output.exists(): raise FileExistsError(f"refusing to overwrite existing run: {output}")
    output.mkdir(parents=True)
    cfg = load_config(args.config); stage = run_dir(cfg); base = repo_path(BASELINE)
    queries = list(read_jsonl(base / "pilot/queries.jsonl")); qids = [str(r["question_id"]) for r in queries]
    gold = collections.defaultdict(set)
    for r in read_jsonl(base / "pilot/gold_evidence.jsonl"): gold[str(r["question_id"])].add(page(r))
    frozen = collections.defaultdict(dict)
    for r in read_jsonl(base / "retrieval/hybrid_visual_scores.jsonl"): frozen[str(r["question_id"])][page(r)] = float(r["score"])
    node_page, page_nodes = {}, collections.defaultdict(list)
    for r in read_jsonl(base / "retrieval/node_pages.jsonl"):
        if len(r["source_pages"]) != 1: raise ValueError("ambiguous node/page map")
        node_page[r["node_id"]] = page(r["source_pages"][0]); page_nodes[node_page[r["node_id"]]].append(r["node_id"])
    vectors, ids = load_embeddings(cfg); vectors = np.asarray([norm(x) for x in np.asarray(vectors, dtype=np.float32)])
    index = {node: i for i, node in enumerate(ids)}
    if len(index) != len(ids) or not set(ids) <= set(node_page): raise ValueError("embedding IDs must be unique and canonically map to frozen Pilot pages")
    unmapped_frozen_nodes = sorted(set(node_page) - set(ids))
    qcache = stage / "qkv_attention_probe/query_vectors_qwen3_0_6b.npy"
    if not qcache.is_file(): raise FileNotFoundError(f"required cached query vectors absent: {qcache}")
    query = np.load(qcache); 
    if query.shape != (len(queries), vectors.shape[1]) or not np.isfinite(query).all(): raise ValueError("query cache shape/nonfinite mismatch")
    query = np.asarray([norm(x) for x in query], dtype=np.float32)
    initial = {qid: stable_rank(frozen[qid]) for qid in qids}
    seeds = {}; d_reps = {}; seed_pages_by_q = {}
    for qi, qid in enumerate(qids):
        ranked = initial[qid]
        if len(ranked) < 11: raise ValueError("baseline has fewer than 11 pages")
        seed_pages_by_q[qid] = set(ranked[:10]); picked = []
        for pid in ranked[:10]:
            choices = [n for n in page_nodes[pid] if n in index]
            if not choices: raise ValueError(f"seed page unscorable: {qid} {pid}")
            picked.append(max(choices, key=lambda n: (float(query[qi] @ vectors[index[n]]), n)))
        seeds[qid] = picked
        d = ranked[10]; choices = [n for n in page_nodes[d] if n in index]
        d_reps[qid] = (d, max(choices, key=lambda n: (float(query[qi] @ vectors[index[n]]), n)) if choices else None)
    all_seeds = set().union(*map(set, seeds.values())); adjacency = collections.defaultdict(set); scanned = 0
    for r in read_jsonl(repo_path(cfg["candidate_union_path"])):
        left, right = r["source_id"], r["target_id"]; scanned += 1
        if left in all_seeds and right in index: adjacency[left].add(right)
        if right in all_seeds and left in index: adjacency[right].add(left)
    # Freeze one representative (page, target, source) route before arm scoring.
    reps, route_rows = {}, []
    for qi, qid in enumerate(qids):
        by_target = collections.defaultdict(set)
        for source in seeds[qid]:
            for target in adjacency[source]:
                pid = node_page[target]
                if pid not in seed_pages_by_q[qid] and pid != d_reps[qid][0]: by_target[target].add(source)
        by_page = collections.defaultdict(list)
        for target, sources in by_target.items(): by_page[node_page[target]].append((target, sources))
        for pid, choices in by_page.items():
            target, sources = max(choices, key=lambda x: (float(query[qi] @ vectors[index[x[0]]]), x[0]))
            source = max(sources, key=lambda n: (float(query[qi] @ vectors[index[n]]), n))
            reps[(qid, pid)] = (source, target)
            route_rows.append({"question_id": qid, "page": list(pid), "source_node_id": source, "target_node_id": target, "route_kind": "graph_representative", "target_q_cosine": float(query[qi] @ vectors[index[target]]), "linked_seed_count": len(sources)})
        d, dn = d_reps[qid]
        route_rows.append({"question_id": qid, "page": list(d), "source_node_id": None, "target_node_id": dn, "route_kind": "dense_replacement_representative", "target_q_cosine": None if dn is None else float(query[qi] @ vectors[index[dn]])})
    write_jsonl(output / "page_representatives.jsonl", route_rows)
    arms = ("R0_dense_next", "R1_target_only", "R2_pair", "R3_QK", "R3_QKV")
    decisions = []; score_rows = []; page_sets = []; metric_rows = []; arm_data = {a: [] for a in arms}
    started = time.perf_counter(); value_ranges = []
    for qi, qid in enumerate(qids):
        d, dn = d_reps[qid]; s10 = initial[qid][:10]
        candidates = sorted(pid for (q, pid) in reps if q == qid)
        route_score = {a: [] for a in arms}
        if dn is not None:
            for pid in candidates:
                source_id, target_id = reps[(qid, pid)]; source, target, dense_target = vectors[index[source_id]], vectors[index[target_id]], vectors[index[dn]]
                target_score = lambda t: float(query[qi] @ t)
                pair_score = lambda t: pair_aware_score(query[qi], source, t)[0]
                z, u = qkv_scores(query[qi], source, target); zd, ud = qkv_scores(query[qi], source, dense_target); value_ranges += [u, ud]
                values = {"R1_target_only": (target_score(target), target_score(dense_target)), "R2_pair": (pair_score(target), pair_score(dense_target)), "R3_QK": (math.exp(z) / 2, math.exp(zd) / 2), "R3_QKV": (math.exp(z) * (1 + u) / 2, math.exp(zd) * (1 + ud) / 2)}
                for arm, (candidate_score, dense_score) in values.items():
                    route_score[arm].append((candidate_score - dense_score, pid, source_id, target_id, candidate_score, dense_score, z, u, zd, ud))
        for arm in arms:
            if arm == "R0_dense_next":
                picked, reason, selected = d, "DENSE_NEXT", None
            elif dn is None:
                picked, reason, selected = d, "REFERENCE_UNSCORABLE", None
            else:
                options = route_score[arm]
                best = max(options, default=None, key=lambda x: (x[0], tuple(-ord(c) for c in "".join(x[1]))))
                if best is None or best[0] <= 0:
                    picked, reason, selected = d, "KEEP_DENSE_NONPOSITIVE_MARGIN", best
                else:
                    picked, reason, selected = best[1], "GRAPH_REPLACEMENT", best
            final = s10 + [picked]
            if len(set(final)) != 11: raise AssertionError("slot decision failed page uniqueness")
            met = at_k(final, gold[qid]); arm_data[arm].append(met)
            seed_complete = set(s10) >= gold[qid]
            metric_rows.append({"question_id": qid, "arm": arm, **met, "seed_top10_already_complete": seed_complete, "slot_page": list(picked), "dense_replacement_page": list(d), "slot_is_gold": picked in gold[qid], "dense_slot_is_gold": d in gold[qid]})
            decisions.append({"question_id": qid, "arm": arm, "action": reason, "selected_page": list(picked), "dense_replacement_page": list(d), "selected_route": None if selected is None else {"source_node_id": selected[2], "target_node_id": selected[3], "margin": selected[0]}})
            page_sets.append({"question_id": qid, "arm": arm, "pages": [list(x) for x in final], "dense_top10": [list(x) for x in s10], "slot_page": list(picked)})
        for arm in ("R1_target_only", "R2_pair", "R3_QK", "R3_QKV"):
            for margin,pid,src,tgt,fs,fd,z,u,zd,ud in route_score[arm]:
                score_rows.append({"question_id": qid, "arm": arm, "candidate_page": list(pid), "source_node_id": src, "target_node_id": tgt, "candidate_score": fs, "dense_counterfactual_score": fd, "margin": margin, "qk_logit": z, "value_logit": u, "dense_qk_logit": zd, "dense_value_logit": ud})
    write_jsonl(output / "route_scores.jsonl", score_rows); write_jsonl(output / "decisions.jsonl", decisions); write_jsonl(output / "page_sets.jsonl", page_sets); write_jsonl(output / "per_query_metrics.jsonl", metric_rows)
    summary = {"queries": len(qids), "page_budget": 11, "fixed_dense_seed_pages": 10, "candidate_pairs_scanned": scanned, "representative_routes": len(reps), "value_logit_range": [min(value_ranges), max(value_ranges)] if value_ranges else None, "arms": {}}
    r0 = {r["question_id"]: r for r in metric_rows if r["arm"] == "R0_dense_next"}
    for arm in arms:
        rows = arm_data[arm]; decisions_arm = [r for r in decisions if r["arm"] == arm]
        gains = losses = 0
        for r in metric_rows:
            if r["arm"] != arm: continue
            base_row = r0[r["question_id"]]
            gains += int(r["slot_is_gold"] and not base_row["slot_is_gold"]); losses += int(base_row["slot_is_gold"] and not r["slot_is_gold"])
        group = {}
        for label, complete in (("seed_top10_complete", True), ("seed_top10_incomplete", False)):
            group_rows = [r for r in metric_rows if r["arm"] == arm and r["seed_top10_already_complete"] == complete]
            group[label] = {"queries": len(group_rows), "page_recall_at_11": macro(group_rows, "page_recall_at_11") if group_rows else None, "gold_complete_at_11": macro(group_rows, "gold_complete_at_11") if group_rows else None}
        summary["arms"][arm] = {"page_recall_at_11": macro(rows, "page_recall_at_11"), "gold_complete_at_11": macro(rows, "gold_complete_at_11"), "ndcg_at_11": macro(rows, "ndcg_at_11"), "gold_gains_vs_R0_occurrences": gains, "gold_losses_vs_R0_occurrences": losses, "net_gold_change_vs_R0_occurrences": gains-losses, "keep_dense_rate": sum(d["action"].startswith("KEEP") or d["action"] == "DENSE_NEXT" for d in decisions_arm)/len(decisions_arm), "graph_replacement_queries": sum(d["action"] == "GRAPH_REPLACEMENT" for d in decisions_arm), "candidate_routes_scored": len([r for r in score_rows if r["arm"] == arm]), "posthoc_seed_coverage_groups": group}
    write_json(output / "summary.json", summary)
    replay = replay_legacy_value_aware(base, stage / "qkv_attention_probe_value_aware", queries, gold, frozen)
    check = {"P0_legacy_value_aware_replay": replay, "P1_duplicate_route_dedup": "PASS: adjacency uses sets; one representative per (query,page)", "P1_all_final_sets_have_11_unique_pages": "PASS", "P1_v_zero_wiring": "PASS by formula: exp(z)*(1+0)/2 == exp(z)/2", "P1_context_weight_zero_identity": "PASS by construction: context is only an additive term multiplied by context_weight; P1 core arms use no context", "P1_no_candidate_or_nonpositive_margin": "PASS by explicit KEEP_DENSE branch", "source_or_target_nonfinite": "PASS" if all(math.isfinite(r["candidate_score"]) and math.isfinite(r["dense_counterfactual_score"]) for r in score_rows) else "FAIL"}
    write_json(output / "mechanism_checks.json", check)
    (output / "REPLAY_VALIDATION.md").write_text("# P0 replay validation\n\n```json\n" + json.dumps(replay, indent=2) + "\n```\n\nLegacy attention weights were not trusted; rankings were reconstructed from saved QK/V logits.\n")
    (output / "MECHANISM_CHECKS.md").write_text("# P1 mechanism checks\n\n```json\n" + json.dumps(check, indent=2) + "\n```\n")
    lines = ["# Edge utility slot P1 results", "", "This is a fixed 11-page set diagnostic; it does **not** measure Top-5 improvement.", "", "| Arm | Recall@11 | RecallAll@11 | nDCG@11 | gain | loss | net | keep | replacements |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for arm, x in summary["arms"].items(): lines.append(f"| {arm} | {x['page_recall_at_11']:.4f} | {x['gold_complete_at_11']:.4f} | {x['ndcg_at_11']:.4f} | {x['gold_gains_vs_R0_occurrences']} | {x['gold_losses_vs_R0_occurrences']} | {x['net_gold_change_vs_R0_occurrences']} | {x['keep_dense_rate']:.4f} | {x['graph_replacement_queries']} |")
    lines += ["", f"Representative routes: {len(reps)}; actual route scores: {len(score_rows)}; elapsed seconds: {time.perf_counter()-started:.3f}.", "", "R3-QKV minus R3-QK is the only V-specific comparison. R2 minus R1 is the pair-specific comparison. No Gold was used before these outputs were frozen."]
    (output / "RESULTS.md").write_text("\n".join(lines) + "\n")
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_path("."), capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(["git", "status", "--short"], cwd=repo_path("."), capture_output=True, text=True, check=True).stdout.splitlines()
    manifest = {"run_kind": "P0 replay + P1 fixed extra page utility", "git_head": git, "git_status_at_end": status, "source_sha256": sha256_file(Path(__file__)), "config": str(args.config), "input_hashes": {"embedding": sha256_file(repo_path(cfg["embedding_path"])), "embedding_ids": sha256_file(repo_path(cfg["embedding_ids_path"])), "candidate_union": sha256_file(repo_path(cfg["candidate_union_path"])), "query_vectors": sha256_file(qcache)}, "query_ids_in_order": qids, "counts": {"queries": len(qids), "pages_per_baseline_query": len(initial[qids[0]]), "nodes_with_embeddings": len(ids), "frozen_nodes_without_embeddings": len(unmapped_frozen_nodes), "frozen_nodes_without_embeddings_ids": unmapped_frozen_nodes, "candidate_pairs": scanned, "seed_occurrences": sum(map(len, seeds.values()))}, "parameters": {"seed_pages": 10, "page_budget": 11, "tie_break": "page ID; representative node ID", "normalization_scope": "none: per-route margins; no cross-edge softmax", "prototype": "not used in P1 core arms", "gold_access": "post-hoc evaluation only"}}
    write_json(output / "input_manifest.json", manifest); write_json(output / "protocol.json", {"arms": list(arms), "R0": "always baseline rank 11", "R1": "q dot target margin versus same-source dense target", "R2": "fixed pair_aware_score margin", "R3_QK": "exp(qk_logit)/2 margin", "R3_QKV": "exp(qk_logit)*(1+value_logit)/2 margin", "action": "replace only if maximum candidate margin > 0; otherwise KEEP_DENSE"})
    print(output)

if __name__ == "__main__": main()
