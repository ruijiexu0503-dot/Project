"""Read-only readiness audit for the fixed Stage 1 Balanced v1 package.

It validates the selected candidate graph but never recalculates ABC or treats an
IMAGE node's HTML/OCR fallback as a visual embedding input.
"""
from __future__ import annotations
import argparse, collections, json
from pathlib import Path
import numpy as np
from common import read_jsonl, sha256_file, write_json

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--package", type=Path, default=Path("DynamicEdgeGraph/stage1_candidate_pruning/outputs/vldocir_balanced_v1")); parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    manifest = json.loads((args.package / "MANIFEST.json").read_text()); config = json.loads((args.package / "balanced_v1_config.json").read_text())
    bundle = np.load(args.package / "balanced_v1_candidate_pairs.npz"); catalog = list(read_jsonl(args.package / "node_catalog.jsonl"))
    if len(catalog) != manifest["eligible_retrieval_views"]: raise ValueError("node catalog count mismatch")
    n = len(bundle["pair_id"])
    if n != manifest["candidate_pairs"] or n != 1_495_665: raise ValueError("unexpected Balanced v1 pair count")
    if not np.all(bundle["source_view_row"] < bundle["target_view_row"]): raise ValueError("pairs are not canonical undirected view pairs")
    if np.any(bundle["source_view_row"] >= len(catalog)) or np.any(bundle["target_view_row"] >= len(catalog)): raise ValueError("pair endpoint outside node catalog")
    if not np.all(bundle["rule_A"] | bundle["rule_B"] | bundle["rule_C"]): raise ValueError("pair not selected by fixed ABC")
    by_type = collections.Counter(row["node_type"] for row in catalog)
    image_rows = [row for row in catalog if row["node_type"] == "IMAGE"]
    endpoint_types = collections.Counter()
    for left, right in zip(bundle["source_node_type_code"], bundle["target_node_type_code"], strict=True): endpoint_types[f"{int(left)}->{int(right)}"] += 1
    output = {"stage1_policy": "balanced_v1", "fixed_thresholds": config["rules"], "candidate_pairs": n,
      "eligible_views": len(catalog), "catalog_node_types": dict(by_type), "image_nodes_requiring_visual_description": len(image_rows),
      "image_policy": "Do not encode HTML/OCR fallback as a visual representation. Generate/version visual descriptions before including IMAGE endpoints in one-space Stage 2 embeddings.",
      "integrity": {"abc_union": True, "canonical_undirected": True, "endpoint_bounds": True, "bm25_missing_is_not_zero": config["bm25_missing"]},
      "files": {name: {"sha256": sha256_file(args.package / name)} for name in ("balanced_v1_candidate_pairs.npz", "node_catalog.jsonl", "balanced_v1_config.json", "normalization_reference.json")}}
    args.output.parent.mkdir(parents=True, exist_ok=True); write_json(args.output, output); print(json.dumps(output, ensure_ascii=False))
if __name__ == "__main__": main()
