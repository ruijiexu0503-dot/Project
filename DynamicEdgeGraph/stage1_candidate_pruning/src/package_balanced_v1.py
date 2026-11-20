"""Materialize the fixed Stage 1 Balanced-v1 candidate graph from existing artifacts.

No retrieval, ANN indexing, embedding encoding, or pruning search is performed.
The selected indices produced by the completed normalized threshold search are the
source of truth; this module only validates and packages them for downstream use.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np

from .common import read_jsonl, write_jsonl
from .search_abc_normalized import DENSE, ecdf_midrank

EXPECTED_EDGES = 1_495_665
B_THRESHOLD = np.float32(0.9817807078361511)
C_THRESHOLD = np.float32(0.9951319098472595)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cross", type=Path, required=True)
    parser.add_argument("--balanced", type=Path, required=True)
    parser.add_argument("--views", type=Path, required=True)
    parser.add_argument("--nodes", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty output directory: {args.out}")
    args.out.mkdir(parents=True, exist_ok=True)

    pairs = np.load(args.cross / "effective_union_pairs.npy", mmap_mode="r")
    raw_dense = np.load(args.cross / "dense_cross_scores.npy", mmap_mode="r")
    evidence = np.load(args.cross / "effective_union_evidence.npy", mmap_mode="r")
    selected = np.load(args.balanced / "retained_cross_score_indices.npy", mmap_mode="r")
    retained_ids = np.load(args.balanced / "retained_pair_ids.npy", mmap_mode="r")
    if len(selected) != EXPECTED_EDGES:
        raise RuntimeError(f"selected count {len(selected):,} != expected {EXPECTED_EDGES:,}")
    if not np.array_equal(retained_ids, pairs[selected]):
        raise RuntimeError("retained Pair IDs no longer align with selected cross-score indices")
    if np.any(selected[1:] <= selected[:-1]):
        raise RuntimeError("selected indices must be strictly ascending and unique")

    # Recreate only normalized values, under exactly the fixed search-universe
    # reference distribution. This is deterministic and does not modify source data.
    dense_ecdf = np.empty_like(raw_dense, dtype=np.float32)
    reference = {"reference_universe": "complete 24,177,794-pair union of four usable Dense Top-100 routes plus BM25",
                 "dense_ecdf": "tie-aware midrank F(s-) + 0.5 P(S=s), separately per Dense route",
                 "bm25_ecdf": "same tie-aware ECDF over observed BM25 candidate scores only; unavailable BM25 remains NaN",
                 "dense_routes": list(DENSE), "B_threshold": float(B_THRESHOLD), "C_threshold": float(C_THRESHOLD)}
    for ri, route in enumerate(DENSE):
        dense_ecdf[:, ri], meta = ecdf_midrank(np.asarray(raw_dense[:, ri]))
        reference[route] = meta
    bm25_observed = evidence["bm25_present"].astype(bool)
    bm25_raw = np.asarray(evidence["bm25_score"], dtype=np.float32)
    bm25_ecdf = np.full(len(pairs), np.nan, dtype=np.float32)
    bm25_ecdf[bm25_observed], bm25_meta = ecdf_midrank(bm25_raw[bm25_observed])
    reference["bm25"] = {"observed_pairs": int(bm25_observed.sum()), **bm25_meta}

    e_mean = dense_ecdf.mean(axis=1)
    e_max = np.maximum(dense_ecdf.max(axis=1), np.nan_to_num(bm25_ecdf, nan=-np.inf))
    dense_support = np.asarray(evidence["support"], dtype=np.uint8)
    effective_support = dense_support + bm25_observed.astype(np.uint8)
    rule_a = effective_support == 5
    rule_b = e_mean >= B_THRESHOLD
    rule_c = e_max >= C_THRESHOLD
    should_keep = rule_a | rule_b | rule_c
    if not np.array_equal(np.flatnonzero(should_keep), selected):
        raise RuntimeError("fixed ABC rules do not reproduce the supplied Balanced selection")

    # Canonical packed IDs are (min view row << 32) | max view row. One view exists
    # for each eligible canonical node, and node_catalog retains the authoritative
    # node/document/modality provenance for these row IDs.
    view_rows = list(read_jsonl(args.views))
    node_by_id = {row["id"]: row for row in read_jsonl(args.nodes)}
    if len(view_rows) != 104318:
        raise RuntimeError(f"unexpected retrieval view count: {len(view_rows)}")
    catalog = []
    doc_values = sorted({str(v["document_id"]) for v in view_rows})
    source_values = sorted({str(node_by_id[v["node_id"]].get("data_source", "unknown")) for v in view_rows})
    type_values = sorted({str(node_by_id[v["node_id"]].get("node_type", "OTHER")) for v in view_rows})
    doc_code = {value: i for i, value in enumerate(doc_values)}
    source_code = {value: i for i, value in enumerate(source_values)}
    type_code = {value: i for i, value in enumerate(type_values)}
    for row_id, view in enumerate(view_rows):
        node = node_by_id[view["node_id"]]
        catalog.append({"view_row": row_id, "node_id": view["node_id"], "document_id": view["document_id"],
                        "page_number": node.get("page_number"), "node_type": node.get("node_type", "OTHER"),
                        "data_source": node.get("data_source", "unknown"), "view_id": view["view_id"],
                        "view_kind": view.get("view_kind"), "canonical_node_reference": str(args.nodes)})
    write_jsonl(args.out / "node_catalog.jsonl", catalog)
    (args.out / "metadata_dictionaries.json").write_text(json.dumps({"document_id": doc_values, "data_source": source_values,
                                                                        "node_type": type_values}, indent=2) + "\n")

    selected_pairs = np.asarray(pairs[selected])
    left = (selected_pairs >> np.uint64(32)).astype(np.int32)
    right = (selected_pairs & np.uint64(0xffffffff)).astype(np.int32)
    if np.any(left == right):
        raise RuntimeError("self-loop detected")
    if np.any(selected_pairs[1:] <= selected_pairs[:-1]):
        raise RuntimeError("duplicate or unsorted canonical Pair ID detected")
    docs = np.asarray([doc_code[str(v["document_id"])] for v in view_rows], dtype=np.int16)
    types = np.asarray([type_code[str(node_by_id[v["node_id"]].get("node_type", "OTHER"))] for v in view_rows], dtype=np.uint8)
    sources = np.asarray([source_code[str(node_by_id[v["node_id"]].get("data_source", "unknown"))] for v in view_rows], dtype=np.uint8)
    # NPZ stores the full selected-pair evidence in compact typed arrays. NaN in
    # BM25 fields has an explicit companion flag; it is never a zero score.
    np.savez_compressed(args.out / "balanced_v1_candidate_pairs.npz",
                        pair_id=selected_pairs, cross_score_index=np.asarray(selected, dtype=np.int64),
                        source_view_row=left, target_view_row=right,
                        source_document_code=docs[left], target_document_code=docs[right],
                        source_node_type_code=types[left], target_node_type_code=types[right],
                        source_data_source_code=sources[left], target_data_source_code=sources[right],
                        dense_raw_score=np.asarray(raw_dense[selected], dtype=np.float32),
                        dense_ecdf=np.asarray(dense_ecdf[selected], dtype=np.float32),
                        bm25_observed=bm25_observed[selected], bm25_raw_score=bm25_raw[selected], bm25_ecdf=bm25_ecdf[selected],
                        dense_retrieval_support=dense_support[selected], effective_retrieval_support=effective_support[selected],
                        dense_mutual_route_count=np.asarray(evidence["mutual_routes"][selected], dtype=np.uint8),
                        bge_diagnostic_present=np.asarray(evidence["bge_diagnostic_present"][selected], dtype=np.uint8),
                        rule_A=rule_a[selected], rule_B=rule_b[selected], rule_C=rule_c[selected])
    # Human-readable source configuration is copied, never moved or altered.
    shutil.copy2(args.balanced / "config.json", args.out / "source_balanced_search_config.json")
    final_config = {"stage": "stage1_candidate_pruning", "version": "vldocir_balanced_v1", "rules": {
        "A": "effective retrieval support == 5 (four usable Dense routes + BM25)",
        "B": "mean of four Dense tie-aware ECDF scores >= 0.9817807078361511",
        "C": "max of observed Dense/BM25 tie-aware ECDF scores >= 0.9951319098472595"},
        "BGE": "diagnostic-only; excluded from support, scores, normalisation, and ABC rules", "top_n_truncation": None,
        "bm25_missing": "bm25_observed=false and bm25_raw_score/bm25_ecdf=NaN; missing is not zero"}
    (args.out / "balanced_v1_config.json").write_text(json.dumps(final_config, indent=2) + "\n")
    manifest = {"version": "vldocir_balanced_v1", "candidate_pairs": int(len(selected)), "expected_candidate_pairs": EXPECTED_EDGES,
                "eligible_retrieval_views": len(view_rows), "canonical_nodes": 112591, "pair_encoding": "(min_view_row << 32) | max_view_row",
                "source_cross_scores": str(args.cross), "source_balanced_selection": str(args.balanced),
                "integrity": {"selection_matches_fixed_ABC": True, "no_self_loops": True, "strictly_sorted_unique_undirected_pair_ids": True,
                              "node_catalog_rows": len(catalog), "dense_score_coverage": "4/4 for every retained pair",
                              "bm25_observed_pairs_retained": int(bm25_observed[selected].sum()), "bm25_missing_pairs_retained": int((~bm25_observed[selected]).sum())},
                "files": {"pair_bundle": "balanced_v1_candidate_pairs.npz", "node_catalog": "node_catalog.jsonl", "metadata_dictionaries": "metadata_dictionaries.json",
                          "config": "balanced_v1_config.json", "normalization_reference": "normalization_reference.json"}}
    (args.out / "normalization_reference.json").write_text(json.dumps(reference, indent=2) + "\n")
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    report = ["# VL-DocIR Stage 1 Balanced-v1 Candidate Graph", "", f"- Candidate pairs: **{len(selected):,}** (expected {EXPECTED_EDGES:,}).",
              "- Reused the completed Balanced selection; no retrieval, ANN, embedding, or edge-embedding computation was run.",
              "- Integrity: Pair IDs are strictly sorted/unique, canonical undirected, and contain no self-loops.",
              f"- Node catalog: {len(catalog):,} eligible retrieval views, referencing the 112,591-node canonical universe.",
              f"- Dense scores: four raw cosine cross-scores and four tie-aware ECDF values for every retained pair.",
              f"- BM25: observed for {int(bm25_observed[selected].sum()):,} retained pairs; absent for {int((~bm25_observed[selected]).sum()):,} and stored as NaN with `bm25_observed=false`.",
              "- BGE-en-ICL is diagnostic-only and excluded from all saved support/ABC semantics.", "", "See `MANIFEST.json` for schema and source provenance."]
    (args.out / "REPORT.md").write_text("\n".join(report) + "\n")
    print(json.dumps({"out": str(args.out), "pairs": len(selected), "bm25_observed": int(bm25_observed[selected].sum())}))


if __name__ == "__main__":
    main()
