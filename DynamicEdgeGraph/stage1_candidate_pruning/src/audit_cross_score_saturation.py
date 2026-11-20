"""CPU-only audit for the bounded dense cross-score artifact.

This module deliberately reads existing candidate pairs and frozen vectors only.  It
does not alter embeddings, candidate retrieval, or any pruning policy.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROUTES = ["qwen3_0_6b_dense", "gte_qwen2_1_5b_dense", "mxbai_dense", "gte_large_dense"]
LEVELS = (0.999, 0.9999, 0.99999)
QUANTILES = (0.99, 0.995, 0.999)


def read_jsonl(path: Path):
    with path.open() as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cross", type=Path, required=True)
    parser.add_argument("--views", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sample-per-stratum", type=int, default=12)
    parser.add_argument("--chunk", type=int, default=1_000_000)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    pairs = np.load(args.cross / "effective_union_pairs.npy", mmap_mode="r")
    scores = np.load(args.cross / "dense_cross_scores.npy", mmap_mode="r")
    evidence = np.load(args.cross / "effective_union_evidence.npy", mmap_mode="r")
    manifest = json.loads((args.cross / "cross_score_manifest.json").read_text())
    views = list(read_jsonl(args.views))
    n = len(pairs)
    assert scores.shape == (n, len(ROUTES)), scores.shape
    assert len(views) > int(np.max(pairs[: min(n, 1_000_000)] >> np.uint64(32)))

    # There is one type-aware view per eligible canonical node in this artifact;
    # keep the full provenance nevertheless rather than infer it from position.
    text = [str(v.get("retrieval_text", "")) for v in views]
    node_id = [str(v["node_id"]) for v in views]
    document_id = [str(v["document_id"]) for v in views]
    node_type = [str(v.get("node_type", "OTHER")) for v in views]
    text_freq = Counter(text)
    text_code_map = {value: index for index, value in enumerate(text_freq)}
    text_code = np.asarray([text_code_map[value] for value in text], dtype=np.int32)
    repeated_text = np.asarray([text_freq[value] > 1 for value in text], dtype=bool)
    node_code_map = {value: index for index, value in enumerate(node_id)}
    node_code = np.asarray([node_code_map[value] for value in node_id], dtype=np.int32)
    doc_code_map = {value: index for index, value in enumerate(sorted(set(document_id)))}
    doc_code = np.asarray([doc_code_map[value] for value in document_id], dtype=np.int16)

    # Streaming totals, exact threshold counts, and high-score pair attributes.
    route_stats = []
    high_rows = []
    rng = np.random.default_rng(126094)
    attr = {route: {level: Counter() for level in LEVELS} for route in ROUTES}
    mapping = Counter()
    above_one = Counter()
    max_pair_indices = 0

    # Quantiles are calculated from a memmap in a bounded extra-memory manner by
    # NumPy's partition implementation; 24m float32 values are ~97 MB per route.
    quantile_values = {route: [float(np.quantile(scores[:, ri], q)) for q in QUANTILES]
                       for ri, route in enumerate(ROUTES)}
    for ri, route in enumerate(ROUTES):
        values = scores[:, ri]
        q_values = quantile_values[route]
        route_stats.append({
            "route": route,
            "min": float(np.min(values)), "max": float(np.max(values)),
            "mean": float(np.mean(values)), "std": float(np.std(values)),
            **{f"p{q * 100:g}": quantile_values[route][qi] for qi, q in enumerate(QUANTILES)},
            **{f"count_ge_p{q * 100:g}": int(np.count_nonzero(values >= q_values[qi])) for qi, q in enumerate(QUANTILES)},
            **{f"count_eq_p{q * 100:g}": int(np.count_nonzero(values == q_values[qi])) for qi, q in enumerate(QUANTILES)},
            **{f"count_ge_{level:g}": int(np.count_nonzero(values >= level)) for level in LEVELS},
            **{f"count_gt_1": int(np.count_nonzero(values > 1.0))},
        })

    for start in range(0, n, args.chunk):
        end = min(n, start + args.chunk)
        packed = np.asarray(pairs[start:end])
        left = (packed >> np.uint64(32)).astype(np.int64)
        right = (packed & np.uint64(0xffffffff)).astype(np.int64)
        value = np.asarray(scores[start:end])
        mapping["pairs_checked"] += len(left)
        mapping["self_embedding_row"] += int(np.count_nonzero(left == right))
        mapping["left_out_of_range"] += int(np.count_nonzero((left < 0) | (left >= len(views))))
        mapping["right_out_of_range"] += int(np.count_nonzero((right < 0) | (right >= len(views))))
        mapping["same_canonical_node"] += int(np.count_nonzero(node_code[left] == node_code[right]))
        max_pair_indices = max(max_pair_indices, int(left.max()), int(right.max()))
        same_text = text_code[left] == text_code[right]
        same_doc = doc_code[left] == doc_code[right]
        repeated_endpoint = repeated_text[left] | repeated_text[right]
        for ri, route in enumerate(ROUTES):
            for level in LEVELS:
                mask = value[:, ri] >= level
                c = attr[route][level]
                c["pairs"] += int(mask.sum())
                c["same_exact_retrieval_text"] += int(same_text[mask].sum())
                c["same_document"] += int(same_doc[mask].sum())
                c["cross_document"] += int((~same_doc[mask]).sum())
                c["repeated_text_endpoint"] += int(repeated_endpoint[mask].sum())
                # Different packed indices are guaranteed by canonical-pair construction;
                # this explicit count tests whether they nevertheless map to one node.
                c["different_node_id"] += int(np.count_nonzero(node_code[left[mask]] != node_code[right[mask]]))

    # Verification samples: independently recompute the score in float64 from the
    # unmodified frozen rows, after the same per-row L2 normalisation used in Job 126094.
    # Draw after aggregate statistics.  This is uniform within every route/score
    # stratum and remains bounded even when a saturated tail contains millions.
    reservoirs = defaultdict(list)
    for route_i, route in enumerate(ROUTES):
        for level in LEVELS:
            candidates = np.flatnonzero(scores[:, route_i] >= level)
            if len(candidates):
                chosen = rng.choice(candidates, size=min(args.sample_per_stratum, len(candidates)), replace=False)
                for pair_index in chosen:
                    packed = int(pairs[pair_index])
                    reservoirs[(route, level)].append({
                        "route": route, "threshold": level, "pair_index": int(pair_index),
                        "source_view_row": int(packed >> 32), "target_view_row": int(packed & 0xffffffff),
                    })
    verify = []
    for ri, route in enumerate(ROUTES):
        vectors = np.load(args.models / route / "view_vectors.npy", mmap_mode="r")
        selected = reservoirs[(route, LEVELS[0])][: min(5, len(reservoirs[(route, LEVELS[0])]))]
        for item in selected:
            left, right = item["source_view_row"], item["target_view_row"]
            a = np.asarray(vectors[left], dtype=np.float64); b = np.asarray(vectors[right], dtype=np.float64)
            cosine64 = float(np.dot(a / np.linalg.norm(a), b / np.linalg.norm(b)))
            stored = float(scores[item["pair_index"], ri])
            verify.append({"route": route, "pair_index": item["pair_index"], "stored_float32": stored,
                           "recomputed_float64": cosine64, "absolute_difference": abs(stored - cosine64),
                           "left_vector_norm_raw": float(np.linalg.norm(a)), "right_vector_norm_raw": float(np.linalg.norm(b))})

    # Add full metadata and all four scores only after reservoir selection, limiting
    # output to explainable, inspectable samples.
    for key, items in sorted(reservoirs.items(), key=lambda x: (x[0][0], x[0][1])):
        for item in items:
            li, ri = item["source_view_row"], item["target_view_row"]
            item.update({
                "source_node_id": node_id[li], "target_node_id": node_id[ri],
                "source_document_id": document_id[li], "target_document_id": document_id[ri],
                "source_node_type": node_type[li], "target_node_type": node_type[ri],
                "source_text": text[li], "target_text": text[ri],
                "same_exact_retrieval_text": bool(text[li] == text[ri]),
                "same_document": bool(document_id[li] == document_id[ri]),
                "source_text_global_frequency": int(text_freq[text[li]]),
                "target_text_global_frequency": int(text_freq[text[ri]]),
                **{f"score_{route}": float(scores[item["pair_index"], route_i]) for route_i, route in enumerate(ROUTES)},
            })
            high_rows.append(item)

    with (args.out / "high_score_pair_samples.jsonl").open("w") as handle:
        for row in high_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.out / "cross_score_distribution.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(route_stats[0])); writer.writeheader(); writer.writerows(route_stats)
    attr_rows = []
    for route in ROUTES:
        for level in LEVELS:
            c = attr[route][level]; total = c["pairs"]
            attr_rows.append({"route": route, "threshold": level, **dict(c),
                              "pair_fraction": total / n if n else 0,
                              "same_text_fraction": c["same_exact_retrieval_text"] / total if total else 0,
                              "same_document_fraction": c["same_document"] / total if total else 0,
                              "cross_document_fraction": c["cross_document"] / total if total else 0,
                              "repeated_text_endpoint_fraction": c["repeated_text_endpoint"] / total if total else 0})
    with (args.out / "high_score_pair_characteristics.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(attr_rows[0])); writer.writeheader(); writer.writerows(attr_rows)
    with (args.out / "mapping_score_verification.json").open("w") as handle:
        json.dump({"manifest": manifest, "views": len(views), "pairs": n, "max_pair_row": max_pair_indices,
                   "mapping_checks": dict(mapping), "float64_recomputations": verify}, handle, indent=2)

    lines = ["# Job 126094 Cross-score Reliability Audit", "", "## Scope", "",
             f"- Cross-scored pairs: **{n:,}**.",
             "- This is the complete union of Top-100 candidates from the four usable Dense routes plus BM25, not a partial computation.",
             "- The original six-route union has 34,558,320 pairs. The difference is attributable to removing the known-invalid BGE-en-ICL route from the *input union*; BGE remains diagnostic-only.",
             "- Scores are raw cosine similarities: each stored frozen vector is L2-normalized per row at scoring time and the score is the dot product. No percentile, clipping, distance inversion, or cross-route scaling is applied.",
             "", "## Outputs", "", "- `cross_score_distribution.csv`: threshold/tail counts and P99/P99.5/P99.9 values.",
             "- `high_score_pair_characteristics.csv`: exact-text, repeated-template, and document provenance rates.",
             "- `high_score_pair_samples.jsonl`: stratified provenance samples with all four scores.",
             "- `mapping_score_verification.json`: row-bound checks and independent float64 recomputations.", "",
             "## Interpretation guardrail", "", "Scores at or slightly above 1.0 can occur from float32 dot-product rounding after normalization. This audit reports exact tie counts; P99-family values must not be used as a strict selector until the tail and provenance tables have been inspected."]
    (args.out / "CROSS_SCORE_RELIABILITY_AUDIT.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
