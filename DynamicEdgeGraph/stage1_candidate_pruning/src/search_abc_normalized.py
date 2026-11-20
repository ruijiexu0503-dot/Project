"""Reproducible CPU search for score-normalized A OR B OR C pruning.

The candidate universe is deliberately bounded: the union of the five effective
Top-100 routes.  Four dense scores are available for every member because Job
126094 cross-scored that bounded union.  BM25 is only observed for pairs returned
by BM25; a missing BM25 score is NaN/``bm25_observed=0``, never zero.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

from .common import read_jsonl

DENSE = ("qwen3_0_6b_dense", "gte_qwen2_1_5b_dense", "mxbai_dense", "gte_large_dense")
TAIL_TARGETS = (0.001, 0.0025, 0.005, 0.01, 0.02)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def ecdf_midrank(values: np.ndarray) -> tuple[np.ndarray, dict]:
    """Tie-aware ECDF F(x-) + .5 P(X=x), without arbitrary tie breaking."""
    n = len(values)
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    starts = np.r_[True, sorted_values[1:] != sorted_values[:-1]]
    start_i = np.flatnonzero(starts)
    end_i = np.r_[start_i[1:], n]
    mid = ((start_i + (end_i - start_i) / 2.0) / n).astype(np.float32)
    ranked_sorted = np.repeat(mid, end_i - start_i)
    result = np.empty(n, dtype=np.float32); result[order] = ranked_sorted
    largest_tie = int(np.max(end_i - start_i))
    return result, {"n": n, "unique_scores": int(len(start_i)), "largest_tie": largest_tie,
                    "largest_tie_fraction": largest_tie / n}


def robust_z(values: np.ndarray) -> tuple[np.ndarray, dict]:
    med = float(np.median(values)); q25, q75 = (float(x) for x in np.quantile(values, [0.25, 0.75]))
    iqr = q75 - q25
    scale = iqr / 1.349
    if scale <= 0:
        raise RuntimeError("non-positive robust scale")
    unclipped = (values - med) / scale
    clipped = np.clip(unclipped, -6.0, 6.0).astype(np.float32)
    return clipped, {"median": med, "q25": q25, "q75": q75, "iqr": iqr, "scale_iqr_over_1_349": scale,
                     "clipped_low": int(np.count_nonzero(unclipped < -6)), "clipped_high": int(np.count_nonzero(unclipped > 6))}


class DSU:
    def __init__(self, n: int): self.parent = np.arange(n); self.size = np.ones(n, dtype=np.int32)
    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]; x = int(self.parent[x])
        return x
    def union(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a != b:
            if self.size[a] < self.size[b]: a, b = b, a
            self.parent[b] = a; self.size[a] += self.size[b]


def choose_threshold(values: np.ndarray, tail_fraction: float) -> float:
    # Values already use tie-aware ECDF for that method.  This is an automatically
    # generated search grid expressed as target tail mass, not a hard-coded P95/P99.
    return float(np.quantile(values, 1.0 - tail_fraction))


def graph_components(left: np.ndarray, right: np.ndarray, node_count: int) -> dict:
    dsu = DSU(node_count)
    for a, b in zip(left, right): dsu.union(int(a), int(b))
    active = np.unique(np.concatenate([left, right]))
    roots = {dsu.find(int(x)) for x in active}
    largest = max((int(dsu.size[root]) for root in roots), default=0)
    return {"connected_components_active": len(roots), "largest_component_nodes": largest,
            "largest_component_active_coverage": largest / len(active) if len(active) else 0.0}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cross", type=Path, required=True)
    p.add_argument("--views", type=Path, required=True)
    p.add_argument("--nodes", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--original-six-union", type=int, default=34558320)
    args = p.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    pairs = np.load(args.cross / "effective_union_pairs.npy", mmap_mode="r")
    raw = np.load(args.cross / "dense_cross_scores.npy", mmap_mode="r")
    evidence = np.load(args.cross / "effective_union_evidence.npy", mmap_mode="r")
    manifest = json.loads((args.cross / "cross_score_manifest.json").read_text())
    n = len(pairs)
    if raw.shape != (n, 4): raise RuntimeError(f"unexpected score shape {raw.shape}")
    if len(evidence) != n: raise RuntimeError("evidence alignment failure")

    views = list(read_jsonl(args.views)); nodes = {x["id"]: x for x in read_jsonl(args.nodes)}
    if len(views) != 104318: raise RuntimeError(f"unexpected eligible-view count {len(views)}")
    docs = np.asarray([nodes[v["node_id"]]["document_id"] for v in views], dtype=object)
    types = np.asarray([nodes[v["node_id"]].get("node_type", "OTHER") for v in views], dtype=object)
    sources = np.asarray([nodes[v["node_id"]].get("data_source", "unknown") for v in views], dtype=object)
    left = (pairs >> np.uint64(32)).astype(np.int32); right = (pairs & np.uint64(0xffffffff)).astype(np.int32)
    assert int(left.max()) < len(views) and int(right.max()) < len(views)

    # Fixed reference distributions: the complete five-effective-route Top-100
    # union. This is selection-biased relative to all O(N^2) pairs, but identical
    # for every policy in this search and therefore documented rather than hidden.
    dense_ecdf = np.empty_like(raw, dtype=np.float32); dense_z = np.empty_like(raw, dtype=np.float32)
    normalization_rows, normalization_meta = [], {"reference_universe": "all 24,177,794 pairs in the effective five-route Top-100 union"}
    for ri, route in enumerate(DENSE):
        dense_ecdf[:, ri], e_meta = ecdf_midrank(np.asarray(raw[:, ri]))
        dense_z[:, ri], z_meta = robust_z(np.asarray(raw[:, ri]))
        normalization_rows.append({"route": route, "score_coverage": n, "score_observed_fraction": 1.0, **e_meta, **z_meta})
    bm25_observed = evidence["bm25_present"].astype(bool)
    bm25_ecdf = np.full(n, np.nan, dtype=np.float32); bm25_z = np.full(n, np.nan, dtype=np.float32)
    bscore = np.asarray(evidence["bm25_score"])
    bm_ecdf_values, e_meta = ecdf_midrank(bscore[bm25_observed]); bm_z_values, z_meta = robust_z(bscore[bm25_observed])
    bm25_ecdf[bm25_observed] = bm_ecdf_values; bm25_z[bm25_observed] = bm_z_values
    normalization_rows.append({"route": "bm25", "score_coverage": int(bm25_observed.sum()), "score_observed_fraction": float(bm25_observed.mean()), **e_meta, **z_meta})
    write_csv(args.out / "normalization_reference.csv", normalization_rows)

    # Aggregates intentionally keep the four full-coverage Dense signals separate
    # from partially observed lexical evidence. `available_mean` uses BM25 only when
    # that original lexical score exists; it never substitutes 0 for non-retrieval.
    e_mean4 = dense_ecdf.mean(axis=1)
    e_second = np.partition(dense_ecdf, -2, axis=1)[:, -2]
    e_available = (dense_ecdf.sum(axis=1) + np.nan_to_num(bm25_ecdf, nan=0.0)) / (4 + bm25_observed.astype(np.int8))
    z_mean4 = dense_z.mean(axis=1)
    aggregates = {"ecdf_mean4_dense": e_mean4, "ecdf_second_best_dense": e_second,
                  "ecdf_available_mean_dense_bm25": e_available, "robust_z_mean4_dense": z_mean4}
    # C uses an observed-score maximum. Midrank ECDF prevents a giant identical-score
    # plateau from being arbitrarily admitted solely because a percentile cuts through it.
    c_ecdf = np.maximum(dense_ecdf.max(axis=1), np.nan_to_num(bm25_ecdf, nan=-np.inf))

    A = (evidence["support"].astype(np.int8) + bm25_observed.astype(np.int8)) == 5
    aggregate_rows = []
    b_specs = []
    for method, values in aggregates.items():
        for tail in TAIL_TARGETS:
            threshold = choose_threshold(values, tail)
            b_specs.append({"method": method, "tail_target": tail, "threshold": threshold})
            aggregate_rows.append({"kind": "B", "method": method, "tail_target": tail, "threshold": threshold,
                                   "selected": int(np.count_nonzero(values >= threshold)), "tie_at_threshold": int(np.count_nonzero(values == threshold))})
    c_specs = []
    for tail in TAIL_TARGETS:
        threshold = choose_threshold(c_ecdf, tail)
        c_specs.append({"method": "ecdf_max_observed", "tail_target": tail, "threshold": threshold})
        aggregate_rows.append({"kind": "C", "method": "ecdf_max_observed", "tail_target": tail, "threshold": threshold,
                               "selected": int(np.count_nonzero(c_ecdf >= threshold)), "tie_at_threshold": int(np.count_nonzero(c_ecdf == threshold))})
    write_csv(args.out / "generated_threshold_grid.csv", aggregate_rows)

    # Precompute metadata predicates once.  Original modality/type, rather than the
    # common text retrieval view, is used for cross-modal measures.
    cross_document = docs[left] != docs[right]
    cross_modal = types[left] != types[right]
    type_names = sorted(set(types)); source_names = sorted(set(sources))
    policy_rows, masks = [], {}
    for b in b_specs:
        B = aggregates[b["method"]] >= b["threshold"]
        for c in c_specs:
            C = c_ecdf >= c["threshold"]
            keep = A | B | C
            key = f"{b['method']}__Btail{b['tail_target']:g}__Ctail{c['tail_target']:g}"
            masks[key] = keep
            degree = np.bincount(np.concatenate((left[keep], right[keep])), minlength=len(views))
            active = degree > 0; dv = degree[active]
            intersections = {"A_only": int(np.count_nonzero(A & ~B & ~C)), "B_only": int(np.count_nonzero(B & ~A & ~C)),
                             "C_only": int(np.count_nonzero(C & ~A & ~B)), "A_B_only": int(np.count_nonzero(A & B & ~C)),
                             "A_C_only": int(np.count_nonzero(A & C & ~B)), "B_C_only": int(np.count_nonzero(B & C & ~A)),
                             "A_B_C": int(np.count_nonzero(A & B & C))}
            row = {"policy": key, "B_method": b["method"], "B_tail_target": b["tail_target"], "B_threshold": b["threshold"],
                   "C_method": c["method"], "C_tail_target": c["tail_target"], "C_threshold": c["threshold"],
                   "A_count": int(A.sum()), "B_count": int(B.sum()), "C_count": int(C.sum()), "union_count": int(keep.sum()),
                   "retention_of_original_six_union": float(keep.sum() / args.original_six_union),
                   "retention_of_effective_union": float(keep.mean()), "eligible_node_coverage": float(active.mean()),
                   "canonical_node_coverage": float(active.sum() / 112591), "isolated_eligible_nodes": int((~active).sum()),
                   "average_degree_eligible": float(2 * keep.sum() / len(views)), "degree_p50_active": float(np.quantile(dv, .5)),
                   "degree_p90_active": float(np.quantile(dv, .9)), "degree_p95_active": float(np.quantile(dv, .95)),
                   "degree_p99_active": float(np.quantile(dv, .99)), "degree_max": int(degree.max()),
                   "cross_document_count": int(cross_document[keep].sum()), "cross_document_rate": float(cross_document[keep].mean()),
                   "cross_modal_count": int(cross_modal[keep].sum()), "cross_modal_rate": float(cross_modal[keep].mean()), **intersections}
            for typ in type_names:
                all_n = int(np.count_nonzero(types == typ)); row[f"coverage_type_{typ}"] = float(np.count_nonzero(active & (types == typ)) / all_n)
            for source in source_names:
                all_n = int(np.count_nonzero(sources == source)); row[f"coverage_source_{source}"] = float(np.count_nonzero(active & (sources == source)) / all_n)
            policy_rows.append(row)
    policy_rows.sort(key=lambda x: x["union_count"])
    write_csv(args.out / "abc_threshold_search.csv", policy_rows)

    # Select naturally occurring operating points nearest to three scale references;
    # this only chooses among threshold policies and never truncates individual pairs.
    used = set(); recommended = []
    for label, target in (("conservative", 1_000_000), ("balanced", 1_500_000), ("broad", 2_000_000)):
        choices = [x for x in policy_rows if x["policy"] not in used]
        chosen = min(choices, key=lambda x: (abs(x["union_count"] - target), -x["eligible_node_coverage"], x["degree_max"]))
        used.add(chosen["policy"]); recommended.append({"label": label, "target_edges_reference": target, **chosen})
    write_csv(args.out / "recommended_operating_points.csv", recommended)

    rec_dir = args.out / "recommended_configs"; rec_dir.mkdir(exist_ok=True)
    detail_rows = []
    for rec in recommended:
        key, keep = rec["policy"], masks[rec["policy"]]
        idx = np.flatnonzero(keep); chosen_left, chosen_right = left[idx], right[idx]
        components = graph_components(chosen_left, chosen_right, len(views))
        # Pair IDs retain the canonical packed view-row encoding and are coupled to
        # retrieval_views.jsonl; selected indices retain all cross-score provenance.
        policy_dir = rec_dir / rec["label"]; policy_dir.mkdir(exist_ok=True)
        np.save(policy_dir / "retained_pair_ids.npy", np.asarray(pairs[idx]))
        np.save(policy_dir / "retained_cross_score_indices.npy", idx)
        (policy_dir / "config.json").write_text(json.dumps({"label": rec["label"], "policy": key,
            "rule_A": "effective_support == 5", "rule_B": {"method": rec["B_method"], "threshold": rec["B_threshold"], "tail_target": rec["B_tail_target"]},
            "rule_C": {"method": rec["C_method"], "threshold": rec["C_threshold"], "tail_target": rec["C_tail_target"]},
            "normalization": "tie-aware ECDF; fixed reference universe stated in normalization_reference.csv", "bm25_missing": "unobserved, not zero"}, indent=2) + "\n")
        # Route-combination diagnostics for selected pairs: four Dense discovery bits,
        # BM25 observation bit, and BGE diagnostic-only observation bit.
        ev = evidence[idx]; combo = Counter()
        for support, bm, bge in zip(ev["support"], ev["bm25_present"], ev["bge_diagnostic_present"]):
            combo[f"dense_support_{int(support)}__bm25_{int(bm)}__bge_diagnostic_{int(bge)}"] += 1
        write_csv(policy_dir / "selected_route_combination.csv", [{"combination": k, "pairs": v} for k, v in sorted(combo.items())])
        # Edge type combinations use original canonical node types.
        comb = Counter("__".join(sorted((types[a], types[b]))) for a, b in zip(chosen_left, chosen_right))
        write_csv(policy_dir / "node_type_edge_combinations.csv", [{"node_type_combination": k, "pairs": v} for k, v in sorted(comb.items())])
        detail_rows.append({"label": rec["label"], **components})
    write_csv(args.out / "recommended_graph_components.csv", detail_rows)

    def pct(value: float) -> str:
        return f"{value:.2%}"
    report = ["# Score-normalized ABC threshold search", "", "## Data and score availability", "",
              f"- Original six-route Top-100 union: **{args.original_six_union:,}** pairs.",
              f"- Search universe: **{n:,}** pairs, the complete union after excluding the invalid BGE route.",
              "- Every search-universe pair has four Dense cross-scores. BM25 is observed only when BM25 retrieved the pair; absent BM25 is represented as missing, never as zero.",
              "- Raw ANN/retrieval scores are not aggregated with cross-scores. Dense cross-scores are normalized cosine similarities; BM25 remains a route-local lexical score.", "",
              "## Normalization", "", "- **ECDF (recommended):** tie-aware midrank ECDF on the complete bounded search universe per route. It maps equal raw scores to the same normalized value and does not let an arbitrary percentile cut through a saturated tie plateau.",
              "- **Robust Z-score (comparison):** `(s − median) / (IQR / 1.349)`, clipped to [-6, 6]. It remains sensitive to raw-scale tail geometry and is reported as a comparator, not a probability.",
              "- Reference distributions are candidate-conditioned (not all O(N²) pairs), so thresholds are valid for this Top-100 pipeline and should be recalibrated for a different corpus or K.", "",
              "## Rule semantics", "", "- A: all four usable Dense routes and BM25 retrieved the pair.",
              "- B: an automatically scanned aggregate threshold; its variant is recorded per row. The four Dense routes are complete; BM25 enters `available_mean` only when observed.",
              "- C: maximum observed tie-aware ECDF across Dense and available BM25. It measures an extreme route-local position, not confidence.",
              "", "## Recommended operating points", "",
              "| Profile | Rule B | Rule C | Edges | Original-union retention | Eligible coverage | Mean degree | P99 degree | Max degree | Cross-document | Cross-modal |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for rec in recommended:
        report.append("| {label} | {B_method} ≥ {B_threshold:.6f} | max ECDF ≥ {C_threshold:.6f} | {union_count:,} | {ret} | {cov} | {average_degree_eligible:.2f} | {degree_p99_active:.0f} | {degree_max:,} | {cross_doc} | {cross_mod} |".format(
            ret=pct(rec["retention_of_original_six_union"]), cov=pct(rec["eligible_node_coverage"]), cross_doc=pct(rec["cross_document_rate"]), cross_mod=pct(rec["cross_modal_rate"]), **rec))
    report += ["", "These are nearest naturally occurring threshold policies to 1M/1.5M/2M reference scales; no Top-N truncation was used. The corresponding machine-readable configuration, packed canonical-pair IDs, and selected cross-score indices are under `recommended_configs/`.",
               "", "## Rule complementarity for recommended policies", "", "| Profile | A only | B only | C only | A∩B∩C |", "|---|---:|---:|---:|---:|"]
    for rec in recommended:
        report.append(f"| {rec['label']} | {rec['A_only']:,} | {rec['B_only']:,} | {rec['C_only']:,} | {rec['A_B_C']:,} |")
    report += ["", "## ECDF versus robust Z-score", "", "For each B method, the full 25-combination grid is in `abc_threshold_search.csv`. ECDF is recommended because it gives a route-local relative position while respecting exact-score ties. Robust Z-score is useful as a sensitivity comparison but is more sensitive to tail geometry and its clipped scale is not bounded as a percentile.",
               "", "## Saturation caveat", "", "The separate Job 126255/126256 audit found that the raw 1.0 plateau is overwhelmingly repeated short text/template content. Midrank ECDF prevents a quantile threshold from silently admitting all tied values. This does not validate retained pairs as semantic edges: the output remains a query-independent candidate graph for Stage 2.",
               "", "## Limits", "", "- Candidate-conditioned reference distributions do not estimate scores over all possible Node pairs.", "- BM25 is incompletely observed outside its own Top-100 output and is not imputed.", "- Dense models are correlated; score normalization does not make them independent evidence.", "- BGE-en-ICL is excluded from all A/B/C calculations because its legacy CLS pooling produced invalid frozen vectors."]
    (args.out / "REPORT.md").write_text("\n".join(report) + "\n")
    (args.out / "search_manifest.json").write_text(json.dumps({"cross_manifest": manifest, "effective_pairs": n,
        "original_six_union": args.original_six_union, "BGE": "diagnostic-only and excluded", "dense_routes": DENSE,
        "bm25_score_coverage": int(bm25_observed.sum()), "tail_targets": TAIL_TARGETS}, indent=2) + "\n")
    print(json.dumps({"out": str(args.out), "policies": len(policy_rows), "recommended": [x["policy"] for x in recommended]}))


if __name__ == "__main__":
    main()
